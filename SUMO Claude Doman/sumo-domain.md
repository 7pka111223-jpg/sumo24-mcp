# SUMO24 Domain Knowledge

Background a modelling engineer needs when planning/executing tasks. For deep
process-model detail, consult the bundled SUMO PDFs (guide at the end).

## 1. SumoCore variable naming

Case-sensitive, double-underscore separated. Three shapes:

```
Sumo__Plant__<UnitName>__param__<suffix>     editable design/operational parameter
Sumo__Plant__<UnitName>__<stateVar>          computed state (read, don't set)
Sumo__StopTime  Sumo__DataComm  Sumo__...    simulation-control globals
```

`<UnitName>` is the instance name as it exists in the *compiled* model — not the
schematic label, not the Excel `instance_name` unless they happen to match.
Always discover real names before writing:

- `list_unit_processes` → real unit names.
- `list_parameters` (substring filter) / `search_variables` → real variable names.
- `validate_variable_name` → confirms existence, returns ≤10 suggestions on miss.

A wrong variable name is the single most common cause of a "successful" call that
changes nothing. `validate_asm_kinetics` exists specifically because a fat-finger
like `Y_H = 6.7` (should be ~0.67) silently wrecks a run.

## 2. Process / kinetic models

SUMO is a full-plant simulator (mainstream + digestion + sidestream in one model).
Model families, simplest → most detailed:

- **Mini_Sumo** — OUR & sludge-production focus; OHO, nitrifiers, methanogens,
  algae; no precipitates, simplified P.
- **Sumo1** — one-step nitrification whole-plant; OHO, nitrifiers, carbon-storing
  organisms mimicking PAO/GAO; no pH calc; O2/CH4 gas transfer.
- **Sumo2** — two-step nitrification + fuller physico-chemistry (consult the
  Technical Reference for the exact organism/precipitate set).
- **ASM1** — COD removal, single-step nitrification, denitrification (no bio-P).
  Params: mu_H, K_S, b_H, Y_H, mu_A, K_NH, b_A, Y_A, k_h, K_X.
- **ASM2d** — adds biological P (PAOs), GAOs, chemical precipitation; heterotroph,
  PAO, autotroph, precipitation parameter blocks.
- **ASM3** — endogenous respiration + internal storage (X_STO).
- **ADM1** — anaerobic digestion; **Takács** — secondary-settler model.

Set/switch with `set_kinetic_model`; tune with the matching
`set_asm{1,2d,3}_kinetics`. Null params fall back to IWA/Egyptian research
defaults, **Arrhenius-corrected to the operating temperature**. After any
temperature change call `apply_temperature_correction` (it flags any parameter
that moved >20%). Choose the model to the question: nutrient-removal compliance
needs ASM2d/Sumo2; a quick BOD/energy screen can use ASM1/Sumo1.

## 3. Engineering sanity ranges (Metcalf & Eddy 5th ed., warm climate)

Use these to sanity-check inputs and explain validator output — not as hard
limits (site-specific).

| Quantity | Typical conventional AS | Notes |
|---|---|---|
| SRT | 5–15 d (≥8–10 d for stable nitrification, warm) | nitrifier washout if too low |
| HRT (aeration) | 4–8 h | |
| F/M | 0.2–0.5 kg BOD/kg MLVSS·d | high → bulking risk |
| MLSS | 2,500–4,500 mg/L (MBR 8,000–12,000) | |
| MLVSS/MLSS | 0.7–0.85 | |
| DO aerobic | 1.5–2.5 mg/L | anoxic ~0, anaerobic ~0 |
| SVI | <120 mL/g good; >150 bulking | |
| RAS ratio | 0.5–1.0 of influent Q | |
| Sec. clarifier SOR | 0.7–1.3 m/h (peak ≤2.0) | |
| Mass-balance closure | within ±5% (COD/N/P/TSS) | post-run gate territory |
| Influent COD:TKN | ~8–12 municipal | low → poor denitrification |
| Anaerobic zone for EBPR | DO≈0, no NO3 intrusion, COD:TP sufficient | |

