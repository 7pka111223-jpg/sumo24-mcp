# Cowork Task — Add Group FF: SUMO File Editing via DTT (12 new tools + 1 new module)

> **Deliverable type:** Cowork automated code insertion
> **Server baseline:** previous revision (148 or 156 tools, depending on whether
> Group EE was applied). This deliverable is **additive** — no existing code is
> modified, only new content is appended. The new group letter is **FF**; if
> Group EE has not been applied, rename the new group to **EE** before
> inserting (single search-and-replace on this file).
> **Group focus:** edit an already-loaded .sumo project **through the DTT
> bridge** (`ds.sumo.executeCommand`) — topology rename / retype, stream
> removal & flow setting, full controller CRUD, transactional editing with
> rollback, in-memory ↔ disk diffing, and a raw DTT batch escape hatch.
> **Pattern followed:** identical to Group DD (`sumo_compiler.py`) and Group
> EE (`template_bridge.py`) — one new pure-stdlib module plus thin
> append-only `server.py` wrappers.

---

## 0. STRICT INSERTION RULES (read first — do not deviate)

1. **Never modify, reformat, or delete any existing code** in `server.py`.
2. Create **one new file**: `F:\UNI\SUMO\MCP\PY\dtt_editor.py` (Section 3).
3. In `server.py`, only **append**:
   - one import block — placed **immediately after** the last existing
     `import ... as _...` group module import (Section 4).
   - twelve `types.Tool(...)` definitions — placed **immediately after the last
     existing `types.Tool(...)` definition** and before the list/array is
     closed (Section 5).
   - twelve dispatch handlers — placed **immediately before** the existing
     `# Unknown tool` / `return ... f"Unknown tool: {name}"` line (Section 6).
   - twelve `_exp_*` helper functions — appended at the **end of the helper
     region**, after the last existing `_exp_*` function and before `main()`
     (Section 7).
4. Do **not** touch `requirements.txt`, `build_pdf_v*.py`, or any registry
   file. PDF regeneration is a separate task.
5. After every append, the file must still pass `python -m py_compile server.py`.

### Four reconciliation points (Cowork must confirm against the live file)

These are the only spots where the inserted code depends on conventions only
visible in the live `server.py`. Confirm each once, then apply consistently.

- **R1 — return envelope.** Find the last existing `_exp_*` function and note
  its return mechanism. Replace every `_RETURN(payload)` in Section 7 with that
  exact mechanism.
- **R2 — dispatch shape.** Find an existing dispatch branch (e.g.
  `elif name == "set_parameter":`). Match its `await`/`async` style in
  Sections 6 and 7. If existing handlers are synchronous, drop `await` /
  `async def` in this deliverable.
- **R3 — DTT bridge.** Locate the existing helper that produces a DTT
  scheduler instance (commonly `_make_ds()` or similar — the same helper
  `set_parameter` uses to dispatch `ds.sumo.executeCommand(...)`). Use that
  identical helper inside every `_exp_*` here that dispatches commands.
- **R4 — output directory & CONFIG.** Reuse the server's existing output-dir
  constant (e.g. `_OUT_DIR` or `CONFIG["output_dir"]`) and `CONFIG` dict
  exactly as other helpers do.

---

## 1. Why this group exists (context for the reviewer)

The current server can **add** topology (`add_unit_process`,
`connect_unit_processes`, `add_recycle_stream`, `add_controller`) and **modify
parameters** (Group G, 26 tools). What it cannot do today, through DTT, on an
already-loaded `.sumo`:

- Rename a unit (e.g. `AerationTank1` → `AT1_north`).
- Change a unit's class (e.g. Generic clarifier → Otterpohl).
- Remove a stream (only `modify_flow_connection` exists).
- Set a stream's fixed flow rate / split fraction.
- List, modify, or remove controllers (only `add_controller` exists).
- Run a multi-step edit *transactionally* with rollback on failure.
- See **what differs** between the live in-memory model and the .sumo on disk.
- Dispatch a vetted batch of raw DTT commands with structured logging.

Group FF fills these in a single coherent block. Every edit goes through the
**same DTT bridge** the existing parameter tools use; persistence happens via
the existing `save_model` / `save_state`, which means rollback is just a state
snapshot.

### The 12 tools

