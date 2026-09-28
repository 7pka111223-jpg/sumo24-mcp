# SUMO24 MCP server: architecture and code review

Date: 2026-09-08. Scope: current working tree, including uncommitted Group HH code. Git HEAD at review: `1ad2c964c2d1cc456efec04edc914dff0ba09de0`.

## Assessment

**Live review completed:** see the [live simulation, installation, and GUI supplement](2026-09-08-live-review.md). A real MCP handshake listed 235 tools. Native simulations and a fresh install/uninstall passed, but both standard MCP simulation tools failed on the nonexistent `ds.sumo.dur` attribute at line 2718. Fix this public execution defect first, together with model-specific output mapping. The supplement also answers the DynaSand brief and distinguishes completed GUI checks from unverified modal workflows.

There is substantial useful engineering here, particularly the custom-unit authoring modules, conservative checks, native-format preservation, and checks of compiler output beyond exit codes. Keep those investments. The main improvement is to make execution state and verification evidence explicit across the server. Several callers currently interpret “queued,” “file exists,” “no checks failed,” or “some values available” as successful completion.

The architecture review found reproducible correctness and recovery defects, not just maintainability concerns. Fix those before undertaking a large file reorganization.

The source inventory contains 57 Python files under `PY`, totaling 31,871 lines. `server.py` contains 13,307 lines; its tool-list function spans 2,639 lines and its dispatcher 3,885. Evaluating the actual tool-list function in an isolated environment with HH enabled produces 235 unique definitions, about 115 KB of JSON definitions. This is not a live MCP handshake measurement. The legacy static checker sees only 211 definitions.

Supporting artifacts:

- [Source inventory and SHA-256 hashes](2026-09-08-source-inventory.json)
- [Reproducible isolated probes](review_probes_2026_09_08.py)
- [Recorded results from 11 probe cases](2026-09-08-probe-results.json)

## Findings, ordered by priority

P1 means a correctness, false-success, or data-loss issue to fix before relying on the affected workflow. P2 means a robustness or maintainability issue to address during the following refactor. These are engineering priorities, not claims of observed production incidents.

### 1. P1 — Missing results can produce a compliance pass