Diagnostics encode these: `diagnose_nitrification_failure` (SRT/T/pH/DO),
`diagnose_bulking_risk` (SVI/F:M/DO/COD:TP), `diagnose_phosphorus_removal`
(anaerobic DO/NO3/COD:TP). `assume_parameters_from_research` returns a coherent
default set sized to plant scale + T when the user has no values.

## 4. Regulatory limits (Egypt)

**Law 48/1982** (as amended by Decrees 92/2013 & 208/2018) — discharge to
waterways. Server default `CONFIG['law48_limits']`: **TSS 50, BOD₅ 60, COD 80
mg/L** (the `'drain'`/agricultural-drain target; the `'nile'` target is
stricter). `set_plant_wide_parameters` switches target and resyncs limits;
`get_law48_limits_from_excel` pulls the exact limit row from the workbook into
CONFIG. Always report compliance against the *configured* target and say which
one it is.

**Egyptian Standard 501/2015** — treated-water reuse for agriculture (quality
classes). Relevant when the user asks about reuse rather than discharge.

`check_compliance` and `check_dataset_against_law48` give the verdicts; never
hand-compute a pass/fail.

## 5. The `.sumo` file format

A `.sumo` is a zip container:

```
my_plant.sumo
├── manifest.xml     unit list, connections, parameter overrides
├── state.xml        steady-state initial values (one <variable> each)
├── metadata.json    summary + provenance
└── sumoslang.txt    optional SumoSlang skeleton
sumoproject.dll       companion — MUST sit in the same folder to load
```

SUMO loads a project only if the matching `sumoproject.dll` is co-located.
`attach_companion_dll` / `check_dll_companion` manage this. The MCP server can
*write* a .sumo and its manifest/state, but **new topology only becomes runnable
after a compile in the SUMO GUI** (`compile_model` checks/forces but cannot
itself compile). State this whenever the next step needs the GUI.

Canonical activated-sludge topology contract (the Mermaid loop the schematic
builder and Group DD enforce):

```
IN → AT → SC → EFF
SC → SPLIT → { RAS → AT (the loop) ,  WAS → WAS_OUT }
```

## 6. Build-from-template workbook map

`WWTP_Model_Input_Template.xlsx` sheets, in fill order:
`Plant_Info → Influent_Dataset & Influent_Fractionation → Effluent_Dataset &
Effluent_Targets → Treatment_Processes → Connections → Process_Sizing →
Bio_Operational / Phys_Operational / Chem_Operational` (+ `Variable_Map`).
`Treatment_Processes` is ordered by `order_index` (topological build order);
`Connections` carries `stream_type` + `recycle_type` for forward and loop
streams. `read_wwtp_template` echoes it all; `validate_wwtp_template` checks
required Plant_Info fields, duplicate instance names, dangling connections,
missing reactor/clarifier sizing, and the COD-fraction sum before a build.

## 7. Bundled SUMO reference PDFs — when to open which

These live in the project. Read them when a task needs process-model depth
beyond this file. They are SUMO-version documentation (Sumo22.1 lineage; the
server targets SUMO24 — concepts carry, exact UI/paths may differ).

- **Sumo_Technical_Reference.pdf** — the process models and unit operations in
  detail (organism groups, physico-chemistry, available functions in the
  standard library). Open for: "which model does X", kinetic structure,
  precipitate handling, unit-process equations.
- **The_Book_of_SumoSlang.pdf** — the SumoSlang modelling language: table
  structure, symbol roles, expandable symbols (SV/PAR/CVAR/SPC), rules,
  multi-model use. Open for: anything touching
  `generate_sumoslang_from_schematic`, custom models, or editing a .sumo's
  sumoslang.txt skeleton.
- **Sumo_User_Manual.pdf** / **Sumo_Quick_Tutorial.pdf** — GUI workflow,
  building/compiling a project, the Core Window. Open for: explaining the
  required GUI compile step, how a user extracts `state.xml`/`sumoproject.dll`,
  or where to find a variable name in the GUI.

When you cite specifics from a PDF, name the source. Do not invent equations or
parameter values — read them or say they need to be looked up in the GUI.
