# SumoSlang workbook format — full-corpus contract

Source: full-corpus census of the shipped library, 2026-09-06, ticket 02b.
Measured over **all 236 process-unit workbooks** in the 5 categories
(`Process code/Process units/{10 Bioreactors,20 Flow elements,30 Separators,40
Special units,50 Catchments and rivers}`) plus **51 contrast workbooks**
(Energy units 11, Hidden units 28, Plantwide units 12) plus **84 Group Info
files** tree-wide. openpyxl read-only. Raw data:
`.scratch/sumoslang-unit-authoring/artifacts/census_full.json`.
Machine-readable contract: `PY/data/workbook_format.json`.
Unit-string vocabulary: `PY/data/unit_vocabulary.json`.

This document supersedes the 02a pilot draft. Corrections and refinements from
the pilot are marked `[corrected]`.

## Corpus (corrected counts)

| Category | Files | Group Info | Units |
|---|---:|---:|---:|
| 10 Bioreactors | 83 | 16 | 67 |
| 20 Flow elements | 76 | 16 | 60 |
| 30 Separators | 67 | 12 | 55 |
| 40 Special units | 13 | 6 | 7 |
| 50 Catchments and rivers | 66 | 19 | 47 |
| **Total (5 categories)** | **305** | **69** | **236** |

- Tree-wide: 420 workbooks, **84 Group Info** (the 69 category ones + 15 in
  Energy/Hidden/Plantwide). Zero unreadable workbooks.
- Group Info detection must be case-insensitive: `Deflocculator Group info.xlsx`
  (lowercase "info") in `40 Special units` is a Group Info file, not a unit.

## Sheet universe

| Sheet | Workbooks carrying it (all 287 scanned) | Status |
|---|---:|---|
| `Help` | 287 | universal |
| `Unit` | 287 | universal |
| `Parameters` | 282 | near-universal |
| `Code` | 282 | near-universal |
| `Display` | 264 | common |
| `Popup` | 264 | common |
| `Structure` | 65 | optional |
| `Components` | 45 | optional |
| `Predefined charts` | 6 | rare |
| `Functions` | 1 | singleton |

`[corrected]` The pilot's "Structure 31% / Components 31% / Predefined charts
9%" were Bioreactor-only. Full-corpus: Structure 23%, Components 16%,
Predefined charts 2%, and there is a 1-file `Functions` sheet (C++ escapes).

**The modal unit is 6 sheets** (`Help, Unit, Parameters, Code, Display, Popup`).
Missing-sheet classes: Hidden units mostly `Help|Unit|Parameters|Structure|Code`
(no Display/Popup); ChildU sub-units `Help|Unit|Parameters|Code`; `Model checker
PU`/`SV mapper` `Help|Unit|Code`; `CFP off*` `Help|Unit`.

## Sheet order

Observed sequences across all 287 scanned workbooks:

| Count | Sequence |
|---:|---|
| 157 | `Help \| Unit \| Parameters \| Code \| Display \| Popup` |
| 38 | `Help \| Unit \| Parameters \| Code \| Structure \| Display \| Popup` |
| 37 | `Help \| Unit \| Parameters \| Components \| Code \| Display \| Popup` |
| 12 | `Help \| Unit \| Parameters \| Structure \| Code` |
| 6 | `Help \| Unit \| Parameters \| Code \| Predefined charts \| Display \| Popup` |
| 3 | `Help \| Unit \| Parameters \| Structure \| Code \| Display \| Popup` |
| 2 | `Help \| Unit \| Components \| Parameters \| Code \| Display \| Popup` |
| 2 | `Help \| Unit \| Parameters` |
| 2 | `Help \| Unit \| Code` |
| 1 | `Help \| Unit \| Parameters \| Code \| Popup \| Display` |
| 1 | `Help \| Unit` |
| 1 | `Help \| Unit \| Parameters \| Code \| Display \| Popup \| Functions` |

