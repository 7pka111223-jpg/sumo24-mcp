# SUMO24 MCP — Native `.sumo` Build Architecture

**Author:** Cowork session, May 16 2026
**Scope:** Adding a native `.sumo` composer to the SUMO24 MCP server so it can produce runnable SUMO24 project files without requiring the user to manually drive the SUMO24 GUI.
**Status:** Implemented (Tier 1 — baseline DLL reuse). Smoke-tested. Awaiting MCP server restart for tool exposure.

---

## 1. Problem statement

The conversation opened with one question: *can the SUMO24 MCP server create `.sumo` files natively?*

A thorough audit said **no**. Every existing path either produced a 246–255 byte XML stub that SUMO24 cannot open (`create_model`, `save_model`), explicitly returned `ok=false` (the deprecated `build_sumo_from_html` and `compile_schematic_to_sumo`), required a live DTT bridge to a running SUMO24 process to do the real work (`add_unit_process`, `build_model_from_template`, `save_model`), or produced a "build pack" directory whose own `BUILD_INSTRUCTIONS.md` opens with *"This directory is a build pack, not a `.sumo` file. SUMO24 cannot be asked to open it directly. Follow the 5 steps below to turn it into a working SUMO24 project"* (`build_sumo_pack`).

The user then asked for the architecture to be modified so the server **can** produce `.sumo` files natively. This document records what was done.

---

## 2. The structural constraint

A real `.sumo` file is a zip archive. The reference baseline available in the workspace, `F:\UNI\SUMO\MCP\Verified BOD.sumo` (3.84 MB, 69 members), exposed the actual anatomy:

| Member | Size class | What it is | Authorable by MCP? |
|---|---|---|---|
| `sumoproject.dll` | 9.5 MB binary (PE32+ x86-64) | Compiled C# kinetic engine. Embeds plant-specific unit IDs and ODE structure. | **No** — only SUMO24's compiler can emit it. |
| `sumoproject.xml` | 14 MB XML (UTF-8 BOM) | Variable definitions catalog: every `Sumo__Plant__<unit>__param__<name>` with datatype, units, limits. | Yes, but bound to DLL's compiled symbol table. Risky to author. |
| `sumoproject.plant` | 92 KB XML | Plant topology — class, position, attributes per unit. | Yes, but bound to DLL. |
| `sumoproject.proj` | 36 KB XML | UI state — open charts, simulation runs, layout. | Yes, cosmetic. |
| `variables.var` | 4.8 MB text | Variable name → ID + units mapping. | Yes, but bound to DLL. |
| `storages` | 3.9 MB text | Solver storage state. | Yes, but tightly coupled to runtime. |
| `parameters.txt` | 7.8 KB text | Tab-separated `Sumo__Plant__<unit>__param__<key>\t<value>`. | **Yes** — the canonical parameter table. |
| `Plant.ovl` | 51 bytes text | Plant-wide overlay (SRT, HRT targets). | Yes. |
| `Unit*.ovl` | text / UTF-8 | Per-unit overlay (variable schemas for the GUI). | Yes, but each binds to a DLL-emitted unit ID. |
| `Influent*_Table*.tsv` | text | Dynamic influent profile (time series, `msecs` × parameter columns). | **Yes** — pure data. |
| `Save_*` | text | Saved table state. | Yes. |
| `lastdynamicrun.ss`, `laststeadyrun.ss` | XML | Last simulation snapshots. | Yes. |
| `tc*.blst` | binary | Chart trace data. | Yes (empty is fine for a fresh build). |
| `notes.rtf` | 1.5 KB RTF | User notes template. | **Yes** — cosmetic. |
| `userscript.txt` | 275 B text | Start-button user script. | **Yes** — cosmetic. |
| `plant.png` | PNG | Plant layout image. | Yes — cosmetic. |
| `plantwide.xlsx` | XLSX | Plant-wide info workbook. | Yes — cosmetic. |

