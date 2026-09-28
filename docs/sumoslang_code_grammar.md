# SumoSlang Code-Sheet Grammar — Reconciled (Docs + Library Census)

Tickets 03a (vendor PDFs) + 03b (236-workbook library census). Every claim below is tagged
**[READ]** (a named source), **[MEASURED]** (a script run over the shipped library / generated
artifacts), or **[REASONED]** (inferred). Where the docs and the corpus disagree, **the corpus
wins** — it is what the SMT actually accepts.

Sources: `The Book of SumoSlang.pdf` (BoSS), `Sumo Technical Reference.pdf` (incl. "SumoSlang
for Dummies" pp 189–220), the shipped `D:\SUMO24\Process code\` library (236 unit workbooks),
and the compiled artifacts in the ticket-01 harness
`C:\Users\DELL\AppData\Local\Temp\slc_rev\` (`tpx\sumoproject.xml`, `srcdir\model_sumo.cpp`).

---

## 1. Codelocation vocabulary (03a stale — corrected by 03b)

**[READ]** BoSS §3.1/§3.2.1 gives the `Codelocation(block[,section] … [;block[,section]])` syntax:
`,` separates sections, `;` separates blocks, both parts optional; a table repeated in multiple
listed blocks. **[MEASURED]** The corpus confirms the syntax (`ZeroTime; Dynamic`,
`ZeroTime, eff`, `ZeroTime, sludge`, `ZeroTime, outp`, `Event, <name>`).

**But the block set is wrong as documented.** 03a reported exactly four keywords (`ZeroTime`,
`DataComm`, `Integrated`, `Equilibrium`). **[MEASURED]** The actual distribution over 7,355
tables:

| block arg | count | share |
|---:|---:|---:|
| `Dynamic` | 6,587 | **89.6%** |
| `Equilibrium` | 314 | 4.3% |
| `ZeroTime; Dynamic` | 142 | 1.9% |
| `ZeroTime` | 107 | 1.5% |
| `ZeroTime, <section>` | ~70 | ~1% |
| `Integrated` | 20 | 0.3% |
| `Event, <name>` | ~70 | ~1% |
| `DataComm` / `Accumulated` | 5 | <0.1% |

**`Dynamic` — the actual workhorse — is not one of the four documented keywords.** It never
appears as a runtime block name (see §6). Treat `Codelocation` as an arbitrary location string
with a small set of scheduler-special blocks; `Dynamic` is the ordinary per-timestep location.

---

## 2. Table structure (03b — descriptor layout)

**[MEASURED]** Each `Code` table has a **descriptor row** immediately above its header row:

- descriptor cell in the column of `Symbol` — table **type** (`` empty, or `Array`, or `if block`;
  one `SolverConfiguration` in the corpus);
- one column left of `Symbol` — table **name** (essentially always empty in practice);
- two columns right of `Symbol` — the **`Codelocation(…)` tag**.

`Symbol` is **not fixed to column B**: 6,554 tables have it in col B (index 1), but 453 in col 3,
231 in col 4, 117 in col 5 (GUI-arranged headers). An extractor must locate `Symbol`, not assume
column B.

---

## 3. Header columns (03b)

**[MEASURED]** 21 distinct header signatures; the dominant one (5,606 tables) is:

```
Symbol, Name, Expression, Unit, Decimals, Rule, Principle/comment
```

Array tables use multi-`Expression` columns (`Expression 1`, `Expression 2`,
`Expression i(2 to n-1)`, `Expression n`, …) inserted before `Unit`. `if block` tables replace
the leading columns with `Operator [, Operator 2 [, Operator 3]], Condition` before `Symbol`.

---

## 4. Decimals column (03a "not found" — answered by 03b)

**[MEASURED]** The `Decimals` column is a **display-precision integer 0–5** (occasionally stored
as text). It is present on every ordinary table, absent from `if block` tables, and is **not part
of the parse contract** — the SMT does not consume it. 03a's 0-hits in all five manuals are
correct: it is a workbook UI convention, not documented grammar.

---

## 5. Variable classes and Model-reference forms (03a + 03b)

**[READ]** roles: Constant, Parameter, state variable (SV), derivative `d<sv>_dt`, SystemState;
shorthands `SV`/`PAR`/`CVAR`/`SPC` ≡ `MODEL.<sheet>.<column>` triplets.

**[MEASURED]** Working `MODEL.*` forms the emitter must support (with `MODEL` a model identifier,
default = first ID on the Unit sheet): `MODEL.SV.Name/Unit`, `MODEL.PAR.Name/Default/Unit`,
`MODEL.CVAR.Name/Expression/Unit`, `MODEL.Model.j`, `MODEL.Model.Rate`, `MODEL.Model.SV`,
`MODEL.pH.Symbol`, `MODEL.pH.SPC`, `MODEL.Species.Name/Unit`, and the vector prefixes
`rMODEL.Model.j`, `vMODEL.Model.j,SV`. The dominant single reference is
`MODEL.CVAR.Expression` (1,234 hits).

Forms the corpus uses that 03a did not document: `[]`-suffixed array shorthands with a `[n]`/
`[ncycle]` rule; the inline `If(c; a; b)` builtin as the standard conditional (the `if block`
table is reserved for multi-statement branches); `SolverConfiguration` table type;
`Accumulated`-location code.

---

## 6. Execution ordering and the default block (03b — from compiled artifacts)

**[MEASURED / READ]** The SMT-generated XML lists blocks in this order: `Functions → Unspecified →
LoadBlock → ZeroTime → DataComm → AlgebraicLoop → Equilibrium → Integrated → SteadyState →
Algebraic → Event → RuleBase → Final → Energy → Dynamic → Accumulated → SaveAccumulated → DataIn →
ParameterAlias`. The `Energy/Dynamic/Equilibrium/Algebraic/Event/RuleBase/Final` slots are empty
schema placeholders in the compiled plant.

The slcompiler-generated C++ instantiates and registers the **runtime** blocks in this order:

```
LoadBlock → ZeroTime → DataComm → Accumulated → SaveAccumulated → DataIn → ParameterAlias
→ AlgebraicLoop(×N) → SteadyState → Integrated
```

with `Dynamic` folding into the `DataComm`/`SteadyState`/`Integrated` machinery (there is no
`Dynamic` block at runtime), `Equilibrium` into the Newton–Raphson equilibrium solve, and
`Integrated` into the BDF ODE. **Default block when the tag is absent:** the corpus never omits
the tag (0/7,355 untagged), so there is no observed default — the linter must refuse an untagged
table rather than assume one.

---

## 7. Gujer matrix row layout (03b)

**[MEASURED]** Model-base `Model` sheet (e.g. `Sumo2C.xlsm`, 258×105):

- header row = `j | Symbol | Name | <one coefficient column per component> | Rate | Unit |
  Reaction | Rule`;
- each row = one process `j` (index), `r<n>` symbol, name, a coefficient per component (blank ⇒
  not involved), the `Rate` expression, and `Unit = g.m-3.d-1`.

The process-unit side multiplies via `rMODEL.Model.j ← MODEL.Model.Rate`,
`vMODEL.Model.j,SV ← MODEL.Model.SV`, `rate_SV = vMODEL.Model.j,SV * rMODEL.Model.j`
(`sum(MODEL.Model.j)`), then folds `rateF_L.SV = L.V * rate_SV` into `dM_L.SV` and
`dL.SV_dt = dM_L.SV / L.V`. **Type A units keep this entire chain** (gated `Reactive`/
`Non-Reactive`); **Type B's unit-of-change is on the model base** (a new `Model` row +
`Parameters`/`Components`/`Species` entries), leaving the unit Code sheet untouched.

---

## 8. Minimum viable subset + linter refusal rules

Cycle-1 generator may emit only:

- Ordinary `Symbol`-leading tables, type `` / `Array` / `if block`, header
  `Symbol, Name, Expression, Unit, Decimals, Rule, Principle/comment`.
- Tags: `Codelocation(Dynamic)`, `(ZeroTime)`, `(ZeroTime; Dynamic)`, `(Equilibrium)`,
  `(ZeroTime, <section>)`. **No `Event`/`Accumulated`/`DataComm`/`Integrated` in cycle 1.**
- LHS symbols: `SV/SV[]`, `dM_L.SV`, `rateF_L.SV`, `rate_SV`, `dL.SV_dt`/`dSV_dt`, `M_L.SV`,
  `L.V/L.Vmin/L.Vmax`, `dL.V_dt`, `HRT`, `Q` + `..`-port names from the Unit sheet, `CVAR`,
  `PAR`, `outp..SV`/`outp..F_SV`; model refs from §5.
- Rule vocabulary (closed set): `Handling(…)`, `Type(…)`, `Inherit*PAR` + `Non-` forms,
  `Reactive`/`Non-Reactive`, `Phase(…)`, `sum(…)`, `[n]`, `Exempt()`, `Only()`, `Call`,
  `Boolean`, `Integer`.

Linter **hard refusals**: (1) untagged table; (2) tag outside the allow-list; (3) table type
other than ``/`Array`/`if block`; (4) Rule token outside the closed vocabulary; (5) `Decimals`
outside 0–5 or non-integer; (6) any `MODEL.*`/port reference the emitter did not itself declare.

Everything in the library outside this set (pump/energy plates, SBR `Event` chains, `C++ code`
escapes, `SolverConfiguration`, `Model(…)` filters, `SumTo(…)`, `SOTECorr_*`, catchment plates) is
a documented limitation, never silently generatable.
