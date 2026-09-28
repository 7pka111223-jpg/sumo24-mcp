# Review implementation and DynaSand distribution

Date: 2026-09-08. Implements the correctness/recovery fixes from the [architecture review](2026-09-08-server-architecture-review.md) and [live supplement](2026-09-08-live-review.md), plus the requested bundled DynaSand installation.

## Delivered

The documented [PowerShell installer](../../install.ps1) installs the Python server/dependencies and deploys DynaSand into **SUMO24 MCP units → DynaSand**. The [wheel](../../dist/sumo24_mcp-0.2.0-py3-none-any.whl) includes the source specification, unit workbook, group workbook, icon and content-bound release manifest. No SUMO executables, native model DLLs, licenses or private plant projects are included.

Both installation entry points use [install_server.py](../../PY/install_server.py). Setup resolves explicit paths/environment/registry, checks native loading and a real MCP handshake, installs the unit transactionally, preserves other MCP configuration entries, and records ownership/backups. On failure, interactive setup asks for the SUMO files directory and retries. Noninteractive setup returns an error. Python/dependency bootstrap failures report their own prerequisite problem.

This machine's unit was migrated from `90 HH Custom/HH Custom Units` to `SUMO24 MCP units/DynaSand`. Known old files were backed up; the internal `HH_DynaSand_v1` class identity was preserved. The category and placed unit were verified in SUMO's Configuration tab: [screenshot](implementation-2026-09-08/dynasand-installed-palette.png). The workspace `.mcp.json` registration now contains the resolved SUMO directory and existing project paths.

## Review fixes

| Area | Implementation |
|---|---|
| Public simulation | Removed nonexistent `ds.sumo.dur`; checked positive finite durations; resolved model outlet/inlet symbols; corrected milliseconds-to-days conversion and total COD/BOD metric identity |
| Results/compliance | Empty, unknown, partial, nonfinite and incomplete-job data cannot pass compliance; observation metadata identifies symbols, units and source |
| Native jobs | `sumo_runtime.py` owns callbacks, routes by job ID, handles early callbacks, caps retained rows/jobs, and handles owned-job cancellation/timeouts |
| Saved edits | Project-scoped queues and overrides; no guessed highest job ID; queued edits and saved reads carry truthful provenance; saved-only operations no longer initialize native code |
| Transport | Worker execution keeps the stdio loop responsive; errors become MCP `isError`; warnings use stderr; registry preserves 235 tool names and provides a migration interface |
| Recovery | Snapshot archive/member/manifest validation before replacement; previous state retained; rollback on commit failure |
| Approval/build evidence | Whole-spec approval digest; workbook, macro model-base, icon, XML and DLL identities; explicit addpath/compiler dependency hashes; source-only release attestation for distribution |
| Installation | File/manifest staging, old-byte restoration, journals, cross-process locks, cross-drive atomic destination commits and config rollback; edited assets are not silently replaced |
| Verification | Stage 8 requires positive schematic-reference evidence and matching native-validation hashes; invalid mapping targets, wiring mismatches and DLL identity conflicts rejected |
| Analysis | Missing values remain missing; partial nutrient sums and COD estimates are labeled; unverified X-variable reconstructions cannot masquerade as exact TSS/VSS |
| Configuration/packaging | Shared SUMO directory resolver used by runtime setup and authoring modules; package metadata, optional extras, installed CLI entry points and fresh-environment validation |
| DynaSand | Existing conservative/zero-flow equations preserved; local diagnostics and wash-routing help retained; MCP preflight rejects simultaneous positive alum/ferric doses; GUI family/category updated |

## Verification