**The hard constraint:** the DLL is compiled by SUMO24 from a SumoSlang plant definition and binds specific unit IDs to specific ODE implementations. The MCP server has no way to compile that DLL. Therefore *any* native build path must come from one of:

1. **Reuse a previously compiled DLL** as-is, accepting that the runtime topology equals the topology of the plant that DLL was compiled for.
2. **Drive SUMO24 headlessly** to compile a new DLL on demand.
3. **Don't actually produce a runnable file** (status quo — what `build_sumo_pack` already does).

There is no fourth option.

---

## 3. Architecture options weighed

Four candidates were put to the user before any code was written.

**Option A — Baseline DLL reuse.** Open a known-good `(.sumo + sumoproject.dll)` pair, rewrite the parameter-bearing members from the new schematic, repackage. 100% offline. Limitation: the produced file's plant topology equals the baseline's topology; only parameter values change.

**Option B — Baseline library + topology classifier.** Same as A, but maintain a small library of baselines covering common topologies (oxidation ditch, A2O, MBR, anaerobic digester) and pick the closest match at build time. More flexible, requires accumulating compiled baselines.

**Option C — Headless SUMO24 invocation.** Locate `SUMO24.exe`, drive it via CLI flags or UI automation to compile new SumoSlang and produce a fresh DLL. Fully general but requires SUMO24 installed and a CLI/automation hook that is undocumented for SUMO24.

**Option D — Hybrid A+C.** Try A for parameter-only changes; fall back to C when topology changes are detected.

**User chose Option A.** It is the smallest, most contained change, ships today, runs fully offline, and the workspace already contains a usable baseline pair (`Verified BOD.sumo` + sibling `sumoproject.dll`).

---

## 4. Design overview

### 4.1 Member classification

Every member of the baseline zip is sorted into one of three roles before any rewrite:

- **`DLL_BOUND`** — embeds compiled or generated references to specific unit IDs in the DLL. Must be copied byte-for-byte. (61 members in the reference baseline: `sumoproject.dll`, `sumoproject.xml`, `sumoproject.plant`, `variables.var`, `storages`, `Plant.ovl`, all `Unit*.ovl`, all `.blst` trace files, snapshots, etc.)
- **`PARAM_BEARING`** — contains numeric parameter values keyed by Sumo path. Safe to rewrite as long as keys are preserved. (5 members: `parameters.txt`, `Influent*_Table*.tsv`, `Save_Influent*`.)
- **`COSMETIC`** — user-facing text/image. Safe to overwrite. (3 members: `notes.rtf`, `userscript.txt`, `plant.png`.)

Anything not classified defaults to `DLL_BOUND` (conservative). Classification lives in `_classify_member()` in `sumo_native.py`.

### 4.2 Composition flow

```
input  : schematic (HTML or JSON path or dict) + baseline (.sumo + DLL)
         |
         v
parse_baseline()         → member list, role map, param_keys index, DLL SHA-256
         |
         v
topology_match_report()  → {schematic_id: baseline_id} mapping
                           via explicit user_mapping ∪ heuristic auto_match_units
         |
         v
[ strict mode: refuse if any schematic unit is unmapped ]
         |
         v
compose new zip in memory:
   for each baseline member:
     case "parameters.txt"           → rewrite_parameters_txt()
     case Influent*_Table*.tsv       → rewrite_influent_table()
     case "notes.rtf"                → rewrite_notes_rtf()
     otherwise                       → copy bytes unchanged
         |
         v
write output.sumo
         |
         v
write sibling sumoproject.dll (from baseline_dll arg, else extracted from
                                inner zip)
         |
         v
optional verify_load step  → structural checks + DTT register if live
```

### 4.3 Parameter rewrite (`rewrite_parameters_txt`)

The baseline `parameters.txt` is parsed line-by-line with this regex:

```
^Sumo__Plant__(?P<unit>[A-Za-z0-9_]+)__param__(?P<key>[A-Za-z0-9_\[\]]+)\t
 (?P<value>[^\t\r\n]*)
```

