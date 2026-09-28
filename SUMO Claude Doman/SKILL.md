---
name: sumo24-modelling
description: >-
  Plan and execute wastewater treatment plant (WWTP) modelling tasks against the
  SUMO24 MCP server (the Qaha WWTP digital twin, 148 tools, Groups A–DD). Use this
  skill WHENEVER the user asks anything about SUMO, SUMO24, a .sumo file, the Qaha
  plant, WWTP simulation, an activated-sludge / ASM / MBR / digester model, an
  influent or effluent dataset, Law 48/1982 compliance, calibration, scenario
  comparison, a process-failure diagnosis (nitrification, bulking, EBPR), building
  a plant from an Excel template or HTML schematic, or generating an academic
  report/figures from simulation results — even if they do not name a specific
  tool. The skill turns a vague modelling request into an ordered, validated
  tool-call plan and runs it. Always consult this skill before calling any
  sumo24 MCP tool.
---

# SUMO24 WWTP Modelling — Planning & Execution

This skill makes you a competent SUMO24 modelling engineer driving the MCP server.
SUMO is a third-generation wastewater process simulator; the MCP server wraps its
Digital Twin Toolkit (DTT) and a schematic/Excel build pipeline as **148 tools in
15 groups (A–DD)**. The default project is the **Qaha WWTP** (Egypt), regulated by
**Egyptian Law 48/1982** (Decrees 92/2013, 208/2018) and Egyptian Standard
501/2015 for reuse. Authoritative design reference: Metcalf & Eddy 5th ed.

Your job for any request: **classify → plan → gate → execute → verify → report.**
Never fire tools ad hoc. A WWTP model is a coupled mass-balance system; an
unvalidated run produces confident nonsense.

## Step 0 — Always orient first

Before planning, establish ground truth with cheap read-only calls. Do not skip
this even if the user is specific.

1. `validate_sumo_environment` — confirms DTT import, DLL, state.xml, license,
   openpyxl, schematic_parser, directory layout. If this fails, the task is a
   *troubleshooting* task (see below) regardless of what was asked.
2. `get_model_info` + `get_compile_status` — is a model loaded? compiled? when?
3. If the user references a file/dataset/scenario you have not seen, read it
   (`read_wwtp_template`, `read_dataset_excel`, `list_scenarios`,
   `read_sumo_manifest`) before proposing a plan.

State what you found in one or two sentences, then present the plan.

## Step 1 — Classify the task

Every request maps to one of seven families. Pick the dominant one (a request can
chain families — e.g. "build it and check compliance" = BUILD then SIMULATE).

| Family | Trigger phrases | Entry point |
|---|---|---|
| **BUILD** | "create / build a plant", "from my Excel/template", "from the schematic", "make a .sumo" | `references/workflows.md` §Build |
| **CONFIGURE** | "set / change parameter", "size the aeration tank", "switch to ASM2d", "apply my influent" | `references/workflows.md` §Configure |
| **SIMULATE** | "run steady state", "run 30 days", "what's the effluent", "is it compliant" | `references/workflows.md` §Simulate |
| **CALIBRATE** | "match my data", "calibrate", "compare measured vs simulated", "tune until it fits" | `references/workflows.md` §Calibrate |
| **SCENARIO** | "compare scenarios", "what if RAS↑", "increased SRT case", "sensitivity" | `references/workflows.md` §Scenario |
| **DIAGNOSE** | "why is nitrification failing", "bulking", "P removal broken", "results look wrong" | `references/workflows.md` §Diagnose |
| **TROUBLESHOOT** | ".sumo won't open", "crash", "license error", "DLL", environment check failed | `references/workflows.md` §Troubleshoot |
| **REPORT** | "academic report", "publication figures", "LaTeX/Word table", "export results" | `references/workflows.md` §Report |

Read the matching section of `references/workflows.md` for the exact ordered
tool sequence. Read `references/tool-catalog.md` when you need the precise tool
for a sub-step. Read `references/sumo-domain.md` for variable naming, kinetic
models, engineering sanity ranges, and Law 48 limits — and consult the bundled
SUMO PDFs (see that file) for deep process-model questions.

## Step 2 — Write the plan before acting

Produce a short numbered plan and show it to the user before executing anything
that mutates state or runs a simulation. Each step names the tool and its
purpose. Example for "build my plant from the Excel template and check it's
compliant":

```
1. read_wwtp_template        — load & echo the workbook
2. validate_wwtp_template    — required fields, dangling streams, COD-fraction sum
3. build_model_from_template — dry_run=True first → review build plan
4. build_model_from_template — dry_run=False → create .sumo + wire + size
5. validate_full_model       — GATE (must be READY_TO_SIMULATE)
6. run_steady_state          — effluent + Law 48 status
7. validate_post_simulation  — GATE (must be RESULTS_VALID)
8. generate_report           — design summary
```

