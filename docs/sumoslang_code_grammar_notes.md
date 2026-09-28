# SumoSlang Code-Sheet Grammar — Extracted from the Vendor PDFs

Ticket 03a. Sources: `The Book of SumoSlang.pdf` (52 pp, "BoSS") and `Sumo Technical
Reference.pdf` (220 pp, containing the four-part "SumoSlang for Dummies" wiki article at pp
189–220 by Dwight Houweling). Page references below are the printed page numbers of the PDFs,
not PDF-page indices.

Every fact below is **[READ]** (from the named PDF section) unless marked otherwise. Where the
documentation is silent, the gap is flagged and handed to ticket 03b (corpus census).

---

## 1. Codelocation vocabulary

**[READ]** BoSS §3.1 "Table structure" (pp 12–13) and §3.2.1 "Table tag" (pp 17–18).

- The `Code` worksheet of a process unit groups code in **tables**. Each table carries a
  3-segment **descriptor** in cells `B2:D2`:
  - `B2` — table **type** (may be empty, or a keyword: `Array`, `if block`, `C++ code`,
    `Newton-Raphson`; on the Unit worksheet `Port`, `Attribute`, `Model`, `Handling`; and
    `SolverConfiguration` which replaces `Newton-Raphson` in tandem with Equilibrium code
    locations).
  - `C2` — table **name** (free grouping name; must be unique on the Parameters worksheet).
  - `D2` — table **tag**. For the Code worksheet the tag used by nearly the whole shipped
    library is `Codelocation(arg)`.
- The `Codelocation(arg)` argument is one or more of these four **block** keywords:
  1. `ZeroTime`
  2. `DataComm`
  3. `Integrated`
  4. `Equilibrium`
- **Syntax** (BoSS p 19): `Codelocation(block[,section] … [;block[,section]])`
  - `block` — code block name.
  - `section` — code section name under the block node.
  - `,` — section separator; `;` — block separator.
  - Both `[,section]` and `[;block[,section]]` are optional.
  - If `section` is omitted, the default `"1"` to `"n"` is used.
  - If **multiple distinct blocks** are listed, the table's code lines are **repeated** in the
    generated XML within each listed block.
- The grouping is reflected verbatim in the generated XML as `<codeblocks>` children (BoSS
  p 18, Figure 15: code locations begin at XML row 10759 under a `<model>` node).
- **Ordering guarantee**: BoSS §3.2.1 gives only the block keyword list, not an execution
  ordering contract. The XML Debugger wiki article (Technical Reference pp 181–182, "Block"
  view) lists the calculation blocks in the order *"loading functions, parameters, initializing
  variables at ZeroTime, calculations in DataComm, … Algebraic loops"*. That informal sequence
  — parameters → ZeroTime (initialisation) → DataComm → Integrated (integration) → Algebraic
  loops → Equilibrium — is the best documented ordering; the exact solver ordering is otherwise
  **[UNVERIFIED]** in these two PDFs. → **for ticket 03b**: confirm block ordering from the
  generated-XML codeblocks order in the shipped library.
- **Default when the tag is absent**: **[UNVERIFIED]**. BoSS never states what happens to a Code
  table whose tag `D2` is empty or is an arbitrary (non-`Codelocation`) filtering text. §3.2.1
  says the tag "may contain … code filtering information" (arbitrary text used with expansion
  rules) in addition to the `Codelocation` keyword — implying a tag can be a filter string with
  no block. → **for ticket 03b**: census whether any shipped unit has a Code table without a
  `Codelocation` tag, and which block the SMT defaults it into.

### Event handling (uses Codelocation)

**[READ]** BoSS §6.4 (p 37). Events are event-location function chains. The **event function's
name is the `section` part** of its `Codelocation(…)` argument. An event function is defined in
the `Event` code location (a block outside the four listed above — event handling introduces
`Event` as a further block/location). Called from code by setting `Symbol` = function name,
`Expression` = function argument, and a `Call` rule. `Now` and `Time` are keywords: time at
simulation start, and current time at each call.

---

## 2. Variable classes

**[READ]** BoSS §4.3 "Symbol roles" (p 22) and §5.1 "Expandable symbols" (pp 24–25).

