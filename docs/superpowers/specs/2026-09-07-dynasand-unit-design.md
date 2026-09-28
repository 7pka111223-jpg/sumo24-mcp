# HH_DynaSand_v1 — Continuous Up-Flow Sand Filter (Type A custom unit)

**Date:** 2026-09-07
**Status:** IMPLEMENTED — compiled, tracer-verified, installed to the overlay (see §12)
**Authoring path:** Group HH (SumoSlang unit authoring ladder), Type A
**Base unit:** vendor `Sand filter with fixed solids removal efficiency.xlsx`
(`D:\SUMO24\Process code\Process units\30 Separators\Sand filter`)

---

## 1. Purpose

A SUMO24 process unit representing a DynaSand continuous up-flow sand filter for
**tertiary polishing of secondary effluent**, calibrated against the Qaha WWTP pilot
study (El-Gendy et al. 2026, Sustainability 18(12), 6058, doi:10.3390/su18126058).
It supports both plain operation and coagulant-assisted operation (alum or ferric
chloride) via a built-in dose response. Intended use: Qaha plant schematics and
reuse-compliance simulation (ECP 501/2015 Category A targets).

Out of scope (per user decision): dynamic bed inventory / head loss / breakthrough
modelling (would require Type B + model-base fork); coagulant as an upstream
ChemDosing unit (user chose built-in response instead); DynaSand WWR / eVo / Carbon
variants.

## 2. Routing decision — Type A

**No new state variables.** The unit expresses everything in the biokinetic model's
generic state triplets (`sSV` soluble / `cSV` colloidal / `xSV` particulate) and
CVAR passthrough, exactly like the shipped sand filter. No model-base fork, no new
`Model` rows, no Gujer-matrix edits. Consequences: rung 2.5 (additive-only diff)
is not exercised; rungs 1, 1.5, 2, 3, 4, 5 apply to the process unit only.

Routing confirmed by the user in the design conversation (2026-09-07).

## 3. Ports (3 — the shipped 4-port backwash pattern is deliberately dropped)

| Symbol | Name              | Direction | Phase | Notes                                   |
|--------|-------------------|-----------|-------|-----------------------------------------|
| `inp`  | Influent          | in        | L     | bottom inlet distributor                |
| `eff`  | Filtrate          | out       | L     | top weir outlet                         |
| `wash` | Wash water reject | out       | L     | continuous sand-washer reject side-stream |

Rationale: in a DynaSand the wash water is a small recirculated side-stream of the
*filtrate*, not an externally supplied backwash. The shipped unit's `backwashinp`
port models batch backwash physics and is removed.

## 4. Hydraulics

```
wash..Q = fWash * inp..Q
eff..Q  = (1 - fWash) * inp..Q
```

`fWash` is the airlift-driven wash fraction, approximately constant across loading
(paper §3.1: 10.8 % at high flow 7.5 m³/h, 11.0 % at medium 5.7 m³/h, 12.3 % at low
4.6 m³/h — the paper attributes the slight inverse relation to the wash flow being
governed by the airlift, not hydraulic loading). The unit stays **volumeless**
(`Volumeless = True`, shipped-unit pattern): bed pore HRT is ~5 min at pilot flows
(bed volume ≈ 1.09 m³, voids ≈ 0.4), negligible next to plant-scale dynamics, and a
storage-free separator needs no new state variables.

## 5. Capture model (no coagulant) — v1 final

Per state-variable class, mirroring the shipped separator's mechanism:

```
eff..L.sSV = inp..L.sSV                       (generic soluble triplet: pass-through)
eff..L.cSV = inp..L.cSV * (1 - fCol,eff)      (colloids — turbidity proxy)
eff..L.xSV = inp..L.xSV * (1 - fXTSS,eff)     (particulates — TSS)
wash..F.L.sSV = inp..F.L.sSV - eff..F.L.sSV   (per state variable: closure)
wash..F.L.cSV = inp..F.L.cSV - eff..F.L.cSV
wash..F.L.xSV = inp..F.L.xSV - eff..F.L.xSV
wash..L.sSV = wash..F.L.sSV / wash..Q         (wash concentrations from closure)
wash..L.cSV = wash..F.L.cSV / wash..Q
wash..L.xSV = wash..F.L.xSV / wash..Q
```

