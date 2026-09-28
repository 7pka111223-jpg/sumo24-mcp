# SUMO24 MCP Tool Catalog (148 tools, Groups A–DD)

Lookup table for picking the exact tool for a sub-step. Workflows in
`workflows.md` already sequence these; come here when you need the precise tool
or its purpose. `(ro)` = read-only/safe to run freely; everything else mutates
state, runs a simulation, or writes a file → show the plan first.

## Group B — Simulation Runs (2)
- `run_steady_state` — steady-state Qaha run, optional influent overrides;
  returns effluent + Law 48 status.
- `run_dynamic_simulation` — dynamic run for N days; transient/storm/seasonal;
  returns a job ID to poll.

## Group C — Reports & Diagnostics (6, all ro)
- `get_job_status` — poll a scheduled job.
- `get_effluent_statistics` — min/max/mean of every numeric column in a job CSV.
- `get_sludge_production` — WAS rate, SRT, biosolids estimate from a job.
- `get_energy_estimate` — DO setpoints + airflow params as an aeration-energy proxy.
- `list_completed_jobs` — every in-memory job with status/scenario/type.
- `get_mass_balance` — COD/N/P/TSS in-vs-out from a job's CSV.

## Group D — Topology Editing (11)
- `list_unit_processes` (ro) — units visible in the compiled model.
- `get_unit_process_info` (ro) — params + state vars for one unit.
- `list_available_unit_process_types` (ro) — all SUMO24 unit types.
- `add_unit_process` — add a unit via DTT executeCommand; optional kinetic model.
- `remove_unit_process` — remove a unit (+ optionally its streams).
- `list_available_kinetic_models` (ro) — ASM1/2d/3, ADM1, MBR, Takács, …
- `connect_unit_processes` — create a flow stream between two units.
- `add_recycle_stream` — RAS/WAS/internal-recycle/reject/sidestream loop.
- `modify_flow_connection` — redirect/resize a stream.
- `list_flow_streams` (ro) — registered streams + compiled flow vars.
- `add_controller` — DO/SRT/NH4/NO3/FlowSplitter control loop with setpoint.

## Group E — Model Lifecycle (11)
- `get_model_info` (ro) — DLL/state.xml/var counts/compile status.
- `save_state` — snapshot in-memory state → timestamped state.xml.
- `load_state` — point server at a different state.xml.
- `list_saved_states` (ro) — state.xml snapshots in outputs/.
- `get_compile_status` (ro) — DLL+state readiness + timestamps.
- `create_model` — blank project folder + .sumo stub (build-from-scratch start).
- `load_model` — load an existing .sumo, auto-detect adjacent DLL/state.xml.
- `save_model` — copy .sumo + DLL + fresh state snapshot.
- `compile_model` — check/force recompile (actual compile is GUI-side).
- `extract_dll` — locate/register a compiled sumoproject.dll.
- `initialize_state` — reset to baseline state.xml; clears in-memory overrides.

## Group F — Scenarios (8)
- `run_scenario_comparison` — multi-scenario side-by-side vs Law 48.
- `list_scenarios` (ro) — defined scenarios + their param changes.
- `create_scenario` / `update_scenario` / `delete_scenario` / `clone_scenario` —
  manage the in-memory SCENARIOS dict.
- `get_scenario_diff` (ro) — params differing between two scenarios.
- `import_scenario` — load a .scs script as a scenario.

## Group G — Parameters (26)
- `set_parameter` / `get_parameter` (ro) / `list_parameters` (ro) /
  `set_multiple_parameters` / `reset_parameter_to_default` — raw param access.
- `set_kinetic_model` — switch a reactor's biological model.
- `set_influent_characteristics` — composition + flow in one call (lab→SUMO map).
- `set_fractionation` — COD/TSS fractions (Xs, Xp, Si, Ss, Xi, fXS…).
- `set_parameter_persistent` — write a param into state.xml (survives restart).
- `set_asm1_kinetics` / `set_asm2d_kinetics` / `set_asm3_kinetics` — kinetic +
  stoichiometric sets; nulls fall back to Arrhenius-corrected research defaults.