| # | Tool | Family | Reuses |
|---|------|--------|--------|
| 1 | `rename_unit_process` | Topology | DTT `executeCommand` |
| 2 | `change_unit_type` | Topology | DTT + sumo_compiler unit registry |
| 3 | `remove_flow_connection` | Topology | DTT `executeCommand` |
| 4 | `set_stream_flow_rate` | Topology | DTT `executeCommand` |
| 5 | `list_controllers` | Controllers | DTT read |
| 6 | `modify_controller` | Controllers | DTT `executeCommand` |
| 7 | `remove_controller` | Controllers | DTT `executeCommand` |
| 8 | `begin_edit_transaction` | Transaction | `save_state` snapshot |
| 9 | `commit_edit_transaction` | Transaction | retire snapshot |
| 10 | `rollback_edit_transaction` | Transaction | restore snapshot |
| 11 | `apply_dtt_command_batch` | Generic | DTT `executeCommand` |
| 12 | `diff_inmemory_vs_disk` | Sync | `sumo_compiler.read_sumo_manifest` |

---

## 2. Import / dependency verification (run before inserting)

In the `F:\UNI\SUMO\MCP\PY` directory:

```bash
python -c "import json, os, shutil, datetime, zipfile, xml.etree.ElementTree; print('stdlib OK')"
python -c "import sumo_compiler as s; print('sumo_compiler OK:', hasattr(s,'read_sumo_manifest'))"
python -m py_compile server.py && echo "server.py compiles OK (pre-insert baseline)"
```

All three must pass. `dtt_editor.py` is **pure stdlib** and has **no direct
DTT dependency** — DTT is invoked from the server's `_exp_*` wrappers via the
existing `_make_ds()` bridge (R3). This mirrors how `sumo_compiler.py` works.

---

## 3. NEW FILE — create `F:\UNI\SUMO\MCP\PY\dtt_editor.py`

Create this file verbatim. It is self-contained pure stdlib.