- The **wash stream is defined by mass closure**, so elemental continuity (COD, N, P,
  TSS) closes *by construction*; rung 2 verifies rather than assumes.
- Nutrient behaviour *emerges* from the particulate/colloidal split: particle-bound
  N/P leaves with `wash`. No dedicated TN/TP processes — consistent with the paper
  (Table 2: TN removal 7.2 ± 6.7 %, TP 32.9 ± 32.3 %, both predominantly dissolved
  and "unable to be effectively removed").
- **v1 limitation (measured):** per-state soluble overrides (SB,mono / SB,poly
  enmeshment of the paper's Phase III) are NOT implementable in a Type A unit: the
  SMT refuses any equation whose LHS duplicates a member of the generic `sSV`
  pass-through ("Two equations with the same lefthandside in the same block" —
  row-independent; section breaks do NOT create separate SMT blocks). The
  `fSB,rem` / `fMaxSB,alum` / `fMaxSB,fe` parameters were dropped in v1; BOD₅
  removal is represented through particulate/colloidal capture only, and ferric's
  BOD₅ edge (87.5 %) is not representable until v2 (Type B or a model-base-assisted
  variant).
- **v1 limitation:** CVAR passthrough (eff..CVAR / wash..CVAR) dropped — it pulls
  the model's full calculated-variable chain (incl. ORP-switch chemistry such as
  `SORPswitch`) onto the filtrate port, requiring chemistry-capable upstream units
  that a minimal plant cannot provide.
- **Measured SumoSlang rule:** cross-port references to a SPECIFIC component take
  the form `inp..SB,mono` — no phase qualifier. `inp..L.SB,mono` expands to a
  nonexistent `L_SB_mono`; the `L.` prefix is only valid before group tokens
  (`L.SV`, `L.sSV`, `L.cSV`, `L.xSV`).
- **Measured unit convention:** port flow `Q` is m³/d in SUMO (not m³/h); code-line
  unit labels therefore use m³/d for flows and m/d for HLR.

## 6. Built-in coagulant response — v1 final

Two numeric dose parameters instead of a string attribute (schema-valid for the
workbook emitter): `Dose,alum` (mg Al/L) and `Dose,fe` (mg Fe/L), both default 0 =
no coagulant. For each capture class (particulate, colloidal):

```
f_rem(D) = f_base + (f_max - f_base) * D / (K_D + D)
```

`D = 0` reproduces the no-coagulant calibration; the curve saturates at `f_max`.
2 classes × 2 coagulants in v1 (the soluble-biodegradable class dropped, §5).

**Continuity note:** the dose response only *re-partitions* influent mass between
filtrate and wash (floc-forming is represented as shifted capture fractions, not new
mass). COD/N/P elemental continuity therefore holds at any dose. The physical mass
of Al(OH)₃/Fe(OH)₃ flocs is not added — a declared simplification; if metal-solid
mass matters for a study, use an upstream ChemDosing unit instead.

## 7. Parameters and provenance

All magnitudes enter the spec at the REQUIRED sentinel and are filled with the
values below + provenance, then confirmed by the user at acceptance.

### 7.1 Hydraulics / geometry (cited)

| Symbol       | Name                       | Unit | Value | Provenance |
|--------------|----------------------------|------|-------|------------|
| `fWash`      | Wash-water fraction of Q_in| –    | 0.110 | El-Gendy 2026 §3.1 (10.8–12.3 % across flow categories); default = category mean |
| `Diameter`   | Filter diameter            | m    | 0.960 | El-Gendy 2026 §2.1 |
| `BedDepth`   | Sand bed depth             | m    | 1.500 | El-Gendy 2026 §2.1 |
| `BedHeightEff`| Effective bed height     | m    | 3.125 | El-Gendy 2026 §2.1 |
| `UnitHeight` | Total unit height          | m    | 4.175 | El-Gendy 2026 §2.1 |
| `SandVolume` | Sand inventory             | m³   | 1.7   | El-Gendy 2026 §2.1 |
| `SandDmin`   | Media size (min)           | mm   | 1.2   | El-Gendy 2026 §2.1 |
| `SandDmax`   | Media size (max)           | mm   | 2.0   | El-Gendy 2026 §2.1 |
| `AirLiftQ`   | Air-lift air flow          | m³/h | 1.9   | El-Gendy 2026 §2.1 (at 4 bar) |

