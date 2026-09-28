# SUMO24 MCP — Bulletproof Multi-Stage WWTP Build Pipeline

**Subject:** Definitive architecture for Claude + Cowork to build SUMO24 WWTP models from an Excel data template + HTML schematic, end-to-end, with every prior failure mode designed out.

**Foundation documents:** Builds on `SUMO24_MCP_Fix_Plan.md` (the build-pack pivot) and `SUMO24_MCP_Qaha1_Fix_Plan.md` (the six follow-up sharp edges). Read those first; this plan assumes their edits are applied.

**Target:** `F:/UNI/SUMO/MCP/PY/server.py`, new modules under `F:/UNI/SUMO/MCP/PY/pipeline/`, additions to `unit_type_registry.py`, the HTML builder, and the Excel template generator.

**Author:** Master plan, 2026-05-15.

---

## 1. Executive Summary

### 1.1 What we have now (after the prior two fixes)

- `build_sumo_pack` works: produces a directory with `plant.sumoslang`, `apply_parameters.scs`, `BUILD_INSTRUCTIONS.md`, `schematic.json`.
- `apply_schematic_to_baseline` works: copies a verified `.sumo`+DLL pair and applies parameter overrides.
- Deprecated paths (`build_sumo_from_html`, `compile_schematic_to_sumo`, `attach_companion_dll`, `verify_sumo_file_against_schematic`) now hard-refuse with `ok=False`.
- `verify_dll_matches_schematic`, `update_schematic_in_html`, `next_step_for_project`, `apply_template_auto_fixes` exist.
- 155 tools total.

### 1.2 What we don't have

**Orchestration.** Every tool is callable in any order. Nothing tracks where the user is in the workflow. Nothing prevents calling `build_sumo_pack` before `validate_wwtp_template`, or running `apply_parameters.scs` against a topology that doesn't match the schematic. Each tool is locally correct; the *sequence* is uncontrolled.

The Qaha1 session is the canonical evidence: a 12-phase build, manually narrated, with six workarounds where the user had to step out of MCP and into PowerShell/Python to recover. A working workflow exists in the user's head, not in the server.

### 1.3 What this plan adds

A **seven-stage gated pipeline** that mirrors SUMO24's own multi-page workflow (configuration → parameters → tools → static inputs → dynamic inputs → controllers → build). Each stage:

- Has a single entry tool and a single validation tool
- Reads from and writes to a central `project.yaml` manifest
- Refuses to advance until the previous stage's hash is recorded
- Auto-invalidates downstream stages when an upstream artefact changes
- Snapshots before every destructive write

The user (or Claude on their behalf) navigates the pipeline via one driver tool: `pipeline_status(project_dir)`. It always returns the current stage, what's done, what's next, and the exact tool to call. No more "where am I?" moments.

### 1.4 The outcome

For any new WWTP, the entire build collapses to:

```
1.  pipeline_init(project_dir="F:/.../MyPlant", plant_name="MyPlant")
2.  pipeline_status                                    → "Stage 1: edit schematic at <path>"
3.  (user edits HTML schematic)
4.  pipeline_advance                                   → validates + locks Stage 1
5.  pipeline_status                                    → "Stage 2: fill Excel at <path>"
6.  (user fills Excel)
7.  pipeline_advance                                   → validates + locks Stage 2
8.  pipeline_status                                    → "Stage 3: run engineering checks"
... and so on through Stage 6.
final: open <stub>.sumo in SUMO GUI, follow auto-generated BUILD_INSTRUCTIONS.md.
```

If anything fails, `pipeline_status` reports the exact stage, the exact reason, the exact tool to call to fix it. There is no path through which the pipeline can return `ok=True` while producing a SUMO-unloadable artefact.

---

## 2. Design Principles

Six rules every part of this plan obeys.

1. **Never manufacture a `.sumo` file's internals.** The build-pack approach is the only honest path. The MCP server produces SumoSlang + `.scs` + instructions; SUMO produces the `.sumo` + DLL + `state.xml`. Tier-3 (live DTT-driven build) is out of scope for this plan and stays out until DTT capability is verified.