```python
"""
dtt_editor.py  —  Group FF support module (SUMO24 MCP)

Pure-stdlib. NO direct DTT import — DTT is dispatched from the server's
_exp_* wrappers (which already own the _make_ds() bridge). This module's job
is to:

  * generate vetted DTT command strings,
  * manage edit-transaction state.xml snapshots on disk,
  * diff a live manifest summary against the .sumo file on disk.

Every public function returns a plain dict; the server wraps it in the
project's JSON return envelope.
"""

from __future__ import annotations
import datetime as _dt
import json
import os
import shutil
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# DTT command builders — pure string assembly, no execution.
# These follow the SumoCore convention used everywhere else in the server:
#     Sumo__Plant__<UnitName>__param__<suffix>
# Cowork: if the live DTT exposes different verbs (e.g. `renameUnit` vs
# `rename`), adjust ONLY the right-hand strings in _DTT_VERBS below.
# ---------------------------------------------------------------------------
_DTT_VERBS = {
    "rename_unit":       "renameUnit",        # ds.sumo.executeCommand("renameUnit X Y")
    "change_unit_class": "changeUnitClass",   # "changeUnitClass <unit> <new_class>"
    "remove_stream":     "removeStream",      # "removeStream <stream_id>"
    "set_stream_q":      "setStreamFlow",     # "setStreamFlow <stream_id> <Q>"
    "remove_controller": "removeController",  # "removeController <ctrl_id>"
}

def cmd_rename_unit(old: str, new: str) -> str:
    _require_ident(old, "old unit name")
    _require_ident(new, "new unit name")
    return f'{_DTT_VERBS["rename_unit"]} {old} {new}'

def cmd_change_unit_type(unit: str, new_class: str) -> str:
    _require_ident(unit, "unit name")
    _require_ident(new_class, "new class")
    return f'{_DTT_VERBS["change_unit_class"]} {unit} {new_class}'

def cmd_remove_stream(stream_id: str) -> str:
    _require_ident(stream_id, "stream id")
    return f'{_DTT_VERBS["remove_stream"]} {stream_id}'

def cmd_set_stream_flow(stream_id: str, q_m3d: float) -> str:
    _require_ident(stream_id, "stream id")
    if q_m3d is None:
        raise ValueError("q_m3d is required")
    return f'{_DTT_VERBS["set_stream_q"]} {stream_id} {float(q_m3d)}'

def cmd_remove_controller(ctrl_id: str) -> str:
    _require_ident(ctrl_id, "controller id")
    return f'{_DTT_VERBS["remove_controller"]} {ctrl_id}'

def cmds_modify_controller(ctrl_id: str,
                           setpoint: Optional[float] = None,
                           gain: Optional[float] = None,
                           integral_time: Optional[float] = None,
                           output_min: Optional[float] = None,
                           output_max: Optional[float] = None) -> List[str]:
    """Controllers expose tunable parameters as SumoCore variables; we just
    set them. The exact suffixes can vary by controller class — common ones
    are SP/Kp/Ti/uMin/uMax. Adjust _CTRL_SUFFIX if your build uses different
    names; this is the only place that matters."""
    _require_ident(ctrl_id, "controller id")
    out: List[str] = []
    mapping = (
        ("SP",   setpoint),
        ("Kp",   gain),
        ("Ti",   integral_time),
        ("uMin", output_min),
        ("uMax", output_max),
    )
    for sfx, val in mapping:
        if val is None:
            continue
        out.append(
            f"set Sumo__Plant__{ctrl_id}__param__{sfx} {float(val)}")
    if not out:
        raise ValueError("No controller field provided to modify.")
    return out

# ---------------------------------------------------------------------------
# Edit-transaction primitives (state.xml snapshot ring).
# Snapshots live alongside the active state.xml; commit retires them; rollback
# replaces state.xml with the snapshot. Pure file ops — DTT is reset in the
# server wrapper via initialize_state-like behaviour after a rollback.
# ---------------------------------------------------------------------------
def tx_begin(state_xml_path: str, label: str = "edit") -> Dict[str, Any]:
    if not os.path.isfile(state_xml_path):
        return {"ok": False, "error": f"state.xml not found at {state_xml_path}"}
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = _slug(label)
    snap = f"{state_xml_path}.tx_{ts}_{safe}.bak"
    shutil.copy2(state_xml_path, snap)
    tx_id = os.path.basename(snap)
    return {"ok": True, "tx_id": tx_id, "snapshot_path": snap,
            "state_xml": state_xml_path, "label": label, "created": ts}

def tx_list(state_xml_path: str) -> Dict[str, Any]:
    folder = os.path.dirname(state_xml_path) or "."
    base = os.path.basename(state_xml_path)
    snaps: List[Dict[str, Any]] = []
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            if fn.startswith(base + ".tx_") and fn.endswith(".bak"):
                full = os.path.join(folder, fn)
                snaps.append({"tx_id": fn,
                              "snapshot_path": full,
                              "size_bytes": os.path.getsize(full),
                              "mtime": _dt.datetime.fromtimestamp(
                                  os.path.getmtime(full)).isoformat()})
    return {"transactions": snaps, "count": len(snaps)}

def tx_commit(state_xml_path: str, tx_id: str,
              keep_snapshot: bool = False) -> Dict[str, Any]:
    snap = _resolve_snapshot(state_xml_path, tx_id)
    if not snap:
        return {"ok": False, "error": f"tx_id not found: {tx_id}"}
    if not keep_snapshot:
        try:
            os.remove(snap)
            return {"ok": True, "tx_id": tx_id, "snapshot_removed": True}
        except OSError as e:
            return {"ok": False, "error": f"could not remove snapshot: {e!r}"}
    return {"ok": True, "tx_id": tx_id, "snapshot_kept": snap}

def tx_rollback(state_xml_path: str, tx_id: str) -> Dict[str, Any]:
    snap = _resolve_snapshot(state_xml_path, tx_id)
    if not snap:
        return {"ok": False, "error": f"tx_id not found: {tx_id}"}
    try:
        # also back up the current state.xml before overwriting it
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        side = f"{state_xml_path}.preRollback_{ts}.bak"
        if os.path.isfile(state_xml_path):
            shutil.copy2(state_xml_path, side)
        shutil.copy2(snap, state_xml_path)
        return {"ok": True, "restored_from": snap,
                "previous_state_backup": side,
                "note": "Re-initialise the DTT state in the server wrapper "
                        "(initialize_state) so in-memory matches disk."}
    except OSError as e:
        return {"ok": False, "error": f"rollback failed: {e!r}"}

def _resolve_snapshot(state_xml_path: str, tx_id: str) -> Optional[str]:
    folder = os.path.dirname(state_xml_path) or "."
    full = os.path.join(folder, tx_id)
    return full if os.path.isfile(full) else None

# ---------------------------------------------------------------------------
# Batch dispatcher — validation + structured planning only; the server runs
# the commands.
# ---------------------------------------------------------------------------
_FORBIDDEN_TOKENS = ("rm ", "del ", ";", "&&", "|", "exec(", "eval(")

def plan_command_batch(commands: List[str],
                       allow_raw: bool = False) -> Dict[str, Any]:
    """Vet a list of DTT command strings. Returns a plan the server can
    dispatch with ds.sumo.executeCommand(line) per entry."""
    if not isinstance(commands, list) or not commands:
        return {"ok": False, "error": "commands must be a non-empty list"}
    cleaned: List[str] = []
    rejected: List[Dict[str, str]] = []
    for raw in commands:
        if not isinstance(raw, str):
            rejected.append({"command": repr(raw), "reason": "not a string"})
            continue
        line = raw.strip()
        if not line:
            continue
        if not allow_raw:
            low = line.lower()
            bad = next((t for t in _FORBIDDEN_TOKENS if t in low), None)
            if bad:
                rejected.append({"command": line,
                                 "reason": f"forbidden token {bad!r}; "
                                           f"set allow_raw=True to override"})
                continue
            # Sanity: every safe line should look like 'set ...' or be a known
            # DTT verb. Otherwise flag for human review.
            first = line.split(" ", 1)[0]
            known = first == "set" or first in _DTT_VERBS.values()
            if not known:
                rejected.append({"command": line,
                                 "reason": f"unknown verb {first!r}; "
                                           f"set allow_raw=True to override"})
                continue
        cleaned.append(line)
    return {"ok": bool(cleaned), "planned": cleaned,
            "rejected": rejected, "count": len(cleaned),
            "rejected_count": len(rejected)}

# ---------------------------------------------------------------------------
# in-memory ↔ disk diff (manifest level)
# ---------------------------------------------------------------------------
def diff_units_streams(live_units: List[str],
                       live_streams: List[str],
                       manifest_summary: Dict[str, Any]) -> Dict[str, Any]:
    """live_* come from list_unit_processes / list_flow_streams in-memory.
    manifest_summary is what sumo_compiler.read_sumo_manifest() returns."""
    disk_units = set(manifest_summary.get("unit_ids")
                     or manifest_summary.get("units") or [])
    disk_streams = set(manifest_summary.get("stream_ids")
                       or manifest_summary.get("connections") or [])
    live_u = set(live_units or [])
    live_s = set(live_streams or [])
    units_only_live = sorted(live_u - disk_units)
    units_only_disk = sorted(disk_units - live_u)
    streams_only_live = sorted(live_s - disk_streams)
    streams_only_disk = sorted(disk_streams - live_s)
    in_sync = not any([units_only_live, units_only_disk,
                       streams_only_live, streams_only_disk])
    return {"in_sync": in_sync,
            "units_only_in_memory": units_only_live,
            "units_only_on_disk":   units_only_disk,
            "streams_only_in_memory": streams_only_live,
            "streams_only_on_disk":   streams_only_disk,
            "live_unit_count":   len(live_u),
            "disk_unit_count":   len(disk_units),
            "live_stream_count": len(live_s),
            "disk_stream_count": len(disk_streams)}

# ---------------------------------------------------------------------------
# manifest helpers (read-only on the .sumo zip)
# ---------------------------------------------------------------------------
def read_controllers_from_manifest(sumo_path: str) -> Dict[str, Any]:
    """Best-effort enumeration of <controller> entries in manifest.xml.
    Used as a fallback when DTT does not expose a controller-list API."""
    if not os.path.isfile(sumo_path):
        return {"ok": False, "error": f".sumo not found: {sumo_path}"}
    out: List[Dict[str, Any]] = []
    try:
        with zipfile.ZipFile(sumo_path, "r") as zf:
            if "manifest.xml" not in zf.namelist():
                return {"ok": False, "error": "manifest.xml missing in .sumo"}
            with zf.open("manifest.xml") as fh:
                tree = ET.parse(fh)
        root = tree.getroot()
        for c in root.iter():
            tag = c.tag.lower()
            if "controller" in tag:
                rec = {"tag": c.tag}
                rec.update({k: v for k, v in c.attrib.items()})
                out.append(rec)
    except (zipfile.BadZipFile, ET.ParseError) as e:
        return {"ok": False, "error": f"manifest parse failed: {e!r}"}
    return {"ok": True, "controllers": out, "count": len(out)}

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _require_ident(s: Any, label: str) -> None:
    if not isinstance(s, str) or not s.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if any(ch in s for ch in (" ", "\t", "\n", ";", "|", "&")):
        raise ValueError(f"{label} contains forbidden whitespace/shell char: {s!r}")

def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(s))[:40] or "tx"
```