Rules: `Help` always first (287/287). `Popup` last in the canonical 6-sheet
layout and `Display` immediately precedes it — **with one exception**:
`20 Flow elements/Chemicals/SodiumBicarbonate.xlsx` reverses them
(`...|Popup|Display`).

Positional slots are **conventions, not contracts**:
- `Structure` dominant slot is after `Code` (42 of 53), but Energy units,
  Hidden units, and the two Metal-chemical workbooks place it between
  `Parameters` and `Code`.
- `Components` dominant slot is between `Parameters` and `Code` (37), but
  `Drawdown Gen3 Facultative Pond.xlsx` and `Gen3 Facultative Pond.xlsx` place
  it *before* `Parameters`, and `Plantwide units/Statistics/Response time.xlsx`
  places it *after* `Code`.
- `Predefined charts` is always between `Code` and `Display` (6/6).
- `Functions` is appended last (1/1).

The generator should emit the canonical order and let the linter flag the
variants as warnings (they are accepted by the SMT; the corpus proves it).

## Table grammar (every sheet)

Every sheet is a **vertical stack of blocks** separated by blank rows. A block =
optional title cell(s) + header row + data rows. Header row index is
**unit-specific** (not a fixed global grid): `Unit` sheet headers occur at rows
3..214, `Code` at 3..1046, `Display` at 3..441, `Parameters` at 3..291,
`Structure` at 3..41. The generator must emit blocks, not a fixed row plan.

Title cell by sheet:

| Sheet | Title cell | Example |
|---|---|---|
| `Code` | column A | `Initialization`, `Hydraulics` |
| `Unit` | column B | `Port`, `Attribute`, `Model`, `Handling`, `AttributeGroup`, `Appearance` |
| `Parameters` | column C | section names |
| `Display` / `Popup` | column C (block name) + column D (`Location(Unit)` etc.) | `Frequently used variables` / `Location(Unit)` |
| `Components` | column C | `State variables` |
| `Structure` block 1 | column B | `Unit component` |
| `Structure` block 2 | column C | `Internal connection` |
| `Functions` | column C | `C++ functions` |
| `Predefined charts` | column C | `Time chart` |

Header row: the row whose column B cell is `Symbol` (or `Unit component` for
Structure block 1). **Every table starts in column B except the `Components`
table, which starts in column C.**

Data rows follow the header until a blank row. The blank-row separator between
blocks is load-bearing — ticket 01's bisection found that a **blank row between
a table title and its header breaks the SMT table scan**; the emitter must never
emit that.

## Column contracts (exact header strings, in order)

| Sheet | Header (B..) | Count |
|---|---|---|
| `Unit` Ports | `Symbol\|Name\|Position\|Phase\|Direction\|Image\|Size\|Rule\|Comments` | 197 |
| `Unit` Ports (no Image/Size) | `Symbol\|Name\|Position\|Phase\|Direction\|Rule\|Comments` | 37 |
| `Unit` Ports (minimal) | `Symbol\|Name\|Position\|Phase\|Direction\|Comments` | 35 |
| `Unit` Attributes | `Symbol\|Name\|Default\|Rule\|Comments` | 1755 |
| `Unit` Attributes (value form) | `Symbol\|Name\|Value\|Rule\|Comments` | 375 |
| `Unit` Attributes (value, no comments) | `Symbol\|Name\|Value\|Rule` | 41 |
| `Unit` Model block | `Symbol\|Name\|Valid\|Invalid\|Rule\|Comments` | 287 |
| `Parameters` | `Symbol\|Name\|Default\|Low limit\|High limit\|Unit\|Decimals\|Rule\|Principle/comment` | 2080 |
| `Parameters` array | `Symbol\|Name\|Default 1\|Default i(2 to n)\|Low limit\|High limit\|Unit\|Decimals\|Rule\|Principle/comment` | 39 |
| `Code` | `Symbol\|Name\|Expression\|Unit\|Decimals\|Rule\|Principle/comment` | 6407 |
| `Code` array variants | `Expression 1\|Expression i(2 to n)` / `Expression i(1 to n)` / `Expression 1\|Expression 2\|Expression i(3 to n-1)\|Expression n` | 244 |
| `Display` | `Symbol\|Name\|Value\|Unit\|Decimals\|Rule\|Principle/comment` | 3942 |
| `Popup` | `Symbol\|Name\|Value\|Unit\|Decimals\|Rule\|Principle/comment` | 2567 |
| `Components` (starts col C) | `Symbol\|Name\|Initial value\|Unit\|Decimals\|Handling` | 37 |
| `Predefined charts` | `Symbol\|Name\|Format\|Unit\|Decimals\|Rule\|Principle/comment` | 6 |
| `Structure` block 2 | `Symbol\|Label\|From\|To` | 100 |
| `Functions` | `Symbol\|Name\|Expression\|Rule\|Unit` | 1 |
| `Group Info` `Unit` | `Symbol\|Name\|Value\|Rule` | 84 |