Geometry is informational (documentation/GUI group) plus one calculated variable
`HLR = inp..Q / (π·Diameter²/4)` (surface loading rate; pilot range ≈ 5.4–11.7 m/h
across 3.9–8.5 m³/h) — a diagnostic, not a state.

### 7.2 No-coagulant capture fractions (cited maxima, calibration-adjustable) — v1 final

| Symbol         | Class                     | Value (base) | Provenance |
|----------------|---------------------------|--------------|------------|
| `fXTSS,rem`    | particulate (TSS)         | 0.621        | El-Gendy 2026 abstract: baseline max TSS removal 62.1 % (Figure 6 per-category detail is image-only; value set to the reported maximum, lower values by scenario calibration) |
| `fColloid,rem` | colloidal (turbidity)     | 0.670        | El-Gendy 2026 abstract: baseline max turbidity removal 67.0 % |

(The `fSB,rem` soluble-biodegradable class was dropped in v1 — §5 limitation.)

### 7.3 Dose-response parameters — v1 final

| Symbol             | Value | Provenance |
|--------------------|-------|------------|
| `fMaxTSS,alum`     | 0.717 | abstract: alum max TSS removal 71.7 % |
| `fMaxTurb,alum`    | 0.945 | abstract: alum max turbidity removal 94.5 % |
| `fMaxTSS,fe`       | 0.838 | abstract: ferric max TSS removal 83.8 % |
| `fMaxTurb,fe`      | 0.814 | abstract: ferric max turbidity removal 81.4 % |
| `KD,alum`          | 7.0   | **fitted (declared engineering assumption):** half-improvement dose ≈ ½ of the 8–14 mg Al/L optimum range (§3.3); to be refined against Figure 8 per-dose data if extracted |
| `KD,fe`            | 7.5   | **fitted (declared engineering assumption):** half-improvement dose ≈ ½ of the 14–16 mg Fe/L optimum range |
| `Dose,alum`        | 0.0   | design decision: coagulation inactive by default; pilot range 8–14 mg Al/L |
| `Dose,fe`          | 0.0   | design decision: coagulation inactive by default; pilot range 14–16 mg Fe/L |

(The `fMaxSB,alum` / `fMaxSB,fe` BOD₅ parameters were dropped in v1 — §5 limitation.)
Final v1 parameter count: **19** (9 geometry/hydraulics + 2 base fractions + 4 alum/ferric
maxima + 2 K_D + 2 doses).

The `K_D` pair are the only non-cited magnitudes. They enter the spec as
`provenance = user-fitted`, `source = "engineering assumption: ½ optimum dose; El-Gendy 2026 §3.3"`,
so the review gate lists them as unverified-but-declared — honest, and the user
confirms them explicitly at acceptance.

Validated pilot dose range for the response (§2.2.3, §3.3): alum 8, 12, 14 mg Al/L;
ferric 14, 16 mg Fe/L; 14 mg/L either coagulant = practical sweet spot for ECP
Category A compliance. Doses outside this range are extrapolation.

## 8. Structure of the emitted workbook

Same canonical 6-sheet shape as the shipped unit (Help, Unit, Parameters, Code,
Display, Popup) via `hh_emit_unit_workbook`. `Unit` sheet: 3 ports (§3),
`MODEL` binding = Biokinetic model (valid: any, like the shipped separator),
attributes `Volumeless=True`, `CoagulantType`, `Dose_mgL`.

**v1 mode decision:** single mode (fixed removal fractions). The shipped unit's
`PercentSolidsRemoval` attribute and its "fixed effluent solids" twin are **not**
carried into v1; if that mode is ever needed it will be authored separately as
`HH_DynaSand_v2`.

Icon: `hh_emit_icon` placeholder EMF; opt-in template copy of the shipped
`Sand filter.emf` if the user wants visual parity on the canvas.