SumoSlang assigns every symbol a **role**:

| Role | Definition |
|---|---|
| **Constant** | numerical constants from `Constants` worksheet of `systemcode.xlsx` |
| **Parameter** | user-modifiable; everything on `Parameters` worksheets (models and units) except dimensions |
| **State variable (SV)** | dynamic state; a symbol matching a row on the `Components` worksheet of model-or-unit that has `Integrated` handling, with a corresponding derivative present in unit code |
| **Derivative** | `d<state variable>_dt` |
| **SystemState** | any other variable (calculated variables, temps, etc.) |

The four **expandable shorthand keywords** (each a shorthand for a triplet, §5.1):

- `SV` ≡ `MODEL.SV.Symbol` — state variables; filterable by phase/particle-size shorthands:
  `L.SV` (liquid), `G.SV` (gas), `S.SV` (solid); `sSV` (dissolved/small), `cSV` (colloidal),
  `xSV` (particulate). All composable in that order (`L.sSV` = liquid dissolved).
- `PAR` ≡ `MODEL.PAR.Symbol` — parameters from the model's `Parameters` worksheet; filtered by
  `Type(…)`.
- `CVAR` ≡ `MODEL.CVAR.Symbol` — calculated variables from `Calculated variables`; filtered by
  `Type(…)`.
- `SPC` ≡ `MODEL.SPC.Symbol` — chemical species from `Species` worksheet (whole list pulled in,
  no grouping).

**Triplet notation** (§5.1.5, pp 25–26): `MODEL.Worksheet.Column` — model identifier, worksheet
name, column name. Worksheet/column parts may use shorthand (`SV`, `PAR`, `CVAR`, `SPC`) or
explicit names (quoted if they contain spaces). `MODEL` is **not a keyword** — it is the model
identifier declared on the Unit sheet.

**Data types** (§4.2, pp 21–22): `Integer`, `Real`, `Boolean`, `String`, `Dimension`. Default
type is **Real**; there is **no type inference** — the author must set the type in the `Rule`
column.

**Declared place of each class** (BoSS §2.2 "Process model" pp 7–8; §2.3 "Process units"
pp 8–9): model worksheets `Parameters`, `Species`, `Components`, `Calculated variables` (fixed
names) plus arbitrary `Model` (Gujer/kinetic matrix) and `pH`. Unit worksheets: `Unit`
(attributes/handlings), `Parameters`, `Code` (mandatory); optional `Components`, `Functions`,
`Structure`.

**Which the SMT rejects out of scope**: **[UNVERIFIED]** — the PDFs never enumerate SMT
rejections. The Dummies tutorial shows build-time rejections instead (missing `muOHO_T`,
`kLaGCH4_bub`, unmapped `XBIO` CVAR) that surface at **build/compile**, not SMT-parse. →
**for ticket 03b / 01**: the actual SMT error vocabulary.

---

## 3. Expression language

**[READ]** BoSS §4 "Basic language elements" (pp 20–23), §3.1.3/§3.1.4 (pp 16–17), §5.2 "Rules"
(pp 26–31).

**Assignment**: `a = b` (strictly one variable on the LHS). Symbol column holds LHS; `Value`/
`Default`/`Expression` column(s) hold RHS. RHS may be variables, numeric values, string
literals, functions, operators.

**Operators** (Table 1, p 21): `+ - * / ^ && || ! == != < > <= >=`. Division-by-zero is
auto-protected (a tiny ε is added to every quotient).

**Variable name rules** (pp 20–21): start with a letter; may contain letters, numbers, comma
`,`, single dot `.`, single underscore `_`, and sub/superscript parts. `..` and `__` are
forbidden (they are namespacing keywords). Example legal name: `Tlocal,max_P12.V1.0_x`.

**Conditionals** — `if block` table type (§3.1.3, p 16): extra columns `Operator` and
`Condition` before `Symbol`. Operator ∈ {`if`, `else if`, `else`}; an `if` always pairs with an
`else`/`else if`, and paired rows must carry identical symbols. Condition column is C-like;
notably `=` is read as `==` (`control = 1` ≡ `control == 1`). Nested `if` supported via numbered
Operator columns.