Display/Popup short variants without `Rule\|Principle/comment` occur (282 + 167).

## Controlled vocabularies

**`Direction` — closed.** Exactly `in` (276) and `out` (389).

**`Phase` — closed.** Exactly `L` (471), `Air` (69), `Sewer` (63), `River` (42),
`Biogas` (20).

**`Position` — mini-language, 86 distinct tokens.**
`{TL|TR|BL|BR};{optional port-point letter};{dx px};{dy px}`, e.g. `BL;;6px;-60px`,
`TL;L;1px;1px`, `BR;R;-2px;-2px`. The middle field is empty in the dominant
form; letters `L`/`R`/`B` appear in a minority. A `97;50` form appears in some
Size fields — it is a size, not a position.

**`Rule` — compound expression language, NOT a closed list** (1249 distinct
tokens across the corpus). Semicolon-joined flag tokens plus function-call
forms:
- flags: `Energy`, `Reactive`, `Inherit`, `Hidden`, `Constant`, `Integer`,
  `pH`, `Reactive`, `ModelExcluded(Mini_Sumo)`, negations `Non-<flag>`
- functions: `Type(Stoichiometric|Equilibrium|Energy|Chargebalance)`,
  `Model(Sumo2C|Sumo2S|Mini_Sumo|…)`, `Only(SPO4|GCO2|…)`,
  `Handling(Set)`, `SumTo(EnergyCenter)`
- array markers: `[n]`, `[Top..n]`, `[Bottom..n]`
- compounds: `Energy; Centrifugal`, `Integer; Energy; Screw`, `[n]; Reactive`,
  `InheritstoPAR; Type(Stoichiometric)`, `Non-SOTEFixed_fine; Non-SOTEFixed_coarse`

**Limit sentinels.** Named boundaries in the `Low limit`/`High limit` columns:
`BigNumber` (8720), `-BigNumber` (329), `SmallNumber` (1326), `MaxStateVar`
(2024), `MaxFlow` (267), `MinFlow` (249), `MinV` (157), `MaxV` (147), `Zero`
(207), `One` (54), `NonDetect` (81), `0` (22). Model-expandable quoted limits:
`"MODEL.PAR.Low limit"`, `"MODEL.PAR.High limit"`, `"MODEL.Components.High limit"`.

**`Decimals`** is a display-precision integer 0–5 (rare 6); the SMT ignores it
(confirmed ticket 03b). Workbook UI convention only.

**`Handling`** (Components sheet): `Integrated` observed.

## Structure sheet

Two blocks. Block 1 (`Unit component|Unit name|Label|<toggles>|Models`) lists
child sub-units and their sub-model toggles; block 2 (`Symbol|Label|From|To`)
is the internal connection table.

