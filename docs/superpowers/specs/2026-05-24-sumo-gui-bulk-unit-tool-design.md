# SUMO GUI Bulk-Unit Tool — Design Spec

**Date:** 2026-05-24
**Status:** Approved (pending user review)
**Author/Brainstorm session:** Claude Opus 4.7 with user 7pka111223@gmail.com

## 1. Goal

Add a SUMO24 MCP tool that lets Claude drive the SUMO24 desktop GUI directly
to drop treatment units, wire forward streams, and save the resulting `.sumo`
file in a single MCP call. Motivation: today, the only way to edit SUMO's GUI
from Claude is the `computer-use` MCP, which streams screenshots and pixel
clicks — every placement burns ~thousands of tokens. The new tool collapses N
computer-use round-trips into one MCP call that returns a compact text JSON.

This is the **Approach A** outcome from the brainstorm session: a pywinauto
bridge with a discovery-first phase, scoped to drop-units + wire-connections +
auto-save. Parameters stay with the existing parameter tools.

## 2. Scope

**In scope**
- New helper module `PY/sumo_gui_driver.py` (pywinauto-based).
- Two new MCP tools in `PY/server.py`: `probe_sumo_gui` (ro), `place_units_in_gui` (mutating, dry-run default).
- A discovery artifact `outputs/sumo_gui_profile.json`.
- Topological ordering of units so streams can reference already-placed units.
- Forward (acyclic) streams only — recycle streams (RAS / WAS / internal recycle) continue to go through the existing `add_recycle_stream` tool after the topology is in place.
- Text-only readback via the existing `sumo_compiler.read_sumo_manifest`.
- Unit tests for both tools and a manual smoke test against a live SUMO install.

**Out of scope**
- Setting unit parameters via the GUI — keep using `set_aeration_tank_parameters`, `set_secondary_clarifier_parameters`, etc.
- Per-step screenshots in the response (defeats the token-saving goal).
- Driving any non-SUMO app.
- Recompiling the DLL (still a manual GUI action; document it as the follow-up step).

## 3. Architecture

```
Claude ──MCP──▶ PY/server.py
                ├── _exp_probe_sumo_gui       (ro wrapper)
                └── _exp_place_units_in_gui   (mutating wrapper, dry_run=True default)
                          │
                          ▼
                 PY/sumo_gui_driver.py
                  ├── probe(timeout_s, auto_launch)        → outputs/sumo_gui_profile.json
                  └── place_units(profile, units,
                                  streams, save_path,
                                  dry_run, overwrite) ──pywinauto──▶ SUMO24.exe
                                                                       │
                                                                       ▼
                                                              save_path (.sumo)
                                                                       │
                                                  read back via existing
                                                  sumo_compiler.read_sumo_manifest
```

**Invariants**
- `sumo_gui_driver.py` never imports `dynamita`, never touches `ACTIVE_MODEL` or `state.xml`, and never reads/writes any existing tool's in-memory state. It operates only on the GUI and the resulting `.sumo` file.
- `outputs/sumo_gui_profile.json` is the contract between the two tools. `place_units_in_gui` refuses to run if the profile is missing or its `sumo_version` does not match the running SUMO window.
- Tool surface is intentionally small (2 tools). All token-saving comes from collapsing what would have been N `computer-use` round-trips into one MCP call returning one compact JSON.

## 4. Components

### 4.1 `PY/sumo_gui_driver.py` (new)

Pure stdlib + `pywinauto`. Public surface:

```python
def probe(timeout_s: int = 30, auto_launch: bool = False) -> dict
def place_units(profile: dict,
                units: list[dict],      # [{type: str, name: str, x: int, y: int}]
                streams: list[dict],    # [{from: str, to: str, name: str, stream_type: str}]
                save_path: str,
                dry_run: bool = True,
                overwrite: bool = False) -> dict
```