**C++ code escapes** (§3.1.4, pp 16–17): raw C++ blocks (`C++ code` table type). `Inputs` column
lists input Sumo variables; `Outputs` the generated outputs. Code lives in the `Expression`
column and may reference variables via a `NAMESPACE__` prefix, which the SMT replaces with the
unit's namespace.

**Function library** (§4.4 "Functions", pp 22–23): `Functions` worksheet of `systemcode.xlsx`
declares functions. The usual math functions are in a table tagged `Pure`; other tables are Sumo
functions written in C++. Declaration syntax:
`[type][array_sign] name([type][array_sign] [name][;] …)` where type ∈ `REAL` (default), `INT`,
`BOOL`, `STRING`; `[]` = array. Example: `Average([] x; INT start; INT end)` → REAL array arg
`x`, INT args. The **actual function list is not enumerated** in the PDFs. → **for ticket
03b**: census the real `Pure` function set from `systemcode.xlsx`.

**Rules** (the `Rule` column, §5.2 pp 26–31). A rule is a Boolean expression over a code line;
result = AND-composition of `;`-separated elements. Kinds:
- `Type(arg1;…;argn)` — table-descriptor rule; pulls code from all tables tagged with matching
  args (usually from the model, or parent/children).
- `Handling(…)` and other **table-header rules** — `columnname(arg1;…;argn)`, OR across args;
  context worksheet inferred from the Symbol expandable.
- Attribute filters (`Non-` = negation) — e.g. `InheritkinPAR` / `Non-InheritkinPAR`.
- `Exempt(list)`, `Only(list)` — explicit symbol filters during expansion (pp 29–30).
- `[n]` — array size (on array rows), and `sum(arg)`, `mul(arg)`, `sum(<n>)` with distribution
  handlings `Free|Head|Tail|Equal`, `Step(arg)`, `Call`.

**The `Decimals` column**: **[UNVERIFIED / NOT FOUND]**. Neither PDF mentions any `Decimals`
column. The Book (§3.1, pp 12–13) names fixed header columns *"e.g. Symbol, Name, Value, Rule"*
as the fixed set, others arbitrary. The Dummies tutorial works with `Symbol`, `Name`, `Value`,
`Rule` and `Expression`/`Default` columns. `Decimals` does not appear anywhere in the 3 main
manuals (`SUMO Manual`, `Sumo User Manual`, `Sumo22.1 documentation`, `The Book of SumoSlang`,
`Sumo Technical Reference` — verified by full-text search, 0 hits). → **This is a corpus
question; ticket 03b owns it.** If a `Decimals` column exists in the shipped workbooks it is a
non-keyword display column the SMT ignores (like `Name`/`Unit`), but that is **[REASONED]**, not
read.

---

## 4. Namespacing

**[READ]** BoSS §7 "Namespaces" (pp 38–39), §2.4.1 "Plantwide code" (pp 11–12), §8 (pp 40–42);
Dummies (pp 202–213).

Two kinds:

**Implicit** (§7.1): the SMT decorates every symbol with the unit path from the plant root,
segments joined by `__`. Root is virtual (`Sumo` fixed first segment, `Plant` second). Example:
`SV = SV_0` in unit `PU1,2` → `Sumo__Plant__PU1__PU1_2__SV = Sumo__Plant__PU1__PU1_2__SV_0`.
Model parameters gain one extra model-name segment when inheritance is on:
`Sumo__Plant__PU1__PU1_2__Sumo1__muOHO = Sumo__Plant__PU1__Sumo1__muOHO`.

**Explicit** (§7.2): prefix before a symbol, delimiter `..`. Namespace may be:
- `Parent` — direct parent unit (only direct parent referenceable).
- `Root` — hierarchy root.
- **port name** — a port from the unit's `Unit` sheet (this is how `inp..Q`, `outp..L.SV` work;
  the port location is declared in the `Port` table, `Unit` sheet cell `$D$5`).
- **model ID** — the identifier on the `Unit` sheet (enables multi-model units / non-default
  models).