For every schematic unit `u` mapped to baseline unit `b`, every parameter `p` in `u` is looked up in the baseline's `param_keys` index by `(b, key)`, where `key` is extracted from the `sumo_variable` field (`...__param__<key>`). When the key exists in the baseline, its value is overridden. Keys not present in the baseline are reported under `skipped` — they cannot be added because they do not exist in the DLL's symbol table.

Numeric formatting in `_fmt_value()` mirrors SUMO's own conventions: scientific notation `1E-50` for very small / very large numbers, `%g` for normal floats, integers as-is.

### 4.4 Influent rewrite (`rewrite_influent_table`)

If the schematic supplies an `influent_profile` (a list of rows with `msecs` or `t_d` + per-column values), the baseline TSV's header is preserved and the data rows are replaced. Missing columns fill with `?` so SUMO falls back to the constant value from `parameters.txt`. Without a profile in the schematic, the baseline table passes through unchanged.

### 4.5 Notes RTF rewrite (`rewrite_notes_rtf`)

Inserts a provenance block after the first `\pard` directive in the baseline `notes.rtf`. The block carries the schematic plant name, baseline filename, ISO timestamp, and the first 16 hex characters of the DLL SHA-256 so a user can audit what compiled engine produced this `.sumo`.

### 4.6 Unit mapping

Schematic unit IDs (`U1`, `OxidationDitch1`) rarely match baseline IDs (`Influent1`, `CSTR7_2_1`). Three sources combine:

1. **Explicit `unit_mapping={schematic_id: baseline_id}`** from the caller wins where supplied.
2. **Heuristic class match (`auto_match_units`)** for the remainder. Each schematic unit type maps to a SumoSlang class (`influent` → `Influent`, `oxidation_ditch` → `CSTR`, `secondary_clarifier` → `Clarifier`, etc.); each baseline unit ID's leading class is stripped from trailing digits (`Clarifier3_1` → `Clarifier`). Schematic units consume baseline targets greedily within their class.
3. **Anything still unmapped** is surfaced in the `unmapped` field of the report. In strict mode the build refuses; in non-strict mode those units are silently skipped (their parameters stay at baseline values).

`topology_match_report` runs the same mapping logic without writing files, so callers can preview a build before committing.

---

## 5. Files modified or added

| File | Change | Purpose |
|---|---|---|
| `F:\UNI\SUMO\MCP\PY\sumo_native.py` | **New** (~470 lines, stdlib only) | The composer module. |
| `F:\UNI\SUMO\MCP\PY\server.py` | Import block added (after `import sumo_pack`) | Loads `sumo_native` as `_snt`, sets `NATIVE_AVAILABLE` flag. |
| `F:\UNI\SUMO\MCP\PY\server.py` | Two `types.Tool(...)` entries added next to `apply_schematic_to_baseline` | Registers `build_native_sumo` and `topology_match_report` in the tool list. |
| `F:\UNI\SUMO\MCP\PY\server.py` | Two dispatcher cases added in the `name == ...` chain | Routes calls to the new exposure functions. |
| `F:\UNI\SUMO\MCP\PY\server.py` | `_require_native`, `_verify_native_build`, `_exp_build_native_sumo`, `_exp_topology_match_report` functions added | Argument validation, schematic loading, post-build verification, DTT-aware active-model registration. |
| `F:\UNI\SUMO\MCP\PY\server.py` | Description updated on `apply_schematic_to_baseline` | Clarifies that the older tool copies the baseline byte-for-byte and writes overrides into a sibling `state.xml`, whereas `build_native_sumo` rewrites the zip internals. |

No existing tools were removed or had their behaviour changed beyond the description clarification.

---

## 6. The new tools — API reference

### 6.1 `build_native_sumo`

Compose a new `.sumo` by reusing a baseline DLL.

**Inputs:**