Internal helpers (private):
- `_connect_to_sumo(profile, auto_launch)` — find SUMO main window by title regex (from profile); launch via `subprocess.Popen` only when `auto_launch=True`.
- `_drag_palette_to_canvas(app, profile, unit_type, x, y)` — pywinauto `drag_mouse_input` from palette item to canvas-local `(x, y)`.
- `_rename_unit(app, profile, placeholder_label, new_name)` — open the unit's properties dialog, set name field, OK. Assumes SUMO auto-names placements (e.g. `AerationTank_1`) and we rename after. **The probe phase verifies this assumption.**
- `_connect_two_units(app, profile, src, dst, stream_name)` — click source unit's output port, click destination's input port, name the stream in the resulting dialog.
- `_save_as(app, profile, path, overwrite)` — File → Save As → type path → confirm. Refuses if path exists and `overwrite=False`.

### 4.2 `outputs/sumo_gui_profile.json` (discovery artifact)

Written by `probe`, read by `place_units`:

```json
{
  "sumo_version": "24.x.y",
  "window_title_regex": "SUMO24.*",
  "palette": {
    "AerationTank": {"selector": "..."},
    "Influent": {"selector": "..."},
    "SecondaryClarifier": {"selector": "..."}
  },
  "canvas":  {"selector": "...", "client_rect": [x, y, w, h]},
  "menus":   {"file_save_as": ["File", "Save As..."]},
  "dialogs": {
    "unit_props":   {"name_field": "...", "ok_button": "..."},
    "save_as":      {"path_field": "...", "ok_button": "..."},
    "stream_name":  {"name_field": "...", "ok_button": "..."}
  },
  "probed_at": "2026-05-24T00:00:00Z"
}
```

### 4.3 `PY/server.py` additions (~150 lines)

Following the existing Group FF pattern (`_exp_apply_dtt_command_batch`, `_exp_diff_inmemory_vs_disk`):

- Two `types.Tool(...)` entries added to the tool-list registration near the Group FF block.
- Two `if name == "..."` branches added to `call_tool`.
- Two `_exp_*` helpers wrapping `sumo_gui_driver` and the standard JSON envelope.
- The `_exp_*` for `place_units_in_gui` calls `sumo_compiler.read_sumo_manifest(save_path)` after a successful save and inlines the summary into the response — this is the text-only readback.

**Tool surfaces**

`probe_sumo_gui` (ro):
- `timeout_s` (int, default 30)
- `auto_launch` (bool, default false)

`place_units_in_gui` (mutating):
- `units` (required): `[{type: str, name: str, x: int, y: int}]`
- `streams` (required): `[{from: str, to: str, name: str, stream_type: str}]` — forward streams only; the topological sort will reject inputs whose stream graph contains a cycle (use `add_recycle_stream` afterwards for RAS/WAS/internal recycle).
- `save_path` (required, str)
- `dry_run` (bool, default true) — matches `apply_dtt_command_batch` convention
- `overwrite` (bool, default false)
- `auto_launch` (bool, default false)

### 4.4 Files NOT changed

- `PY/dtt_editor.py` — unchanged.
- `ACTIVE_MODEL`, `state.xml`, all existing tools — unchanged.
- All existing parameter / template / schematic tools — unchanged. The new tool is additive.

## 5. Data flow — `place_units_in_gui` happy path

1. Claude calls `place_units_in_gui` with `{units, streams, save_path, dry_run: false}`.
2. `_exp_place_units_in_gui` loads `outputs/sumo_gui_profile.json`; fails fast with `{ok: false, error: "probe required", tip: "call probe_sumo_gui first"}` if missing or version-mismatched.
3. Topologically sorts `units` so each stream's `from` and `to` already exist when the stream is wired.
4. Calls `sumo_gui_driver.place_units(profile, units, streams, save_path, dry_run=False, overwrite=overwrite)`. Driver attaches to SUMO via pywinauto.
5. For each unit: drag palette → canvas → rename. Per-unit result `{name, type, placed: bool, error?: str}`.
6. For each stream: click source port → destination port → name. Per-stream result.
7. File → Save As → `save_path` → confirm (or refuse if exists and not `overwrite`).
8. `sumo_compiler.read_sumo_manifest(save_path)` produces the verifiable summary.
9. Returns one JSON envelope:
   ```json
   {
     "ok": true,
     "units": [{"name": "...", "type": "...", "placed": true}],
     "streams": [{"name": "...", "from": "...", "to": "...", "created": true}],
     "save_path": "...",
     "manifest_summary": {"unit_count": 3, "stream_count": 2, "unit_names": [...]},
     "errors": []
   }
   ```