- **47 portable regression tests passed** with `python -m unittest discover -s tests -v`.
- Existing spec-review smoke suite: **55/55 passed**. Existing pipeline smoke suite: **all eight groups passed**.
- DynaSand was emitted, built by actual SMT24/SlCompiler, and run at positive/zero flow. Measured flow/load checks passed. Build and native records: [fixture evidence](implementation-2026-09-08/dynasand_build/).
- Public dynamic simulation on the isolated plant completed with `time_days = 0.01`, TSS approximately 3.8570 mg/L and total COD approximately 32.7276 mg/L. This is a runtime smoke test, not model calibration or compliance certification.
- Public dynamic **and steady-state** tools completed on the DynaSand fixture. These were also executed using the **wheel-installed server in a fresh venv**, with MCP 1.30.0: [dynamic status](implementation-2026-09-08/get_job_status-separator.json), [steady result](implementation-2026-09-08/run_steady_state-separator.json). The original environment used MCP 1.27.1.
- The restrictive Windows-client test returns an explanatory tool error and keeps the server alive: [response](implementation-2026-09-08/run_dynamic_simulation-blocked-client.json).
- Real source installer, installed-wheel CLI and PowerShell wrapper succeeded. Reinstallation preserved the same unit files and did not duplicate the palette entry. Supplying `D:\SUMO24\Process code` normalized to the correct root.
- A fresh venv installed the wheel and GUI dependencies; `pip check` found no conflicts; installed stdio discovery returned 235 tools. [Exact tested dependency set](implementation-2026-09-08/tested-dependencies.txt).
- [Distribution integrity record](implementation-2026-09-08/distribution-verification.json) compares installed assets with the wheel and source bundle, checks the absence of vendor/private binary artifacts, and records the wheel hash.
- PowerShell installer syntax parsed successfully. GUI launch/window/screenshot tools worked through the server's worker thread. The temporary blank GUI schematic was discarded when the test client was released; the DynaSand installation remains available.
- Added a portable Windows/Linux CI matrix for Python 3.11/3.14, package building and installed stdio discovery. This workflow has not been run on a remote CI host during this session; native licensed SUMO tests remain explicitly local.

## Findings discovered during implementation

The first live replacement failed because the staged manifest was on D: and the owning source directory on F:. The transaction correctly rolled back. Commit/restore now stages destination replacement on the destination volume when Windows reports cross-device move error 17. A dedicated regression and the successful live retry cover this.

SUMO24 native workers request Windows process breakaway. The Python MCP SDK's default stdio Job Object prohibits it, causing native `CreateProcessA: 5` and potentially terminating the server. Native scheduling now detects that client policy before launch and returns an actionable error. The server does not change client policy. Successful live runs used an explicit compatible test-client policy. Users need a client/launcher that permits SUMO worker processes; changing the SUMO installation directory cannot resolve this restriction.

The full active-kinetics plant did not finish the short native steady-state diagnostic within 15 seconds, and the earlier public test reached its wait limit. An unrelated legacy local-variable shadowing defect on the timeout path was corrected (`ds` ownership). No full-plant steady convergence claim is made. A small DynaSand steady fixture did finish, proving the public command and completion path.

## Architectural limits retained explicitly

This implementation introduces shared ownership and migration interfaces while preserving existing tool names. It does not mechanically split every legacy helper out of the large dispatcher. Native work is currently owned by a worker thread rather than a separate native-runtime service; compiler/GUI cancellation remains bounded by adapter timeouts. Compiler calls are serialized across processes sharing the machine's temp-directory lock. A hard process crash can leave a recovery journal that requires inspection rather than automatic replay.

Opaque native baseline topology still cannot be decoded into a complete graph by the existing reader. Strict reuse therefore refuses to claim compatibility; explicitly requested parameter-only reuse preserves baseline topology without asserting graph verification. Old specifications without a whole-spec approval hash require explicit reacceptance. The bundled DynaSand specification was accepted under the user's implementation instruction with the reviewed coefficients unchanged.

GUI-only execution does not run Python's coagulant preflight; the workbook's conflict diagnostic and single-coagulant help remain relevant there. Every one of the 235 tools has not been exercised against every SUMO model. These limits are documented rather than hidden behind successful smoke tests.