- `apply_temperature_correction` — recompute Arrhenius-corrected ASM params at a
  new T; flags >20% shifts.
- `set_plant_wide_parameters` — global T + Law 48 target ('nile'/'drain').
- `set_influent_parameters` — flow/composition/COD fractionation (Egyptian
  municipal defaults).
- `set_primary_clarifier_parameters` / `set_secondary_clarifier_parameters`
  (Takács) / `set_aeration_tank_parameters` / `set_anoxic_zone_parameters` /
  `set_anaerobic_zone_parameters` / `set_mbr_parameters` /
  `set_ras_was_parameters` / `set_digester_parameters` /
  `set_chemical_dosing_parameters` — unit-specific sizing/operation with
  literature defaults (Metcalf & Eddy, Takács 1991/BSM1, Judd MBR).
- `set_dynamic_simulation_parameters` — duration/timestep/solver/warm-up/diurnal/
  storm/seasonal T.
- `assume_parameters_from_research` (ro) — full research-default recommendation
  sized to plant scale + T; returns a dict to review, does NOT apply.

## Group H — Datasets (13, mostly ro)
- `create_dynamic_input_table` — build a TSV input profile matching
  Sumo__StopTime/Sumo__DataComm (constant/ramp/step/sinusoid/custom).
- `list_state_variables` (ro) / `get_state_variable` (ro) / `search_variables`
  (ro) — variable discovery (use before set_parameter).
- `import_influent_profile` — register a time-varying influent CSV by label.
- `read_dataset_excel` (ro) — structured summary of the WWTP Excel dataset.
- `list_dataset_measurement_points` (ro) — points + their mapped SUMO units.
- `get_measurement_point_data` (ro) — measured params at a point; flags Law 48.
- `get_parameter_across_points` (ro) — trace one parameter end-to-end + removal %.
- `get_law48_limits_from_excel` (ro) — pull Law 48 row, sync into CONFIG.
- `map_dataset_to_sumo_variables` (ro) — resolve dataset cells → compiled vars.
- `apply_influent_from_dataset` — apply one dataset row to the Influent unit.
- `apply_point_to_unit` — apply a point's values to a unit (unit_override ok).

## Group X — Validation (19, all ro) — the safety layer
- `validate_full_model` — **pre-run gate**; READY/CHECK_WARNINGS/DO_NOT_SIMULATE.
- `validate_post_simulation` — **post-run gate**; RESULTS_VALID/SUSPECT/INVALID.
- `ensure_dtt_bridge` — (re)install dynamita_compat shim; reports buffered queue.
- `validate_variable_name` — exists? else ≤10 suggestions.
- `validate_model` — config/readiness; 'full' adds a quick steady-state probe.
- `validate_dataset` / `check_dataset_against_law48` — dataset sanity + limits.
- `validate_model_structure` — DLL+state present/consistent; required unit types.
- `validate_influent_configuration` — non-zero flow/COD, T/pH range, COD:TKN.
- `validate_mass_balance_pre_run` / `validate_mass_balance_post_run` — closure
  (well-behaved plants close ±5%).
- `validate_mlss_health` — MLSS, MLVSS/MLSS, heterotroph/nitrifier fractions vs
  Metcalf & Eddy.
- `validate_srt_fm_feasibility` — actual vs target SRT, F/M, HRT.
- `validate_do_levels` — zone DO ranges (aerobic 1.5–2.5, anoxic ~0, anaerobic ~0)
  + KLa.
- `validate_oxygen_demand_vs_supply` — O2 demand (BOD+nitrification) vs KLa supply.
- `validate_hydraulic_balance` — Q continuity, RAS ratio, SOR, underflow conc.
- `validate_asm_kinetics` — mu_H/K_S/b_H/Y_H/… vs IWA/Henze bounds (typo catcher).
- `validate_simulation_convergence` — steady/stable over last N% of series.
- `validate_simulation_plausibility` — negatives, pH 4–10, DO oversaturation,
  effluent>influent for conserved species.