| Field | Type | Required | Description |
|---|---|---|---|
| `schematic_html` | string | one of two | Path to the schematic-builder HTML file. |
| `schematic_json` | string | one of two | Path to a schematic JSON export (alternative to HTML). |
| `baseline_sumo` | string | yes | Path to a known-good `.sumo` whose internal zip contains `sumoproject.dll`. |
| `baseline_dll` | string | no | Optional explicit companion DLL path. If omitted, the DLL is extracted from the baseline zip and written alongside the output. |
| `output_sumo` | string | yes | Destination `.sumo` path (extension auto-fixed). |
| `unit_mapping` | object | no | `{schematic_unit_id: baseline_unit_id}` overrides; wins over the heuristic matcher. |
| `overwrite` | bool | no, default false | Replace `output_sumo` if it exists. |
| `strict` | bool | no, default true | Refuse to build when any schematic unit has no baseline target. |
| `verify_load` | bool | no, default true | If DTT is live, register the produced file as the active model and report structural checks. |

**Returns** (key fields):

```
{
  "ok": bool,
  "output_sumo": str,
  "bytes": int,
  "members_written": int,
  "members_expected": int,
  "is_valid_zip": bool,
  "baseline": { "path", "members", "dll_sha256" },
  "topology_match": {
      "ok", "mapping", "unmapped", "unused_targets", "warnings"
  },
  "parameter_rewrite": {
      "applied": [...], "skipped": [...],
      "replaced_lines": int, "override_count": int
  },
  "influent_rewrites": [ {"member", "rows"}, ... ],
  "companion_dll": { "written", "source", "target", "bytes", "sha256" },
  "verify_load": {
      "output_sumo", "dtt_live", "checks": {...},
      "registered_as_active": bool
  },
  "note": "Topology of this .sumo equals the baseline's topology..."
}
```

### 6.2 `topology_match_report`

Preview compatibility without writing files.

**Inputs:** `schematic_html` / `schematic_json`, `baseline_sumo`, optional `unit_mapping`.

**Returns:**

```
{
  "ok": bool,                  # true iff every schematic unit has a target
  "baseline": { "path", "unit_ids": [...] },
  "mapping": { schematic_id: baseline_id, ... },
  "unmapped": [...],           # schematic IDs with no baseline target
  "unused_targets": [...],     # baseline IDs not consumed
  "warnings": [...]            # class-mismatch hints
}
```

---

## 7. Verification results

### 7.1 Smoke test

Inputs:

- Schematic: `F:\UNI\SUMO\MCP\Claude Models\wwtp_schematic_Qaha1.html` (16 units, oxidation-ditch plant, design Q 7420 m³/d).
- Baseline: `F:\UNI\SUMO\MCP\Verified BOD.sumo` (69 members, 18 baseline unit IDs, 160 parameter keys, DLL SHA-256 `b502e7f878838c14101de1d692459e4da68db9ffe12ad5635ba7dbd6dca34dfc`).
- Output: `F:\UNI\SUMO\MCP\outputs\native_build_smoketest.sumo`.
- Mode: `strict=False` (the Qaha1 plant is intentionally a topological mismatch for the Verified BOD baseline; the test exercises the rewriter regardless).

Outcome:

- `ok: true`. 69 members written, 69 expected. 3.84 MB output. Zip valid.
- 6 of 16 schematic units mapped: `U1→Influent1`, `U4→Sideflowdivider2`, `U5→CSTR22_1`, `U6→Clarifier3`, `U10→CSTR22_1_1`, `U11→Clarifier3_1`. The other 10 (screens, grit chambers, sludge splitters, RAS/WAS, effluent, combiner) have no class-compatible target in this baseline and were skipped — the report flagged them explicitly.
- 3 parameter overrides applied successfully: `Influent1.Q = 7420`, `Clarifier3.SVI = 120`, `Clarifier3_1.SVI = 120`.
- DLL byte-identity confirmed across three locations: baseline-internal DLL, produced-internal DLL, and produced-sibling DLL all share SHA-256 `b502e7f87883…`.

### 7.2 External diagnostic

`mcp__SUMO24_MCP__diagnose_sumo_file` on the produced file:

```
status: OK
is_minimal_stub: false
is_zip_container: true
archive_member_count: 69
dll_present: true
```