`[corrected]` The toggle column set is **NOT install-fixed** — 11 distinct
variants observed. Common toggles: `Reactive`, `Polymer`, `Energy`, `CFPcalc`,
`AlphaPred`, `AlphaSet`, `SOTECorr_*`, `SOTEFixed_*`, `SumoBioFilm`,
`DOCalculated`, `DOControl`, `OffGasEntry`, `AfterPrezone`. Invariant tail:
`InheritkinPAR`, `InheritstoPAR`, `InheritequPAR`, `Models`. The generator must
emit the toggle set appropriate to the unit class.

## Components sheet

`[corrected]` Starts at column **C** (the one table not anchored at B):
`C=Symbol, D=Name, E=Initial value, F=Unit, G=Decimals, H=Handling`. Lists extra
state variables the unit owns (e.g. `L.V`, `Sediments.L.V`).

## Group Info contract

84 files, each exactly two sheets: `Help` + `Unit`. The `Unit` sheet has
`C2` = group display name, header row 3 = `Symbol|Name|Value|Rule`, and rows:
- `SortingPriority` — int 70..2000, present 84/84.
- `DefaultUnit` — names the default unit workbook in the folder, present 84/84.
- `HideName` = `True` — present 8/84 (connector/mapper groups only).

Naming: folder contains `<name> Group Info.xlsx` beside its unit workbooks;
`C2` is usually the folder base name; `DefaultUnit` names a workbook in the
same folder.

## Symbol grammar

6751 distinct symbols. Shape:
`[port..]base[.field][,subscript][]` with separators `..` (port), `.` (field),
`,` (subscript), `[]` (array). Examples: `inp..Q`, `outp..F.XTSS`,
`inp..F.TBOD,5`, `Pel,pump`, `TBOD,5`, `α[]`, `ηFLOC,Process`.
Greek letters are load-bearing (α β γ δ ε η θ κ λ ρ τ Δ Θ); the Granular SBR
family uses **U+019E `ƞ`** (eta substitute) — a real symbol is `ƞactual`, not
`ηactual`.

## Encoding

The corpus is Unicode-native: Greek lowercase and capitals, degree sign
`°` (771), superscript `³` (225), micro `µ` (49), ellipsis `…`, curly quotes,
umlauts `ä ö`, `×`, `€`, non-breaking space. `xlsxwriter` writes Unicode
natively; the emitter must copy symbols and unit strings verbatim, never
transliterate.

## Unit-string vocabulary — feeds ticket 20

359 distinct unit tokens (see `PY/data/unit_vocabulary.json`), classified:

- **clean dimensional** (286 tokens, 72,260 occurrences) — `m3`, `g.m-3`,
  `g.m-3.d-1`, `d`, `kW`, `Pa`, `eq ALK.L-1`, `g VSS.g TSS-1`, …
- **conditioner / physical-state** (19, 1,455) — `m3 gas.d-1 at NTP`,
  `m3 gas.d-1 at field`, `m3 gas.d-1 at STP`, `Nm3.d-1`, `m3 gas.m-3`, …
- **non-dimensional marker** (30, 11,061) — `-`, `unitless`, `pHunit`, `ppm`,
  `pc`, `integer`, `CVunit`/`MVunit`/`ISunit` (custom unit placeholders),
  ratios `g.g-1`, `m2/m2`, `rpm`, `cap`, `PE`
- **model-expandable** (17, 7,300) — `MODEL.SV.Unit`, `MODEL.PAR.Unit`,
  `MODEL.CVAR.Unit`, `MODEL.Species.Unit`, `MODEL.pH.Unit`,
  `MODEL.Model.Unit`, `MODEL.Components.Unit`, `MODEL.Elemental.Unit`, and
  composites `MODEL.SV.Unit * m3.d-1`, `MODEL.CVAR.Unit * m3.d-1.m-2`,
  `MODEL.SV.Unit * d-1`, `MODEL.CVAR.Unit * g TSS.m-3`
