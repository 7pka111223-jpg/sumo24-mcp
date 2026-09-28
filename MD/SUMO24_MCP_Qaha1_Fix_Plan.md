# SUMO24 MCP — Qaha1 Follow-Up Fix Plan

**Subject:** Sharp edges exposed by the Qaha1 build session that the MCP server should handle automatically instead of forcing the user to diagnose and patch by hand.

**Context:** The previous fix plan (`SUMO24_MCP_Fix_Plan.md`) landed — `build_sumo_pack` and `apply_schematic_to_baseline` are live, and `build_sumo_from_html` / `compile_schematic_to_sumo` are marked DEPRECATED in their descriptions. The Qaha1 session used `build_sumo_pack` successfully **after** working around six separate issues that the server should have caught earlier. This document targets those six.

**Author:** Diagnostic follow-up, 2026-05-14.
**Target files:** `PY/server.py`, `PY/sumo_pack.py`, `PY/schematic_parser.py`, `PY/unit_type_registry.py`, `PY/sumo_compiler.py`, `wwtp_schematic_template.html`, `PY/template_generator.py` (or wherever `generate_wwtp_template_xlsx` lives).

---

## 1. Executive Summary

The Qaha1 session reached a working deliverable but only after six distinct workarounds. Each is a place where the server returned `ok=True` (or a warning the user had to interpret correctly), when it should have either refused, auto-fixed, or guided.

| # | Symptom in the Qaha1 session | What the server should have done | Severity |
|---|---|---|---|
| 1 | A 29.8 KB hand-rolled `Qaha1.sumo` got written and `diagnose_sumo_file` returned `ok=True` with three warnings the user had to interpret. | Deprecated paths must **refuse**, not just warn in their description. `diagnose_sumo_file` must distinguish a minimal-stub from a malformed project. | **Critical** |
| 2 | `build_sumo_pack` failed late with `Unit U3 has unsupported type 'grit_chamber'`. The HTML builder's palette doesn't expose `grit_chamber` at all — the value came from a manual edit. | Either add `grit_chamber` to the registry properly, **or** validate the schematic at parse time so the failure happens before any artefact is written. | **High** |
| 3 | `sumoproject.dll` and `state.xml` were **copied from a different model save** (`model_save_20260511_113853`) and placed next to `Qaha1.sumo`. The DLL's symbol table doesn't match the Qaha1 topology, so the project will not actually simulate. | A `verify_dll_matches_schematic` check that compares DLL exports against the schematic's variable references and refuses to declare success when they don't match. | **Critical** |
| 4 | `validate_wwtp_template` returned 22 identical errors ("from_unit='NA' not present") because the Connections sheet shipped empty. | The Excel template generator should ship with the Connections sheet pre-populated with a worked example, plus data-validation dropdowns sourced from Treatment_Processes. | **High** |
| 5 | A regex replace on the HTML matched inside an HTML comment, removed the `<style>` block and `<body>` tag, and required a full file reconstruction. | A dedicated `update_schematic_in_html` tool that edits the JSON block by SAX/AST, never by string regex. | **High** |
| 6 | The session ran `build_model_from_template` in offline mode, generated 89 commands into a sidecar file the user has no easy way to apply, and recorded "0 failed actions" as if that meant the model was built. | Offline mode must (a) explicitly label its output as "build script, not built model", (b) fold the 89 commands into the build-pack's `apply_parameters.scs` so the user has **one** file to paste, not two. | **Medium** |

---

## 2. Per-Issue Diagnosis & Fix

### Issue 1 — Deprecated paths still produce files; `diagnose_sumo_file` reports "ok"

**What happened.** The Qaha1 session produced a 29,790-byte `Qaha1.sumo` with a hand-written `<SumoProject version="24.0" schema="2024.1">` schema. SUMO refused to open it. `diagnose_sumo_file` returned:

```json
{
  "ok": true,
  "warnings": [
    "sumoproject.dll companion missing — MISSING_DLL",
    "state.xml missing next to .sumo — MISSING_STATE",
    "Manifest parsed but 0 units found — EMPTY_MANIFEST"
  ]
}
```

Two failure modes are tangled here:

- **`ok=True` with serious warnings is wrong.** `MISSING_DLL` on its own is fatal — without the DLL, SUMO can't open the file. `ok=True` masks this.
- **`EMPTY_MANIFEST` means two different things now.** It was originally a "this file is broken" signal; the new build-pack workflow produces minimal stubs that *legitimately* have zero units (units come later, from SUMO GUI). The session author had to interpret the same warning as "expected and correct" in the working case and "fatal" in the broken case — same warning, opposite meaning.

**Fix.**

1. **Tighten `ok` semantics.** `ok=True` only when the file would actually load in SUMO. Otherwise `ok=False` with a single `reason` field, and the warnings become `details`. `MISSING_DLL` → `ok=False`. `MISSING_STATE` next to a real (non-stub) `.sumo` → `ok=False`.

2. **Detect the stub workflow explicitly.** Add a new check `is_minimal_stub` that returns True iff:
   - file is XML (not zip),
   - root is `<SumoProject>` with `name` and `version` attributes,
   - file size ≤ 1 KB,
   - no `<Unit>` / `<Param>` / `<Stream>` children.

   When `is_minimal_stub` is True, replace `EMPTY_MANIFEST` with `PENDING_BUILD` and report:

   ```
   "status": "PENDING_BUILD",
   "next_step": "Open this stub in SUMO24 GUI and follow BUILD_INSTRUCTIONS.md from the matching .sumo-pack/ directory.",
   "pack_dir_found": "<path or null>"
   ```

