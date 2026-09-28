# Plan: Implement the server review and distribute DynaSand

Date: 2026-09-08 · Source prompt: implement review recommendations and install DynaSand under SUMO24 MCP units with directory retry.
Estimated sessions: one sustained implementation · Models used: inherited session model (available agent tooling; no speculative pricing assumptions).

## Objective
Repair the demonstrated correctness and recovery defects, introduce shared runtime and installation responsibilities, and make the supported server installer provision DynaSand for every installation. Preserve existing public tool names.

## Deliverables
- Runtime, verification, transactional installation, packaging and portable regression tests in MCP.
- Bundled DynaSand assets and install/retry flow with GUI category SUMO24 MCP units.
- Live integration evidence and installation documentation.

## Assumptions (made because the prompt did not specify)
- SUMO files directory means either the SUMO installation root or its Process code/user-overlay directory; normalize these to a verified installation root. A model-project directory alone cannot supply the runtime.
- Keep HH_DynaSand_v1's qualified symbol identity for existing model compatibility; rename its GUI category and family rather than its executable class.
- Do not distribute vendor binaries, license files, or private plant models in the Python package.

## Open questions (answers change the plan)
- None blocking. Interactive retry will request the actual directory when discovery fails.

## Phase 1 — Implementation
### Task 1.1 [model: inherited | effort: inherited] [P]
**Context:** public simulation calls fail despite healthy native runtime.
**Inputs:** PY/server.py, tracer_test.py, dynamita_compat.py, docs/reviews/*.md.
**Work:** central runtime callback ownership, duration/symbol/result correctness, truthful compliance and MCP outcomes, project edit scoping, dispatcher execution isolation.
**Output:** runtime modules and tests/test_runtime_review.py.
**Acceptance:** missing data cannot pass, callbacks do not cross jobs, public simulations schedule, timeout/cancel explicit; portable tests pass.
**Depends on:** none.

### Task 1.2 [model: inherited | effort: inherited] [P]
**Context:** approval, recovery and verification currently overstate safety/completion.
**Inputs:** PY/pipeline, spec_review.py, sumo_native.py, academic_bundle.py, sumo_offline.py.
**Work:** staged snapshot restore, full-spec acceptance digest, meaningful stage8 verification, topology validation and missingness preservation.
**Output:** corrected modules and verification regression tests.
**Acceptance:** corrupt tar preserves current bytes, equations invalidate acceptance, empty evidence cannot pass, invalid mapping rejected, missing data remain missing.
**Depends on:** none.

### Task 1.3 [model: inherited | effort: inherited] [P]
**Context:** replacement installation can lose existing assets and unrelated DLLs count as evidence.
**Inputs:** PY/unit_installer.py, unit_emitter.py, smt_runner.py, slc_runner.py.
**Work:** transactional install and manifest journal, locks, compiled-input digests, configurable installation directory.
**Output:** installer and build provenance modules/tests.
**Acceptance:** fault injection restores old bytes and manifest; unrelated or modified build inputs rejected.
**Depends on:** none; use Task 1.4 discovery interface.

### Task 1.4 [model: inherited | effort: inherited] [P]
**Context:** server installation currently installs only MCP and omits DynaSand.
**Inputs:** install.ps1, requirements.txt, custom_units/HH_DynaSand_v1, dynamita/scheduler.py.
**Work:** shared discovery, install CLI with prompt/retry, Python packaging including curated assets, DynaSand GUI grouping and dose validation.
**Output:** PY/sumo_paths.py, installation CLI, package metadata, assets and docs.
**Acceptance:** temp install includes unit under SUMO24 MCP units, wrong directory retries, rerun preserves other MCP entries and unit files, package contains assets but no vendor/private artifacts.
**Depends on:** Task 1.3 for final integration.

## Phase 2 — Verification and delivery
### Task 2.1 [model: inherited | effort: inherited]
**Context:** native-only smoke tests missed public transport failures.
**Inputs:** all Phase 1 outputs and docs/reviews/live_review_2026_09_08.py.
**Work:** run portable suite and existing relevant checks; test actual stdio/native calls and real DynaSand installation, inspect GUI group; document remaining limits.
**Output:** docs/reviews implementation results and updated installation docs.
**Acceptance:** regression tests pass, real MCP simulation completes, DynaSand appears in requested GUI category; no false success claims.
**Depends on:** 1.1–1.4.

## Token-optimization notes
- Independent implementation areas have exclusive owners; root handles packaging/install integration and live tests.
- Reuse recorded diagnosis and fixtures; do not rebuild an unrelated code graph.

## Execution order
1. Tasks 1.1–1.4 concurrently, then root integration and Task 2.1.

## Progress
- Tasks 1.1–1.4 implemented: runtime/result/registry ownership, fail-closed verification, transactional installation and bundled DynaSand setup.
- Task 2.1 verified: 47 regression tests, 55 spec smoke checks, eight pipeline groups, real compile/native runs, source/wheel/PowerShell installation, and visible GUI palette/placement.
- Delivered migration seams while retaining legacy helpers and a worker thread; remaining architectural limits are listed in docs/reviews/2026-09-08-implementation-results.md.