Evidence: [server.py:2757](../../PY/server.py#L2757), and the `check_compliance` branch beginning around line 5833.

`_check_compliance` silently omits absent measurements. The dispatcher then uses `all(...)` over the remaining checks. An empty sequence therefore produces `COMPLIANT`.

The probes reproduce all three cases:

- Empty arguments: `COMPLIANT`, with zero parameters checked.
- An unknown job ID: `COMPLIANT`, with zero parameters checked.
- Only a low TSS value supplied: overall `COMPLIANT`, with BOD and COD absent.

The same code compares `sCOD_mgL` to a limit labeled `COD`. Soluble COD and total COD must remain different metrics. This review does not validate the legal limits themselves.

**Change:** introduce `pass`, `fail`, and `insufficient_data` outcomes; require the configured metric set, valid finite numbers, a known job, and the required completion/convergence evidence. Partial checks must explicitly report their coverage and missing metrics. Store the exact metric, unit, source, and ruleset version. Use total COD for a total-COD criterion; if unavailable, return insufficient data.

**Acceptance:** empty input, unknown jobs, incomplete jobs, missing required metrics, NaN, and soluble-COD-only data cannot return an overall pass.

### 2. P1 — Tracer runs take over the global scheduler callbacks

Evidence: [tracer_test.py:124](../../PY/tracer_test.py#L124), [server.py:2620](../../PY/server.py#L2620).

`run_model()` overwrites `ds.sumo.message_callback` and `datacomm_callback`. It neither filters events by job ID nor restores previous callbacks. Normal simulation tools use the same singleton. Consequently, an existing dynamic simulation can lose its monitoring, and another job's completion or data can satisfy the tracer test.

An isolated fake scheduler returns job 42 but emits data and completion for job 777. The actual tracer function returns `ok: true` for job 42 using job 777's row. Its previous callbacks remain replaced.

**Change:** make one runtime module the sole scheduler owner. Install callbacks once and route events by job ID. Every simulation, tracer, cancellation, and status tool must use that module. Prefer a dedicated worker process for native runtime isolation; merely adding a lock around one tracer function does not cover the other scheduler callers.

**Acceptance:** overlapping normal/tracer jobs never share rows or completion messages; finishing or failing either job leaves the other observable. Scheduling exceptions and cancellation release all resources.

### 3. P1 — Offline/queued operations masquerade as live edits, and project state leaks

Evidence: [dynamita_compat.py:62](../../PY/dynamita_compat.py#L62), [dynamita_compat.py:108](../../PY/dynamita_compat.py#L108), [server.py:12783](../../PY/server.py#L12783).

The compatibility shim's `set` and `executeCommand` methods return true even with no running job. They try the highest numeric job ID when a job exists and swallow send failures. `_dispatch_dtt` then labels the command successful because no exception escaped. Reads return overrides or saved files, which does not verify execution in the live model.

`set_active_project()` changes only the project path. It does not scope/reset the overrides. The probe sets a parameter in project A, switches to B, and reads A's override back. The separate `_pending_sets` queue in the server further splits ownership of pending edits.

**Change:** replace class monkey-patching with explicit live-runtime and saved-project adapters. Operations must identify their project and, where appropriate, job. Return `queued`, `sent`, `confirmed`, or `failed` honestly, with read provenance such as saved-state versus live-result. Store pending changes in a project session and consume them only after successful scheduling. Remove “highest job ID” targeting.

**Acceptance:** opening B cannot read/apply A's pending edits; a queued offline edit cannot be reported as a confirmed live edit. A read-back from an override cache is not execution confirmation.

### 4. P1 — Snapshot restore destroys current work before validating its archive

Evidence: [pipeline/snapshot.py:52](../../PY/pipeline/snapshot.py#L52).

`revert()` deletes every non-snapshot item in the project directory, then opens and extracts the selected tar. A corrupt archive leaves the current project erased. The probe uses a new temporary project, writes an ordinary text file and a broken tar, and confirms that `ReadError` occurs after the text file is deleted.

**Change:** validate the archive and its member paths first, extract into a sibling staging directory, verify the restored project, then commit the replacement while retaining a recoverable backup. Reject absolute/traversing paths and unsafe links explicitly; do not depend on the Python version's tar extraction defaults. Make the project directory ownership check part of the restore operation.

**Acceptance:** corrupt/truncated archives, invalid paths, and injected extraction failures leave the original project intact. A valid restore replaces it completely and can itself be rolled back.

### 5. P1 — Approval and compilation evidence are not tied to the complete artifact

Evidence: [spec_review.py:317](../../PY/spec_review.py#L317), [unit_installer.py:213](../../PY/unit_installer.py#L213).

Approval fingerprints track parameter magnitudes and their provenance, not the whole executable specification. The probe changes the accepted DynaSand particulate equation to a pass-through equation in a copy; `may_emit(..., allow_bulk=True)` still returns true. This contradicts the broader expectation that changing an accepted spec invalidates its approval, although the narrower magnitude-fingerprint mechanism itself works.

Installer preflight calls a slug “compiled” if any `*.dll` exists in its artifact folder. It does not bind that DLL to the exact workbook about to be installed. A later workbook edit can therefore retain old compile evidence.

**Change:** retain per-value provenance, and add a canonical whole-spec approval hash. Generate an immutable build manifest linking spec hash, emitted workbook hashes, model-base hash, compiler identities/options, generated XML hash, DLL hash, and verification results. Installer preflight must match the current inputs to successful evidence. Identity, ports, bindings, and code changes must invalidate approval/build evidence as applicable.

**Acceptance:** modifying a code expression invalidates executable-spec approval. Modifying a workbook after compilation invalidates install readiness. Dropping an unrelated DLL into the artifact directory cannot satisfy preflight.

### 6. P1 — Stage 8 can declare readiness without a schematic comparison

Evidence: [server.py:11495](../../PY/server.py#L11495), [server.py:12724](../../PY/server.py#L12724).

The DLL inspection helper returns `ok: true, mode: exports_only` when no schematic is provided. Stage 8 supplies an empty schematic path if the expected HTML is absent, then promotes that result to “Project is ready for simulation.” The `state_xml` argument is read but unused. With a schematic, zero collected parameter references also yields an empty missing set and success.

The probe supplies an existing placeholder file and stubs symbol extraction to return no exports. With no schematic, the actual stage-8 function still marks verification passed. This tests the promotion logic; it does not exercise a native DLL loader.

**Change:** separate inspection from compatibility verification and runtime validation. Stage 8 must require the expected schematic, meaningful references, validated model/state identity, and the evidence appropriate to the claim. An exports-only result is `not_verified`, never simulation-ready. Symbol presence alone does not verify wiring, convergence, or engineering behavior.

**Acceptance:** missing schematics, zero-reference comparisons, unrelated states, and inspection-only results cannot pass stage 8.

### 7. P1 — Replacing an installed unit is not transactional

Evidence: [unit_installer.py:329](../../PY/unit_installer.py#L329).

The installer copies files directly over existing files. On failure, its rollback removes only newly created files; overwritten files are not restored. Nevertheless it reports that installation “was rolled back.” Writing the install manifest occurs after the guarded copy block and can also fail after installed files have changed.

**Change:** stage the complete installation, validate it, back up every overwritten destination, and journal the operation. Roll back both created and replaced files on failure, including manifest-write failure. Report any incomplete rollback explicitly. Use a scoped install lock to coordinate processes sharing an overlay.

**Acceptance:** fault injection on each file copy and the manifest write restores the exact pre-install bytes and manifest. Test entirely against a temporary overlay.

### 8. P2 — Slow tools block the MCP event loop; timeout outcomes are ambiguous

Evidence: [server.py:9516](../../PY/server.py#L9516), [smt_runner.py:135](../../PY/smt_runner.py#L135), [slc_runner.py:109](../../PY/slc_runner.py#L109), [server.py:5699](../../PY/server.py#L5699).

The async dispatcher has only two `await` sites. Compiler, tracer, GUI, and substantial file/report operations execute synchronously through it. HH compilation uses blocking subprocess waits, and tracing contains sleeps. During these calls, other MCP requests cannot be serviced normally by that event loop.

The normal steady-state tool stops waiting after 120 seconds but summarizes whatever rows exist without reporting an explicit timeout/completion verdict. Scenario comparison does likewise after 300 seconds. Job rows grow in memory without a retention policy. Main has no explicit scheduler lifecycle cleanup.

SMT documentation says shared logs/cache require serialization, but the wrapper has no lock. Multiple server processes or CLI invocations can race. Offloading calls to threads without resource coordination would make this more frequent.

**Change:** use a bounded operation manager with operation IDs, progress, explicit terminal states, cancellation and cleanup. Run blocking work outside the event loop. Serialize native/GUI/Excel work where required, use isolated build directories, and coordinate shared compiler/install resources across processes. Persist or stream large results with bounded in-memory buffers. Keep timed-out/partial data clearly labeled.

**Acceptance:** health/status requests remain responsive during a deliberately slow compile; timed-out work cannot appear complete; two builds cannot consume each other's logs; cancellation stops the owned work and preserves unrelated jobs.

### 9. P2 — Derived values lose units, missingness, and provenance

Evidence: [server.py:2733](../../PY/server.py#L2733), [academic_bundle.py:61](../../PY/academic_bundle.py#L61), [sumo_offline.py:242](../../PY/sumo_offline.py#L242).

`_summarise` labels raw `Sumo__Time` as `time_days` without converting milliseconds. The probe supplies 86,400,000 and receives 86,400,000 days.

Academic export turns absent soluble COD/nitrogen components into zeros. Its empty-input probe returns `SCOD=0, TKN=0, TN=0`. TKN and TN also use restricted component sums, while the field names imply the complete quantities. Offline solids reconstruction accepts almost every `X*` symbol by name, rather than using model-specific calculated-variable definitions.

**Change:** introduce a typed observation/result model carrying value, unit, source, timestamp, derivation and quality status. Preserve missing values; explicitly label estimates and partial nutrient sums. Resolve aggregate metrics through verified model-specific definitions. Configure effluent locations per project rather than assuming `Sumo__Plant__Effluent` for every model.

**Acceptance:** one simulation day reports as one day; missing observations remain missing in CSV/XLSX/report output; estimates cannot silently satisfy exact-metric checks; supported model mappings are checked against known SUMO results.

### 10. P2 — Native baseline matching does not establish topology compatibility

Evidence: [sumo_native.py:290](../../PY/sumo_native.py#L290), [sumo_native.py:618](../../PY/sumo_native.py#L618).

`topology_match_report` establishes a unit mapping rather than validating the connection graph. Explicit mapping targets are not required to exist. The probe maps `u1` to `DOES_NOT_EXIST` and gets `ok: true` despite a baseline containing only `Influent1`.

The composer explicitly preserves baseline topology and documents this, which is good. However, strict mode trusts a report whose success condition is merely that every schematic unit has a mapping. This can overstate what was verified.

**Change:** require valid targets, intentional cardinality, and compatible classes. For strict reuse, compare normalized connections and ports against the baseline; otherwise report only parameter-mapping compatibility and reject requested topology changes. Return a precise changed/unchanged/unsupported summary. Verify companion DLL identity rather than merely copying a provided file.

**Acceptance:** nonexistent targets and changed wiring cannot produce a strict topology-compatibility pass. A parameter-only change to a verified matching baseline remains supported.

### 11. P2 — Transport errors and unavailable capabilities are inconsistent

Evidence: [server.py:53](../../PY/server.py#L53), [server.py:9511](../../PY/server.py#L9511), [server.py:9521](../../PY/server.py#L9521).

Import-warning branches use plain `print`, which writes non-protocol text to stdout. Seven print calls exist in server.py. Tool failures variously return an `ERROR:` string, an `error` dictionary, or `ok: false`, all wrapped in ordinary text content. Neither server.py nor hh_tools.py specifies MCP `isError` or output schemas. Optional-group availability frequently means only “the module imported,” not that its underlying capability is usable.

**Change:** use stderr logging from startup onward and centralize conversion from domain outcomes to MCP results. Return tool errors with `isError: true`; preserve actionable structured details and an operation ID. Define capabilities separately for saved-file reading, native runtime, GUI, compiler, Excel editing and export dependencies. Make tool definitions, schemas, handlers, capability requirements, and documentation derive from one registry.

**Acceptance:** a real stdio handshake/list/call sequence succeeds with optional dependencies absent; stdout contains only protocol messages; representative failed tools are marked as failures in the MCP result, not merely in prose.

Protocol references: [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [tool errors](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).

### 12. P2 — Packaging and tests are not yet a portable release contract

Evidence: [requirements.txt](../../requirements.txt), [pipeline/manifest.py:20](../../PY/pipeline/manifest.py#L20), [smoke_test_offline_extract.py:27](../../PY/smoke_test_offline_extract.py#L27), [smoke_test_bb_cc.py:1](../../PY/smoke_test_bb_cc.py#L1).

The dependency list omits optional feature stacks used by GUI, reports and the YAML pipeline. Some may currently arrive transitively or already be installed, which is not reproducible packaging. Compiler/install defaults repeatedly assume `D:\SUMO24`. Native scheduler construction happens at import time in vendored code; importing server.py for discovery/docs can therefore touch native infrastructure.

Tests are standalone smoke scripts. Some depend on machine-specific research files or vendor workbooks; the BB/CC script explicitly reimplements some helpers instead of exercising the server path. There is no collected test/configuration contract or CI workflow in the inspected tree. Existing smoke passes do not cover the failure modes above.

**Change:** package the server with a `pyproject.toml`, an entry point and explicit optional extras for GUI, reports, compiler authoring and Excel-based editing. Resolve SUMO installation through one configuration module. Separate dev/build dependencies from runtime dependencies and record a tested dependency set. Introduce portable collected tests, then separately marked Windows/SUMO/GUI integration tests. Generate documentation from the tool registry without importing the native runtime.

**Acceptance:** a fresh environment installs the selected extras and discovers the expected capabilities; portable tests run without SUMO or private datasets; live tests skip with explicit reasons when unavailable; a release includes a successful stdio contract test.

## Recommended architecture

Use small, explicit interfaces around the existing implementations. Keep one MCP server; there is no demonstrated need for microservices or a new web framework.

```text
MCP stdio transport + tool registry
              |
       Application modules
   projects / jobs / builds / analysis
              |
       Explicit adapters
 saved SUMO files | native runtime worker | compiler | GUI/Excel
              |
      Artifact and result storage
```

| Module | Owns | Interface direction |
|---|---|---|
| Transport/registry | Input/output schemas, capability checks, MCP errors, logging | Delegates operations; no engineering calculations or global model mutation |
| Projects | Active project identity, model/state hashes, pending edits, transactions | `open_project`, `read_snapshot`, `prepare_changes`, `apply_changes` |
| Jobs | Scheduler ownership, callback routing, lifecycle, cancellation, result provenance | `start_run`, `get_status`, `cancel`, `read_results` with explicit project/job IDs |
| Builds/artifacts | Validation evidence, compilation, build manifests, installation/recovery | `validate`, `build`, `verify`, `install` returning evidence for exact input hashes |
| Analysis/reporting | Metric definitions, units, missingness, estimates, report rendering | Consumes immutable observations/results; cannot mutate a live model |
| Adapters | Saved-file parsing, native DTT, compiler processes, GUI and Excel | Hide backend mechanics; advertise actual capabilities |

A deep module here hides complexity that callers currently have to manage: scheduler callback ownership, command ordering, the identity of a state/DLL pair, or a multi-file rollback. Splitting the giant dispatcher into smaller dictionaries without addressing those responsibilities would help navigation but leave the substantive defects intact.

Group HH is the best starting template for feature-level separation. Preserve its rung implementations and compiler evidence checks. Evolve `hh_tools` into the shared registry style, then migrate simulation, projects, pipeline, analysis and GUI groups incrementally. Keep existing tool names as compatibility adapters during migration. Retain deprecated tools as explicit migration errors if needed, but omit them from default discovery where client compatibility permits.

## Suggested implementation order

1. **Trustworthiness patch:** findings 1–7 and the unit/missingness fixes in finding 9. Convert the isolated probes into tests at the eventual public module interfaces; add installer fault injection and timeout tests.
2. **Runtime ownership:** introduce project sessions and the job/runtime module. Route all normal runs and tracer runs through it before enabling concurrent execution. Add build/install coordination and cancellation.
3. **Transport and registry:** move logging/error translation into one location; migrate one tool family at a time while preserving names and testing schemas and outcomes.
4. **Artifact verification:** finish whole-build provenance, strict baseline matching, staged recovery, and truthful distinctions between inspection, compilation and runtime verification.
5. **Packaging and test automation:** fresh-environment install checks, portable test suite, separately marked live integration gates, generated documentation, and release artifacts.

Do not mix a broad mechanical file move with changes to simulation semantics. First capture behavior, then move one cohesive module, then strengthen its interface with targeted tests.

## Verification performed and limits

- Parsed all 57 `PY` Python files and recorded source hashes and top-level definitions.
- Inspected the server dispatcher, normal job lifecycle, compatibility shim, DTT editing, custom-unit workflow, compiler wrappers, installer, pipeline state/recovery, native composer, offline extraction, report derivation, GUI dependency structure and test organization.
- Existing `smoke_test_spec_review.py`: **55/55 passed**.
- Existing `smoke_test_pipeline.py`: **all eight test groups passed**.
- Existing `smoke_test_bb_cc.py`: **passed**; its helper duplication limits the server-path coverage claim.
- Legacy dispatch coverage checker: **211 registered / 211 dispatched**, no static mismatch.
- Isolated evaluation of the actual list function with HH available: **235 unique tool definitions**. This deliberately avoids native import-time initialization and is not the existing runtime-registration script or a real MCP client connection.
- Review probes reproduced missing-data compliance, incorrect time labeling, missing-to-zero report derivation, invalid baseline mapping, cross-project override leakage, approval surviving equation changes, destructive corrupt-archive restore, stage-8 inspection promotion, and foreign-job tracer success/callback takeover.
- Probes use function AST extraction or mocked external adapters where needed. They exercise actual function bodies but do not prove native backend behavior or MCP wire behavior. Tests involving deletion use new temporary directories only.
- At the initial static-review stage, no live operations had been performed. Subsequent native simulations, SMT/SlCompiler builds, MCP calls, real installation/uninstallation, and GUI placement are recorded in the [live supplement](2026-09-08-live-review.md). Installer replacement-failure behavior and event-loop blocking remain source-traced rather than live fault-injection measurements; real project restore was not exercised.
- This is a broad architecture review with targeted correctness checks, not a line-by-line proof of every numerical formula, every GUI selector, or regulatory validity. Existing uncommitted implementation files were left unchanged; only review artifacts were added.