Read-only exploration (list_*, get_*, read_*, validate_*, preview_*, *_diff,
compare_*) needs no approval — run it freely. Mutating or expensive actions
(build_*, set_*, run_*, save_*, compile_*, apply_*, optimize_*, export_*) get
the plan shown first; if the user already said "do it", proceed.

## Step 3 — The two mandatory gates

These are non-negotiable. They exist because the failure mode of WWTP simulation
is silent: the solver converges to a physically impossible state and reports
clean numbers.

**Pre-run gate.** Before *any* `run_steady_state` / `run_dynamic_simulation` /
`run_scenario_comparison`, call **`validate_full_model`**. It returns
`READY_TO_SIMULATE` / `CHECK_WARNINGS` / `DO_NOT_SIMULATE`.
- `READY_TO_SIMULATE` → proceed.
- `CHECK_WARNINGS` → summarise the warnings to the user, proceed only if they are
  benign (e.g. cosmetic naming) or the user accepts them.
- `DO_NOT_SIMULATE` → stop, report the blocking issues, propose fixes. Do not run.

**Post-run gate.** After every completed run, call **`validate_post_simulation`**
(mass-balance closure, convergence, plausibility). It returns
`RESULTS_VALID` / `RESULTS_SUSPECT` / `RESULTS_INVALID`.
- Never present effluent numbers, compliance verdicts, or figures from a
  `RESULTS_INVALID` job. Say the run is invalid and why.
- `RESULTS_SUSPECT` → present results *with* the caveat and the specific concern.

Targeted validators (`validate_mass_balance_*`, `validate_mlss_health`,
`validate_srt_fm_feasibility`, `validate_do_levels`, `validate_asm_kinetics`,
`validate_hydraulic_balance`, `validate_simulation_convergence`) are diagnostic
zoom-ins — use them to explain a gate failure, not to replace the gates.

## Step 4 — Execute, adapting to results

Run the plan step by step. After each tool call, check the result before the next
step. If a step fails or a validator blocks:
1. Read the structured error / suggestions the tool returned.
2. Map it to a fix (the diagnostic tools — `diagnose_*`,
   `recommend_setpoint_adjustments` — name the corrective tool to use).
3. Apply the smallest corrective change, re-validate, continue. Don't restart
   the whole pipeline for a one-parameter fix.

For long dynamic runs: `run_dynamic_simulation` returns a job ID. Poll with
`get_job_status`; only analyse once complete.

## Step 5 — Report honestly

Lead with the answer the user asked for (compliant? what changed? root cause?).
Then the supporting numbers, then caveats. State which gates passed. If you
changed parameters in-memory, say so and note they aren't persisted unless
`set_parameter_persistent` / `save_state` / `save_model` was called.

Quantitative claims must come from a tool result, never from estimation. If a
number wasn't produced by a run or a dataset read, don't state it — run the tool
or say it's unknown.

## SUMO variable naming — the one rule you must internalise

SumoCore variables are case-sensitive, double-underscore separated:

```
Sumo__Plant__<UnitName>__param__<suffix>      # editable parameter
Sumo__Plant__<UnitName>__<state-variable>     # computed state
Sumo__StopTime, Sumo__DataComm                # simulation control
```

Never guess a variable name. Resolve it with `search_variables`,
`list_parameters`, or `validate_variable_name` (which returns up-to-10
suggestions on a miss) before `set_parameter`. Full convention, kinetic-model
parameter sets, and engineering ranges: `references/sumo-domain.md`.

## Hard constraints

- The MCP server only **prepares** projects; actual `.sumo` *compilation* of new
  topology happens in the SUMO GUI. `compile_model` checks/forces a recompile but
  cannot itself compile. Tell the user when a GUI step is required.
- `build_model_from_template` / `build_model_from_schematic` override parameters
  on units that exist in the compiled model; they don't invent topology. Full
  topology generation is the schematic-to-.sumo compiler (Group DD) or
  `generate_sumoslang_from_schematic` (a hand-editable skeleton, not final).
- In-memory parameter changes apply to the *next run only*. Persist deliberately.
- Don't fabricate scenario names, measurement points, or unit names — enumerate
  them first (`list_scenarios`, `list_dataset_measurement_points`,
  `list_unit_processes`).

## Reference files

- `references/workflows.md` — the ordered playbook for each task family. Read the
  section matching your classification *before* writing the plan.
- `references/tool-catalog.md` — all 148 tools by group with "use when". Read when
  you need the exact tool for a sub-step.
- `references/sumo-domain.md` — variable naming, ASM1/2d/3 & Sumo1/2 kinetic
  models, engineering sanity ranges (SRT/HRT/F:M/MLSS/SVI), Law 48 & ES 501/2015
  limits, the .sumo file format, and a guide to the bundled SUMO PDF manuals for
  deep process questions.