2. **One source of truth per stage.** Stage 1 = the HTML schematic. Stage 2 = the Excel template. There is no third place where unit names or parameters live. Cross-references (Excel's `Treatment_Processes.instance_name` ↔ schematic unit IDs) are validated at stage boundaries, never silently reconciled.

3. **Stages are content-addressed.** Each stage records a SHA-256 of its inputs in `project.yaml`. Downstream stages refuse to run unless they record the upstream hash they were built against. When the upstream hash changes, downstream stages are marked `stale` and require re-run.

4. **Gating, not warnings.** A stage either passes validation and advances, or it doesn't. There is no "passed with warnings, but here's the thing you should worry about". Warnings exist only as informational annotations on a passed stage; they never sit between `ok=True` and a broken downstream artefact.

5. **Idempotent and resumable.** Every stage tool can be re-run safely. Re-running advances if conditions are met, no-ops if already advanced, or reports a clear diff if the inputs have changed since the last run.

6. **Snapshot before mutating.** Any tool that writes to disk first copies the target to `<path>.bak.<timestamp>`. This is non-negotiable for the Excel template and the HTML schematic — both have already been corrupted once by an in-place edit.

---

## 3. The Seven-Stage Pipeline

This is the user-visible workflow. Each stage maps to a page in SUMO24 GUI.

| Stage | Name | SUMO GUI equivalent | Primary artefact | Validation tool |
|:---:|---|---|---|---|
| **0** | Init | (new project dialog) | `project.yaml` + scaffolding | `pipeline_status` |
| **1** | Configuration | Process Flow Diagram | `<plant>_schematic.html` | `stage1_validate_schematic` |
| **2** | Parameters | Unit property pages | `<plant>_data.xlsx` | `stage2_validate_parameters` |
| **3** | Engineering tools | "Tools" page (SRT, HRT, F:M, mass balance) | `engineering_checks.json` | `stage3_run_engineering_checks` |
| **4** | Static inputs | Static input page | `static_inputs.json` | `stage4_validate_static_inputs` |
| **5** | Dynamic inputs (optional) | Dynamic input tables page | `dynamic_inputs/*.tsv` | `stage5_validate_dynamic_inputs` |
| **6** | Controllers (optional) | Controllers page | `controllers.json` | `stage6_validate_controllers` |
| **7** | Build & handoff | (none — leaves SUMO) | `<plant>.sumo-pack/` + stub | `stage7_build` |
| **8** | Verification (post-SUMO-compile) | (back inside SUMO + first sim) | `verification.json` | `stage8_verify` |

Stages 5 and 6 are **optional**. Skipping them is recorded in the manifest as `{stage: "5", status: "skipped"}` so a future re-entry knows the difference between "not done" and "not needed".

### 3.1 Stage flow diagram

```
                    ┌────────────────────────────────────────────────┐
                    │            project.yaml manifest               │
                    │  current_stage · stage_hashes · provenance     │
                    └────────────────────────────────────────────────┘
                                       ▲    ▲    ▲
                                       │    │    │  reads/writes
       ┌───────────────────────────────┘    │    └───────────────────────────────┐
       │                                    │                                    │
   Stage 0 ─► Stage 1 ─► Stage 2 ─► Stage 3 ─► Stage 4 ─► Stage 5 ─► Stage 6 ─► Stage 7 ─► Stage 8
   init      schema      params      tools      static      dynamic     ctrl       build      verify
                                                          (optional)  (optional)             (post-SUMO)
       │         │           │          │          │          │          │          │
       ▼         ▼           ▼          ▼          ▼          ▼          ▼          ▼
   scaffold  validate    validate   M&E sanity validate    validate   validate   pack +
   files     topology    sizing +   SRT/HRT/   fractionation profiles  setpoints  stub +
             & types     ASM map    F:M/MB                                        SumoSlang
```

The downward arrows are stage outputs (artefacts on disk). The horizontal arrows are gated transitions — `pipeline_advance` from Stage N to Stage N+1 only succeeds when Stage N's validator returns `ok=True` and writes a fresh hash to `project.yaml`.

---

## 4. The Project Manifest (`project.yaml`)

Single source of truth for pipeline state. Lives at `<project_dir>/project.yaml`. Schema:

```yaml
schema_version: 1
plant_name: "Qaha1"
created: "2026-05-14T10:32:11Z"
modified: "2026-05-14T18:04:55Z"
project_dir: "F:/UNI/SUMO/MCP/Claude Models/Qaha1"

# Stage state — one entry per stage. Status is one of:
#   pending  · not yet attempted
#   in_progress · scaffold exists, user is editing
#   passed   · validator returned ok=True, hash recorded
#   failed   · validator returned ok=False (with details below)
#   stale    · was passed, but an upstream hash changed → must re-run
#   skipped  · explicitly marked optional and not needed
stages:
  - id: 0
    name: init
    status: passed
    completed_at: "2026-05-14T10:32:11Z"
    artefact_path: "project.yaml"
    input_hash: null
    output_hash: "sha256:abc123..."
    based_on:    null
  - id: 1
    name: configuration
    status: passed
    completed_at: "2026-05-14T12:14:02Z"
    artefact_path: "Qaha1_schematic.html"
    input_hash: null
    output_hash: "sha256:def456..."
    based_on:    "sha256:abc123..."   # stage 0's output hash
    summary:
      units: 16
      streams: 18
      unit_types_used: ["influent","screen","oxidation_ditch","secondary_clarifier",...]
  - id: 2
    name: parameters
    status: passed
    artefact_path: "Qaha1_data.xlsx"
    output_hash: "sha256:789..."
    based_on:    "sha256:def456..."   # stage 1's hash
    summary:
      processes: 7
      connections: 7
      influent_rows: 301
  - id: 3
    name: engineering_checks
    status: passed
    artefact_path: "engineering_checks.json"
    output_hash: "sha256:..."
    based_on:    "sha256:789..."      # stage 2's hash
    summary:
      srt_d: 12.4
      hrt_h: 18.2
      fm_d_inv: 0.21
      mass_balance_closure_pct: 98.7
      checks_passed: 14
      checks_with_warnings: 2
  - id: 4
    name: static_inputs
    status: passed
    ...
  - id: 5
    name: dynamic_inputs
    status: skipped
    skip_reason: "steady-state design study only"
  - id: 6
    name: controllers
    status: skipped
  - id: 7
    name: build
    status: passed
    artefact_path: "Qaha1.sumo-pack/"
    output_hash: "sha256:..."
    based_on: "sha256:..."           # chained from stage 4 (or whichever last non-skipped)
    summary:
      pack_files: [plant.sumoslang, apply_parameters.scs, BUILD_INSTRUCTIONS.md, schematic.json, static_inputs.scs, controllers.scs]
      stub_bytes: 498
  - id: 8
    name: verification
    status: pending     # waits for user to compile in SUMO
    artefact_path: null

# Provenance — what tools touched the project, in order. Append-only.
provenance:
  - ts: "2026-05-14T10:32:11Z"
    tool: pipeline_init
    args: {project_dir: "...", plant_name: "Qaha1"}
    result: ok
  - ts: "2026-05-14T10:45:03Z"
    tool: update_schematic_in_html
    args: {html_path: "...", schematic_json: "..."}
    result: ok
  ...

# Engineering metadata snapshot — copied out of the artefacts at advance-time
# so reports/queries don't need to re-parse them.
plant_summary:
  design_flow_avg_m3d: 7420
  temperature_C: 20
  kinetic_model: ASM2d
  discharge_target: law48_drain
  unit_count: 16
  has_recycle: true
```

### 4.1 Why YAML, not JSON

Comments survive round-trips, multi-line strings read cleanly, humans can hand-edit in an emergency without breaking the file. `ruamel.yaml` is the recommended parser (preserves comments and ordering); fall back to `pyyaml` if not available.

### 4.2 Hash rules

- Each stage's `output_hash` is SHA-256 of its primary artefact's canonical form (for HTML: extract the `<script id="schematic-data">` JSON only, hash that; for Excel: deterministic-key dump of every non-empty cell; for JSON files: hash with sorted keys).
- Each stage records `based_on` = the `output_hash` of the latest non-skipped upstream stage.
- When `pipeline_status` runs, it re-hashes the artefact on disk and compares with `output_hash` in the manifest. Mismatch → `status: stale`, the stage and everything downstream re-runs.
- Hashes never include timestamps or volatile fields (created/modified). This is what makes them stable.

---

## 5. Stage-by-Stage Specification

For each stage: entry tool, artefact, validator, advance rules, what it adds to the manifest.

### Stage 0 — Init

**Entry tool:** `pipeline_init(project_dir, plant_name, kinetic_model="ASM2d", from_template="qaha_oxditch")`

**What it does.** Creates `project_dir/` if missing; refuses to overwrite a non-empty dir without `force=True`. Scaffolds:

```
<project_dir>/
├── project.yaml                       # the manifest (stage 0 marked passed)
├── <plant_name>_schematic.html        # copy of wwtp_schematic_template.html, plant_name baked into meta
├── <plant_name>_data.xlsx             # fresh template via generate_wwtp_template_xlsx
├── snapshots/                         # .bak files land here, not next to the originals
├── engineering_checks.json            # empty: {"status": "pending"}
├── static_inputs.json                 # empty
├── controllers.json                   # empty
└── README.md                          # auto-generated, explains stages + next steps
```

`from_template` can be one of `qaha_oxditch`, `classic_as`, `mbbr`, `bnr_3stage`, `blank`. Maps to a preset schematic loaded into the HTML.

**Validator:** `pipeline_init` itself; no separate validator needed (the artefacts are scaffolds, not user content).

**Manifest update:** stage 0 → `passed`. `plant_summary.plant_name` set; everything else null.

**Advance rule:** Stage 0 always passes if scaffolding succeeded. Stage 1 starts immediately.

### Stage 1 — Configuration (Schematic)

**Entry tool:** `stage1_open_schematic(project_dir)` — returns the schematic HTML path, opens it in the user's browser if `open_in_browser=True`. Nothing else; the HTML is the editor.

**Update tool:** `update_schematic_in_html(html_path, schematic_json, backup=True)` — already exists from the Qaha1 fix plan. Cowork or Claude uses this when re-applying a JSON the user has hand-edited or generated from elsewhere.

**Validator:** `stage1_validate_schematic(project_dir)`. Runs all of:

- `parse_html_schematic` returns successfully
- `validate_schematic` (the fail-fast checker from the Qaha1 plan) returns `ok=True`
- Every unit type is in `UNIT_TYPES` registry (no `grit_chamber`-style typos)
- Every stream references unit IDs that exist
- Topology has at least one `influent` and one `effluent`
- No orphan units (excluding boundary types)
- For each recycle stream type, the source/target make hydraulic sense (RAS source is a clarifier or splitter; RAS target is a reactor; etc.)
- The schematic's mean design flow is within ±20% of the Excel `Plant_Info.design_flow_avg` if Stage 2 is already passed (cross-stage sanity)

**Advance rule:** `pipeline_advance(from_stage=1)` runs the validator, on `ok=True` writes `output_hash` (of the JSON block), marks stage 1 `passed`, marks stages 2–8 `pending` (or `stale` if previously passed and the hash changed).

**Refusal modes:**
- Unknown unit type → returns the closest match suggestion, marks stage `failed`, does NOT advance.
- No effluent → `failed`, message `"Add an Effluent boundary unit before advancing."`
- Schematic hash matches last advance → `passed` (no-op).

### Stage 2 — Parameters (Excel)

**Entry tool:** `stage2_open_data(project_dir)` — returns the Excel path. If the template was generated at Stage 0, it's already there; otherwise re-generates it from `generate_wwtp_template_xlsx`.

**Cross-stage seeding.** When Stage 1's hash is fresh, `stage2_open_data` does something the current template tool doesn't: it pre-populates the `Treatment_Processes` sheet from the schematic's units, and the `Connections` sheet from the schematic's streams. The user only fills in numbers; the names are already filled in and locked. This eliminates the "WAS unit missing from Treatment_Processes" class of error entirely.

Implementation:

```python
def seed_excel_from_schematic(template_path, schematic, backup=True):
    """Write schematic units/streams into the template's Treatment_Processes
    and Connections sheets. Adds DataValidation dropdowns on both sheets
    sourced from the seeded names — preventing typos by construction."""
    import openpyxl
    from openpyxl.worksheet.datavalidation import DataValidation

    if backup:
        _snapshot(template_path)
    wb = openpyxl.load_workbook(template_path)
    ws_tp   = wb["Treatment_Processes"]
    ws_conn = wb["Connections"]

    # Wipe existing data rows; preserve headers.
    for ws in (ws_tp, ws_conn):
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.value = None
                cell.comment = None

    # Seed Treatment_Processes
    for i, u in enumerate(schematic["units"], start=2):
        ws_tp.cell(i, 1).value = i - 1                           # order_index
        ws_tp.cell(i, 2).value = u["name"]                       # instance_name
        ws_tp.cell(i, 3).value = _registry_to_process_type(u["type"])
        ws_tp.cell(i, 4).value = UNIT_TYPES[u["type"]]["category"]
        ws_tp.cell(i, 5).value = _stage_for_type(u["type"])
        ws_tp.cell(i, 6).value = _kinetic_for_type(u["type"])    # ASM2d for reactors, blank otherwise
        # Lock the name column — it's the primary key.
        ws_tp.cell(i, 2).protection = openpyxl.styles.Protection(locked=True)

    # Seed Connections
    for i, s in enumerate(schematic["streams"], start=2):
        from_unit = _unit_name_by_id(schematic, s["from"])
        to_unit   = _unit_name_by_id(schematic, s["to"])
        ws_conn.cell(i, 1).value = from_unit
        ws_conn.cell(i, 2).value = to_unit
        ws_conn.cell(i, 3).value = s.get("label") or f"{from_unit}_to_{to_unit}"
        ws_conn.cell(i, 4).value = _scs_stream_type(s["type"])
        ws_conn.cell(i, 5).value = s["type"] if s["type"] in ("ras","was","recycle") else ""

    # Dropdowns
    n_units = len(schematic["units"])
    dv = DataValidation(type="list",
                        formula1=f"=Treatment_Processes!$B$2:$B${n_units+1}",
                        allow_blank=False, showDropDown=False)
    ws_conn.add_data_validation(dv)
    dv.add(f"A2:A{n_units*4}")
    dv.add(f"B2:B{n_units*4}")

    wb.save(template_path)
```

**Validator:** `stage2_validate_parameters(project_dir)`. Runs:

- `validate_wwtp_template` (existing tool, with the grouped-errors + auto-fix patch from the Qaha1 plan)
- Cross-check: every `Treatment_Processes.instance_name` matches a schematic unit name (case-sensitive)
- Cross-check: every connection's `from_unit`/`to_unit` exists in `Treatment_Processes`
- Influent dataset has at least 7 rows (one week minimum for steady design)
- Influent COD, TSS, TKN, TP, T are numeric and in physical ranges
- Effluent_Targets sheet has Law 48/1982 limits filled in
- Process sizing: every biological reactor has V > 0; every clarifier has A > 0

**Refusal modes:**
- Unit name in Excel doesn't match schematic → `failed`, message points to the row with the typo.
- Connections sheet contains rows the schematic doesn't have, or vice versa → `failed`, with the diff.

**Advance rule:** On `ok=True`, hash the Excel (deterministic cell-by-cell), record, mark passed. Mark stages 3-8 `pending` or `stale`.

### Stage 3 — Engineering tools (SRT, HRT, F:M, mass balance)

This is the "Tools" page equivalent the user specifically called out. The point of this stage is to **fail loud, early** on physically impossible designs before any further effort is spent.

**Entry tool:** `stage3_run_engineering_checks(project_dir)`. Reads the schematic + Excel, runs every relevant calculator/validator, writes `engineering_checks.json`.

The calculators (most already exist in Group X/Y of the 155 tools — this stage chains them):

| Calculator | What it computes | Refuses if |
|---|---|---|
| `compute_srt` | SRT = V_total × MLSS / (Q_WAS × X_R) | SRT < 3 d for nitrification, < 1 d for BOD-only |
| `compute_hrt` | HRT = V_reactor / Q_avg | HRT < 0.5 h or > 48 h |
| `compute_fm_ratio` | F:M = (Q × BOD) / (V × MLVSS) | F:M outside 0.05–1.5 d⁻¹ for activated sludge |
| `compute_oxygen_demand` | AOR from BOD + nitrification − denitrification credit | computed KLa > installed KLa × 1.2 |
| `validate_mass_balance_pre_run` | mass-balance closure on the static design | closure < 90% on COD or N |
| `check_alkalinity` | residual alkalinity after nitrification | residual < 50 mg/L as CaCO₃ |
| `check_takacs_settler` | clarifier SOR, SLR, v0 vs Takacs band | SOR > 24 m³/m²/d or SLR > 5 kg/m²/h |
| `check_aeration_supply` | OTRf / AOR ratio | < 1.0 (under-aerated) |
| `validate_srt_fm_feasibility` | F:M and SRT can both be hit at given V, MLSS, Q_WAS | infeasible |
| `validate_oxygen_demand_vs_supply` | demand vs KLa capacity | demand > capacity |

The output JSON looks like:

```json
{
  "ok": true,
  "stage": 3,
  "computed": {
    "srt_d": 12.4,
    "hrt_h": 18.2,
    "fm_d_inv": 0.21,
    "aor_kgO2_d": 2890,
    "scor_m_d": 23.7,
    "mass_balance_closure_pct": 98.7
  },
  "checks": [
    {"name": "srt_in_range",       "ok": true,  "value": 12.4,  "range": [3, 30], "unit": "d"},
    {"name": "hrt_in_range",       "ok": true,  "value": 18.2,  "range": [4, 24], "unit": "h"},
    {"name": "fm_in_range",        "ok": true,  "value": 0.21,  "range": [0.05, 1.5], "unit": "d^-1"},
    {"name": "aeration_supply",    "ok": true,  "value": 1.18,  "min": 1.0,   "unit": "OTR/AOR"},
    {"name": "mass_balance_cod",   "ok": true,  "closure_pct": 98.7, "min": 90.0},
    {"name": "takacs_sor",         "ok": false, "value": 27.1, "max": 24.0, "fix": "Increase clarifier surface area to ≥ 690 m² or reduce design flow."}
  ],
  "passed": 9,
  "warnings": 0,
  "failed": 1
}
```

**Validator:** the checks themselves. If any check fails, the stage fails with the *worst-offender's* `fix` field surfaced as the user-facing message. The full report stays in the JSON.

**Refusal mode:** Stage 3 returns `failed` even if only one check fails, but the message is the *fix*, not the failure: `"Increase clarifier surface area to ≥ 690 m² or reduce design flow."` This is actionable. The user goes back to Stage 2, updates the sizing, advances Stage 2 again, then re-runs Stage 3.

**Advance rule:** On all checks `ok=True` (or `ok=true` with only warnings), record hash of `engineering_checks.json`, mark passed.

### Stage 4 — Static inputs

**Entry tool:** `stage4_define_static_inputs(project_dir)`. Reads the Excel's `Influent_Dataset` (means or design point), `Influent_Fractionation`, and any standing operational parameters. Writes `static_inputs.json` and the matching SumoCore-format `static_inputs.scs` (the script the user will paste in SUMO once compile completes).

Static inputs are what SUMO needs to initialise a steady state:

```
influent flow, temperature
COD components: S_S, S_I, X_S, X_I, X_BH, X_BA  (computed from total COD × fractions)
N components:   S_NH, S_ND, X_ND, S_N2, S_NO    (from TKN × fractions)
P components:   S_PO4, X_PP, X_PHA              (for ASM2d)
TSS, alkalinity, DO_setpoint per reactor
MLSS setpoint per reactor (if controlled), Q_RAS, Q_WAS
```

The fractionation came from the Excel; the static inputs step **resolves** it into actual ASM state-variable initial values. It also validates that the resolved values satisfy basic conservation (sum of COD fractions = 1.0 ± 0.01, sum of N fractions = 1.0, etc.).

**Validator:** `stage4_validate_static_inputs`. Checks:

- COD fractions sum to 1.0
- N fractions sum to 1.0
- All ASM2d state variables resolved and non-negative
- DO setpoint between 0.5 and 4.0 mg/L for aerobic reactors, ≤ 0.3 for anoxic, ≤ 0.1 for anaerobic
- MLSS setpoints between 2000 and 6000 mg/L
- Q_RAS within 0.5×Q to 1.5×Q
- Q_WAS produces an SRT within the Stage 3 computed value ±30%

**Advance rule:** On `ok=True`, record, mark passed.

### Stage 5 — Dynamic inputs (optional)

**Entry tool:** `stage5_generate_dynamic_inputs(project_dir, profile_type, ...)`. Wraps the existing `create_dynamic_input_table` and `import_influent_profile` tools.

Five profile types map to SUMO's input-table conventions:

- `constant` — uses the Stage 4 static value; trivially produces a flat table.
- `from_excel` — reads `Influent_Dataset` rows as a daily time series, writes TSV.
- `diurnal` — sinusoidal Q + COD around the daily mean; phase locked to 7 AM peak by default.
- `storm` — diurnal + a 6-hour storm event peaking at 2.5× design flow (configurable).
- `seasonal_temperature` — monthly mean temperatures, others held at means.

Output goes to `<project_dir>/dynamic_inputs/<name>.tsv`. The file is in the exact format `run_dynamic_simulation` expects.

**Validator:** `stage5_validate_dynamic_inputs`. Checks:

- TSV is well-formed (header + uniform column count)
- Time column is monotonic
- All numeric columns are within physical ranges
- Simulation duration in `Sumo__StopTime` from `state.xml` matches or is shorter than the table's duration
- Row interval matches `Sumo__DataComm`

This is the same logic that already exists in `create_dynamic_input_table` — Stage 5 just chains the call and records the artefact.

**Advance rule:** `passed` if any TSV exists and validates. `skipped` if `pipeline_advance(skip_stage=5, reason="...")` is called explicitly. Skipping is recorded; the build pack at Stage 7 then doesn't include dynamic input TSVs.

### Stage 6 — Controllers (optional)

**Entry tool:** `stage6_add_controller(project_dir, kind, target_unit, setpoint, ...)`. Wraps the existing `add_controller` and adds it to a `controllers.json` block in the project:

```json
{
  "controllers": [
    {"kind": "DO", "unit": "OxidationDitch1", "setpoint": 2.0, "sensor": "DO", "actuator": "KLa", "Kp": 50, "Ti": 0.01},
    {"kind": "SRT", "unit": "WAS", "setpoint_days": 12.0, "sensor": "MLSS@OxDitch", "actuator": "Q_WAS"},
    {"kind": "NH4", "unit": "OxDitch", "setpoint": 1.5, "sensor": "NH4@SecondaryClarifier", "actuator": "DO_setpoint", "feedforward": true}
  ]
}
```

**Validator:** `stage6_validate_controllers`. Checks:

- Each `unit` references a real unit in the schematic
- Each `sensor` references a measurable variable that exists in the compiled model namespace (heuristic: matches one of the known sensor patterns)
- Setpoints are in physical range
- No conflicting controllers on the same actuator (two controllers both driving `KLa` on the same unit is invalid)

**Advance rule:** Same as Stage 5 — `passed` if at least one controller defined and valid, or `skipped` if explicit.

### Stage 7 — Build pack & SUMO handoff

**Entry tool:** `stage7_build(project_dir)`. The terminal stage on the MCP side.

Runs `build_sumo_pack` (already exists) but with **all prior stages folded into the pack**. The pack written to `<project_dir>/<plant_name>.sumo-pack/` now contains:

| File | Comes from | Purpose in SUMO |
|---|---|---|
| `plant.sumoslang` | Stage 1 (schematic) | Topology — paste in SumoSlang editor, Compile |
| `apply_parameters.scs` | Stage 2 (Excel) | Sizing + influent values — paste in Core Window |
| `static_inputs.scs` | Stage 4 | Initial state values — paste after apply_parameters |
| `dynamic_inputs/*.tsv` | Stage 5 (if not skipped) | Input tables — import via SUMO's dynamic input dialog |
| `controllers.scs` | Stage 6 (if not skipped) | Controller setup — paste after static_inputs |
| `BUILD_INSTRUCTIONS.md` | regenerated | Numbered 7-step procedure tailored to which stages are present |
| `schematic.json` | Stage 1 | Reference, for traceability |
| `engineering_checks.json` | Stage 3 | Reference, for the report |
| `project.yaml` | (copy) | Full pipeline state at build time |
| `<plant_name>.sumo` | Stage 7 | The minimal 498-byte XML stub. **This is the file the user opens in SUMO.** |

The stub is the only file that ends in `.sumo`. Its content is the minimal known-good schema confirmed from inspection of real SUMO project files:

```xml
<?xml version="1.0" encoding="utf-8"?>
<SumoProject name="Qaha1" version="24">
  <!-- Open this file in SUMO24 GUI to build the process network -->
  <!-- Then: Simulate -> maptoic; save "state.xml"; copy DLL here  -->
</SumoProject>
```

**BUILD_INSTRUCTIONS.md is generated, not templated.** Each instruction step explicitly references files present in *this* pack:

```markdown
# Build Qaha1 in SUMO24

Generated 2026-05-14 18:04 by SUMO24 MCP pipeline.

## 1. Open the stub
File → Open → Qaha1.sumo (498 bytes — this is just an entry point)

## 2. Compile the topology
Edit → Plant Definition (or SumoSlang panel)
Paste the contents of: plant.sumoslang
Click Compile. SUMO writes sumoproject.dll next to Qaha1.sumo.

## 3. Save initial state
Simulate → Initialize
Wait for "Ready for simulation"
Advanced → Core Window:
  > maptoic; save "state.xml";

## 4. Apply unit parameters
Core Window: paste the contents of apply_parameters.scs.
> save "state.xml";

## 5. Apply static input values
Core Window: paste the contents of static_inputs.scs.
> save "state.xml";

## 6. (optional) Load dynamic inputs
Inputs → Import:
  - dynamic_inputs/influent.tsv  (or your chosen profile)

## 7. (optional) Configure controllers
Core Window: paste the contents of controllers.scs.
> save "state.xml";

## 8. Verify
Run Simulate → Steady State. If it converges, return to MCP and call:
  stage8_verify(project_dir)
```

If Stages 5 or 6 are skipped, those steps are omitted from the instructions entirely (not greyed out — gone).

**Validator:** stage 7 has no separate validator; the build either produces a complete pack and passes, or fails the SumoSlang lint or sub-script generation and fails.

**Advance rule:** On success, hash the pack directory (concatenated hashes of each file in sorted order), record, mark Stage 7 `passed`, Stage 8 `pending`.

### Stage 8 — Verification (post-SUMO-compile)

**Entry tool:** `stage8_verify(project_dir)`. The user has now compiled the plant in SUMO and obtained a real `sumoproject.dll` + `state.xml`. Stage 8 confirms the compile matches the schematic.

Runs:

- `verify_dll_matches_schematic` (from Qaha1 plan) on the freshly-compiled DLL
- `read_state_variable_names(state.xml)` and confirm every schematic parameter resolves
- A trial steady-state run (`run_steady_state`) with a 1-day simulation as a smoke test
- `validate_post_simulation` on the result
- `validate_mass_balance_post_run`

Writes `verification.json`:

```json
{
  "ok": true,
  "dll_check": {"refs_in_schematic": 54, "refs_resolved": 54, "missing_total": 0},
  "state_check": {"variables_declared": 4127, "schematic_refs_present": 54},
  "trial_sim": {"job_id": "...", "converged": true, "duration_s": 17.4},
  "post_sim_validation": {"status": "RESULTS_VALID"},
  "mass_balance": {"cod_closure_pct": 99.1, "n_closure_pct": 97.4, "p_closure_pct": 98.2}
}
```

**Advance rule:** On all green, mark Stage 8 `passed`. The project is now complete and ready for production simulations.

If verification fails, the message is structured by what failed:

- DLL missing variables → "DLL was compiled for a different plant. Re-do Stage 7 step 2 (Compile) in SUMO."
- State.xml missing variables → "state.xml is stale. Re-do Stage 7 step 3 (maptoic; save) in SUMO."
- Trial sim diverged → "Solver diverged. Re-run engineering checks (Stage 3) — likely an aeration or SRT problem."

---

## 6. The Pipeline Driver

One tool everyone calls when they don't know what to do next.

### 6.1 `pipeline_status(project_dir)`

Returns a complete picture in one call:

```json
{
  "ok": true,
  "project_dir": "F:/UNI/SUMO/MCP/Claude Models/Qaha1",
  "plant_name": "Qaha1",
  "current_stage": 3,
  "current_stage_name": "engineering_checks",
  "current_stage_status": "failed",
  "next_action": {
    "tool": "stage2_open_data",
    "reason": "Stage 3 reports Takacs SOR exceeded (27.1 > 24.0). Increase clarifier surface area to ≥ 690 m² in the Excel template, then re-advance Stage 2.",
    "args": {"project_dir": "F:/UNI/SUMO/MCP/Claude Models/Qaha1"}
  },
  "stages": [
    {"id": 0, "status": "passed"},
    {"id": 1, "status": "passed"},
    {"id": 2, "status": "passed"},
    {"id": 3, "status": "failed", "blocker": "takacs_sor"},
    {"id": 4, "status": "pending"},
    {"id": 5, "status": "pending"},
    {"id": 6, "status": "pending"},
    {"id": 7, "status": "pending"},
    {"id": 8, "status": "pending"}
  ],
  "stale": []
}
```

If a file on disk has changed since its last hash:

```json
{
  "ok": true,
  "current_stage": 1,
  "current_stage_status": "stale",
  "stale": [{"stage": 1, "reason": "schematic file modified since last advance"}],
  "next_action": {
    "tool": "pipeline_advance",
    "reason": "Schematic was edited. Re-validate Stage 1 (and any downstream stages will also be marked stale).",
    "args": {"project_dir": "...", "from_stage": 1}
  }
}
```

### 6.2 `pipeline_advance(project_dir, from_stage=None, skip=False, skip_reason=None, force=False)`

The state-machine transition:

- `from_stage=None` → advance the lowest non-passed stage
- `from_stage=N` → re-run stage N's validator regardless of current state
- `skip=True` → only valid on optional stages (5, 6); requires `skip_reason`
- `force=True` → advance even with warnings (but never with errors)

Returns the same shape as `pipeline_status` after the transition.

### 6.3 `pipeline_revert(project_dir, to_stage)`

Rollback. Restores the project to the state at the end of `to_stage`. Uses the snapshots directory:

```
snapshots/
├── 2026-05-14T10-32-11_pre_stage1.tar
├── 2026-05-14T12-14-02_post_stage1.tar
├── 2026-05-14T15-22-30_pre_stage2.tar
└── ...
```

`pipeline_revert(project_dir, to_stage=2)` finds the latest `post_stage2.tar` and extracts. The manifest is part of the snapshot, so all subsequent stages return to `pending`.

### 6.4 `pipeline_describe(project_dir)`

A human-readable Markdown report of the full pipeline state. Useful for documentation and for the `BUILD_INSTRUCTIONS.md` generator at Stage 7.

---

## 7. Idempotency, Hashing, and Snapshotting

Three cross-cutting mechanisms make the pipeline robust.

### 7.1 Idempotency

Every stage tool must be safe to re-run:

| Tool | Idempotency rule |
|---|---|
| `pipeline_init` | If `project_dir/project.yaml` exists, returns the existing state with `idempotent=True`. Refuses to re-scaffold without `force=True`. |
| `update_schematic_in_html` | Diff-based: if the new JSON equals the on-disk JSON, no write, no backup. |
| `seed_excel_from_schematic` | Compares cell-by-cell with current Excel state; only writes if differences exist; preserves user-entered data in cells the seed doesn't touch (i.e., the columns the user fills in are never overwritten — only the names columns are seeded). |
| `stage3_run_engineering_checks` | Always runs (cheap); writes new `engineering_checks.json` only if computed values differ. |
| `stage7_build` | Re-generates the pack from scratch each time; the pack directory is fully owned by this tool. Always backs up the previous pack to `snapshots/`. |

### 7.2 Hashing rules (in detail)

The hash chain is what makes the pipeline self-healing.

**Schematic hash** (Stage 1):
```python
def hash_schematic(html_path):
    raw = open(html_path).read()
    # Extract the JSON block, ignoring comments outside it
    json_text = _extract_schematic_data_block(raw)   # tag-aware, comment-safe
    obj = json.loads(json_text)
    # Strip volatile fields
    obj.get("meta", {}).pop("created", None)
    obj.get("meta", {}).pop("modified", None)
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**Excel hash** (Stage 2):
```python
def hash_excel(xlsx_path):
    wb = openpyxl.load_workbook(xlsx_path, data_only=False)
    h = hashlib.sha256()
    for ws_name in sorted(wb.sheetnames):
        ws = wb[ws_name]
        h.update(ws_name.encode("utf-8"))
        for row in ws.iter_rows(values_only=True):
            # Drop trailing Nones (deals with phantom empty columns)
            row = tuple(row)
            while row and row[-1] is None:
                row = row[:-1]
            if any(c is not None for c in row):
                h.update(repr(row).encode("utf-8"))
    return h.hexdigest()
```

Note: `data_only=False` is crucial. If you load with `data_only=True` and a user has unsaved formulas, the hash changes spuriously.

**JSON hash** (Stages 3, 4, 6, 8):
```python
def hash_json(path):
    obj = json.load(open(path))
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**Pack hash** (Stage 7):
```python
def hash_pack(pack_dir):
    h = hashlib.sha256()
    for f in sorted(pathlib.Path(pack_dir).rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(pack_dir)).encode("utf-8"))
            h.update(f.read_bytes())
    return h.hexdigest()
```

### 7.3 Snapshotting

Every stage advance triggers a snapshot **before** the destructive writes. The snapshot is a tar archive of the current project directory, excluding `snapshots/` itself:

```python
def snapshot(project_dir, label):
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    out = pathlib.Path(project_dir) / "snapshots" / f"{ts}_{label}.tar"
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w") as t:
        for item in pathlib.Path(project_dir).iterdir():
            if item.name != "snapshots":
                t.add(item, arcname=item.name)
    return str(out)
```

The snapshots directory is bounded — keep at most 30 snapshots, prune oldest on overflow.

`pipeline_revert` uses these directly. They're also human-inspectable (`tar -tf`).

---

## 8. New Tool Inventory

Tools added by this plan, grouped:

### 8.1 Pipeline driver (new — these are the ones the user calls)

| Tool | Purpose |
|---|---|
| `pipeline_init` | Scaffold a new project |
| `pipeline_status` | Where am I and what's next |
| `pipeline_advance` | Run the validator and move forward |
| `pipeline_revert` | Roll back to a known-good stage |
| `pipeline_describe` | Human-readable report |

### 8.2 Stage tools (new — orchestration around existing checkers)

| Tool | Wraps |
|---|---|
| `stage1_open_schematic` | (file path return) |
| `stage1_validate_schematic` | `validate_schematic` + topology rules |
| `stage2_open_data` | `generate_wwtp_template_xlsx` + new `seed_excel_from_schematic` |
| `stage2_validate_parameters` | `validate_wwtp_template` + cross-checks against schematic |
| `stage3_run_engineering_checks` | the existing Group X/Y validators, chained |
| `stage4_define_static_inputs` | new |
| `stage4_validate_static_inputs` | new |
| `stage5_generate_dynamic_inputs` | `create_dynamic_input_table` + `import_influent_profile` |
| `stage5_validate_dynamic_inputs` | TSV validator |
| `stage6_add_controller` | `add_controller` (existing) |
| `stage6_validate_controllers` | new |
| `stage7_build` | `build_sumo_pack` + multi-script assembly |
| `stage8_verify` | `verify_dll_matches_schematic` + `run_steady_state` + `validate_post_simulation` |

### 8.3 Internal helpers (new — not exposed as MCP tools)

These live in `PY/pipeline/` as a sub-package:

```
PY/pipeline/
├── __init__.py
├── manifest.py          # project.yaml read/write, schema, hash chain
├── hashing.py           # the four hash functions in §7.2
├── snapshot.py          # snapshot / revert / prune
├── seeding.py           # seed_excel_from_schematic
├── engineering.py       # the calculators for Stage 3
├── static_inputs.py     # Stage 4 resolver
├── dynamic_inputs.py    # Stage 5 profile generators
└── build.py             # Stage 7 multi-script pack assembly
```

### 8.4 Net effect on tool count

- Pipeline driver: +5
- Stage tools: +14
- Net new: +19
- Tools that effectively become internal (no longer the main entry points but still callable): no removals; existing build/validate tools stay because Tier-1 / one-off use cases still need them.

Total: 155 → **174**.

---

## 9. File Layout (Final)

```
F:/UNI/SUMO/MCP/
├── PY/
│   ├── server.py
│   ├── sumo_pack.py                    # from prior plan
│   ├── sumo_compiler.py                # deprecated, kept for legacy reads
│   ├── unit_type_registry.py           # incl. grit_chamber
│   ├── schematic_parser.py
│   ├── html_schematic_io.py            # from Qaha1 plan
│   ├── pipeline/                       # NEW sub-package — orchestration
│   │   ├── __init__.py
│   │   ├── manifest.py
│   │   ├── hashing.py
│   │   ├── snapshot.py
│   │   ├── seeding.py
│   │   ├── engineering.py
│   │   ├── static_inputs.py
│   │   ├── dynamic_inputs.py
│   │   └── build.py
│   ├── template_generator.py
│   └── smoke_test_pipeline.py          # NEW — covers all 8 stages end-to-end
├── wwtp_schematic_template.html        # incl. grit_chamber palette entry
├── WWTP_Model_Input_Template.xlsx      # ships with seeded Connections + dropdowns
├── baselines/                          # known-good (.sumo + .dll) pairs
│   ├── qaha_baseline.sumo
│   └── sumoproject.dll
└── Claude Models/                      # user's working area
    └── <plant_name>/                   # each project = one directory
        ├── project.yaml
        ├── <plant_name>_schematic.html
        ├── <plant_name>_data.xlsx
        ├── engineering_checks.json
        ├── static_inputs.json
        ├── controllers.json
        ├── dynamic_inputs/
        ├── snapshots/
        └── <plant_name>.sumo-pack/     # written by Stage 7
            ├── <plant_name>.sumo       # the stub
            ├── plant.sumoslang
            ├── apply_parameters.scs
            ├── static_inputs.scs
            ├── controllers.scs         # if Stage 6 not skipped
            ├── dynamic_inputs/         # if Stage 5 not skipped
            ├── BUILD_INSTRUCTIONS.md
            ├── schematic.json
            ├── engineering_checks.json
            └── project.yaml            # snapshot at build time
```

Per-project everything lives under `Claude Models/<plant_name>/`. Cross-project state (templates, baselines, the server itself) lives in `F:/UNI/SUMO/MCP/`.

---

## 10. Concrete Edits for Cowork

Apply in the order below. Each block is a complete unit; do not interleave.

### 10.1 New sub-package: `PY/pipeline/`

Create `PY/pipeline/__init__.py` (empty marker), then create each module.

**`PY/pipeline/manifest.py`** — `project.yaml` read/write, schema enforcement, hash chain:

```python
"""project.yaml manifest read/write, schema, hash chain."""
from __future__ import annotations
import hashlib, json, os, pathlib
from datetime import datetime
from typing import Any

try:
    from ruamel.yaml import YAML
    _yaml = YAML()
    _yaml.preserve_quotes = True
    _yaml.indent(mapping=2, sequence=4, offset=2)
    HAS_RUAMEL = True
except ImportError:
    import yaml as _yaml  # type: ignore
    HAS_RUAMEL = False


STAGES = ["init", "configuration", "parameters", "engineering_checks",
          "static_inputs", "dynamic_inputs", "controllers", "build", "verification"]

OPTIONAL_STAGES = {5, 6}  # dynamic_inputs and controllers


def manifest_path(project_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(project_dir) / "project.yaml"


def load(project_dir: str | pathlib.Path) -> dict:
    p = manifest_path(project_dir)
    if not p.exists():
        raise FileNotFoundError(f"No project.yaml in {project_dir} — call pipeline_init first")
    text = p.read_text(encoding="utf-8")
    if HAS_RUAMEL:
        return _yaml.load(text)
    return _yaml.safe_load(text)  # type: ignore


def save(project_dir: str | pathlib.Path, manifest: dict) -> None:
    p = manifest_path(project_dir)
    manifest["modified"] = datetime.utcnow().isoformat() + "Z"
    if HAS_RUAMEL:
        import io
        buf = io.StringIO()
        _yaml.dump(manifest, buf)
        p.write_text(buf.getvalue(), encoding="utf-8")
    else:
        p.write_text(_yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")  # type: ignore


def new_manifest(project_dir: str, plant_name: str) -> dict:
    now = datetime.utcnow().isoformat() + "Z"
    return {
        "schema_version": 1,
        "plant_name": plant_name,
        "project_dir": str(project_dir),
        "created": now,
        "modified": now,
        "stages": [
            {"id": i, "name": STAGES[i], "status": "pending",
             "artefact_path": None, "input_hash": None,
             "output_hash": None, "based_on": None, "summary": None}
            for i in range(len(STAGES))
        ],
        "provenance": [],
        "plant_summary": {"plant_name": plant_name},
    }


def get_stage(manifest: dict, stage_id: int) -> dict:
    return manifest["stages"][stage_id]


def set_stage(manifest: dict, stage_id: int, **fields) -> None:
    s = manifest["stages"][stage_id]
    s.update(fields)
    if fields.get("status") in ("passed", "failed", "skipped"):
        s["completed_at"] = datetime.utcnow().isoformat() + "Z"


def last_passed_hash(manifest: dict, before_stage: int) -> str | None:
    """Return the output_hash of the latest non-skipped passed stage before `before_stage`."""
    for i in range(before_stage - 1, -1, -1):
        s = manifest["stages"][i]
        if s["status"] == "passed":
            return s["output_hash"]
    return None


def mark_downstream_stale(manifest: dict, from_stage: int) -> list[int]:
    """When stage `from_stage` is re-run with a new hash, every passed stage
    above it that depended on the old hash gets marked stale."""
    stale = []
    for i in range(from_stage + 1, len(STAGES)):
        s = manifest["stages"][i]
        if s["status"] == "passed":
            s["status"] = "stale"
            stale.append(i)
    return stale


def record(manifest: dict, tool: str, args: dict, result: str) -> None:
    manifest.setdefault("provenance", []).append({
        "ts": datetime.utcnow().isoformat() + "Z",
        "tool": tool,
        "args": args,
        "result": result,
    })
```

**`PY/pipeline/hashing.py`** — the four hash functions from §7.2 (copy verbatim).

**`PY/pipeline/snapshot.py`** — `snapshot()`, `revert()`, `prune()`:

```python
"""Tar-based snapshots of the project directory. Excludes the snapshots dir itself."""
from __future__ import annotations
import pathlib, tarfile
from datetime import datetime

KEEP = 30


def snapshot(project_dir: str | pathlib.Path, label: str) -> str:
    pdir = pathlib.Path(project_dir)
    sdir = pdir / "snapshots"
    sdir.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    out = sdir / f"{ts}_{label}.tar"
    with tarfile.open(out, "w") as t:
        for item in pdir.iterdir():
            if item.name != "snapshots":
                t.add(item, arcname=item.name)
    prune(pdir)
    return str(out)


def list_snapshots(project_dir: str | pathlib.Path) -> list[pathlib.Path]:
    sdir = pathlib.Path(project_dir) / "snapshots"
    if not sdir.exists():
        return []
    return sorted(sdir.glob("*.tar"))


def revert(project_dir: str | pathlib.Path, to_label_substring: str) -> str:
    """Restore from the latest snapshot whose name contains `to_label_substring`."""
    matches = [p for p in list_snapshots(project_dir) if to_label_substring in p.name]
    if not matches:
        raise FileNotFoundError(f"No snapshot matching {to_label_substring!r}")
    src = matches[-1]
    # wipe everything except snapshots/
    pdir = pathlib.Path(project_dir)
    for item in pdir.iterdir():
        if item.name == "snapshots":
            continue
        if item.is_dir():
            import shutil
            shutil.rmtree(item)
        else:
            item.unlink()
    with tarfile.open(src, "r") as t:
        t.extractall(pdir)
    return str(src)


def prune(project_dir: str | pathlib.Path) -> int:
    snaps = list_snapshots(project_dir)
    n_removed = 0
    while len(snaps) > KEEP:
        snaps[0].unlink()
        snaps = snaps[1:]
        n_removed += 1
    return n_removed
```

**`PY/pipeline/seeding.py`**, **`PY/pipeline/engineering.py`**, **`PY/pipeline/static_inputs.py`**, **`PY/pipeline/dynamic_inputs.py`**, **`PY/pipeline/build.py`** — implementations from §5. Each is straightforward; the patterns are established in the prior fix plans and in the existing 155 tools.

### 10.2 `PY/server.py` — register the 19 new tools

Add a single dispatch block near the end of the existing tool registration. Group prefix: **Group EE — Pipeline**.

```python
# ── Group EE: Pipeline driver and stage orchestration ───────────────────
from pipeline import manifest as _manifest
from pipeline import hashing as _hashing
from pipeline import snapshot as _snap
from pipeline import seeding as _seed
from pipeline import engineering as _eng
from pipeline import static_inputs as _si
from pipeline import dynamic_inputs as _di
from pipeline import build as _bld

PIPELINE_TOOLS = [
    # Driver
    ("pipeline_init",             "Scaffold a new project directory with project.yaml, HTML schematic, and Excel template. Required first call."),
    ("pipeline_status",           "Return the full pipeline state and the next recommended action. Call any time you don't know what to do next."),
    ("pipeline_advance",          "Run the current stage's validator and advance if it passes. Use skip=True with a reason for optional stages 5/6."),
    ("pipeline_revert",           "Roll back to the end of a named stage using the latest matching snapshot."),
    ("pipeline_describe",         "Generate a human-readable Markdown report of the project state."),
    # Stage tools
    ("stage1_open_schematic",     "Stage 1 entry: return the schematic HTML path (and optionally open in browser)."),
    ("stage1_validate_schematic", "Stage 1 validator: parse, registry-check, topology-check, cross-check with Stage 2 if present."),
    ("stage2_open_data",          "Stage 2 entry: ensure the Excel template exists, seed Treatment_Processes and Connections from Stage 1, return path."),
    ("stage2_validate_parameters","Stage 2 validator: validate_wwtp_template + cross-check against schematic."),
    ("stage3_run_engineering_checks","Stage 3: run SRT, HRT, F:M, mass balance, oxygen demand, aeration supply, settler hydraulics; write engineering_checks.json."),
    ("stage4_define_static_inputs","Stage 4: resolve fractionation into ASM state variables; write static_inputs.json and static_inputs.scs."),
    ("stage4_validate_static_inputs","Stage 4 validator: conservation of COD/N/P fractions, range checks on DO/MLSS/Q_RAS, SRT cross-check."),
    ("stage5_generate_dynamic_inputs","Stage 5: produce a dynamic input TSV for one of {constant, from_excel, diurnal, storm, seasonal_temperature}."),
    ("stage5_validate_dynamic_inputs","Stage 5 validator: TSV well-formed, monotonic time, physical ranges, matches Sumo__StopTime / Sumo__DataComm."),
    ("stage6_add_controller",     "Stage 6: register a controller (DO / SRT / NH4 / NO3 / FlowSplitter) in controllers.json."),
    ("stage6_validate_controllers","Stage 6 validator: unit references, sensor references, setpoint ranges, no conflicting actuators."),
    ("stage7_build",              "Stage 7: assemble the build pack (plant.sumoslang + apply_parameters.scs + static_inputs.scs + controllers.scs + dynamic TSVs + BUILD_INSTRUCTIONS.md + stub)."),
    ("stage8_verify",             "Stage 8 (post-SUMO-compile): verify DLL matches schematic, run a trial steady-state, validate post-sim mass balance."),
]
```

Each tool gets a matching `types.Tool(...)` definition with appropriate `inputSchema` and a matching `_exp_*` handler. The handler bodies are mostly thin wrappers around the `pipeline.*` modules.

Example for `pipeline_status` (the most-called tool):

```python
async def _exp_pipeline_status(args: dict) -> str:
    project_dir = args["project_dir"]
    try:
        m = _manifest.load(project_dir)
    except FileNotFoundError as e:
        return json.dumps({"ok": False, "reason": str(e),
                           "next_action": {"tool": "pipeline_init",
                                           "reason": "Initialise the project first."}}, indent=2)

    # Re-hash on-disk artefacts to detect stale stages
    stale_stages = _detect_stale(m, project_dir)
    for s in stale_stages:
        _manifest.set_stage(m, s, status="stale")

    # Find the current stage: lowest non-passed, non-skipped
    cur = None
    for s in m["stages"]:
        if s["status"] not in ("passed", "skipped"):
            cur = s
            break
    cur = cur or m["stages"][-1]  # everything passed → point at the last stage

    next_action = _recommended_action(m, cur, project_dir)

    _manifest.record(m, "pipeline_status", {"project_dir": project_dir}, "ok")
    _manifest.save(project_dir, m)

    return json.dumps({
        "ok": True,
        "project_dir": project_dir,
        "plant_name": m["plant_name"],
        "current_stage": cur["id"],
        "current_stage_name": cur["name"],
        "current_stage_status": cur["status"],
        "stages": [{"id": s["id"], "name": s["name"], "status": s["status"],
                    "summary": s.get("summary"),
                    "blocker": s.get("blocker")} for s in m["stages"]],
        "stale": stale_stages,
        "next_action": next_action,
    }, indent=2)


def _detect_stale(manifest, project_dir) -> list[int]:
    """For each passed stage, re-hash its artefact and compare to manifest."""
    pd = pathlib.Path(project_dir)
    stale = []
    hashers = {
        1: lambda: _hashing.hash_schematic(pd / f"{manifest['plant_name']}_schematic.html"),
        2: lambda: _hashing.hash_excel(pd / f"{manifest['plant_name']}_data.xlsx"),
        3: lambda: _hashing.hash_json(pd / "engineering_checks.json"),
        4: lambda: _hashing.hash_json(pd / "static_inputs.json"),
        6: lambda: _hashing.hash_json(pd / "controllers.json"),
        7: lambda: _hashing.hash_pack(pd / f"{manifest['plant_name']}.sumo-pack"),
    }
    for s in manifest["stages"]:
        if s["status"] != "passed":
            continue
        h_fn = hashers.get(s["id"])
        if not h_fn:
            continue
        try:
            current = h_fn()
        except FileNotFoundError:
            stale.append(s["id"])
            continue
        if current != s["output_hash"]:
            stale.append(s["id"])
    return stale


def _recommended_action(manifest, current_stage, project_dir):
    sid = current_stage["id"]
    if current_stage["status"] == "stale":
        return {"tool": "pipeline_advance",
                "reason": f"Stage {sid} ({current_stage['name']}) artefact changed since last advance — re-validate.",
                "args": {"project_dir": project_dir, "from_stage": sid}}
    if current_stage["status"] == "failed":
        msg = current_stage.get("blocker", "see manifest for details")
        return {"tool": _stage_entry_tool(sid),
                "reason": f"Stage {sid} failed: {msg}. Fix and re-advance.",
                "args": {"project_dir": project_dir}}
    if current_stage["status"] == "pending":
        return {"tool": _stage_entry_tool(sid),
                "reason": f"Stage {sid} ({current_stage['name']}) not started — begin here.",
                "args": {"project_dir": project_dir}}
    # all passed
    return {"tool": None, "reason": "All stages passed. Project is complete."}


_STAGE_ENTRY_TOOLS = {
    0: "pipeline_init",
    1: "stage1_open_schematic",
    2: "stage2_open_data",
    3: "stage3_run_engineering_checks",
    4: "stage4_define_static_inputs",
    5: "stage5_generate_dynamic_inputs",
    6: "stage6_add_controller",
    7: "stage7_build",
    8: "stage8_verify",
}


def _stage_entry_tool(stage_id: int) -> str:
    return _STAGE_ENTRY_TOOLS.get(stage_id, "pipeline_status")
```

The remaining 18 handlers follow the same pattern: load manifest → do work → write artefact → re-hash → write manifest → return JSON.

### 10.3 `PY/server.py` — register the Group EE block in the tool list

After the existing Group DD/EE definitions, append the 19 new entries. Update `validate_sumo_environment` to report:

```python
env["pipeline_module_loaded"] = True
env["pipeline_project_count"] = len(list(pathlib.Path(CONFIG.get("models_dir","./Claude Models")).glob("*/project.yaml")))
```

### 10.4 `wwtp_schematic_template.html` — palette parity check on save

Add a runtime check inside `persistState()` that compares the in-memory `UNIT_TYPES` keys against a hardcoded list of expected types. If a unit on the canvas has a type not in the registry, the schematic-data block is **not** written and a banner appears: "Unsaved: unit U3 has type 'grit_chamber' which is not in the palette. Use stage1_validate_schematic for diagnostics."

This is the last line of defence against the Qaha1-style failure where a manual JSON edit slips an unsupported type past the builder.

### 10.5 `PY/smoke_test_pipeline.py` — end-to-end test

Replaces all prior smoke tests. Builds a Qaha1-like project from scratch and runs every stage. The success criterion is `pipeline_status` returning `current_stage: 7, status: passed` at the end. Stage 8 is marked `[SKIP]` unless SUMO is available on the machine.

```python
"""smoke_test_pipeline.py — end-to-end pipeline smoke test."""
import json, tempfile, pathlib, sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Import directly rather than through MCP for testability
from pipeline import manifest, hashing, snapshot, seeding
# ... etc

def main():
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td) / "TestPlant"

        # Stage 0
        # ... (call pipeline_init's body directly)

        # Stage 1: load Classic AS template, validate, advance
        # Stage 2: seed Excel from schematic, fill in mock values, validate, advance
        # Stage 3: run engineering checks (use deliberately marginal values)
        # Stage 4: resolve static inputs
        # Stage 5: SKIP
        # Stage 6: SKIP
        # Stage 7: build pack, verify all expected files present
        # Stage 8: SKIP (requires SUMO)

        m = manifest.load(proj)
        passed = sum(1 for s in m["stages"] if s["status"] == "passed")
        skipped = sum(1 for s in m["stages"] if s["status"] == "skipped")
        assert passed >= 6, f"only {passed} stages passed"
        print(f"PASS: {passed} passed, {skipped} skipped")


if __name__ == "__main__":
    main()
```

---

## 11. Migration Strategy

The existing 155 tools stay. Nothing is removed. The pipeline tools are additive and become the *recommended* entry points; the underlying tools remain callable for one-off use, scripting, and debugging.

Migration phases:

**Phase A (week 1):** Ship the pipeline sub-package and the 5 driver tools (`pipeline_init` / `_status` / `_advance` / `_revert` / `_describe`). The driver works against any existing project that has a manifest. New projects start using the pipeline immediately. Old projects continue working as before.

**Phase B (week 2):** Ship stages 1-3 (the gates with the highest historical failure rate). At this point any new build goes through schematic→parameters→engineering with proper gating.

**Phase C (week 3):** Ship stages 4-7. End-to-end build-pack generation is now pipeline-driven.

**Phase D (week 4):** Ship stage 8 verification and the post-SUMO loop. Add palette parity check to the HTML builder.

**Phase E (deferred):** Move the deprecated Group DD tools from `ok=False, deprecated=True` to "hidden" — drop them from the public tool list but keep the dispatch handlers so any old scripts get the deprecation message.

---

## 12. Validation: Regression Against Every Prior Failure Mode

Each failure mode logged in the prior sessions is now blocked by a specific pipeline gate.

| Prior failure | Where it was caught (before this plan) | Where it's caught now |
|---|---|---|
| Hand-rolled 29.8 KB `.sumo` | User opening in SUMO | Stage 7 — only `build_sumo_pack`-produced stubs leave the pipeline |
| `grit_chamber` not in registry | `build_sumo_pack` halfway through | Stage 1 validator with closest-match suggestion |
| DLL copied from unrelated model | Never — silent failure at sim time | Stage 8 `verify_dll_matches_schematic` |
| Excel Connections sheet empty | `build_model_from_template` | Stage 2 `seed_excel_from_schematic` pre-fills from Stage 1 |
| `WAS` unit missing from Treatment_Processes | `validate_wwtp_template` 22 errors deep | Stage 2 — auto-seeded from schematic, can't be missing |
| Regex destroyed HTML | Manual file reconstruction | Stage 1 uses `update_schematic_in_html` (comment-aware) |
| Wrong DLL silently produced empty project | Trial sim with no compliance error | Stage 8 trial sim + mass-balance check refuses |
| `ok=True` with critical warnings on `diagnose_sumo_file` | User had to read warnings | Pipeline never relies on it — uses fresh validators per stage |
| Stage skipped without record | Lost between sessions | Manifest records every skip with reason |
| Re-edit invalidates downstream | Silent — old artefacts used | Hash chain marks stale, refuses to advance until re-run |

---

## 13. What Could Still Go Wrong

Acknowledged residual risks, with mitigations:

| Risk | Mitigation |
|---|---|
| User edits Excel without going through pipeline, advances anyway | Hash check on advance catches the change; stage marked stale; user notified |
| Two Claude sessions racing on the same project | `project.yaml` writes are atomic (write-temp-then-rename); first writer wins; loser sees a re-hash mismatch and re-runs |
| `ruamel.yaml` not installed | Plain `yaml` fallback works but loses comments on round-trip; non-fatal |
| SUMO updates its `.sumo` format | Stage 7 stub format is documented to be a minimal stub; if SUMO 25 requires more, edit one string |
| DTT becomes available later | Add Tier-3 dispatch in Stage 7 as an alternative to the manual hand-off; stage logic doesn't need to change |
| User skips Stage 3 (engineering) | Refused — Stage 3 is not optional. Failing the design at Stage 3 is the *point*. |
| Snapshots fill the disk | Bounded at 30 per project; manual cleanup tool can be added |

---

## 14. The User's Experience, After

For someone building a new WWTP — Qaha2, say:

```
> pipeline_init project_dir="F:/.../Qaha2" plant_name="Qaha2" from_template="qaha_oxditch"
  → Scaffolded. Next: edit Qaha2_schematic.html in browser, then call pipeline_advance.

(user opens HTML, edits topology — adds an MBR train — saves)

> pipeline_advance
  → Stage 1 PASSED. 17 units, 19 streams. Stage 2 seeded with unit names.
    Next: edit Qaha2_data.xlsx (numbers only; names are pre-filled).

(user fills in Excel — sizing, fractionation, influent stats)

> pipeline_advance
  → Stage 2 PASSED. Stage 3 ready to run.

> pipeline_advance
  → Stage 3 FAILED: Takacs SOR exceeded (27.1 > 24.0).
    Fix: Increase clarifier surface area to ≥ 690 m² in Qaha2_data.xlsx.
    Next: re-advance Stage 2 after fixing.

(user edits clarifier A from 615 to 700 m², saves)

> pipeline_advance
  → Stage 2 PASSED (re-validated). Stage 3 marked stale.

> pipeline_advance
  → Stage 3 PASSED. SRT=12.4d, HRT=18.2h, F:M=0.21, MB closure=98.7%.

> pipeline_advance
  → Stage 4 PASSED. Static inputs resolved.

> pipeline_advance skip=true skip_reason="steady state only"
  → Stage 5 SKIPPED.

> pipeline_advance skip=true skip_reason="manual control"
  → Stage 6 SKIPPED.

> pipeline_advance
  → Stage 7 PASSED. Build pack written to Qaha2.sumo-pack/.
    Open Qaha2.sumo in SUMO24 GUI; follow BUILD_INSTRUCTIONS.md.

(user goes into SUMO, compiles, saves state, applies scripts — 5 min)

> stage8_verify
  → Stage 8 PASSED. 54/54 schematic refs resolved in DLL. Trial sim converged.
    Mass balance: COD 99.1%, N 97.4%, P 98.2%.
    Project complete.
```

No file format guesses. No "did I do the steps in the right order?". No silent failures. The pipeline is the workflow.

---

*End of master plan. Implement in the order of §11. The validation matrix in §12 is the definition of done — every row must turn into a closed regression in the new smoke test.*