After creating the file:

```bash
python -m py_compile dtt_editor.py && echo "dtt_editor.py OK"
python -c "import dtt_editor as d; print('exports:', [x for x in dir(d) if not x.startswith('_')])"
```

---

## 4. APPEND TO `server.py` — import block

Locate the existing module-import region (lines such as
`import sumo_compiler as _scc` and, if Group EE was applied,
`import template_bridge as _tbr`). **Immediately after** that region, append:

```python
# ---- Group FF: DTT-mediated .sumo editing --------------------------------
try:
    import dtt_editor as _dte
    DTT_EDITOR_AVAILABLE = True
except Exception as _e_dte:  # pragma: no cover
    _dte = None
    DTT_EDITOR_AVAILABLE = False
    _DTE_IMPORT_ERROR = repr(_e_dte)
# --------------------------------------------------------------------------
```

---

## 5. APPEND TO `server.py` — twelve `types.Tool(...)` definitions

Find the **last existing `types.Tool(...)`** definition. Append these **after
it**, inside the same list, matching the existing indentation and
trailing-comma style (**R2**: copy `inputSchema` style from neighbours).

```python
    types.Tool(
        name="rename_unit_process",
        description="Rename a unit process in the loaded .sumo model via DTT "
                    "executeCommand. References to the old name in streams and "
                    "controllers are updated by SUMO; the live model is "
                    "modified in memory. Persist with save_model when done.",
        inputSchema={
            "type": "object",
            "properties": {
                "old_name": {"type": "string"},
                "new_name": {"type": "string"},
                "dry_run":  {"type": "boolean", "default": False},
            },
            "required": ["old_name", "new_name"],
        },
    ),
    types.Tool(
        name="change_unit_type",
        description="Change the class of an existing unit (e.g. Generic "
                    "PrimaryClarifier -> Otterpohl) via DTT. Use with care: "
                    "incompatible class swaps will be rejected by the solver. "
                    "dry_run returns the planned DTT command without "
                    "dispatching.",
        inputSchema={
            "type": "object",
            "properties": {
                "unit_name": {"type": "string"},
                "new_class": {"type": "string",
                    "description": "Target SUMO class name (consult "
                                   "list_available_unit_process_types)."},
                "dry_run":   {"type": "boolean", "default": True},
            },
            "required": ["unit_name", "new_class"],
        },
    ),
    types.Tool(
        name="remove_flow_connection",
        description="Delete a stream from the loaded model via DTT. The "
                    "complement to modify_flow_connection / connect_unit_"
                    "processes. dry_run returns the planned command.",
        inputSchema={
            "type": "object",
            "properties": {
                "stream_id": {"type": "string"},
                "dry_run":   {"type": "boolean", "default": False},
            },
            "required": ["stream_id"],
        },
    ),
    types.Tool(
        name="set_stream_flow_rate",
        description="Set a fixed flow rate (m3/d) on an existing stream via "
                    "DTT — used for RAS/WAS/IR loops or any fixed-Q stream.",
        inputSchema={
            "type": "object",
            "properties": {
                "stream_id": {"type": "string"},
                "q_m3d":     {"type": "number"},
                "dry_run":   {"type": "boolean", "default": False},
            },
            "required": ["stream_id", "q_m3d"],
        },
    ),
    types.Tool(
        name="list_controllers",
        description="List controllers (DO / SRT / NH4 / NO3 / FlowSplitter) "
                    "in the loaded model. Tries DTT enumeration first; falls "
                    "back to the manifest.xml of the on-disk .sumo if DTT "
                    "doesn't expose a list API.",
        inputSchema={
            "type": "object",
            "properties": {
                "sumo_path": {"type": "string",
                    "description": "Optional .sumo path for the fallback "
                                   "manifest read."},
            },
        },
    ),
    types.Tool(
        name="modify_controller",
        description="Modify an existing controller via DTT — setpoint, gain, "
                    "integral time, output min/max. Any field left null is "
                    "left unchanged. Use list_controllers first to confirm "
                    "the controller id.",
        inputSchema={
            "type": "object",
            "properties": {
                "controller_id": {"type": "string"},
                "setpoint":      {"type": "number"},
                "gain":          {"type": "number"},
                "integral_time": {"type": "number"},
                "output_min":    {"type": "number"},
                "output_max":    {"type": "number"},
                "dry_run":       {"type": "boolean", "default": False},
            },
            "required": ["controller_id"],
        },
    ),
    types.Tool(
        name="remove_controller",
        description="Remove a control loop from the loaded model via DTT. "
                    "Complement to add_controller.",
        inputSchema={
            "type": "object",
            "properties": {
                "controller_id": {"type": "string"},
                "dry_run":       {"type": "boolean", "default": False},
            },
            "required": ["controller_id"],
        },
    ),
    types.Tool(
        name="begin_edit_transaction",
        description="Snapshot the current state.xml so a series of DTT edits "
                    "can be rolled back if anything goes wrong. Returns a "
                    "tx_id. Pair with commit_edit_transaction or "
                    "rollback_edit_transaction.",
        inputSchema={
            "type": "object",
            "properties": {
                "label": {"type": "string", "default": "edit"},
            },
        },
    ),
    types.Tool(
        name="commit_edit_transaction",
        description="Mark an edit transaction successful and (by default) "
                    "discard its snapshot. Keep_snapshot=True retains the "
                    "snapshot as a manual restore point.",
        inputSchema={
            "type": "object",
            "properties": {
                "tx_id":          {"type": "string"},
                "keep_snapshot":  {"type": "boolean", "default": False},
            },
            "required": ["tx_id"],
        },
    ),
    types.Tool(
        name="rollback_edit_transaction",
        description="Restore the state.xml saved by begin_edit_transaction "
                    "and re-initialise the in-memory model so DTT and disk "
                    "agree. Backs the rolled-back state.xml aside as "
                    "preRollback_*.bak.",
        inputSchema={
            "type": "object",
            "properties": {
                "tx_id": {"type": "string"},
            },
            "required": ["tx_id"],
        },
    ),
    types.Tool(
        name="apply_dtt_command_batch",
        description="Dispatch a vetted list of DTT command strings against "
                    "the loaded model. Default mode rejects shell-injection "
                    "tokens and any non-`set`/non-DTT verb; allow_raw=True "
                    "bypasses vetting for power users. dry_run returns the "
                    "planned commands without execution.",
        inputSchema={
            "type": "object",
            "properties": {
                "commands":  {"type": "array", "items": {"type": "string"}},
                "allow_raw": {"type": "boolean", "default": False},
                "dry_run":   {"type": "boolean", "default": True},
            },
            "required": ["commands"],
        },
    ),
    types.Tool(
        name="diff_inmemory_vs_disk",
        description="Compare the live in-memory model (units + streams) "
                    "against the manifest of a .sumo on disk. Reports what "
                    "needs save_model / reload to bring them into sync.",
        inputSchema={
            "type": "object",
            "properties": {
                "sumo_path": {"type": "string"},
            },
            "required": ["sumo_path"],
        },
    ),
```

