# SUMO24 Workflow Playbooks

Ordered tool sequences for each task family. Read the section matching the
classification from SKILL.md Step 1, then turn it into the numbered plan you show
the user. `[GATE]` = mandatory validation that can stop the pipeline. `[approve]`
= mutating/expensive; show plan first unless the user already authorised it.
`(ro)` = read-only, run freely.

---

## §Build — create a model from scratch

Two supported source formats. Pick by what the user has.

### Path A — Excel template (Group AA, the structured path)

1. `generate_wwtp_template_xlsx` `[approve]` — only if the user has no workbook
   yet; otherwise skip and use theirs.
2. `read_wwtp_template` (ro) — load and echo Plant_Info, influent/effluent series,
   fractionation, processes, connections, sizing, operational rows.
3. `validate_wwtp_template` (ro) `[GATE]` — required Plant_Info fields, duplicate
   instance names, dangling connections, missing reactor/clarifier sizing,
   COD-fraction sum. Fix the workbook before continuing if it fails.
4. `build_model_from_template` with `dry_run=True` (ro) — review the build plan
   (units in topological order, streams, sizing, influent characteristics).
5. `build_model_from_template` with `dry_run=False` `[approve]` — creates the
   project folder + .sumo stub, adds units, wires forward + recycle streams,
   applies sizing/operational params, sets influent.
6. → continue into §Simulate (pre-run gate first).

### Path B — HTML schematic (Group BB / DD, the visual path)

The user must have built the plant in `wwtp_schematic_template.html` and clicked
**"Save HTML (for MCP)"** — without that the file has no embedded state. The
canonical topology contract is the Mermaid loop: `IN→AT→SC→EFF`,
`SC→SPLIT→{RAS→AT, WAS→WAS_OUT}`.

1. `import_schematic_from_html` (ro) — extract + validate the embedded JSON
   against the 23-type unit registry; returns parsed schematic + report.
2. `list_schematic_unit_types` (ro) — only if a unit type is unrecognised.
3. To **apply onto an existing compiled model**: `compare_schematic_to_model`
   (ro) → `build_model_from_schematic` `[approve]` (parameter overrides only;
   does not create topology).
4. To **produce a new .sumo file from the schematic** (Group DD):
   - `preview_sumo_manifest` (ro) — inspect manifest.xml / state.xml /
     metadata.json before writing.
   - `build_sumo_from_html` `[approve]` — end-to-end: read HTML → validate →
     write the `.sumo` zip. Refuses overwrite without the flag. Canonical entry.
   - `attach_companion_dll` `[approve]` — copy a known-good `sumoproject.dll`
     beside the `.sumo` (SUMO requires a co-located DLL to load).
   - `verify_sumo_file_against_schematic` (ro) `[GATE]` — confirm every unit and
     stream survived the compile (reports missing/extra IDs).
   - `read_sumo_manifest` (ro) — final unit/stream/state-variable count.
5. `generate_sumoslang_from_schematic` `[approve]` — only for advanced full
   topology generation; output is a hand-editable skeleton, **not** GUI-ready.

> New topology must be compiled in the SUMO GUI to produce a runnable DLL. Say
> so explicitly when the next action requires the GUI.

---

## §Configure — change an existing model

1. `list_unit_processes` (ro) → `get_unit_process_info` (ro) for the target unit.
2. Resolve every variable name before writing: `search_variables` /
   `list_parameters` / `validate_variable_name` (ro). Never guess.