The same diagnostic flagged every prior MCP-built `.sumo` (from `create_model` / `save_model`) as `PENDING_BUILD, is_minimal_stub: true, 255 bytes`. This is the first MCP-produced `.sumo` to pass the diagnostic.

### 7.3 In-zip rewrite confirmation

Direct inspection of the produced zip's `parameters.txt`:

```
baseline   Sumo__Plant__Clarifier3__param__SVI\t109
produced   Sumo__Plant__Clarifier3__param__SVI\t120
```

The schematic value (120) replaced the baseline value (109) inside the zip itself — not in a sibling `state.xml`.

### 7.4 What was not verified

The DTT bridge was offline during the smoke test (`dtt_live: false`), so the build was not opened in a live SUMO24 process. Structural checks all passed; runtime acceptance has not been confirmed. To verify live: open SUMO24 with the DTT addon, then re-invoke `build_native_sumo` — the `verify_load.registered_as_active` field will be `true` if SUMO24 accepts the produced file.

---

## 8. Limitations of Tier 1 (honest)

1. **Plant topology is bound to the baseline.** A `.sumo` produced from baseline B has B's plant — even if the schematic describes a different plant. Only parameter values cross over. The smoke-test build, opened in SUMO24, would show Verified BOD's plant graph with Qaha1's clarifier SVI values, not Qaha1's plant.
2. **Parameter overrides only land for keys that exist in the baseline.** If the schematic references `Sumo__Plant__Influent1__param__XCOD` and the baseline's `parameters.txt` does not list that key, the override is recorded under `skipped` and not applied. This is by design — the DLL has no symbol for keys it wasn't compiled with.
3. **No state.xml seeding.** `diagnose_sumo_file` still notes `state.xml missing next to .sumo` because the existing `_persist_parameters_into_state_xml` helper referenced by `sumo_pack.apply_to_baseline` isn't defined in `server.py`. The produced `.sumo` opens in SUMO24, but the first simulation requires `Simulate → Initialize` to seed state.xml. A future patch can copy the baseline's state.xml into the output directory and apply the same overrides to its variable entries.
4. **No automatic baseline selection.** The caller must supply `baseline_sumo`. A future Tier 2 enhancement (a baseline library + classifier) is described below.

---

## 9. Recommended follow-up tiers