Dry-run returns the planned sequence (palette names, drag targets in canvas coords, save path) without touching SUMO.

## 6. Error handling

| Failure | Behaviour |
|---|---|
| SUMO not running | `{ok: false, error: "SUMO24 not running"}`. Auto-launches via `subprocess.Popen` only if caller passed `auto_launch=true` (off by default). |
| Profile missing or stale | Hard fail: `{ok: false, error: "probe required", tip: "call probe_sumo_gui first"}`. Stale = `sumo_version` in profile ≠ live window's reported version. |
| Palette item unknown | Per-unit error in `units[i].error`, continue with remaining units. Reported in final `errors` list. |
| Drag / dialog blocked | Capture error per step, press ESC, continue. After 3 consecutive step failures → abort with partial results in the response. |
| `save_path` exists | Refuse unless `overwrite=true`. |
| Focus stolen / window not foreground | One `set_focus()` + retry. Second failure = step error. |
| Operation timeout | 30s per individual automation step (configurable on the driver, not exposed as a tool arg). On timeout: same as step failure. |
| Crash mid-call | Return whatever was captured up to that point — Claude must know which units made it in so a retry does not double-place. |
| Cycle in `streams` graph | Reject before any GUI action: `{ok: false, error: "stream graph has cycle", tip: "use add_recycle_stream after place_units_in_gui for RAS/WAS/internal recycle"}`. |
| Dry-run | Never touches SUMO; returns the planned sequence. |

Every `_exp_*` returns a dict with `ok: bool`; the JSON envelope carries `error` / `tip` fields, matching the rest of the codebase.

## 7. Testing

- **`PY/tests/test_sumo_gui_driver_probe.py`** — unit. Mock pywinauto's `Application` / `WindowSpecification`, feed a synthetic control tree, assert profile JSON shape and version-mismatch detection.
- **`PY/tests/test_sumo_gui_driver_place_dryrun.py`** — unit. Given a stub profile and a units+streams list, verify the planned automation sequence (palette names, drag targets in canvas coords, menu paths) and that topological sort puts sources before connections.
- **`PY/smoke_test_sumo_gui_driver.py`** — manual operator script alongside existing `smoke_test_bb_cc.py` / `smoke_test_dd.py`. Runs against a real SUMO24 install: probe → place a 3-unit chain (Influent → AerationTank → Effluent) → assert manifest shows 3 units + 2 streams. Not in CI — gated on `SUMO24_LIVE_GUI=1` env var.
- **Integration:** after `place_units_in_gui` saves, pair with the existing `verify_sumo_file_against_schematic` (or `read_sumo_manifest`) for a second-level check. Document in `SUMO Claude Doman/workflows.md` as part of the §Build playbook so it's discoverable.

## 8. Open items the probe phase will resolve

These do not change the public tool surface or the JSON contract, only the
internal helper implementations:

1. **Placement gesture.** Is "drag palette item → canvas" the actual SUMO gesture, or is it click-to-place, double-click from a tree view, or something else?
2. **Naming.** Does SUMO auto-name placements with a counter (the spec's assumption), or does it open a name dialog immediately?
3. **Connection gesture.** Click-then-click on ports, or drag from port to port?
4. **Save-As dialog.** Standard Windows file dialog (easy) or custom (needs profile entry)?
5. **Version reporting.** Does SUMO expose its version in the window title, About dialog, or registry?

If discovery reveals SUMO's controls are not introspectable via UI Automation
(unlikely for a modern WinForms/WPF app, but possible), the fallback is
**Approach B** from the brainstorm (pixel + calibration). The public tool
surface stays identical; only the helpers in `sumo_gui_driver.py` change.

## 9. Non-goals / explicit deferrals

- No COM / OLE / DDE / IPC integration with SUMO. If Dynamita exposes one, that becomes a separate spec.
- No auto-recompile. The DLL recompile still requires the operator in the GUI.
- No "parameters via GUI" path — `set_*_parameters` tools already cover this.
- No retry-from-checkpoint. A crash returns partial results; the caller decides what to do.