## 9. Implementation plan (the HH ladder, in order)

1. `hh_compose_unit_spec` — structured back door with every value + provenance (§7);
   no value without provenance.
2. `hh_lint_unit_spec` (rung 1) → `hh_check_dimensions` (rung 1.5) →
   `hh_check_continuity` (rung 2, against `Sumo2C.xlsm`).
3. `hh_review_unit_spec` → user reads the rendered spec → `hh_accept_unit_spec`
   with per-value confirmation (`accepted_by` = user).
4. `hh_emit_unit_workbook` → slug `custom_units/HH_DynaSand_v1/`.
5. **Prerequisite fix:** `slc_runner.run_slcompiler` must prepend
   `D:\SUMO24\build\mingw\bin` to the subprocess PATH (found during 2026-09-07 tool
   testing: MinGW g++ 5.2 exits 1 with empty output when its own bin dir is not on
   PATH; machine/user PATH do not contain it).
6. `hh_emit_test_plant` (reactive plant on the aeration-bearing CSTR class) →
   `hh_compile_smt` (rung 3) → `hh_compile_slcompiler` (rung 4, PE32+ verified) →
   `hh_run_tracer_test` (rung 5, needs licence; conservative tracer 5a +
   degenerate equivalence 5b).
7. `hh_install_process_unit` preflight → dry-run → real install (explicit opt-in;
   overlay `D:\SUMO24\Dir\My Process Code` only; GUI re-scans at startup only).
8. Post-install validation: build a Qaha schematic variant with the tertiary filter
   after the chlorine contact tank; steady-state run; compare filtrate TSS/turbidity
   proxy/BOD against paper Table 1 effluent ranges and ECP Category A limits
   (dataset tooling `check_dataset_against_law48`, not the unit).

## 10. Validation targets (from the paper, for step 8)

- Wash fraction at 3.9–8.5 m³/h: 0.108–0.123 (§3.1).
- Baseline filtrate TSS < 15 mg/L across influent categories (Table 1 influent
  ranges: TSS 6.4–37.0, BOD₅ 6.2–40.8, turbidity 2.1–30.9 NTU).
- With alum at 14 mg Al/L: turbidity ≤ 5 NTU, TSS ≤ 15 mg/L (ECP Cat A);
  BOD₅ ≤ 15 mg/L only when influent BOD₅ < 25 mg/L.
- With ferric at 14 mg Fe/L: BOD₅ ≤ 15 mg/L even at influent BOD₅ up to 48.4 mg/L.

## 11. References

1. El-Gendy, A.S.; Meshref, M.N.A.; Zein ElDin, M.; El-Zayat, M.; El Sayed, M.M.A.;
   Hosny, O.; Sabry, T. Continuous Up-Flow Sand Filtration as an Effective Tertiary
   Treatment for Wastewater Reuse. *Sustainability* **2026**, 18(12), 6058.
   https://doi.org/10.3390/su18126058 (open access; tables cited as §2.1, §3.1,
   §3.2, §3.3, Tables 1–2).