---

## 6. APPEND TO `server.py` — twelve dispatch handlers

Find the existing `# Unknown tool` block (the final
`return ... f"Unknown tool: {name}"`). Append these **immediately before it**,
matching the existing dispatch style exactly (**R2**):

```python
    elif name == "rename_unit_process":
        return await _exp_rename_unit_process(arguments)
    elif name == "change_unit_type":
        return await _exp_change_unit_type(arguments)
    elif name == "remove_flow_connection":
        return await _exp_remove_flow_connection(arguments)
    elif name == "set_stream_flow_rate":
        return await _exp_set_stream_flow_rate(arguments)
    elif name == "list_controllers":
        return await _exp_list_controllers(arguments)
    elif name == "modify_controller":
        return await _exp_modify_controller(arguments)
    elif name == "remove_controller":
        return await _exp_remove_controller(arguments)
    elif name == "begin_edit_transaction":
        return await _exp_begin_edit_transaction(arguments)
    elif name == "commit_edit_transaction":
        return await _exp_commit_edit_transaction(arguments)
    elif name == "rollback_edit_transaction":
        return await _exp_rollback_edit_transaction(arguments)
    elif name == "apply_dtt_command_batch":
        return await _exp_apply_dtt_command_batch(arguments)
    elif name == "diff_inmemory_vs_disk":
        return await _exp_diff_inmemory_vs_disk(arguments)
```