- **model name** — only for units restricted to a specific model (declared in the `Model`
  table's `Valid` column).
- **process unit name** — a child unit declared on the `Structure` sheet (a unit knows its
  children's names, not its parent's).
All are relative paths, resolved to absolute `__`-paths in the XML.

**Model independence (the Type A/B crux)**: model identifiers on the `Unit` sheet are *not*
model names — they are local variables mapped to actual models from outside during simulation
(§8, p 40). This is exactly the mechanism that lets one process-unit's code work across model
bases (Dummies pp 199, 216). Default model = first ID on the Unit sheet; non-default models need
the full triplet + explicit model-ID namespacing.

`Parent..PAR` is the inheritance idiom: when parameter inheritance is ON, process units pull
model parameters from the parent (`PAR = Parent..PAR`), else from the model (`MODEL.PAR.Default`),
selected by the `InheritkinPAR` / `Non-InheritkinPAR` attribute pair (Book pp 26–27; Dummies pp
218–219).

---

## 5. Where the Gujer matrix physically lives

**[READ]** BoSS §2.2 (p 8), §4.1 (pp 20–21), §6.2 (pp 34–35); Dummies (pp 199, 202–203).

- The **Gujer matrix** (stoichiometric matrix) and the **process rate equations** live in the
  **Model Base** file (`Model base\*.xlsm`, e.g. `Sumo1.xlsm`, `Sumo2C.xlsm`, `Mini_Sumo.xlsm`),
  on the arbitrarily named but conventionally named **`Model` worksheet**.
  - Columns on `Model`: a `j` index column, a `Rate` column (process rate expressions,
    e.g. `$AN$4`, `$AN$5` in the tutorial file), and the stoichiometric coefficient columns
    (e.g. `$E$4:$AM$5`), each headed by a state-variable symbol.
- The **Process Unit** (`Code` worksheet, a table group pointed at by triplet references) does
  the matrix multiplication: `rate_SV[] = vMODEL.Model.j,SV[] * rMODEL.Model.j[]` (summed over
  `j` via `sum(MODEL.Model.j)`). BoSS §4.1 Figure 16 shows the three-line chain on the process
  unit's Code sheet:
  - `rMODEL.Model.j[]` ← `MODEL.Model.Rate[]` (pulls the rate expressions)
  - `vMODEL.Model.j,SV[]` ← `MODEL.Model.SV[]` (pulls the stoichiometric coefficients)
  - `rate_SV[] = vMODEL.Model.j,SV[] * rMODEL.Model.j[]` (the conversion-rate construction)
- The differential equation (`dL.SV_dt` = … `rate_SV` … divided by volume `L.V`) is also in the
  **Process Unit** Code sheet, not the model. Dummies p 203: table 3 (rows 17–19) defines
  `dL.SV_dt` from `rate_SV` and `L.V`.
- **Partition in one line** (Dummies p 199): *"the Conversion rate of X in the mass balance is
  coded in the Model Base whereas the rest of the mass balance equation is coded in the Process
  Units."*
- Gujer matrix rows = processes `rj`; there are two matrices side by side in `Sumo*.xlsm` — the
  symbolic/parametised one and a second "evaluated" numeric duplicate that the **SMT ignores**
  (Dummies p 202).
- Ticket 05 implication: a stoichiometric coefficient row is written on the **Model Base's
  `Model` worksheet**, one column per state variable, one row per process `rj`; the **model also
  carries `Parameters`** (`Type(Kinetic)`/`Type(Stoichiometric)`/`Type(Equilibrium)` groups) and
  `Calculated variables`; the process unit only *references* these by triplet notation and adds
  the mass-balance differential. **[REASONED]** summary; the row/column cell layout (which
  column letter, `Name` vs `Symbol`) is corpus detail → **for 03b/04**.

---

## 6. Gaps handed to other tickets

- **03b (corpus)**: the actual `Decimals` column (or whether it exists / what it means); the
  real `Pure` function library; Codelocation **block ordering**; the default block when a table
  has no `Codelocation` tag; per-column fixed header spellings across the 236 units.
- **04 (model base)**: exact `Model` worksheet cell layout for a Gujer row (column letters,
  `j`/`Rate`/component columns, `Name` vs `Symbol`); the `Parameters`/`Calculated variables`
  `Type(...)` groupings; the second "evaluated" matrix that the SMT ignores.
- **01 (SMT round-trip)**: the SMT's actual error/reject vocabulary (unknown from these PDFs).