- **percent-scaled** (7, 1,330) — `%`, `%.m-1`, `%v.v-1`, `%v/v`, `v/v%`,
  `%p/%`, `%v.v-1.d-1`

Substance qualifier: patterns `g X.m-3`, `g X.d-1`, `g X/m3` where X is a
controlled symbol (`N`, `P`, `S`, `COD`, `TSS`, `VSS`, `O2`, `TIC`, `Al`,
`Fe`, …). Currency base `cur.*` (kWh-equivalent pricing) is a custom base unit.

### Canonicalisation decision

- **`%` is a scaled dimension.** `%` alone is non-dimensional (0–100); `%x`
  composites (`.m-1`, `v.v-1`) keep the `/100` factor.
- **`at NTP` / `at STP` / `at field` are physical-state annotations** — they
  qualify the density/volume reference and do not change the dimensional
  kernel. `Nm3` is the same annotation embedded in the base symbol.
- **Substance qualifiers (`g X.m-3`)** are parsed as mass-of-X per volume; the
  `X` must resolve to a controlled substance symbol, not a free string.
- **Synonymous spellings** fall into families that a real unit parser must fold
  (see `unit_vocabulary.json.grammar_equivalence_families`): `l.s-1` ≡ `l/s` ≡
  `l s-1`; `m3.d-1` ≡ `m3/d`; `g O2.m-3` ≡ `g O2/m3`; `%v.v-1` ≡ `%v/v` ≡
  `v/v%`; `W.m-2` ≡ `W/m²`; `Wh/m³` ≡ `Wh/m3`; `m3` ≡ `m³`; whitespace variants
  `g.d-1` ≡ `g. d-1`; case variants `unitless`/`Unitless`, `pHunit`/`pHUnit`.
  **Folding these requires a parser** (slash → inverted exponent, superscript →
  exponent), not string normalisation — `W/m²` is `W.m-2`, which a string
  normaliser cannot reach from `W.m2`.

### Parseability verdict

**Static dimensional analysis of the literal subset is feasible, and the
offline rung can be built now**:

1. **`MODEL.*` references are unresolvable offline.** Any token containing
   `MODEL.` must be deferred to a second pass after the model base parses
   (ticket 20's split: literal-only check runs truly offline; expandable-unit
   handling waits for the model-base parse — this ticket confirms that split).
   The composite forms `MODEL.SV.Unit * m3.d-1` are a *product of an
   expandable with a literal factor*, which is expressible once the expandable
   resolves.
2. **Literal units need a real grammar, but the grammar is bounded.** A parser
   with: base units (`m, g, kg, s, min, h, d, mol, eq, L, l, m3, m2, Pa, bar,
   atm, K, C, W, kW, Wh, kWh, J, MJ, kJ, Hz, V, mV, m3 gas, Nm3, cur, pc, PE,
   cap, unitless, pHunit, ppm, %`), a `.`-separated factor chain, integer
   exponent syntax (`-1`, `-2`, `d-1`, `d-2`), the `X.Y` substance-qualifier
   prefix, and the `at NTP/STP/field` conditioner, covers the corpus. The
   grammar must also accept `^2` (superscript), `/`, and space spellings as
   canonical synonyms.
3. **Known failure classes to handle explicitly, not silently:**
   - typo units: `kw2`, `g. d-1`, `kg .m-3`, `MJ .kg-1` (whitespace/superscript
     mishaps) — linter warning + auto-correct via equivalence family.
   - `Pa.s^n`, `J.m-2.°C-1`, `(g O2/g biomass)/(W/m2)/d`, `ug.L-1 per g COD.m-3`
     — genuinely irregular forms (symbolic exponent `n`, per-word `per`,
     parenthesised quotients); **flag, do not fabricate**.