> If existing handlers are **synchronous**, drop `await` here and `async` in
> Section 7 to match (**R2**).

---

## 7. APPEND TO `server.py` — twelve `_exp_*` helpers

Append after the **last existing `_exp_*`** function, before `main()`.

**R1:** replace every `_RETURN(payload)` with the **exact return mechanism**
the last existing `_exp_*` uses (e.g.
`return _text(json.dumps(payload, default=str))` or
`return [types.TextContent(type="text", text=json.dumps(payload, default=str))]`).

**R3:** the helper that produces a DTT scheduler (commonly `_make_ds()`) — use
that **same identifier** wherever `_DS()` appears below.

**R4:** the state.xml path constant — replace `_STATE_XML` below with the
server's existing reference (commonly `CONFIG["state_xml"]`).

```python
def _dte_guard():
    if not DTT_EDITOR_AVAILABLE:
        return {"ok": False, "error": "dtt_editor not loaded",
                "detail": globals().get("_DTE_IMPORT_ERROR", "unknown")}
    return None


def _dispatch_dtt(commands):
    """Execute a list of DTT command strings via the existing bridge."""
    ds = _DS()                       # R3: replace with the project's helper
    log = []
    for c in commands:
        try:
            ds.sumo.executeCommand(c)
            log.append({"command": c, "ok": True})
        except Exception as e:
            log.append({"command": c, "ok": False, "error": repr(e)})
            return log, False
    return log, True


async def _exp_rename_unit_process(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    try:
        cmd = _dte.cmd_rename_unit(args["old_name"], args["new_name"])
    except ValueError as e:
        return _RETURN({"ok": False, "error": str(e)})
    if args.get("dry_run", False):
        return _RETURN({"ok": True, "planned": [cmd], "dispatched": False})
    log, ok = _dispatch_dtt([cmd])
    return _RETURN({"ok": ok, "log": log,
                    "note": "Persist with save_model when satisfied."})


async def _exp_change_unit_type(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    try:
        cmd = _dte.cmd_change_unit_type(args["unit_name"], args["new_class"])
    except ValueError as e:
        return _RETURN({"ok": False, "error": str(e)})
    if args.get("dry_run", True):
        return _RETURN({"ok": True, "planned": [cmd], "dispatched": False,
                        "warning": "Class swaps can invalidate the model; "
                                   "validate_full_model after dispatch."})
    log, ok = _dispatch_dtt([cmd])
    return _RETURN({"ok": ok, "log": log})


async def _exp_remove_flow_connection(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    try:
        cmd = _dte.cmd_remove_stream(args["stream_id"])
    except ValueError as e:
        return _RETURN({"ok": False, "error": str(e)})
    if args.get("dry_run", False):
        return _RETURN({"ok": True, "planned": [cmd], "dispatched": False})
    log, ok = _dispatch_dtt([cmd])
    return _RETURN({"ok": ok, "log": log})


async def _exp_set_stream_flow_rate(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    try:
        cmd = _dte.cmd_set_stream_flow(args["stream_id"], args["q_m3d"])
    except ValueError as e:
        return _RETURN({"ok": False, "error": str(e)})
    if args.get("dry_run", False):
        return _RETURN({"ok": True, "planned": [cmd], "dispatched": False})
    log, ok = _dispatch_dtt([cmd])
    return _RETURN({"ok": ok, "log": log})


async def _exp_list_controllers(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    # Try DTT enumeration via search_variables (controllers expose __param__
    # variables under their id) — best-effort, then fall back to manifest.
    found = []
    try:
        ds = _DS()
        names = ds.sumo.getVariableNames()  # existing DTT idiom
        prefix = "Sumo__Plant__"
        for n in names:
            if "__param__SP" in n and n.startswith(prefix):
                ctrl = n[len(prefix):].split("__param__")[0]
                if ctrl not in found:
                    found.append(ctrl)
    except Exception:
        found = []
    if found:
        return _RETURN({"ok": True, "source": "DTT",
                        "controllers": sorted(found), "count": len(found)})
    sp = args.get("sumo_path")
    if sp:
        res = _dte.read_controllers_from_manifest(sp)
        res["source"] = "manifest_fallback"
        return _RETURN(res)
    return _RETURN({"ok": False,
                    "error": "DTT enumeration empty and no sumo_path "
                             "provided for manifest fallback."})


async def _exp_modify_controller(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    try:
        cmds = _dte.cmds_modify_controller(
            args["controller_id"],
            setpoint=args.get("setpoint"),
            gain=args.get("gain"),
            integral_time=args.get("integral_time"),
            output_min=args.get("output_min"),
            output_max=args.get("output_max"))
    except ValueError as e:
        return _RETURN({"ok": False, "error": str(e)})
    if args.get("dry_run", False):
        return _RETURN({"ok": True, "planned": cmds, "dispatched": False})
    log, ok = _dispatch_dtt(cmds)
    return _RETURN({"ok": ok, "log": log})


async def _exp_remove_controller(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    try:
        cmd = _dte.cmd_remove_controller(args["controller_id"])
    except ValueError as e:
        return _RETURN({"ok": False, "error": str(e)})
    if args.get("dry_run", False):
        return _RETURN({"ok": True, "planned": [cmd], "dispatched": False})
    log, ok = _dispatch_dtt([cmd])
    return _RETURN({"ok": ok, "log": log})


async def _exp_begin_edit_transaction(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    return _RETURN(_dte.tx_begin(_STATE_XML, args.get("label", "edit")))


async def _exp_commit_edit_transaction(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    return _RETURN(_dte.tx_commit(
        _STATE_XML, args["tx_id"],
        keep_snapshot=bool(args.get("keep_snapshot", False))))


async def _exp_rollback_edit_transaction(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    res = _dte.tx_rollback(_STATE_XML, args["tx_id"])
    if res.get("ok"):
        # Re-initialise DTT state so the in-memory model matches the restored
        # state.xml. Reuse the existing initialize_state behaviour.
        try:
            # If the project exposes a helper, call it; otherwise mark for
            # the user to call initialize_state manually.
            if "_reinit_state" in globals():
                _reinit_state()                       # type: ignore[name-defined]
                res["reinitialised"] = True
            else:
                res["reinitialised"] = False
                res["next_step"] = "Call initialize_state to sync DTT."
        except Exception as e:
            res["reinitialised"] = False
            res["reinit_error"] = repr(e)
    return _RETURN(res)


async def _exp_apply_dtt_command_batch(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    plan = _dte.plan_command_batch(args["commands"],
                                   allow_raw=bool(args.get("allow_raw", False)))
    if args.get("dry_run", True) or not plan.get("ok"):
        plan["dispatched"] = False
        return _RETURN(plan)
    log, ok = _dispatch_dtt(plan["planned"])
    plan["dispatched"] = True
    plan["ok"] = ok
    plan["log"] = log
    return _RETURN(plan)


async def _exp_diff_inmemory_vs_disk(args):
    g = _dte_guard()
    if g: return _RETURN(g)
    if not globals().get("_scc") or not hasattr(_scc, "read_sumo_manifest"):
        return _RETURN({"ok": False,
                        "error": "sumo_compiler.read_sumo_manifest missing"})
    man = _scc.read_sumo_manifest(args["sumo_path"])
    # Pull the live in-memory enumeration via the project's existing helpers.
    try:
        live_units = list(_list_unit_processes_inmemory())   # may be a helper
    except Exception:
        # Fallback: empty enumeration (the report still has value via disk side)
        live_units = []
    try:
        live_streams = list(_list_flow_streams_inmemory())
    except Exception:
        live_streams = []
    res = _dte.diff_units_streams(live_units, live_streams, man)
    res["ok"] = True
    return _RETURN(res)
```