## Group Y — Optimisation / Diagnostics / Economics (13)
- `check_compliance` (ro) — Law 48/1982 verdict from a job or direct values.
- `apply_dataset_to_model` — full calibration import (dry_run / only_influent).
- `compare_dataset_vs_simulation` (ro) — per-point deltas + MAPE.
- `compute_removal_efficiencies_from_dataset` (ro) — data-only removal %.
- `scan_parameter_sensitivity` (ro) — sweep a param, record an output.
- `optimize_was_for_target_srt` / `optimize_kla_for_target_do` — analytical
  solves that apply the result.
- `diagnose_nitrification_failure` / `diagnose_bulking_risk` /
  `diagnose_phosphorus_removal` (ro) — ranked root causes + fixes.
- `recommend_setpoint_adjustments` (ro) — priority-ranked aggregated fixes.
- `estimate_annual_opex` (ro) — energy + sludge + chemicals USD/yr.
- `estimate_ghg_emissions` (ro) — Scope 2 power + Scope 1 N2O/CH4 kg CO2eq/yr.

## Group Z — Academic Export (17, file-writing)
`export_results_csv`, `export_scenario`, `generate_report`,
`export_simulation_to_dataset`, `export_comparison_report`,
`plot_time_series_chart`, `export_publication_time_series`,
`export_calibration_parity_plot`, `export_scenario_comparison_bar_chart`,
`export_sensitivity_tornado_diagram`, `export_box_plot_distributions`,
`export_academic_results_table_docx`, `export_latex_results_table`,
`export_statistical_summary_xlsx`, `export_academic_report_docx`,
`export_multi_file_batch_comparison`, `export_mass_balance_diagram`.
See `workflows.md` §Report for when to use which.

## Group AA — WWTP Excel Template (4)
- `generate_wwtp_template_xlsx` — fresh input workbook.
- `read_wwtp_template` (ro) — parse a filled workbook.
- `validate_wwtp_template` (ro) — required fields, dupes, dangling streams,
  COD-fraction sum.
- `build_model_from_template` — build from scratch (units, streams, sizing,
  influent); supports `dry_run`.

## Group BB — HTML Schematic ↔ SUMO (5)
- `import_schematic_from_html` (ro) — extract + validate embedded schematic JSON.
- `build_model_from_schematic` — parameter overrides onto existing compiled units
  (not topology); optional .scs.
- `compare_schematic_to_model` (ro) — schematic vs compiled diff.
- `generate_sumoslang_from_schematic` — advanced topology skeleton (hand-edit
  before SUMO accepts it).
- `list_schematic_unit_types` (ro) — the 23-type registry.

## Group CC — SUMO Troubleshooting (7)
- `diagnose_sumo_file` (ro) / `scan_sumo_directory` (ro) — file health.
- `check_dll_companion` (ro) — DLL co-located with .sumo?
- `repair_sumo_file` — auto-fix common breakage (backs up first).
- `diagnose_sumo_crash` (ro) — parse logs for known signatures.
- `validate_sumo_environment` (ro) — end-to-end env health.
- `list_sumo_diagnostics` (ro) — full signature/remediation catalogue.

## Group DD — Schematic-to-SUMO Compiler (6)
- `compile_schematic_to_sumo` — validated schematic dict → .sumo zip.
- `build_sumo_from_html` — HTML → .sumo in one call (canonical entry).
- `preview_sumo_manifest` (ro) — render manifest/state/metadata without writing.
- `attach_companion_dll` — copy sumoproject.dll beside a .sumo.
- `verify_sumo_file_against_schematic` (ro) — compile-fidelity check.
- `read_sumo_manifest` (ro) — parsed unit/stream/state-var summary.