3. Apply with the most specific tool available rather than raw `set_parameter`:
   - Influent: `set_influent_characteristics` / `set_influent_parameters` /
     `set_fractionation`, or `apply_influent_from_dataset` /
     `apply_point_to_unit` to pull from the Excel dataset.
   - Reactor sizing/aeration: `set_aeration_tank_parameters`,
     `set_anoxic_zone_parameters`, `set_anaerobic_zone_parameters`.
   - Clarifier: `set_primary_clarifier_parameters`,
     `set_secondary_clarifier_parameters` (Takács).
   - Kinetics: `set_kinetic_model` then `set_asm1_kinetics` /
     `set_asm2d_kinetics` / `set_asm3_kinetics`; `apply_temperature_correction`
     for a new operating temperature.
   - Sludge/recycle: `set_ras_was_parameters`, `set_digester_parameters`.
   - Chemical P: `set_chemical_dosing_parameters`.
   - Plant-wide: `set_plant_wide_parameters` (temperature + Law 48 target).
   - Many at once: `set_multiple_parameters`.
   - Unsure of good values: `assume_parameters_from_research` (ro — returns a
     recommendation sized to plant scale + temperature; does NOT apply it).
4. Persistence decision (state it to the user):
   - default `set_parameter` = next run only (in-memory).
   - `set_parameter_persistent` = written into state.xml (timestamped backup).
   - `save_state` / `save_model` = snapshot the whole model.
   - `reset_parameter_to_default` / `initialize_state` = undo in-memory changes.
5. Re-validate the touched subsystem (`validate_*`) before any run.

---

## §Simulate — run and report effluent / compliance

1. `validate_full_model` (ro) `[GATE]` — must not be `DO_NOT_SIMULATE`.
2. Steady state: `run_steady_state` `[approve]` (optional influent overrides) →
   returns effluent summary + Law 48 status.
   Dynamic: `set_dynamic_simulation_parameters` `[approve]` (duration, timestep,
   solver, diurnal/storm, seasonal T) → `run_dynamic_simulation` `[approve]` →
   poll `get_job_status` (ro) until complete. Optional `create_dynamic_input_table`
   / `import_influent_profile` for time-varying influent.
3. `validate_post_simulation` (ro) `[GATE]` — must be `RESULTS_VALID` (or present
   `RESULTS_SUSPECT` with the caveat). Never report from `RESULTS_INVALID`.
4. `check_compliance` (ro) — explicit Law 48/1982 verdict if not already clear.
5. Analysis (ro): `get_effluent_statistics`, `get_mass_balance`,
   `get_sludge_production`, `get_energy_estimate`.
6. `generate_report` (ro) — structured design summary. → §Report for publication
   artefacts.

---

## §Calibrate — match simulation to measured data

1. `read_dataset_excel` (ro) → `list_dataset_measurement_points` (ro) →
   `get_measurement_point_data` (ro) for key points.
2. `validate_dataset` (ro) `[GATE]` + `check_dataset_against_law48` (ro) — reject
   physically impossible measurements before calibrating to them.
3. `map_dataset_to_sumo_variables` (ro) — resolve every dataset cell to a real
   compiled variable; note unresolved cells.
4. `compute_removal_efficiencies_from_dataset` (ro) — data-only sanity baseline.
5. Apply data: `apply_dataset_to_model` with `dry_run=True` (ro) → review →
   `dry_run=False` `[approve]` (or `only_influent=True` for influent-only).
6. → §Simulate (both gates).
7. `compare_dataset_vs_simulation` (ro) — per-point deltas + MAPE.
8. Iterate: adjust kinetics/operational params (§Configure) → re-simulate →
   re-compare until MAPE acceptable. `scan_parameter_sensitivity` (ro) to find
   which parameter to move. `export_comparison_report` / `export_calibration_parity_plot`
   for the calibration record.

---

## §Scenario — comparison & sensitivity

1. `list_scenarios` (ro) — never invent scenario names; enumerate first.
2. Manage: `create_scenario` / `update_scenario` / `clone_scenario` /
   `delete_scenario` / `get_scenario_diff` / `import_scenario` / `export_scenario`
   `[approve for mutations]`.
3. `validate_full_model` (ro) `[GATE]`.
4. `run_scenario_comparison` `[approve]` — side-by-side TSS/BOD5/COD vs Law 48.
5. `validate_post_simulation` (ro) `[GATE]` per job.
6. Sensitivity: `scan_parameter_sensitivity` (ro) sweep + pair with
   `run_steady_state` for full effluent response; visualise with
   `export_sensitivity_tornado_diagram`.