> **Two project-specific helpers referenced above** —
> `_list_unit_processes_inmemory` and `_list_flow_streams_inmemory` — are the
> internal Python equivalents of the existing `list_unit_processes` /
> `list_flow_streams` tools. If they don't already exist under those names,
> replace each `try/except` with the actual one-liner those tools use to
> enumerate units/streams from the live DTT scheduler. Both fall back to
> empty lists if enumeration fails, so the diff still produces useful output.

---

## 8. Save, compile, restart

```bash
python -m py_compile server.py && echo "server.py compiles OK (post-insert)"
python -c "import ast; ast.parse(open('server.py',encoding='utf-8').read()); print('AST OK')"
```

Restart the MCP host. Expected new tool count: **previous + 12**. Expected
groups list now includes **FF — SUMO File Editing via DTT**.

---

## 9. Verification prompts (run in the MCP client after restart)

| # | Prompt | Pass criterion |
|---|--------|----------------|
| 1 | "Rename AerationTank1 to AT1_north (dry run)." | Returns `planned` with one `renameUnit` command, `dispatched` false. |
| 2 | "Change PrimaryClarifier1 to class Otterpohl (dry run)." | Returns `planned` command + the class-swap warning. |
| 3 | "Begin an edit transaction labelled 'test_edits'." | Returns `tx_id` + snapshot path under outputs/. |
| 4 | "List controllers in the current model." | DTT path returns controller ids; if empty, manifest fallback works given a sumo_path. |
| 5 | "Modify controller DO_AT1: set setpoint 1.8 (dry run)." | Returns one or more `set Sumo__Plant__DO_AT1__param__SP 1.8` line. |
| 6 | "Apply DTT batch ['set Sumo__Plant__AerationTank1__param__DOsp 2.2'] dry run." | `planned` count 1, `rejected` 0. |
| 7 | "Apply DTT batch ['rm -rf /'] dry run." | `planned` 0, `rejected` 1 with a forbidden-token reason. |
| 8 | "Diff in-memory vs disk for F:/.../my_plant.sumo." | `in_sync` true or a structured list of differences. |
| 9 | "Rollback transaction <tx_id from #3>." | `ok` true; state.xml replaced; previous backed up as preRollback_*.bak. |
| 10 | "Commit transaction <tx_id>." | After rollback the tx_id no longer exists → returns clear `tx_id not found`. Try commit on a fresh begin → snapshot is removed. |
| 11 | "Remove stream S_RAS (dry run)." | Returns `removeStream S_RAS` planned. |
| 12 | "Set stream S_RAS flow to 12000 m3/d (dry run)." | Returns `setStreamFlow S_RAS 12000.0` planned. |

