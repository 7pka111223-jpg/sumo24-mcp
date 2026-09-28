# SUMO24 MCP: live review supplement

Date: 2026-09-08. Read together with [the architecture review](2026-09-08-server-architecture-review.md). This supplement supersedes that review's original static-only verification limit. Production Python sources were not edited. Live runs used isolated copies and a temporary `HH_ReviewProbe_v1` installation.

## Highest-priority live finding

**P1: both standard simulation tools fail before scheduling.** A real MCP SDK stdio client initialized the actual server, listed 235 tools, and called `run_dynamic_simulation` and `run_steady_state`. Both returned `isError: true` with `'SumoScheduler' object has no attribute 'dur'`. See [dynamic response](live-2026-09-08/mcp_run_dynamic_simulation.json) and [steady response](live-2026-09-08/mcp_run_steady_state.json).

The cause is [server.py:2718](../../PY/server.py#L2718): `_build_commands` assumes `ds.sumo.dur` exists. The installed/vendored scheduler does not expose it. Native runtime loading succeeded (SUMO 24.0.0), and direct native simulations completed, so this is a server adapter defect, not evidence of a missing SUMO installation.

**Exact requested change:** replace that attribute access with one tested duration conversion module (`DAY_MS = 86400000`, `HOUR_MS = 3600000`), validate finite positive durations/intervals, and use the same conversion in result summaries. Then run both tools through an actual `ClientSession` against the supported native scheduler. Assert a real job is scheduled and its lifecycle/result is reported correctly.

Fix [the hardcoded result symbols](../../PY/server.py#L2642) in the same patch: this test plant exposes `Effluent1`, `TCOD`, and `TBOD_5`, while the standard list assumes `Effluent`, `SCOD`, and `SBOD5`. Resolve the configured outlet and metric symbols against the compiled model before scheduling. Missing symbols must produce an actionable preflight error, never an empty successful result. The symbol mismatch is source/model evidence; execution currently stops at the duration error first.

## Actual live test results

Evidence JSON files are in [live-2026-09-08](live-2026-09-08/); the reproducible driver is [live_review_2026_09_08.py](live_review_2026_09_08.py).

| Check | Observed result |
|---|---|
| Real MCP initialize/list | Passed; 235 tools |
| Environment tool | Passed; native compiler/runtime dependencies located |
| Standard MCP dynamic and steady tools | Failed with missing `dur` attribute |
| MCP `check_compliance({})` | Incorrectly returned `COMPLIANT` with no parameters and `isError: false` |
| SMT + SlCompiler on isolated review unit | Passed; XML 1,250,933 bytes; linked PE32+ DLL 690,688 bytes |
| Nonreactive conservative tracer, 20 days | Passed; 961 rows, zero imbalances, worst relative residual 2.12e-15 |
| Reactive fixture with reaction rates zeroed, 20 days | Passed; 961 rows, zero imbalances, worst relative residual 2.12e-15 |
| Degenerate reactive/nonreactive equivalence | Passed; worst relative difference 2.88e-10 |
| Wrong-port negative fixture | Correctly rejected by preflight: no shared components |
| Unsorted negative native fixture | Correctly rejected after 49 rows, sentinel 99999.9 |
| Direct native plant dynamic smoke | Completed; 11 rows over 0.01 day with kinetics active |
| Review separator, positive flow | Completed; flow residual zero, TSS load residual 8.73e-11 g/d |
| Review separator, zero flow | Completed; all port flows zero, concentrations finite, load residual zero |
| Install to separate `99 HH Review Audit` category | Passed; three new files, no overwrite |
| MCP GUI launch/window/screenshot | Passed; launcher initially reported the splash window before main-window readiness |
| Visible SUMO palette and drag placement | Passed; [placement screenshot](live-2026-09-08/gui-unit-placed.png) |
| GUI parameter inspection / save / reopen | Not verified; desktop provider could not reliably target modal input |
| Uninstall review fixture | Passed; all three installed files removed, no files retained; [record](live-2026-09-08/uninstall.json) |

The direct plant smoke ended with effluent Q 7234.23 m3/d, TSS 3.8570 mg/L, total COD 32.7276 mg/L, BOD5 1.6834 mg/L, and ammonium 0.4251 mg/L. This short run demonstrates working native execution, not steady-state convergence, model calibration, or regulatory compliance.

For the review separator, the actual inlet was Q 3000 m3/d and **XTSS 207.1613 mg/L**. Setting the particulate state `XB` to 183 does not set total TSS to 183 because other constituent defaults contribute. Filtrate Q was 2670 with XTSS 78.5141; wash Q was 330 with XTSS 1248.0337. This confirms conservative separation and also shows why tests must assert the measured aggregate inlet rather than infer it from one state variable.

Two initial SMT fixture attempts failed correctly: duplicate compatibility definitions when combining copied system files with the whole vendor addpath, then a missing State influent dependency. An explicit isolated dependency closure resolved them. Initial two-day tracer runs showed transients; those records are retained with `_horizon2` suffixes. The final tests use the prescribed twenty-day horizon. Do not present those setup/transient results as unexplained production regressions.

The GUI review reused the DynaSand icon, whose embedded artwork still reads `HH_DynaSand_v1`; the palette/manual identity is `HH_ReviewProbe_v1`. The blank one-unit schematic has expected unconnected-port warnings. It was not compiled through the GUI. The launched review GUI exited when its owning client session was released; no pre-existing user GUI session was closed. All installation changes were then reversed by the installer.

## Implications for architecture and implementation order

1. **Repair public simulation execution first:** duration adapter, model-specific symbol mapping, explicit completion/convergence/timeout results, and an actual MCP-to-native contract test. Native-only tests missed the broken public entry points.
2. **Make outcomes truthful:** compliance requires complete valid observations; inspection is not runtime verification; queued changes are not confirmed native changes. Preserve missing values and metric units. The empty-compliance defect is now reproduced on the wire as well as in isolated probes.
3. **Own scheduler state in one runtime module:** route callbacks by job ID and scope pending edits to a project. Tracer and ordinary tools must share this interface. Passing sequential native tracers does not invalidate the isolated cross-job callback defect.
4. **Make recovery transactional:** validate snapshots before touching current files; stage installs and restore overwritten bytes on failure; bind approval/build evidence to the complete executable input set. The successful install/uninstall here only covers a fresh destination, not replacement rollback.
5. **Extract cohesive services behind one registry:** project sessions, runtime jobs, builds/installations, typed analysis, and native/GUI adapters. Keep one MCP server and existing tool names. Move blocking native/compiler/GUI work off the request loop with explicit ownership and resource locks.
6. **Test the release path:** portable unit tests plus separately marked Windows/SUMO/GUI integration tests. Require real stdio calls, native adapter compatibility, negative numerical fixtures, install rollback fault injection, and cancellation/timeout tests. Add optional dependency extras and centralized installation discovery.

Refinement to the earlier transport finding: the SDK correctly marked these uncaught simulation exceptions `isError: true`. The remaining issue concerns handlers that return ordinary text/error dictionaries as successful content, plus stdout warning branches. It would be incorrect to claim every server exception lacks MCP error signaling.

GUI automation should distinguish process launch, splash visibility, main-window readiness, project readiness, and verified action results. Use explicit ownership so releasing a tool client has documented effects on a GUI it launched. Modal targeting failures observed here belong to the desktop automation path; they do not demonstrate a defect in SUMO's save implementation.

## DynaSand brief: final requested guidance

The [implementation handoff](../../../HH_DynaSand_codex_impl_report.md) already records the earlier four-question review and its implemented changes. Keep those changes; the old brief predates them.

1. **Diagnosis:** agree for the bounded steady, conservative system. With wash fully recycled and only filtrate leaving, external effluent TSS must equal external influent TSS. The inferred mixed-feed concentration supports local separation, but a feed inferred from the same balance is not an independent 99.9% closure measurement. The live isolated separator independently closes its measured balance.
2. **Immediate demo:** connect `influent -> inp`, `eff -> Filtrate outlet`, and `wash -> Wash reject outlet`; no return to the local inlet. At an actually measured TSS of 183 mg/L, fWash 0.11 and concentration reduction 0.621, expect filtrate 2670 m3/d at **69.357 mg/L**, reject 330 m3/d at **1102.4752 mg/L**, and **66.269% inlet TSS load diversion**. The brief's 78/1030 values are incorrect. Retain a separate closed-recycle example as an expected pass-through test.
3. **Spec/display:** retain zero-flow-safe conservative equations and the already-added local inlet/filtrate/wash Q and XTSS, concentration reduction, load diversion, balance residual, HLR units, and wash-routing help in `custom_units/HH_DynaSand_v1/unit_spec.json`. No tank state, cap on wash concentration, or pH mapping change is justified by this symptom. For zero inlet load, percentage diagnostics should explicitly be unavailable. Add application-level validation rejecting simultaneous positive alum and ferric dosing under the current additive capture formula; the existing product flag is advisory and does not prevent unphysical combined capture. Do not inject unsupported MIN/MAX syntax into the unit grammar.
4. **Operation:** use the corrected design record, which describes the pilot downstream of chlorine contact and wash solids sent to sludge treatment. Do not reinstate the old unsupported claim that this paper requires recycle ahead of a primary clarifier. The fixed wash fraction is an empirical simplification. Any full-plant recycle example must contain a real solids withdrawal route. Paper fidelity was addressed in the prior implementation record; this live supplement does not claim a new independent literature review.

The full codebase review is broad coverage with targeted reproductions, not proof of all 235 tools or all numerical models. Replacement-install failure recovery, concurrent native execution, GUI parameter/save workflows, and long-horizon active-kinetics convergence remain live-test gaps. Production fixes are proposals for implementation, not changes made during this review.