4. **Verdict:** literal-unit dimensional checking is **parseable for ~92% of
   the token count** (all tokens except the `MODEL.*` class: 93,406 total
   occurrences, 7,300 `MODEL.*` = 7.8%, so 92.2% is literal). The `MODEL.*`
   class is checkable once the model base is parsed. Ticket 20 can be specified
   against this split.

## Round-trip conformance (the fixture evidence)

`scripts/02b_roundtrip_diff.py` extracts a workbook's value grid
(`data_only=True` — the values the SMT reads, so formula cells are compared by
their cached results), regenerates it with `xlsxwriter`, and diffs cell-for-cell
with a float tolerance for the 15-digit Excel round-trip. Run over **all 236
unit workbooks: 236/236 lossless, 0 differing parts.**

Known cosmetic deltas (not data loss, not in the SMT's semantic read):
- formula cached values: the source `=0.2*200` with cache `40` round-trips as
  the literal `40` (xlsxwriter writes no formula cache) — value grid equal;
- float last-digit differences at the 15th–16th significant digit;
- OOXML-part cosmetics (styles/theme/drawings) are not recreated.

**Conformance fixtures** (chosen to cover the exceptions, not the common case):
- `10 Bioreactors/CSTR/Simple CSTR.xlsx` — canonical 6-sheet core; the
  conformance baseline.
- `20 Flow elements/Chemicals/SodiumBicarbonate.xlsx` — `Popup` before
  `Display` order exception.
- `10 Bioreactors/Drawdown Pond/Drawdown Gen3 Facultative Pond.xlsx` —
  `Components` before `Parameters`.
- `Plantwide units/Statistics/Response time.xlsx` — `Components` after `Code`.
- `20 Flow elements/Metal/Al2(SO4)3.xlsx` — `Structure` between
  `Parameters` and `Code`.
- `10 Bioreactors/Trickling filter/Trickling filter elements/ChildU_TricklingFilter.xlsx`
  — sub-unit, 4 sheets only.
- `Hidden units/Other units/CFP unit/CFP off.xlsx` — minimal `Help|Unit` unit.
- `Plantwide units/Statistics/Noise.xlsx` — the `Functions` sheet (C++ escapes).
- `40 Special units/Deflocculator/Deflocculator Group info.xlsx` — lowercase
  `Group info` naming exception.
- `Energy units/20 Production units/Gastank/Biogas gastank.xlsx` —
  `Structure|Components` both present, Energy-unit contrast.
- `10 Bioreactors/Granular SBR/Aerobic granular sludge reactor.xlsx` — U+019E
  `ƞ` eta-substitute symbol family.

## Confidence and exceptions

High confidence (measured over the full corpus, not sampled): sheet universe,
sheet-order conventions + every named exception, header sequences per sheet,
column offsets, Direction/Phase closed sets, Position mini-language, limit
sentinels, Group Info contract, symbol grammar, encoding set, unit-string
classification, and the 236/236 round-trip conformance.

Exceptions to be treated as **known and expected**, not as bugs:
1. `SodiumBicarbonate` reverses `Popup|Display`.
2. Three different `Components` slot placements.
3. `Structure` slot differs between the 5 process categories and
   Energy/Hidden/Plantwide, and the toggle column set has 11 variants.
4. Hidden units and ChildU sub-units drop `Display`/`Popup`/`Code` entirely.
5. `Functions` sheet exists in exactly one file and carries raw C++.
6. `Deflocculator Group info.xlsx` uses lowercase "info" (Group Info naming is
   case-insensitive).
7. `Rule` is not a closed vocabulary; it is a compound expression language.
8. `%`/`°`/`³`/`²`/Greek/`µ` are load-bearing Unicode, and the Granular SBR
   family uses the `ƞ` eta-substitute.
9. `Predefined charts` has a `Format` column (not `Value`).

Unverified / not established: whether the SMT cares about sheet order at all
(ticket 01's XML is deterministic; nothing yet tests order sensitivity), and
whether the `97;50` position-like cells are ever read by the SMT.