---

## 10. Rollback (this entire deliverable)

If anything fails: delete the appended import block, the 12 `types.Tool`
definitions, the 12 dispatch lines, the 12 `_exp_*` functions, and delete
`dtt_editor.py`. No existing code was changed, so removing the appended
content fully restores the previous server revision.

---

## 11. Known caveats & follow-up tasks (separate deliverables)

1. **DTT verb names.** `_DTT_VERBS` and the controller `__param__` suffixes
   are conventional best-guesses. After the first dispatch run, confirm them
   against the SUMO Core Window output and adjust only that single block in
   `dtt_editor.py`. Until confirmed, prefer `dry_run=True` for tools 1-7 and
   inspect the planned command strings.
2. **PDF regeneration.** Add Group FF to `build_pdf_v*.py` classifier + ORDER
   + title-page text (`previous_count + 12` tools, revision bumped).
3. **Smoke test.** A `smoke_test_ff.py` mirroring `smoke_test_dd.py` should
   cover: command-string assembly, batch vetting (including forbidden-token
   rejection), transaction begin/commit/rollback against a temp state.xml,
   and the diff helper against a synthetic manifest.
4. **Group renaming.** If Group EE has not been applied, run a single
   search-and-replace in this file (`FF` → `EE`, `dtt_editor` → unchanged) and
   re-apply.