3. **Make deprecated tools refuse, not warn.** The previous fix plan marked four tools as `[DEPRECATED — ...]` in their description strings. The Qaha1 session shows that descriptions alone don't stop usage — a hand-rolled XML was produced anyway, presumably by a bash script that bypassed the MCP. There's only so much the server can do about external scripts, but at minimum the deprecated tools themselves should now **return `ok=False`** unconditionally with a redirect to `build_sumo_pack`:

   ```python
   async def _exp_compile_schematic_to_sumo(args):
       return json.dumps({
           "ok": False,
           "deprecated": True,
           "reason": "This tool produces a zip SUMO24 cannot load.",
           "use_instead": "build_sumo_pack",
           "migration": "Replace `compile_schematic_to_sumo(...)` with `build_sumo_pack(output_dir=...)` in your script.",
       })
   ```

   Same treatment for `build_sumo_from_html`, `attach_companion_dll`, `verify_sumo_file_against_schematic`. Keep `read_sumo_manifest` working (it's safe — it only reads legacy artefacts).

### Issue 2 — `grit_chamber` not in the registry; failure happens late

**What happened.** `build_sumo_pack` validated the schematic, generated SumoSlang for 15 of 16 units, then aborted at U3 with `Unit U3 has unsupported type 'grit_chamber' for SumoSlang generation`. The HTML builder doesn't expose `grit_chamber` in its palette — the value got into the schematic JSON by manual edit or template import. The user "fixed" it by renaming the type to `screen`, which is wrong: a grit chamber is hydraulically and biologically different from a fine screen.

**Fix.**

1. **Add `grit_chamber` to the unit registry properly.** It's a real WWTP unit and SUMO models it. Add to `PY/unit_type_registry.py`:

   ```python
   UNIT_TYPES["grit_chamber"] = {
       "category": "pretreatment",
       "label": "Grit Chamber",
       "kind": "Pretreatment",
       "color": "#7e8a8b",
       "sumo_template": "Sumo__Plant__GritChamber",
       "sumo_unit_class": "PointSettler",
       "parameters": {
           "V":          {"value": 50, "unit": "m³",   "sumo": "param__V",    "desc": "Chamber volume"},
           "removalTSS": {"value": 0.10, "unit": "–", "sumo": "param__rTSS", "desc": "TSS (grit) removal fraction"},
       },
   }
   ```

   And mirror the entry in `wwtp_schematic_template.html`'s `UNIT_TYPES` object so it appears in the palette.

   Add the matching SumoSlang block to `_sumoslang_unit_block` in `PY/sumo_pack.py`:

   ```python
   if t == "grit_chamber":
       return f'pointsettler {uid} {{ name = "{name}"; role = grit_removal; }}'
   ```

2. **Fail-fast validation.** Add `validate_schematic` as a standalone tool, called by `build_sumo_pack` before any file is written:

   ```python
   def validate_schematic(schematic):
       errors, warnings = [], []
       known = set(UNIT_TYPES.keys())
       for u in schematic.get("units", []):
           if u.get("type") not in known:
               # Suggest the closest match by edit distance
               from difflib import get_close_matches
               hint = get_close_matches(u.get("type",""), known, n=1, cutoff=0.5)
               errors.append({
                   "unit_id": u["id"],
                   "bad_type": u.get("type"),
                   "suggestion": hint[0] if hint else None,
                   "all_known_types": sorted(known),
               })
       return {"ok": not errors, "errors": errors, "warnings": warnings}
   ```

   And in `build_pack`:

   ```python
   def build_pack(schematic, output_dir, overwrite=False):
       v = validate_schematic(schematic)
       if not v["ok"]:
           return {"ok": False, "stage": "validate", **v}   # do not create the output dir
       # ... rest unchanged
   ```

   With this, the Qaha1 case would have returned at the validate step:

   ```json
   {"ok": false, "stage": "validate", "errors": [
     {"unit_id": "U3", "bad_type": "grit_chamber",
      "suggestion": "grit_chamber",        // (now valid after registry add)
      "all_known_types": ["aerobic_zone", "anaerobic_digester", ...]}]}
   ```

3. **Expose `list_schematic_unit_types` results in the build-pack error path.** When `build_pack` fails with an unknown type, the response should include the full list of known types so the user doesn't have to call a second tool.

### Issue 3 — Copied DLL doesn't match the topology

**What happened.** The session writes:

> `sumoproject.dll` (9,534,464 bytes) copied from `model_save_20260511_113853`

`model_save_20260511_113853` is a previous, different plant. The DLL contains a compiled symbol table for *that* plant's unit names and parameter variables. When SUMO opens `Qaha1.sumo` next to this DLL, every variable reference in `state.xml` either misses (`Sumo__Plant__OxidationDitch1_T1__param__V` not in DLL → null) or — worse — accidentally collides with a similarly named variable from the old plant. Either way the simulation results are meaningless.

The previous fix plan flagged `attach_companion_dll` as deprecated for this reason. The Qaha1 session bypassed that tool and used `Copy-Item` directly in PowerShell, so the deprecation never fired.

**Fix.** Add a positive verification tool the user is encouraged to run before opening anything in SUMO:

```python
# new tool in server.py
types.Tool(
    name="verify_dll_matches_schematic",
    description=(
        "Inspect a sumoproject.dll's exported symbols and check that every "
        "sumo_variable referenced by the schematic exists in the DLL. Catches "
        "the common error of copying a DLL from one plant into another plant's "
        "directory — the file copy succeeds but the DLL has no idea what "
        "OxidationDitch1_T1 means and the project will load empty."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "dll_path":   {"type": "string"},
            "schematic_html": {"type": "string"},
            "schematic_json": {"type": "string"},
        },
        "required": ["dll_path"],
    },
),
```

The handler reads the DLL's export table and the schematic's parameter list, compares them, and returns:

```python
async def _exp_verify_dll_matches_schematic(args):
    dll_path = args["dll_path"]
    schematic = _resolve_schematic(args)

    # Parse DLL exports — Windows .dll uses PE COFF; pefile is the lightest dep.
    # If pefile isn't installed, fall back to dumpbin or a heuristic readstrings.
    exports = _read_dll_symbols(dll_path)

    refs = set()
    for u in schematic.get("units", []):
        for p in u.get("parameters", []):
            if p.get("sumo_variable"):
                refs.add(p["sumo_variable"])

    missing = sorted(refs - exports)
    extra_in_dll = len(exports - refs)   # informational only — DLL almost always has more

    return json.dumps({
        "ok": not missing,
        "dll_path": dll_path,
        "refs_in_schematic": len(refs),
        "refs_resolved": len(refs - set(missing)),
        "missing": missing[:20],
        "missing_total": len(missing),
        "dll_export_count": len(exports),
        "hint": ("DLL appears to be for a different plant" if missing else "DLL symbols cover the schematic")
    }, indent=2)
```

`_read_dll_symbols` should try `pefile` first (recommended dep — add to `requirements.txt`), fall back to a strings-based heuristic that greps the binary for `Sumo__Plant__*` substrings. The strings heuristic is good enough for the symbol-name check we need.

Also extend `validate_sumo_environment` to run this check automatically when both a baseline DLL and a baseline schematic are configured.

### Issue 4 — Excel Connections sheet ships empty

**What happened.** `generate_wwtp_template_xlsx` produces a workbook where the Connections sheet contains 22 rows of `NA`. Users fill in Treatment_Processes and try to build, then `validate_wwtp_template` errors out because none of the connections resolve. The error message lists the same problem 22 times.

**Fix.**

1. **Ship the Connections sheet with a worked example, not NA.** Pre-populate row 2 with a single illustrative connection and a comment cell explaining the format:

   ```python
   # in generate_wwtp_template_xlsx
   ws_conn = wb["Connections"]
   ws_conn.cell(2, 1).value = "Influent"          # from_unit
   ws_conn.cell(2, 2).value = "Screen1"           # to_unit
   ws_conn.cell(2, 3).value = "RawWW"             # stream_name
   ws_conn.cell(2, 4).value = "process"           # stream_type
   ws_conn.cell(2, 5).value = ""                  # recycle_type
   ws_conn.cell(2, 1).comment = openpyxl.comments.Comment(
       "Must match instance_name in Treatment_Processes exactly. "
       "Delete this example row only after adding your own.", "MCP"
   )
   # Leave rows 3-22 EMPTY (not NA) so they don't fail validation.
   ```

2. **Add data-validation dropdowns** sourced from the Treatment_Processes `instance_name` column so users can't type a name that doesn't exist:

   ```python
   from openpyxl.worksheet.datavalidation import DataValidation
   dv = DataValidation(type="list",
                       formula1=f"=Treatment_Processes!$B$2:$B$50",
                       allow_blank=True)
   ws_conn.add_data_validation(dv)
   dv.add("A2:A100")   # from_unit column
   dv.add("B2:B100")   # to_unit column
   ```

3. **Auto-suggest in `validate_wwtp_template`.** When a connection references a unit not in Treatment_Processes, the validator should check whether that name appears in the **schematic** (cross-source) or is one of the canonical boundary names (`WAS`, `RAS`, `Effluent`, `Influent`) and offer to add it:

   ```python
   if to_unit not in known_units:
       suggestion = None
       if to_unit in {"WAS", "RAS"}:
           suggestion = {
               "action": "add_to_treatment_processes",
               "instance_name": to_unit,
               "process_type": f"{to_unit}_Flow",
               "category": "physical",
               "stage": "effluent",
           }
       errors.append({"row": row_idx, "issue": f"to_unit='{to_unit}' not in Treatment_Processes",
                      "auto_fix": suggestion})
   ```

   Pair this with a new tool `apply_template_auto_fixes(template_path, fixes=[...])` that applies the suggestions in place. This was the manual fix the Qaha1 session had to script.

4. **Collapse duplicate errors.** 22 identical errors about NA rows is not informative. The validator should group:

   ```json
   {"errors": [
     {"issue": "from_unit blank or NA", "rows": [2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23], "count": 22}
   ]}
   ```

### Issue 5 — HTML editing destroyed the file with a regex

**What happened.** The session ran a regex replace looking for `<script id="schematic-data"`. This substring appears first inside an HTML comment near the top of the file (the docblock explaining what the script tag is for), so the regex matched there and the replacement removed the `<style>`, `<body>`, and the actual `<script>` tag in one swoop. The file had to be reconstructed by hand.

**Fix.** Add a server-side tool that does the JSON-block edit safely. The right parsing technique here is **not** regex — it's a one-pass HTML scanner that:

1. Locates `<script id="schematic-data" type="application/json">` as a real element (open angle, lowercase `script`, attributes in any order, **outside any comment**),
2. Replaces only the text between `>` and `</script>`,
3. Validates the new content is JSON parseable before writing,
4. Validates the post-edit file still contains `<style`, `<body`, and the canonical builder functions (`buildStateJSON`, `persistState`, `loadFromJSON`) before saving.

```python
# new tool
types.Tool(
    name="update_schematic_in_html",
    description=(
        "Safely replace the embedded schematic JSON inside a schematic-builder "
        "HTML file. Uses a one-pass tag-aware scanner that ignores HTML comments "
        "(unlike a regex on the raw text, which can match inside <!-- ... --> and "
        "destroy the file). Validates JSON before writing, validates structural "
        "tags after writing, and aborts if either check fails."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "html_path":     {"type": "string"},
            "schematic_json":{"type": "string", "description": "Either a JSON string or a path to a .json file."},
            "backup":        {"type": "boolean", "default": True},
        },
        "required": ["html_path", "schematic_json"],
    },
),
```

Implementation (sketch — full version goes in `PY/html_schematic_io.py`):

```python
import re, json, shutil, pathlib

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r'<script\s+id="schematic-data"\s+type="application/json"\s*>(.*?)</script>', re.DOTALL)

def update_schematic_in_html(html_path, new_json_text, backup=True):
    raw = pathlib.Path(html_path).read_text(encoding="utf-8")

    # 1. Strip comments from a *copy* so we can find the real tag without
    #    matching inside <!-- ... -->. Track offsets so we can write back into
    #    the original.
    stripped = _COMMENT_RE.sub(lambda m: " " * len(m.group(0)), raw)

    m = _TAG_RE.search(stripped)
    if not m:
        raise ValueError("No <script id='schematic-data' type='application/json'> tag found outside comments.")

    # 2. Validate the new JSON before touching disk.
    json.loads(new_json_text)

    # 3. Splice into the *original* raw string at the same offsets.
    start, end = m.start(1), m.end(1)
    new_raw = raw[:start] + "\n" + new_json_text.strip() + "\n" + raw[end:]

    # 4. Post-edit structural sanity.
    for required in ("<style", "<body", "buildStateJSON", "persistState", "loadFromJSON"):
        if required not in new_raw:
            raise ValueError(f"Post-edit file lost required marker: {required!r}; refusing to save.")

    # 5. Backup + write.
    if backup:
        shutil.copy2(html_path, html_path + ".bak")
    pathlib.Path(html_path).write_text(new_raw, encoding="utf-8")
    return {"ok": True, "bytes_written": len(new_raw),
            "backup": (html_path + ".bak") if backup else None}
```

The comment-stripping step is the key. Doing it on a length-preserving copy means the offsets we recover from the regex still point at the right place in the original.

### Issue 6 — Offline mode buries the commands in a sidecar file

**What happened.** `build_model_from_template` ran with `allow_offline=True`, dispatched **89 commands** (7 addprocess + 7 connect + 8 sizing + 8 influent + 17 fractionation + ...), and wrote them to a sidecar text file. The session log records `"0 failed actions"` as the success metric — but no model was actually built; the file just lists commands. The user has no easy way to apply those 89 commands later. They have to:
- find the file,
- open the SUMO Core Window,
- paste them in,
- and run them in order.

Meanwhile `build_sumo_pack` separately produced an `apply_parameters.scs` file with a different (overlapping) set of overrides. Two files, two formats, two manual paste steps.

**Fix.** Merge the two outputs.

1. **In offline mode, write the build commands into the build-pack's `apply_parameters.scs`**, not a separate sidecar. The `.scs` script already has the right format for the Core Window; offline-mode commands and parameter-override commands share that format. Merging them into one file gives the user one paste-and-go artefact.

2. **Refactor the return shape.** Offline mode currently returns:

   ```json
   {"ok": true, "planned": 89, "failed": 0, "commands_file": "build.commands.txt"}
   ```

   The `ok=true, failed=0` reads like a success. Change it to:

   ```json
   {
     "ok": true,
     "mode": "offline_script_generated",
     "model_built": false,
     "commands_emitted": 89,
     "next_step": "Open Qaha1.sumo-pack/apply_parameters.scs in SUMO24 Core Window after the SumoSlang plant compiles. No model has been built yet.",
     "merged_into": "Qaha1.sumo-pack/apply_parameters.scs"
   }
   ```

   `model_built: false` makes it unambiguous that the commands are not yet effective.

3. **Add a single guided-workflow tool** `next_step_for_project(project_dir)` that introspects the state of a project directory and tells the user what to do next:

   - no `.sumo` stub → "run `build_sumo_pack` first"
   - stub present, no DLL → "open `<stub>.sumo` in SUMO GUI and compile the SumoSlang"
   - stub + DLL, no `state.xml` → "in SUMO Core Window: `maptoic; save \"state.xml\";`"
   - stub + DLL + state.xml, no `apply_parameters.scs` run → "paste `apply_parameters.scs` into the Core Window"
   - all of the above present → "ready — call `run_steady_state`"

   This collapses the seven-step manual workflow into one tool call the user can run any time they're lost.

---

## 3. Concrete Edits for Cowork to Apply

Each block below is a copy-paste unit. Apply in order.

### 3.1 `PY/server.py` — turn deprecation warnings into refusals

Locate each of the four deprecated dispatch handlers (`_exp_compile_schematic_to_sumo`, `_exp_build_sumo_from_html`, `_exp_attach_companion_dll`, `_exp_verify_sumo_file_against_schematic`) and **replace the body** with the refusal pattern:

```python
async def _exp_compile_schematic_to_sumo(args: dict) -> str:
    return json.dumps({
        "ok": False,
        "deprecated": True,
        "reason": "This tool produced a zip SUMO24 cannot load.",
        "use_instead": "build_sumo_pack",
        "migration_hint": (
            "Replace `compile_schematic_to_sumo(schematic=..., output_path='x.sumo')` "
            "with `build_sumo_pack(schematic_html=..., output_dir='x.sumo-pack')`, "
            "then follow x.sumo-pack/BUILD_INSTRUCTIONS.md inside SUMO24 GUI."
        ),
    }, indent=2)


async def _exp_build_sumo_from_html(args: dict) -> str:
    return json.dumps({
        "ok": False,
        "deprecated": True,
        "reason": "This tool produced a zip SUMO24 cannot load.",
        "use_instead": "build_sumo_pack",
        "migration_hint": (
            "Replace `build_sumo_from_html(html_path=H, output_path='x.sumo')` "
            "with `build_sumo_pack(schematic_html=H, output_dir='x.sumo-pack')`."
        ),
    }, indent=2)


async def _exp_attach_companion_dll(args: dict) -> str:
    return json.dumps({
        "ok": False,
        "deprecated": True,
        "reason": (
            "Copying any sumoproject.dll next to a .sumo file does NOT make the "
            "file loadable — the DLL's symbol table is specific to the plant it "
            "was compiled from."
        ),
        "use_instead": "verify_dll_matches_schematic",
        "migration_hint": (
            "Run `verify_dll_matches_schematic(dll_path=..., schematic_html=...)` "
            "first. If it returns missing symbols, the DLL is the wrong one and "
            "needs to be regenerated by SUMO GUI from the build-pack SumoSlang."
        ),
    }, indent=2)


async def _exp_verify_sumo_file_against_schematic(args: dict) -> str:
    return json.dumps({
        "ok": False,
        "deprecated": True,
        "reason": "This tool only verified the legacy zip format that SUMO can't load.",
        "use_instead": "verify_dll_matches_schematic",
    }, indent=2)
```

Update the `description` in each `types.Tool(...)` definition to begin with `"[DEPRECATED — always returns ok=false. Use ... instead.]"` so the description and the behaviour agree.

### 3.2 `PY/server.py` — fix `_exp_diagnose_sumo_file`

Locate the existing `_exp_diagnose_sumo_file` handler. After the existing checks but before the return, insert:

```python
# Distinguish a minimal valid stub from a malformed file.
is_minimal_stub = (
    checks["size_bytes"] <= 1024
    and checks["looks_xml"]
    and not checks["is_zip_container"]
    and checks["heuristic_unit_count"] == 0
    and _root_is_sumoproject(path)   # add helper
)

# Look for an adjacent build pack.
pack_dir = None
parent = os.path.dirname(os.path.abspath(path))
for entry in os.listdir(parent):
    if entry.endswith(".sumo-pack") and os.path.isdir(os.path.join(parent, entry)):
        pack_dir = os.path.join(parent, entry)
        break

# Reclassify warnings → details, and set ok strictly.
ok = True
status = "OK"
reason = None

if is_minimal_stub:
    status = "PENDING_BUILD"
    # downgrade EMPTY_MANIFEST: not an error in this mode
    warnings = [w for w in warnings if "EMPTY_MANIFEST" not in w]
    # but still require the DLL to be present before the user opens it in SUMO
    if not checks["dll_present"]:
        ok = False
        reason = "stub present but sumoproject.dll missing — SUMO will not be able to open this"
else:
    if not checks["dll_present"]:
        ok = False
        reason = "sumoproject.dll companion missing — MISSING_DLL"
    elif checks["heuristic_unit_count"] == 0:
        ok = False
        reason = "non-stub .sumo has 0 units in manifest — file is malformed"

result = {
    "ok": ok,
    "status": status,
    "reason": reason,
    "is_minimal_stub": is_minimal_stub,
    "pack_dir_found": pack_dir,
    "details": warnings,    # renamed from "warnings"
    "checks": checks,
}
if is_minimal_stub and ok:
    result["next_step"] = (
        f"Open the stub in SUMO24 GUI. Then follow "
        f"{pack_dir}/BUILD_INSTRUCTIONS.md to compile the plant."
        if pack_dir else
        "Open the stub in SUMO24 GUI and build the plant manually, or call "
        "build_sumo_pack to generate the matching build-pack first."
    )
return json.dumps(result, indent=2)
```

Add the `_root_is_sumoproject` helper at module scope:

```python
def _root_is_sumoproject(path):
    """Cheap check: file's first 512 bytes contain <SumoProject ...>."""
    try:
        with open(path, "rb") as f:
            head = f.read(512).decode("utf-8", errors="replace")
        return "<SumoProject" in head
    except OSError:
        return False
```

### 3.3 `PY/unit_type_registry.py` — add `grit_chamber`

```python
UNIT_TYPES["grit_chamber"] = {
    "category": "pretreatment",
    "label": "Grit Chamber",
    "kind": "Pretreatment",
    "color": "#7e8a8b",
    "sumo_template": "Sumo__Plant__GritChamber",
    "sumo_unit_class": "PointSettler",
    "parameters": {
        "V":          {"value": 50,   "unit": "m³", "sumo": "param__V",    "desc": "Chamber volume"},
        "depth":      {"value": 2.0,  "unit": "m",  "sumo": "param__depth","desc": "Side water depth"},
        "removalTSS": {"value": 0.10, "unit": "–",  "sumo": "param__rTSS", "desc": "TSS (grit) removal fraction"},
    },
}
```

### 3.4 `wwtp_schematic_template.html` — mirror `grit_chamber` in the palette

Locate the `UNIT_TYPES` JS object near the top of the script block and add, in the **Pre-treatment** section right after `screen`:

```javascript
grit_chamber: {
    category: 'pretreatment', label: 'Grit Chamber', kind: 'Pretreatment',
    color: '#7e8a8b',
    sumo_template: 'Sumo__Plant__GritChamber', sumo_unit_class: 'PointSettler',
    parameters: {
        V:          { value: 50,   unit: 'm³', sumo: 'param__V',    desc: 'Chamber volume' },
        depth:      { value: 2.0,  unit: 'm',  sumo: 'param__depth',desc: 'Side water depth' },
        removalTSS: { value: 0.10, unit: '–',  sumo: 'param__rTSS', desc: 'TSS (grit) removal fraction' }
    }
},
```

(Both registries must stay in sync — `unit_type_registry.py` and the HTML `UNIT_TYPES` JS — or the schematic parser will reject what the builder accepted, which is exactly the trap that bit Qaha1.)

### 3.5 `PY/sumo_pack.py` — fail-fast schematic validation + grit_chamber block

At the top of the file, add `validate_schematic`:

```python
from difflib import get_close_matches
from unit_type_registry import UNIT_TYPES

def validate_schematic(schematic):
    errors, warnings = [], []
    known = set(UNIT_TYPES.keys())
    for u in schematic.get("units", []):
        t = u.get("type")
        if t not in known:
            hint = get_close_matches(t or "", known, n=1, cutoff=0.5)
            errors.append({
                "unit_id": u.get("id"),
                "bad_type": t,
                "suggestion": hint[0] if hint else None,
            })
    if not schematic.get("units"):
        errors.append({"issue": "schematic has no units"})
    if errors:
        return {"ok": False, "errors": errors,
                "all_known_types": sorted(known)}
    return {"ok": True}
```

In `build_pack`, insert at the very top:

```python
def build_pack(schematic, output_dir, overwrite=False):
    v = validate_schematic(schematic)
    if not v["ok"]:
        return {"ok": False, "stage": "validate", **v}
    # ... existing body unchanged
```

In `_sumoslang_unit_block`, after the `screen` case, add:

```python
if t == "grit_chamber":
    return f'pointsettler {uid} {{ name = "{name}"; role = grit_removal; }}'
```

### 3.6 `PY/server.py` — add `verify_dll_matches_schematic`

Add the tool definition (per §2 Issue 3 above) and the handler:

```python
async def _exp_verify_dll_matches_schematic(args: dict) -> str:
    dll_path = args["dll_path"]
    if not os.path.exists(dll_path):
        return json.dumps({"ok": False, "reason": f"DLL not found: {dll_path}"})
    schematic = _resolve_schematic(args) if (args.get("schematic_html") or args.get("schematic_json")) else None

    exports = _read_dll_symbols(dll_path)
    if schematic is None:
        return json.dumps({"ok": True, "mode": "exports_only",
                           "dll_export_count": len(exports),
                           "sample_exports": sorted(list(exports))[:20]}, indent=2)

    refs = set()
    for u in schematic.get("units", []):
        for p in u.get("parameters", []):
            sv = p.get("sumo_variable")
            if sv:
                refs.add(sv)

    missing = sorted(refs - exports)
    return json.dumps({
        "ok": not missing,
        "dll_path": dll_path,
        "refs_in_schematic": len(refs),
        "refs_resolved": len(refs - set(missing)),
        "missing": missing[:20],
        "missing_total": len(missing),
        "dll_export_count": len(exports),
        "verdict": ("DLL covers the schematic — appears compatible"
                    if not missing else
                    f"DLL is missing {len(missing)} variables the schematic references — "
                    "this DLL is for a DIFFERENT plant. Do not use it."),
    }, indent=2)


def _read_dll_symbols(dll_path):
    """Return the set of Sumo__Plant__* symbol names exported by the DLL."""
    try:
        import pefile
        pe = pefile.PE(dll_path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
        if not pe.DIRECTORY_ENTRY_EXPORT:
            return _read_dll_symbols_strings(dll_path)
        return {e.name.decode("utf-8", errors="replace")
                for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name}
    except Exception:
        return _read_dll_symbols_strings(dll_path)


def _read_dll_symbols_strings(dll_path):
    """Fallback: grep the binary for Sumo__Plant__* substrings."""
    import re
    with open(dll_path, "rb") as f:
        blob = f.read()
    return set(m.group(0).decode("ascii", errors="replace")
               for m in re.finditer(rb"Sumo__Plant__[A-Za-z0-9_]+", blob))
```

Add `pefile` to `requirements.txt` (optional dep — the strings fallback works without it).

### 3.7 `PY/template_generator.py` — pre-populate Connections and add dropdowns

Locate `generate_wwtp_template_xlsx` and the Connections-sheet setup block. Replace the `NA` filler with:

```python
# Connections sheet — ship with a worked example, NOT NA filler.
ws_conn.cell(2, 1).value = "Influent"
ws_conn.cell(2, 2).value = "Screen1"
ws_conn.cell(2, 3).value = "RawWW"
ws_conn.cell(2, 4).value = "process"
ws_conn.cell(2, 5).value = ""
ws_conn.cell(2, 1).comment = openpyxl.comments.Comment(
    "Example row. Replace with your plant's actual connections, or delete. "
    "from_unit and to_unit must EXACTLY match instance_name values in "
    "Treatment_Processes (case-sensitive).", "MCP"
)
# Leave rows 3+ truly empty (not NA) so validate_wwtp_template doesn't choke.

# Data validation: dropdowns sourced from Treatment_Processes.B2:B50
from openpyxl.worksheet.datavalidation import DataValidation
dv_unit = DataValidation(type="list",
                         formula1="=Treatment_Processes!$B$2:$B$50",
                         allow_blank=True,
                         showDropDown=False)
ws_conn.add_data_validation(dv_unit)
dv_unit.add("A2:A100")
dv_unit.add("B2:B100")

dv_stream = DataValidation(type="list",
                           formula1='"process,return_activated_sludge,waste_activated_sludge,internal_recycle,reject"',
                           allow_blank=True)
ws_conn.add_data_validation(dv_stream)
dv_stream.add("D2:D100")
```

### 3.8 `PY/server.py` — improve `_exp_validate_wwtp_template`

Inside the existing handler, group identical errors and add `auto_fix` suggestions:

```python
# After collecting raw_errors as a list of strings...
from collections import defaultdict
grouped = defaultdict(list)
for row_idx, msg in raw_errors:
    grouped[msg].append(row_idx)

errors = []
for msg, rows in grouped.items():
    entry = {"issue": msg, "rows": rows, "count": len(rows)}
    # auto-fix suggestions for the common cases
    if "not present in Treatment_Processes" in msg:
        name = msg.split("'")[1]   # extract the referenced name
        if name.upper() in {"WAS", "RAS"}:
            entry["auto_fix"] = {
                "action": "add_to_treatment_processes",
                "instance_name": name,
                "process_type": f"{name}_Flow",
                "category": "physical",
                "stage": "effluent" if name.upper() == "WAS" else "biological",
                "applied_by_tool": "apply_template_auto_fixes",
            }
    if msg.lower().startswith("connections: from_unit='na'"):
        entry["auto_fix"] = {
            "action": "clear_na_rows",
            "applied_by_tool": "apply_template_auto_fixes",
        }
    errors.append(entry)
```

Add a companion tool `apply_template_auto_fixes(template_path, fixes=[...])` that consumes those `auto_fix` blocks and rewrites the Excel in place.

### 3.9 `PY/html_schematic_io.py` (new) + tool registration

Create the new module with the `update_schematic_in_html` implementation from §2 Issue 5. Register the tool in `server.py` and add a dispatch handler:

```python
async def _exp_update_schematic_in_html(args: dict) -> str:
    import html_schematic_io as _hsi
    s = args["schematic_json"]
    # Accept either inline JSON or a path to a .json file.
    if s.endswith(".json") and os.path.exists(s):
        s = open(s, "r", encoding="utf-8").read()
    try:
        result = _hsi.update_schematic_in_html(
            html_path=args["html_path"],
            new_json_text=s,
            backup=bool(args.get("backup", True)),
        )
    except Exception as e:
        return json.dumps({"ok": False, "reason": str(e)})
    return json.dumps(result, indent=2)
```

### 3.10 `PY/server.py` — add `next_step_for_project`

```python
types.Tool(
    name="next_step_for_project",
    description=(
        "Inspect a project directory and tell the user exactly what to do next. "
        "Looks for the .sumo stub, the build-pack, the DLL, state.xml, and any "
        "applied-overrides marker, then returns a single recommended next action. "
        "Use this any time the workflow feels ambiguous — it collapses the "
        "5-step BUILD_INSTRUCTIONS.md and the apply-parameters step into one "
        "guided call."
    ),
    inputSchema={
        "type": "object",
        "properties": {"project_dir": {"type": "string"}},
        "required": ["project_dir"],
    },
),
```

Handler:

```python
async def _exp_next_step_for_project(args):
    d = pathlib.Path(args["project_dir"])
    if not d.is_dir():
        return json.dumps({"ok": False, "reason": f"not a directory: {d}"})

    sumo_stubs = list(d.glob("*.sumo"))
    pack_dirs  = list(d.glob("*.sumo-pack"))
    dll        = (d / "sumoproject.dll").is_file()
    state      = (d / "state.xml").is_file()
    applied    = (d / ".overrides_applied").is_file()  # write this marker after a successful Core Window paste

    if not sumo_stubs and not pack_dirs:
        return _step("call_build_sumo_pack",
                     "No .sumo stub or .sumo-pack found. Start with build_sumo_pack(schematic_html=..., output_dir='<plant>.sumo-pack').")
    if not sumo_stubs:
        return _step("open_pack_instructions",
                     f"Build pack found ({pack_dirs[0].name}) but no .sumo stub. "
                     f"Open {pack_dirs[0] / 'BUILD_INSTRUCTIONS.md'} and follow step 1.")
    if not dll:
        return _step("compile_in_sumo_gui",
                     f"Stub {sumo_stubs[0].name} present but no sumoproject.dll. "
                     "Open the stub in SUMO24 GUI, paste plant.sumoslang from the pack, "
                     "and click Compile. SUMO will write the DLL next to the stub.")
    if not state:
        return _step("save_state_in_core_window",
                     "DLL present but no state.xml. In SUMO24 Core Window run: maptoic; save \"state.xml\";")
    if not applied:
        return _step("paste_apply_parameters_scs",
                     "Topology compiled and state saved. Paste apply_parameters.scs into the Core Window "
                     "to apply your schematic's parameter values, then create the marker file "
                     ".overrides_applied to record completion.")
    return _step("ready",
                 "Project is fully built. You can now call run_steady_state, run_dynamic_simulation, etc.")


def _step(action, message):
    return json.dumps({"ok": True, "action": action, "message": message}, indent=2)
```

### 3.11 `PY/server.py` — fold offline commands into the pack

Locate the offline branch in `_exp_build_model_from_template`. Where it currently writes a sidecar `<base>.commands.txt`, change to append into the matching pack's `apply_parameters.scs`:

```python
# Existing: commands_path = output_path + ".commands.txt"
# Replace with:
pack_candidate = pathlib.Path(output_path).with_suffix(".sumo-pack")
if pack_candidate.is_dir():
    scs_path = pack_candidate / "apply_parameters.scs"
    with open(scs_path, "a", encoding="utf-8") as f:
        f.write("\n// --- appended by build_model_from_template (offline mode) ---\n")
        for cmd in commands:
            f.write(cmd.rstrip(";") + ";\n")
    merged_into = str(scs_path)
else:
    # No pack present — fall back to a sidecar, but make the next_step very explicit.
    commands_path = output_path + ".commands.txt"
    with open(commands_path, "w", encoding="utf-8") as f:
        f.write("\n".join(commands))
    merged_into = None

return json.dumps({
    "ok": True,
    "mode": "offline_script_generated",
    "model_built": False,    # crucial — was implicit before
    "commands_emitted": len(commands),
    "merged_into": merged_into,
    "next_step": (
        f"In SUMO24 Core Window, paste {merged_into}. No model has been built yet — "
        "this offline mode only generates the build script."
        if merged_into else
        "No matching .sumo-pack found. Run build_sumo_pack first, then re-run "
        "build_model_from_template so the commands can be merged into apply_parameters.scs."
    ),
}, indent=2)
```

---

## 4. Validation Plan

Run these in order after Cowork applies the edits.

1. **Tool count and boot.** `py -3 server.py` boots; tool count goes from **151** (post-previous-fix) to **155** with the additions: `verify_dll_matches_schematic`, `update_schematic_in_html`, `next_step_for_project`, `apply_template_auto_fixes`. The four deprecated tools remain registered but always return `ok=False`.

2. **Regression — the Qaha1 broken-file case.** Call `diagnose_sumo_file` on the legacy 29.8 KB `Qaha1.sumo` (still on disk per the session). Expected: `ok=False`, `reason="non-stub .sumo has 0 units in manifest — file is malformed"`. (Before this fix it returned `ok=True`.)

3. **Regression — the Qaha1 stub case.** Call `diagnose_sumo_file` on the working 498-byte `Qaha1\Qaha1.sumo`. Expected: `ok=True`, `status="PENDING_BUILD"`, `is_minimal_stub=True`, `pack_dir_found="...Qaha1.sumo-pack"`. (Before this fix it returned the same `ok=True` but with the misleading `EMPTY_MANIFEST` warning.)

4. **Schematic validation fail-fast.** Build a schematic with `type: "grit_chamber"` BEFORE applying the registry update. Call `build_sumo_pack`. Expected: returns at the `validate` stage with `suggestion: "screen"` or similar, **without creating the output directory**. Then apply the registry update; same call now succeeds.

5. **DLL-mismatch detection.** Call `verify_dll_matches_schematic(dll_path=<DLL from model_save_20260511_113853>, schematic_html=<Qaha1 schematic>)`. Expected: `ok=False`, `missing_total > 0`, `verdict="DLL is missing ... — this DLL is for a DIFFERENT plant. Do not use it."`

6. **Excel template hardening.** Generate a fresh template with `generate_wwtp_template_xlsx`. Open in Excel. Confirm: Connections sheet has one example row (not 22 NAs), from_unit/to_unit columns show dropdown arrows, stream_type column shows the five-option dropdown.

7. **HTML edit safety.** Take the Qaha1 HTML, call `update_schematic_in_html` with a modified schematic JSON. Confirm: `<style>`, `<body>`, and the canonical JS function names are still present in the output; `.bak` file exists; new JSON is loaded by the browser. (Repeat with a JSON that's syntactically invalid — confirm the tool refuses and doesn't touch the file.)

8. **Workflow guide.** From an empty directory, call `next_step_for_project`. Expected: `action="call_build_sumo_pack"`. Run `build_sumo_pack`. Call again. Expected: `action="open_pack_instructions"`. And so on through the chain.

9. **Offline mode merge.** Generate a build pack for Qaha1, then run `build_model_from_template` with `allow_offline=True`. Confirm: no `*.commands.txt` sidecar is created; `apply_parameters.scs` inside the pack now has an appended `// --- appended by build_model_from_template (offline mode) ---` section. The response includes `model_built: false` explicitly.

---

## 5. What the Qaha1 Workflow Looks Like After This Fix

For comparison with the documented session, here is the same workflow under the proposed server:

```
1. generate_wwtp_template_xlsx → ships with example Connections row + dropdowns
2. Fill in the template; validate_wwtp_template returns clean (or with auto_fix suggestions)
3. Build the HTML schematic; grit_chamber appears in the palette
4. update_schematic_in_html  → safe JSON-block replace, with backup
5. build_sumo_pack            → fails fast if any unit type is unknown
                              → writes the pack and a 498-byte .sumo stub
6. next_step_for_project      → tells you to open the stub in SUMO and compile
7. (In SUMO GUI: compile plant.sumoslang → save state.xml → paste apply_parameters.scs)
8. verify_dll_matches_schematic → confirms the freshly-compiled DLL matches
9. next_step_for_project      → "ready — call run_steady_state"
```

Compared with the Qaha1 session that ran this for the first time, the user no longer has to:
- guess that `grit_chamber` should be renamed to `screen`,
- hand-write or hand-copy a DLL from an unrelated model save,
- decide whether `EMPTY_MANIFEST` is fatal or expected,
- reconstruct a regex-damaged HTML file from JavaScript fragments,
- track two separate command files (`.commands.txt` and `apply_parameters.scs`),
- or interpret `0 failed actions` as success.

Each of those decisions is now handled by the server or refused with a clear redirect.

---

## 6. Out of Scope (Logged for Later)

- **A real `diagnose_sumo_file` round-trip via DTT.** Currently every diagnostic is heuristic on the file bytes. The only honest health check is "does SUMO load this file?" That requires a live DTT connection and is the same problem flagged in the previous plan's Tier-3 section. Defer.
- **Schematic-builder palette parity check.** A CI/lint script that diffs `unit_type_registry.py` against the HTML's `UNIT_TYPES` JS object on every commit and fails if they drift. Worth adding once Tier-2 is stable.
- **Auto-detection of competing `.sumo` files in the same directory.** The Qaha1 directory still has the legacy 29.8 KB file labelled "Do Not Use" next to the working 498-byte stub. A simple housekeeping tool `clean_project_dir` could quarantine the broken one. Low priority.

---

*End of follow-up plan. Apply edits in section 3 order. Validation plan in section 4 verifies the regression cases from the Qaha1 session itself.*