7. Targeted optimisation: `optimize_was_for_target_srt`,
   `optimize_kla_for_target_do` `[approve]` (analytical solves, then verify by run).

---

## §Diagnose — explain a process failure or bad results

Start from the symptom; each diagnostic returns ranked root causes + the
corrective tool to use.

- Nitrification failing / high effluent NH4 → `diagnose_nitrification_failure`
  (SRT, T, pH, DO checks).
- Solids carryover / poor settling → `diagnose_bulking_risk` (SVI, F/M, DO,
  COD:TP).
- High effluent P / EBPR not working → `diagnose_phosphorus_removal` (anaerobic
  DO, NO3 intrusion, COD:TP).
- "Results look wrong" → run the targeted validators:
  `validate_mass_balance_post_run`, `validate_simulation_plausibility`,
  `validate_simulation_convergence`, `validate_mlss_health`,
  `validate_srt_fm_feasibility`, `validate_do_levels`,
  `validate_oxygen_demand_vs_supply`, `validate_hydraulic_balance`,
  `validate_asm_kinetics` (catches kinetic typos like Y_H = 6.7).
- Then `recommend_setpoint_adjustments` — aggregated, priority-ranked fixes
  (critical/high/medium) each naming the tool to apply.
- Apply the highest-priority fix via §Configure → re-simulate → re-check. One
  change at a time.

---

## §Troubleshoot — broken .sumo / environment / crash

Always start here if Step 0's `validate_sumo_environment` failed.

1. `validate_sumo_environment` (ro) — DTT import, DLL, state.xml, license,
   openpyxl, schematic_parser, layout.
2. `diagnose_sumo_file` (ro) on the specific file, or `scan_sumo_directory` (ro)
   to triage many.
3. `check_dll_companion` (ro) — confirm `sumoproject.dll` sits beside the .sumo.
4. `diagnose_sumo_crash` (ro) — parse recent SUMO/DTT logs for known signatures
   (license, DLL load, compile failure).
5. `list_sumo_diagnostics` (ro) — full catalogue of signatures + remediations.
6. `repair_sumo_file` `[approve]` — auto-fix empty/missing state.xml stub,
   missing DLL, zero-byte file, wrong extension. Backs up to `.sumo.bak` first.
7. `ensure_dtt_bridge` `[approve]` — (re)install the dynamita_compat shim if the
   installed DTT lacks executeCommand/.set/.getVariableNames.
8. Re-run `validate_sumo_environment` to confirm green before returning to the
   original task.

---

## §Report — academic / publication outputs

All read-only or file-producing; `[approve]` only because they write files.

- `export_results_csv` — raw time series.
- `generate_report` — structured design summary.
- `export_simulation_to_dataset` — fill a copy of the Excel template with
  simulated values (original untouched).
- `export_comparison_report` — colour-coded Measured/Simulated/Δ/Δ% calibration
  sheet.
- Figures (300 DPI, serif, colourblind palette, PNG+PDF+SVG):
  `plot_time_series_chart`, `export_publication_time_series`,
  `export_calibration_parity_plot` (R²/NSE/RMSE/PBIAS),
  `export_scenario_comparison_bar_chart`, `export_sensitivity_tornado_diagram`,
  `export_box_plot_distributions`, `export_mass_balance_diagram`.
- Tables: `export_academic_results_table_docx` (booktabs Word),
  `export_latex_results_table` (.tex booktabs),
  `export_statistical_summary_xlsx` (multi-sheet stats).
- `export_academic_report_docx` — full Methods/Results/Discussion/References
  Word report with embedded figures + tables across jobs.
- `export_multi_file_batch_comparison` — one call across multiple .sumo files /
  jobs → combined plots + XLSX + LaTeX.

Only build report artefacts from jobs that passed the post-run gate.