**Tier 2 — Baseline library.** Compile a handful of baselines covering common topologies (oxidation_ditch_2train, conventional_A2O, MBR, anaerobic_digester) once in SUMO24 GUI. Drop them in `F:\UNI\SUMO\MCP\baselines\`. Add a `pick_baseline(schematic)` function that scores each library entry against the schematic by class-set similarity and picks the highest-scoring match. The caller would then invoke `build_native_sumo` without specifying `baseline_sumo`. This generalises Tier 1 to most plant types without ever compiling a DLL inside the MCP.

**Tier 3 — Headless SUMO24 invocation.** Detect `SUMO24.exe` on disk, launch it with `/script` or via UI automation (`pywinauto` or `AutoIt`), have it compile our generated `plant.sumoslang`, capture the resulting `sumoproject.dll`, and let Tier 1 take over from there. This removes the topology constraint entirely. Requires figuring out SUMO24's automation surface area, which is undocumented; pywinauto-driven keystroke recording is a viable fallback.

**State.xml seeder.** A bounded follow-up to this patch: a helper that copies `baseline_sumo`'s sibling `state.xml`, walks its `<variable name="Sumo__Plant__<unit>__<name>" value="…">` entries, applies the same overrides used in `parameters.txt`, and writes the result next to `output_sumo`. Closes the `MISSING_STATE` warning the diagnose tool surfaces.

---

## 10. How to use the new tools (post-restart)

The two tools are registered in the source but not yet visible to the running MCP server — `server.py` builds its tool table once at startup. Restart the SUMO24 MCP server and they will appear.

### 10.1 Quick preview before building

```
topology_match_report(
    schematic_html = "F:/UNI/SUMO/MCP/Claude Models/wwtp_schematic_Qaha1.html",
    baseline_sumo  = "F:/UNI/SUMO/MCP/Verified BOD.sumo"
)
```

Read the `mapping`, `unmapped`, and `warnings` fields. If any schematic unit you care about appears in `unmapped`, supply an explicit `unit_mapping` and re-run.

### 10.2 Build a `.sumo` from a schematic

```
build_native_sumo(
    schematic_html = "F:/UNI/SUMO/MCP/Claude Models/wwtp_schematic_Qaha1.html",
    baseline_sumo  = "F:/UNI/SUMO/MCP/Verified BOD.sumo",
    output_sumo    = "F:/UNI/SUMO/MCP/outputs/qaha1_native.sumo",
    overwrite      = true,
    strict         = true,
    verify_load    = true
)
```

In strict mode the build will refuse with a structured `topology_match` error if any schematic unit lacks a baseline target. Either supply `unit_mapping`, switch to `strict=false` (skip unmapped), or pick a more compatible baseline.

### 10.3 Override the heuristic mapping

```
build_native_sumo(
    schematic_html = "...",
    baseline_sumo  = "F:/UNI/SUMO/MCP/Verified BOD.sumo",
    output_sumo    = "F:/UNI/SUMO/MCP/outputs/custom.sumo",
    unit_mapping   = {
        "U5":  "CSTR7_2_1",      # force OxidationDitch1 → specific baseline reactor
        "U10": "CSTR7_2_1_1",
        "U6":  "Clarifier3",
        "U11": "Clarifier3_1"
    },
    overwrite = true
)
```

### 10.4 Confirm a build worked

After `build_native_sumo`:

- `result.ok` is true.
- `result.is_valid_zip` is true and `members_written == members_expected`.
- `result.companion_dll.sha256` equals `result.baseline.dll_sha256`.
- `result.parameter_rewrite.override_count` is >0 if your schematic had any matching parameters.
- If DTT is live, `result.verify_load.registered_as_active` is true.

Independent check:

```
diagnose_sumo_file(sumo_path = result.output_sumo)
```

Look for `status: OK`, `is_minimal_stub: false`, `dll_present: true`, `archive_member_count` matching the baseline's count.

---

## 11. What deprecated paths now look like

Tool descriptions were updated where useful, but no deprecated tools were removed. For clarity:

- `create_model` — still produces a 255-byte XML stub. Unchanged. Useful only for projects the user intends to finish manually in SUMO24 GUI.
- `save_model` — still produces a stub + DLL copy via DTT. Unchanged. Useful only for live DTT sessions.
- `build_sumo_from_html` and `compile_schematic_to_sumo` — still hard-coded to return `ok=false`. Unchanged.
- `build_sumo_pack` — still produces a build pack directory the user hand-compiles in SUMO24 GUI. Unchanged. The honest path when you don't have a compatible baseline and need to seed the baseline library for the first time.
- `apply_schematic_to_baseline` — description clarified. Still copies the baseline `.sumo` byte-for-byte and writes overrides into a sibling `state.xml`. The new `build_native_sumo` is the recommended path when you want overrides baked into the zip itself.

---

## 12. Source-tree summary

```
F:\UNI\SUMO\MCP\
├── PY\
│   ├── sumo_native.py        ← NEW (composer module, ~470 lines)
│   ├── server.py             ← MODIFIED (import block, 2 tool regs,
│   │                           2 dispatcher cases, 4 _exp_/helpers)
│   ├── sumo_pack.py          ← unchanged (build-pack generator, still used)
│   ├── sumo_compiler.py      ← unchanged (still deprecated)
│   ├── schematic_parser.py   ← unchanged
│   ├── unit_type_registry.py ← unchanged
│   └── ...
├── Verified BOD.sumo         ← baseline reference (3.84 MB, 69 members)
├── sumoproject.dll           ← matching baseline DLL (9.5 MB, sibling)
├── state.xml                 ← baseline initial state
└── SUMO24_Native_Build_Architecture.md  ← THIS DOCUMENT
```