2. Nordic Water Products — DynaSand product literature
   (https://www.nordicwater.com/products/filtration/dynasand) — working principle;
   no catalog design ranges used as parameters.
3. Vendor unit workbook: `Sand filter with fixed solids removal efficiency.xlsx`,
   SUMO24 `Process code\Process units\30 Separators\Sand filter` — structural
   template (ports, sSV/cSV/xSV mechanism, volumeless separator pattern).

## 12. Implementation record (2026-09-07)

**Executed ladder** (all gates passed, in order): compose (19 params, 22 code lines,
0 owed) → rung 1 lint clean → rung 1.5 dimensions ok → rung 2 continuity ok →
acceptance recorded (user chat approval, bulk, per-value hash stamps) → workbook +
placeholder icon emitted → test plant emitted (non-reactive, Sumo2C,
`Sumo__Plant__DynaSand__*`) → rung 3 SMT clean (0 errors, 1.23 MB XML) → rung 4
link success (671,744-byte PE32+ x86-64 DLL) → rung 5a splitter conservation (72
components, worst residual 1.4e-9 on a 3.5e6-scale flux ≈ machine precision) →
install preflight clean (6/6, 0 warnings) → dry-run (3 files, nothing written) →
real install to `D:\SUMO24\Dir\My Process Code\Process Units\My Process Unit
Category\HH_DynaSand_v1` (manifest: `custom_units/HH_DynaSand_v1/install_manifest.json`).

**Rung 5a result (splitter form):** Q_in 24000 = Q_eff 21360 + Q_wash 2640 (exact);
fWash realised 0.110 = parameter; capture split exact (XB: 33.73 % to filtrate =
0.89 × (1 − 0.621) ✓). Rung 5b (degenerate equivalence) not applicable — no reactive
twin exists for a Type A splitter.

**Measured lessons baked into the tooling/docs:**

1. `slc_runner.run_slcompiler` now prepends `D:\SUMO24\build\mingw\bin` to the
   subprocess env (MinGW g++ 5.2 needs its own bin dir on PATH; machine/user PATH
   lack it). NOTE: the running MCP server still holds the pre-fix module in memory —
   restart the MCP server before driving rung 4 through MCP tools.
2. SMT bootstrap requires `<cwd>/System files` AND `<cwd>/Model base` to exist WITH
   content; empty stub dirs shadow the install root and fail with
   "Cannot find file. File: systemcode". The proven compile layout (mirrored at
   `C:\Users\DELL\AppData\Local\Temp\opencode\ds_build\Process code`) is: vendor
   subdirs junctioned (Model base, System files, Process units subdirs, …) + real
   Plant classes / Plant instances / Process units\Custom\<unit>.
3. F:\ is non-NTFS — NTFS junctions cannot be created there; compile staging must
   live on an NTFS volume (C:).
4. Writing through a staging junction wrote into the vendor tree once
   (`D:\SUMO24\Process code\Process units\Custom`); removed immediately, vendor
   tree verified clean. Junction-through-writes are a footgun — create real dirs
   for anything you copy into.
5. The HH test-plant emitter should scaffold the System files/Model base content
   (or fail with a clear message) — filed as the follow-up gap this implementation
   surfaced.
6. Acceptance is cleared by ANY spec edit (by design): the compose → accept → emit
   loop must be re-run per iteration; the recorded acceptance stamps are hash-bound
   to the final values.
7. **Palette layout (measured against the live GUI, 17:26 log):** the SUMO scanner
   treats every `<family>\group info.xlsx` as a multi-PU group whose members are the
   SIBLING workbooks in the same folder (vendor pattern, e.g.
   `30 Separators\Sand filter\Sand filter group info.xlsx` + unit xlsx beside it).
   A Group Info placed at the CATEGORY level with the workbook nested deeper is
   parsed (cache .xlc created) but yields `[SETUP] Empty multi-pu interface ...
   There is no model behind the title` and the group is silently dropped from the
   palette. Correct overlay layout actually installed:
   `Dir\My Process Code\Process Units\90 HH Custom\HH Custom Units\{HH Custom Units
   Group Info.xlsx, HH_DynaSand_v1.xlsx, HH_DynaSand_v1.emf}` (category `90 HH
   Custom` sorts last; header renders as "HH Custom"). **HH tooling follow-up:**
   `unit_installer`/preflight currently emit and expect the wrong (category-level)
   layout — must be fixed before the next unit install.
8. **Workbook cell types (measured, second GUI restart):** after the layout fix the
   group resolved but `UnitPalette.LoadUnit` threw `System.FormatException:
   Input string was not in a correct format` (int.Parse) on the unit workbook →
   "Initialization Error [HH_DynaSand_v1]" → group dropped again. Root cause: the
   workbook emitter (xlsxwriter) writes port rows WITHOUT the vendor `Size` (H)
   numeric cell (vendor: 24) and writes every numeric/bool cell as a TEXT string.
   Fix applied surgically at the zip/XML level (no openpyxl): ports got
   `G=Image 'L'` + `H=Size 24` as native cells, 5 attribute defaults became real
   bools, 60 parameter cells became native numerics — SMT rung 3 re-verified clean
   on the patched file. Two tooling rules learned: (a) the emitter must emit
   vendor-typed cells natively; (b) NEVER rewrite an emitted workbook with
   openpyxl — SMT's reader then fails with a bare "File error"; only zip-surgical
   edits of the xlsxwriter output are safe.
9. **Tooling fixed (same day, post-install):** both measured defects are now fixed at the
   source and regression-gated —
   - `unit_emitter`: cells are vendor-TYPED (native numbers/bools; port rows emit
     `Image = phase`, `Size = 24` natively) via `_native()`; new `verify_gui_typing()`
     re-reads the emitted file and REFUSES emission on any GUI-unsafe cell (port Size not
     a native int ≥ 1, text-typed numerals in parameter Default/Low/High/Decimals);
     `emit_unit(..., group_info={name, default_unit, sorting_priority})` now also emits
     the Group Info beside the workbook, so one call produces a palette-ready pair;
   - `unit_installer`: installs map ANY source layout onto
     `Process Units\<category>\<family>\` (family = Group Info stem minus
     " Group Info", sibling of the workbooks); preflight accepts sibling, legacy
     category-level, and slug-root emissions; the planned set is explicit
     (workbook + icon + group info) instead of "everything in the folder";
     `DEFAULT_CATEGORY = "90 HH Custom"` (measured palette behaviour: numeric prefix
     orders the category, header renders without it);
   - `hh_emit_unit_workbook` MCP tool gained `group_name` / `default_unit` /
     `sorting_priority` args;
   - gates re-run: Gate C 36/36 (new E2 typing group), Gate G 76/76 (new G6b
     sibling-layout check; G13 now compares the real overlay before/after instead of
     assuming it empty);
   - HH_DynaSand_v1 was re-emitted and re-installed entirely through the fixed tooling
     (verify_gui_typing clean on the installed file; SMT rung 3 re-verified clean on it,
     identical 1,226,429-byte XML). NOTE: the running MCP server must be restarted to
     load the fixed modules; until then, drive emission/install via `python` imports.
10. **First real-plant failure (22:33 log, user GUI):** a schematic
    `Influent → HH_DynaSand_v1 → Effluent` (wash recycled to the front) failed with
    `[Effluent1/Code row 29]: Variable Sumo__Plant__Pipe3__TK not found` — the vendor
    Effluent unit expects the upstream unit to hand it `TK` via the model's calculated
    variables, which the v1 unit had dropped (§5 limitation). **Fix:** CVAR passthrough
    restored — the spec now carries (a) `eff..CVAR`/`wash..CVAR` scoped
    `Type(Stoichiometric)` AND `Type(Energy)` recomputed at the port
    (`<port>..MODEL.CVAR.Expression`), (b) `F.CVAR` mass flows, and (c) a **pH mapping**
    section mapping Equilibrium CVARs/species/charge balance FROM THE INPUT PORT
    (`inp..CVAR`, vendor State-influent pattern) — recomputing equilibrium at the port is
    what pulled `SORPswitch` into the chain in the original v1 attempt; mapping from the
    input avoids it. Measured rule: **exactly ONE `<port>..CVAR` row per Type scope** —
    two rows sharing a scope expand twice ("Two equations with the same lefthandside",
    first duplicate = `XBIO`). Vendor-parity proof: the shipped separator compiled clean
    in the same test plant once a backwash loop was wired, so the model combo was never
    the problem. Final state: rung 3 clean (1,264,691-byte XML), rung 4 relinked
    (PE32+ x86-64), reinstalled through the fixed tooling. The `eff..F.L.SV,molar` lines
    also gained vendor parity (`mol P.d-1`, decimals 0, `Only(SPO4)`).
11. **spec_review.accept wipe bug (found via the sandbox loop):** calling
    `accept(confirm_all=True)` on a spec with ZERO outstanding magnitudes stamped an
    EMPTY `confirmed` set, REPLACING a perfectly good acceptance record and staling every
    magnitude. Fixed: stamps now UNION with the previous record, previous stamps kept
    VERBATIM (a stamp reflects its acceptance-time value; re-stamping from current values
    would launder edits). Bulk re-accept over a genuinely edited value still downgrades
    the record to `confirmation: bulk` (visible, allow_bulk-gated) — Gate F2 extended,
    spec_review smoke 55/55.
12. **First simulation — "TSS did not change" (user report, 23:0x):** in the user's
    minimal schematic (Influent → junction → DynaSand → Effluent, wash loop back to the
    junction) the steady state showed Influent TSS 183 = Effluent TSS 183, wash Q 371
    (11 %), wash TSS 2906, HLR 4657 m/d. **Diagnosis (confirmed independently by the
    Codex review session):** the unit IS working — its internal balance closes
    (feed 3371 × ≈483 mixed-inlet TSS = eff 3000×183 + wash 371×2906, 99.9 % with the
    inlet inferred, not independently measured) — but the wash returning to the unit's
    own inlet makes it INTERNAL to the Influent→Effluent boundary, so steady-state
    conservation forces Effluent TSS = Influent TSS. The captured solids recirculate
    (internal loop enriches to ≈483 g/m³ feed, 2906 g/m³ in the wash) until the filtrate
    escape equals the fresh load. **Demo fix:** route wash to a second outlet boundary
    ("Wash water reject"), giving filtrate 2670 m³/d @ 69.4 mg/L (62.1 % concentration
    reduction) and reject 330 m³/d @ 1102 mg/L — load diversion to wash 66.3 %
    (= 1 − (1−fWash)(1−fXTSS,eff), because wash also carries water). Full-plant use:
    route wash to whichever installed handling path provides net solids wasting across
    the plant boundary. **Corrections to earlier wording (Codex review):** the paper
    does NOT establish "wash returned upstream of the primary clarifier" as a fact (it
    describes an oxidation-ditch plant with the pilot downstream of chlorine contact and
    coagulant-associated wash solids going to sludge treatment) — route per the actual
    installed system; "recirculate forever" → the loop enriches until filtrate escape
    balances the fresh load; do not claim measured closure without an independently
    measured inlet TSS.
13. **Codex-review hardening implemented (23:5x):** (a) parameter limits — fWash
    (0.001, 0.999), Diameter ≥ 0.05 m, K_D ≥ 0.001 mg/L (no division-by-zero endpoints);
    (b) zero-flow-safe wash concentration forms
    (`wash..L.sSV = inp..L.sSV`, `wash..L.cSV = inp..L.cSV·(1+(1−fWash)·fCol,eff/fWash)`,
    same for xSV) — note the SMT also auto-guards divisions with `Sumo__SmallNumber`;
    (c) label renames to "particulate/colloidal concentration reduction" (colloidal =
    turbidity proxy, not direct NTU); (d) wash-routing + empirical-capture-modifier help
    text on the Help sheet; (e) Display/Popup populated: inlet/filtrate/wash Q and XTSS,
    HLR (m/d and m/h), plus LOCAL diagnostics — TSS concentration reduction
    (1 − eff..XTSS/inp..XTSS), TSS load diversion to wash, TSS balance residual
    (≈0 always), coagulant-conflict flag (`Dose,alum·Dose,fe`, nonzero = both dosed —
    the only way the effective reduction can exceed 1; single-coagulant dosing is bounded
    by the parameter limits). NOT implementable in unit code: MIN/MAX clamps (the SMT
    expression grammar has no comma-argument function calls — `MAX(0, MIN(1, …))` parsed
    as identifiers) and a hard rejection of simultaneous doses (flag + docs instead).
    Fixed fWash is a declared simplification (paper: 10.8–12.3 % across feed rates);
    the demo's fresh feed is 125 m³/h (3000 m³/d) → HLR ≈ 194 m/h through the 0.72 m²
    bed, far above the pilot's tested 3.9–8.5 m³/h (HLR 5.4–11.7 m/h) — treat the demo
    as an arithmetic demonstration, not pilot validation. Rung 3 clean (1,267,981-byte
    XML), rung 4 relinked (PE32+ x86-64), reinstalled.

**Restart note for the user:** the installed unit appears on the SUMO24 drawing
board after the next SUMO restart (startup-only scan). Uninstall:
`hh_install_process_unit(action="uninstall", opt_in=true, slug=".../HH_DynaSand_v1")`.
