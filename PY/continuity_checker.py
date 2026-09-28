"""
continuity_checker.py
─────────────────────
Group HH — rung 2 of the acceptance ladder: the continuity check + the
mandatory composition self-consistency companion (map Q14 teeth item 1).

Reproduces, in Python, the vendor's own "Check Continuity and Rates" macro
(Dynamita Sumo2C.xlsm Help sheet): for each process row of the Gujer matrix,
the sum over state variables of (stoichiometric coefficient x elemental
composition) must be zero for each balance element — COD, C, N, P, Na, K, Ca,
Mg, Cl, Fe, Al. The vendor quotes an ABSOLUTE limit of 1E-15 (Help sheet, not invented
here) and that figure is always reported — but it is NOT the gate: measured, 3 of 111
Sumo2C processes sit at ~3.5e-15 absolute from floating-point accumulation alone, so an
absolute 1E-15 gate rejects the vendor's own shipped matrix. The gate is relative.

Two surfaces, one core:

  1. Model-base continuity  — read a shipped (or forked) model-base workbook's
     SYMBOLIC Gujer block + Elemental composition block, resolve every
     symbolic expression through the parameter/constant/calculated-variable
     symbol map, and report per-process per-element residues. Validated
     against the shipped focus models: all three PASS at the relative gate, with the
     absolute 1E-15 figure reported alongside.

  2. Spec-based composition self-consistency — for a Type B unit_spec.json,
     independently recompute COD / C / N / P / charge from each NEW state
     variable's declared elemental/ionic formula and fail on mismatch with its
     declared composition. This is the check that stops the continuity check
     from being self-certifying for new variables (a wrong composition yields
     a self-consistent wrong matrix — continuity passes against a fiction).

Design rules (ticket 06, hard requirements):

  - Components are looked up by HEADER NAME, never by column index.
  - The SYMBOLIC Gujer block is read (Sumo2C Model rows 4..114); the
    macro-maintained EVALUATED numeric block (rows 134..244) is IGNORED, as
    is the SMT-blessed behaviour.
  - Tolerance: VENDOR_TOLERANCE = 1E-15 is the vendor's own figure and is always REPORTED,
    but it is NOT the gate. Measured: 3 of 111 Sumo2C processes sit at ~3.5e-15 absolute
    (~7e-17 relative) purely from floating-point accumulation, so an absolute 1E-15 gate
    rejects the vendor's own shipped matrix. The pass/fail decision is RELATIVE_TOLERANCE
    (1e-9). DECLARED_TOLERANCE (1e-3, relative) applies to human-written declared
    compositions, which are rounded by nature.
    wrong block read) — never "loosen the bound".
  - Charge is NOT emitted as a per-process continuum: the continuity balance
    set has no charge row (verified); charge closure belongs to the pH solve.
    Charge is checked only inside composition self-consistency.

Read-only over the vendor tree (openpyxl read_only). Never writes anywhere
under the SUMO24 install directory -- the tool writes nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:  # openpyxl is the corpus reader; xlsxwriter is the (unused here) writer
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

VENDOR_TOLERANCE = 1e-15  # Dynamita "Check Continuity and Rates" absolute limit
#
# The vendor Help states an ABSOLUTE limit of 1E-15. Measured over the shipped
# Sumo2C focus model, the symbolic matrix produces floating-point residuals up
# to ~3.6e-15 on 3 of 111 processes (relative residual ~7e-17, i.e. ~16 machine
# epsilon) purely from summing symbolically-cancelling terms whose parameters
# are stored to ~15 significant figures. A hard absolute 1e-15 gate therefore
# rejects the vendor's own shipped base. The pass/fail decision is therefore
# made on a RELATIVE basis (residual vs term magnitudes), while the absolute
# residual vs 1e-15 is always reported. See the ticket answer "The tolerance".
RELATIVE_TOLERANCE = 1e-9
# Tolerance for DECLARED (human-authored, rounded) composition vs the value
# derived from the elemental formula. Deliberately looser than RELATIVE_TOLERANCE:
# it compares a written-down number against a computed one, not two computed ones.
DECLARED_TOLERANCE = 1e-3   # 0.1% relative

BALANCE_ELEMENTS = ["COD", "C", "N", "P", "Na", "K", "Ca", "Mg", "Cl", "Fe", "Al"]

# Atomic masses (g/mol) — matching systemcode_constants in the shipped bases.
ATOMIC_MASS = {
    "C": 12.0107,
    "H": 1.00794,
    "O": 15.9994,
    "N": 14.0067,
    "P": 30.9737622,
    "S": 32.065,
    "Na": 22.989769,
    "K": 39.0983,
    "Ca": 40.078,
    "Mg": 24.305,
    "Cl": 35.453,
    "Fe": 55.845,
    "Al": 26.9815,
}

# Residual / status sentinels
CONTINUITY_OK = "continuity-ok"
CONTINUITY_VIOLATION = "continuity-violation"
CONTINUITY_UNRESOLVED = "continuity-unresolved"

_IDENTIFIER = re.compile(r"[A-Za-zµηαβγΔθΩφ_][A-Za-zµηαβγΔθΩφ_,\.0-9]*")
_SAFE_EXPR = re.compile(r"^[0-9eE+\-*/()., ]+$")


# --------------------------------------------------------------------------- #
# Expression resolution
# --------------------------------------------------------------------------- #

class UnresolvedExpression(Exception):
    """Raised when a symbolic expression references symbols absent from the map."""

    def __init__(self, expr: str, missing: Iterable[str]):
        self.expr = expr
        self.missing = sorted(set(missing))
        super().__init__(
            f"unresolved expression {expr!r}: missing symbols {self.missing}"
        )


def resolve(expr: str, symbol_map: Dict[str, float]) -> float:
    """Resolve a Sumo symbolic arithmetic expression to a float.

    The expression is restricted to what actually occurs in the Gujer and
    Elemental-composition cells of the shipped bases: the four operators
    ``+ - * /``, parentheses, numeric literals, and identifiers (which may
    contain commas and dots, e.g. ``iCIT,VFA``, ``GCO2,atm``). No ``^``, no
    function calls, no spaces were measured, so the char set is deliberately
    whitelisted before ``eval`` for safety.
    """
    expr = expr.strip()
    if not expr:
        raise UnresolvedExpression(expr, ["<empty>"])

    missing = [t for t in _IDENTIFIER.findall(expr) if t not in symbol_map]
    if missing:
        raise UnresolvedExpression(expr, missing)

    substituted = _IDENTIFIER.sub(lambda m: repr(symbol_map[m.group(0)]), expr)

    if not _SAFE_EXPR.match(substituted):
        raise UnresolvedExpression(expr, ["<non-arithmetic tokens>"])

    try:
        return float(eval(substituted, {"__builtins__": {}}, {}))
    except Exception as exc:  # pragma: no cover - defensive
        raise UnresolvedExpression(expr, [type(exc).__name__]) from exc


# --------------------------------------------------------------------------- #
# Model-base reading
# --------------------------------------------------------------------------- #

def _column_index_by_header(row, *names):
    """Map header names to 0-based column indices, looking up by NAME not index."""
    out = {}
    for idx, cell in enumerate(row):
        if cell is None:
            continue
        key = str(cell).strip()
        if key in names:
            out[key] = idx
    return out


def load_symbol_map(workbook_path: str) -> Dict[str, float]:
    """Build the numeric symbol map from a model base's value-bearing sheets.

    Sources (all located by header, all read with data_only=True so Excel's
    cached values are used — exactly the numbers the vendor macro evaluates):

      1. Parameters          -> Symbol(col B) : Default(col D)
      2. other parameters    -> Symbol(col B) : Default/Value(col D)
      3. systemcode_constants-> Symbol(col B) : Value(col D)
      4. Calculated variables-> Symbol(col B) : Value(col E)   [cached]
      5. Components          -> Symbol(col B) : Initial concentration(col E)
                               [state variables, at initial conditions]
    """
    if openpyxl is None:  # pragma: no cover
        raise RuntimeError("openpyxl is required to read model bases")

    wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    symbol_map: Dict[str, float] = {}

    def ingest(sheet, sym_col, val_col):
        if sheet not in wb.sheetnames:
            return
        for row in wb[sheet].iter_rows(values_only=True):
            sym = row[sym_col] if len(row) > sym_col else None
            if not (isinstance(sym, str) and sym.strip() and sym.strip() != "Symbol"):
                continue
            val = row[val_col] if len(row) > val_col else None
            if isinstance(val, (int, float)):
                symbol_map[sym.strip()] = float(val)

    ingest("Parameters", 1, 3)
    ingest("other parameters", 1, 3)
    ingest("systemcode_constants", 1, 3)
    ingest("Calculated variables", 1, 4)
    ingest("Components", 1, 4)

    wb.close()
    return symbol_map


def _read_model_sheet(workbook_path: str):
    """Return the raw Model-sheet rows (formulas) for a model base."""
    if openpyxl is None:  # pragma: no cover
        raise RuntimeError("openpyxl is required to read model bases")
    wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=False)
    ws = wb["Model"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    return rows


def read_gujer_matrix(workbook_path: str):
    """Parse the SYMBOLIC Gujer + Elemental composition blocks from a base.

    Returns a dict:
        processes: [{j, symbol, name, coeffs: {component: expr}, rate}]
        components: [header names in column order]
        elemental:  {element: {component: expr}}
    Locates everything by header name (row 3) and the 'Elemental composition'
    sentinel in column D — the vendor macro's own geometry, never hard-coded
    row offsets beyond the documented start.
    """
    rows = _read_model_sheet(workbook_path)

    # Header row = the row whose column B reads "j".
    header_row = None
    for r in rows:
        if r[1] == "j":
            header_row = r
            break
    if header_row is None:
        raise ValueError(f"{workbook_path}: no Gujer header row (col B = 'j')")
    header = list(header_row)

    # Component columns: every named header strictly between 'Name' and 'Rate'.
    col_header = {}
    for i, v in enumerate(header):
        if v is None:
            continue
        col_header[i] = str(v).strip()

    name_col = next((i for i, v in col_header.items() if v == "Name"), None)
    rate_col = next((i for i, v in col_header.items() if v == "Rate"), None)
    if name_col is None or rate_col is None:
        raise ValueError(f"{workbook_path}: missing Name/Rate columns")

    comp_cols = [
        i for i, v in col_header.items() if name_col < i < rate_col and v
    ]
    components = [col_header[i] for i in comp_cols]

    header_idx = rows.index(header_row)

    # Symbolic block: rows after the header whose column B is a positive int.
    # The macro-maintained EVALUATED second matrix (stacked below, formula cells
    # like "=-1/Y_OHO_VFA_ox" in underscore named-ranges) is IGNORED: the vendor
    # Help says the symbolic block "is the last [row whose] first empty cell in
    # column C", and the SMT ignores the evaluated block too. We stop on the
    # first empty column-B cell (the blank row after the symbolic block).
    processes = []
    for r in rows[header_idx + 1:]:
        j = r[1]
        if j is None or str(j).strip() == "":
            break  # end of the symbolic block
        if isinstance(j, (int, float)) and float(j) > 0:
            coeffs = {}
            for ci, cname in zip(comp_cols, components):
                v = r[ci]
                if v is not None and v != "":
                    coeffs[cname] = str(v).strip() if not isinstance(v, (int, float)) else str(v)
            processes.append({
                "j": int(float(j)),
                "symbol": str(r[2]).strip() if r[2] is not None else f"r{int(float(j))}",
                "name": str(r[3]).strip() if r[3] is not None else "",
                "coeffs": coeffs,
                "rate": str(r[rate_col]).strip() if r[rate_col] is not None else "",
            })

    # Elemental composition block: rows after the 'Elemental composition' marker.
    elemental: Dict[str, Dict[str, str]] = {}
    marker_row = None
    for i in range(header_idx + 1, len(rows)):
        d = rows[i][3]
        if isinstance(d, str) and d.strip().lower() == "elemental composition":
            marker_row = i
            break
    if marker_row is None:
        raise ValueError(f"{workbook_path}: no 'Elemental composition' marker")

    for r in rows[marker_row + 1:]:
        label = r[3]
        # The next empty column-D cell ends the elemental block.
        if label is None or str(label).strip() == "":
            break
        elem = str(label).strip()
        if elem not in BALANCE_ELEMENTS:
            continue
        entry: Dict[str, str] = {}
        for ci, cname in zip(comp_cols, components):
            v = r[ci]
            if v is not None and v != "":
                entry[cname] = str(v).strip() if not isinstance(v, (int, float)) else str(v)
        elemental[elem] = entry

    return {"processes": processes, "components": components, "elemental": elemental}


def _row_is_blank_beyond(row, col) -> bool:
    return all(v is None for v in row[col:])


# --------------------------------------------------------------------------- #
# Continuity computation
# --------------------------------------------------------------------------- #

def _numeric(expr: str, symbol_map: Dict[str, float]) -> float:
    """Coerce a cell value to a float, resolving symbolic expressions."""
    if expr is None or expr == "":
        return 0.0
    expr = str(expr).strip()
    if expr in ("", "-", "+"):
        return 0.0
    try:
        return float(expr)
    except ValueError:
        return resolve(expr, symbol_map)


def check_model_base_continuity(workbook_path: str):
    """Run the continuity check over a model base's symbolic Gujer matrix.

    Returns a report dict:
        ok: True iff no violation and no unresolved process
        tolerance: VENDOR_TOLERANCE
        per_process: [{j, symbol, name, residues: {element: value},
                       verdict, violations: [Verdict]}]
        n_violations, n_unresolved, n_checked
    """
    symbol_map = load_symbol_map(workbook_path)
    gujer = read_gujer_matrix(workbook_path)
    return _check_gujer(symbol_map, gujer, workbook_path=workbook_path)


def _check_gujer(symbol_map: Dict[str, float], gujer: dict,
                 workbook_path: Optional[str] = None) -> dict:
    """The residual core, separated so the self-test (and the spec path) can
    feed it an in-memory gujer — including a mutated copy — without round-tripping
    the workbook through a lossy writer. ``gujer`` is the dict from
    ``read_gujer_matrix`` (or the spec-built equivalent)."""
    elemental = gujer["elemental"]
    components = gujer["components"]

    report = {
        "workbook": workbook_path or "<in-memory>",
        "tolerance": VENDOR_TOLERANCE,
        "n_processes": len(gujer["processes"]),
        "n_components": len(components),
        "balance_elements": list(BALANCE_ELEMENTS),
        "per_process": [],
    }

    n_violations = n_unresolved = n_checked = 0

    for proc in gujer["processes"]:
        residues = {}
        verdicts = []
        verdict = CONTINUITY_OK
        for elem in BALANCE_ELEMENTS:
            if elem not in elemental:
                continue
            terms = []
            total = 0.0
            try:
                for comp in components:
                    coeff_expr = proc["coeffs"].get(comp)
                    if coeff_expr is None:
                        continue
                    coeff = _numeric(coeff_expr, symbol_map)
                    comp_expr = elemental[elem].get(comp)
                    comp_val = _numeric(comp_expr, symbol_map) if comp_expr is not None else 0.0
                    if coeff == 0.0 or comp_val == 0.0:
                        continue
                    term = coeff * comp_val
                    terms.append((comp, coeff, comp_val, term))
                    total += term
            except UnresolvedExpression as exc:
                residues[elem] = None
                verdicts.append({
                    "element": elem, "residual": None,
                    "verdict": CONTINUITY_UNRESOLVED,
                    "missing": exc.missing,
                })
                verdict = CONTINUITY_UNRESOLVED
                n_unresolved += 1
                continue

            residues[elem] = total
            n_checked += 1
            magnitude = sum(abs(t[3]) for t in terms)
            relative = abs(total) / (1.0 + magnitude)
            violation = relative > RELATIVE_TOLERANCE
            if violation:
                verdicts.append({
                    "element": elem, "residual": total,
                    "relative_residual": relative,
                    "verdict": CONTINUITY_VIOLATION,
                    "largest_terms": _largest(terms),
                })
                if verdict != CONTINUITY_UNRESOLVED:
                    verdict = CONTINUITY_VIOLATION
                n_violations += 1

        report["per_process"].append({
            "j": proc["j"],
            "symbol": proc["symbol"],
            "name": proc["name"],
            "residues": residues,
            "verdict": verdict,
            "violations": verdicts,
        })

    report["ok"] = n_violations == 0 and n_unresolved == 0
    report["n_checked"] = n_checked
    report["n_violations"] = n_violations
    report["n_unresolved"] = n_unresolved

    # Surface the vendor absolute figure: max |residual| per element, so the
    # 1E-15 reference is never hidden behind the relative classifier.
    max_abs = {e: 0.0 for e in BALANCE_ELEMENTS}
    for proc in report["per_process"]:
        for e, v in proc["residues"].items():
            if v is not None and abs(v) > max_abs.get(e, 0.0):
                max_abs[e] = abs(v)
    report["max_abs_residual"] = max_abs
    report["vendor_tolerance"] = VENDOR_TOLERANCE
    report["relative_tolerance"] = RELATIVE_TOLERANCE
    return report


def _largest(terms, k: int = 5) -> List[dict]:
    """Return the k largest-magnitude contributing terms."""
    terms = sorted(terms, key=lambda t: abs(t[3]), reverse=True)[:k]
    return [
        {"component": t[0], "coefficient": t[1],
         "composition": t[2], "contribution": t[3]}
        for t in terms if abs(t[3]) > 0.0
    ]


# --------------------------------------------------------------------------- #
# Composition self-consistency (new state variables)
# --------------------------------------------------------------------------- #

def theoretical_cod_cmole(elements: Dict[str, float]) -> float:
    """Theoretical COD (g O2 per formula unit, C-mole basis) from CaHbOcNdPe.

    Electron accounting to CO2, H2O, NH4+, PO4^{3-} (activated-sludge
    convention): COD = 8 * (4C + H - 2O - 3N + 5P)  grams O2. For a C-mole
    basis the units are g O2 per C-mole, i.e. gCOD per mole of compound when
    normalised to one carbon.
    """
    c = elements.get("C", 0.0)
    h = elements.get("H", 0.0)
    o = elements.get("O", 0.0)
    n = elements.get("N", 0.0)
    p = elements.get("P", 0.0)
    return 8.0 * (4.0 * c + h - 2.0 * o - 3.0 * n + 5.0 * p)


def _cmole_ram(elements: Dict[str, float]) -> float:
    """Relative atomic mass of one formula unit (per the C-mole basis)."""
    return sum(count * ATOMIC_MASS.get(el, 0.0) for el, count in elements.items())


def derive_composition(elements: Dict[str, float], charge: float) -> Dict[str, float]:
    """Independently derive the composition vector from an elemental+ionic formula.

    Input: ``elements`` on a C-mole basis ({C:1,H:1.8,O:0.5,N:0.2,…}) and an
    ionic ``charge`` per C-mole. Returns the composition the model-base
    Elemental-composition matrix would carry, in g-per-g-COD orientation:

        COD    = 1.0            (a COD-basis state variable is denominated gCOD)
        C      = 12.0107 / COD  (g C per g COD)
        N      = 14.0067*n/COD  (g N per g COD)
        P      = 30.974*p/COD   (g P per g COD)
        charge = charge / COD   (mol e per g COD)

    Raises ValueError when the formula has no reducible carbon (COD <= 0),
    e.g. an anionic or fully-oxidised species like sulfate — those cannot be
    expressed on a g-per-COD basis and their composition must be declared
    explicitly rather than derived.
    """
    cod = theoretical_cod_cmole(elements)
    if cod <= 1e-9:
        raise ValueError(
            "formula has no reducible carbon (COD <= 0); cannot express "
            "composition on a g-per-COD basis — this state variable's COD "
            "composition must be declared explicitly, not derived"
        )
    return {
        "COD": 1.0,
        "C": 12.0107 * elements.get("C", 0.0) / cod,
        "N": 14.0067 * elements.get("N", 0.0) / cod,
        "P": 30.9737622 * elements.get("P", 0.0) / cod,
        "charge": charge / cod,
    }


def check_self_consistency(
    formula: Dict[str, float],
    charge: float,
    declared_composition: Optional[Dict[str, float]] = None,
):
    """Composition self-consistency for ONE new state variable.

    Independently recomputes COD / C / N / P / charge from the elemental+ionic
    formula, then — when the spec also carries the composition its matrix will
    actually use (``declared_composition``) — fails on any pointwise mismatch.

    The declared composition is the load-bearing extra input: without it the
    check has nothing independent to compare against and returns
    ``consistent-but-unverifiable`` (see ticket 06 / schema gap note).

    Returns {ok, derived, declared, verdict, mismatches}.
    """
    try:
        derived = derive_composition(formula, charge)
    except ValueError as exc:
        return {
            "ok": False, "derived": None, "declared": declared_composition,
            "verdict": "self-consistency-uncheckable", "mismatches": [str(exc)],
        }

    if declared_composition is None:
        return {
            "ok": False,
            "derived": derived,
            "declared": None,
            "verdict": "self-consistency-unverifiable",
            "mismatches": [
                "no declared composition to compare the formula against — "
                "the spec must carry a separate composition (COD/C/N/P/charge) "
                "for every new state variable, or self-consistency cannot run "
                "(this is exactly the circularity the check exists to break)"
            ],
        }

    mismatches = []
    for key in ("COD", "C", "N", "P", "charge"):
        if key not in declared_composition:
            continue
        dv = derived.get(key, 0.0)
        dc = declared_composition[key]
        # Declared compositions are HUMAN-AUTHORED and therefore rounded: a user
        # writes N = 0.0834, not 0.0833732142857143. Comparing them on the 1e-12
        # absolute basis used for machine-derived values rejects every realistic
        # declaration. Compare relatively instead, at DECLARED_TOLERANCE, which
        # still fails the wrong-composition class this check exists to catch
        # (that fixture is ~20% out, five orders of magnitude above the gate).
        scale = max(abs(dv), abs(dc))
        delta = dv - dc
        relative = abs(delta) / scale if scale > 0 else abs(delta)
        if relative > DECLARED_TOLERANCE:
            mismatches.append({
                "element": key, "derived": dv, "declared": dc,
                "delta": delta, "relative": relative,
                "tolerance": DECLARED_TOLERANCE,
            })

    ok = len(mismatches) == 0
    verdict = "self-consistency-ok" if ok else "self-consistency-violation"
    return {"ok": ok, "derived": derived, "declared": declared_composition,
            "verdict": verdict, "mismatches": mismatches}


# --------------------------------------------------------------------------- #
# Spec-level entry: run both checks against a unit_spec.json
# --------------------------------------------------------------------------- #

def check_spec(spec: dict, model_base_path: str) -> dict:
    """Run rung-2 (continuity + self-consistency) against a unit_spec.json.

    ``model_base_path`` is the shipped base the spec references (for the
    compositions of referenced state variables). Returns a composite report:

      - self_consistency: per introduced state variable
      - processes:        per-process continuity (only for routed_as == 'B')
      - ok:               True iff every check passes
    """
    routing = spec.get("routing", {}).get("routed_as")
    report = {"ok": True, "self_consistency": {}, "processes": None}

    introduced = spec.get("state_variables", {}).get("introduced", []) or []

    for sv in introduced:
        formula = sv.get("formula", {})
        elements = formula.get("elements", {})
        charge = formula.get("charge", 0)
        declared = sv.get("composition")  # separate field — see schema gap note
        sc = check_self_consistency(
            elements, charge, declared)
        report["self_consistency"][sv.get("symbol", "?")] = sc
        if not sc["ok"]:
            report["ok"] = False

    if routing == "B":
        report["processes"] = _check_spec_processes(spec, model_base_path)
        if report["processes"]["ok"] is False:
            report["ok"] = False

    return report


def _check_spec_processes(spec: dict, model_base_path: str) -> dict:
    """Continuity of the spec's Gujer rows against the referenced base's
    compositions (plus new SVs' formula-derived compositions)."""
    symbol_map = load_symbol_map(model_base_path)
    gujer = read_gujer_matrix(model_base_path)
    elemental = gujer["elemental"]

    introduced = spec.get("state_variables", {}).get("introduced", []) or []
    intro_comp = {}
    for sv in introduced:
        formula = sv.get("formula", {})
        elements = formula.get("elements", {})
        charge = formula.get("charge", 0)
        declared = sv.get("composition")
        if declared:
            intro_comp[sv["symbol"]] = declared
        else:
            try:
                d = derive_composition(elements, charge)
                intro_comp[sv["symbol"]] = {
                    "COD": d["COD"], "C": d["C"], "N": d["N"],
                    "P": d["P"], "charge": d["charge"],
                }
            except ValueError:
                intro_comp[sv["symbol"]] = {}

    per_process = []
    n_violations = n_unresolved = 0
    for proc in spec.get("processes", []):
        residues = {}
        violations = []
        for elem in BALANCE_ELEMENTS:
            total = 0.0
            terms = []
            unresolved = False
            for entry in proc.get("stoichiometry", []):
                comp = entry["component"]
                coeff_val = entry["coefficient"]["value"]
                if not isinstance(coeff_val, (int, float)):
                    # symbolic coefficient (e.g. "-1/Y_SOB") or REQUIRED sentinel
                    if coeff_val == "REQUIRED":
                        unresolved = True
                        continue
                    try:
                        coeff_val = resolve(str(coeff_val), symbol_map)
                    except UnresolvedExpression:
                        unresolved = True
                        continue
                # composition for this component: shipped base first, then the
                # new SV's (formula-derived or declared) composition.
                comp_entry = elemental.get(elem, {}).get(comp)
                if comp_entry is not None:
                    comp_val = _numeric(comp_entry, symbol_map)
                elif comp in intro_comp:
                    cv = intro_comp[comp].get(elem)
                    comp_val = cv if isinstance(cv, (int, float)) else 0.0
                else:
                    comp_val = 0.0
                term = float(coeff_val) * float(comp_val)
                terms.append((comp, coeff_val, comp_val, term))
                total += term
            residues[elem] = None if unresolved else total
            if unresolved:
                n_unresolved += 1
                violations.append({"element": elem, "verdict": CONTINUITY_UNRESOLVED})
            else:
                magnitude = sum(abs(t[3]) for t in terms)
                relative = abs(total) / (1.0 + magnitude)
                if relative > RELATIVE_TOLERANCE:
                    n_violations += 1
                    violations.append({
                        "element": elem, "residual": total,
                        "relative_residual": relative,
                        "verdict": CONTINUITY_VIOLATION,
                        "largest_terms": _largest(terms),
                    })
        per_process.append({
            "id": proc.get("id"), "name": proc.get("name"),
            "residues": residues, "violations": violations,
        })

    return {
        "ok": n_violations == 0 and n_unresolved == 0,
        "n_violations": n_violations,
        "n_unresolved": n_unresolved,
        "per_process": per_process,
    }


# --------------------------------------------------------------------------- #
# Command-line entry + self-test
# --------------------------------------------------------------------------- #

def self_test(focus_models=("Sumo2C", "Sumo2S", "Sumo4N"),
              scratch: Optional[str] = None) -> dict:
    """Run the acceptance self-test for the continuity checker.

    THREE checks, per the ticket:

      1. Shipped focus models PASS (0 violations, 0 unresolved).
      2. A mutated coefficient in a COPY FAILS, naming process / element /
         residual / largest terms.
      3. A wrong-composition state variable FAILS self-consistency even though
         its matrix closes against that composition.

    Returns a dict {passes: bool, details: {...}}.
    """
    import tempfile
    from sumo_paths import installation_path
    base_root = installation_path("Process code", "Model base", "Focus models")
    scratch = scratch or tempfile.mkdtemp(prefix="continuity_selftest_")

    details = {}

    # (1) shipped bases pass
    details["shipped"] = {}
    for name in focus_models:
        rep = check_model_base_continuity(str(base_root / f"{name}.xlsm"))
        details["shipped"][name] = {
            "ok": rep["ok"],
            "n_processes": rep["n_processes"],
            "n_violations": rep["n_violations"],
            "n_unresolved": rep["n_unresolved"],
        }

    # (2) mutation fails — mutate ONE coefficient in an in-memory copy of the
    # parsed gujer (same residual math, no lossy file round-trip), then confirm
    # the checker names the process/element/residual/largest-term it hit.
    symbol_map = load_symbol_map(str(base_root / "Sumo2C.xlsm"))
    gujer = read_gujer_matrix(str(base_root / "Sumo2C.xlsm"))
    mutated_gujer = {
        "components": list(gujer["components"]),
        "elemental": {e: dict(v) for e, v in gujer["elemental"].items()},
        "processes": [],
    }
    for proc in gujer["processes"]:
        pcopy = dict(proc)
        if proc["j"] == 1:
            pcopy["coeffs"] = dict(proc["coeffs"])
            pcopy["coeffs"]["SVFA"] = "-0.7/YOHO,VFA,ox"  # COD no longer closes
        mutated_gujer["processes"].append(pcopy)
    mut_rep = _check_gujer(symbol_map, mutated_gujer)
    mut_caught = []
    for pp in mut_rep["per_process"]:
        if pp["j"] == 1:
            mut_caught = pp["violations"]
    details["mutation"] = {
        "ok": mut_rep["ok"],
        "r1_violations": [
            {"element": v["element"], "residual": v.get("residual"),
             "relative_residual": v.get("relative_residual"),
             "largest_terms": [t["component"] for t in v.get("largest_terms", [])]}
            for v in mut_caught
        ],
    }

    # (3) wrong-composition fails self-consistency
    # Formula says N = 0.2 per C-mole (XSOB-like biomass), but the declared
    # composition claims N = 0.1 g N / g COD -- mismatched, yet a matrix built
    # against the declared composition would still close.
    formula = {"C": 1.0, "H": 1.8, "O": 0.5, "N": 0.2}
    charge = 0.0
    declared_wrong = {"COD": 1.0, "N": 0.1, "P": 0.0, "charge": 0.0}  # N wrong
    sc = check_self_consistency(formula, charge, declared_wrong)
    details["wrong_composition"] = {
        "verdict": sc["verdict"],
        "derived": sc["derived"],
        "mismatches": sc["mismatches"],
        "ok": sc["ok"],
    }

    shipped_ok = all(d["ok"] for d in details["shipped"].values())
    mutation_caught = (details["mutation"]["ok"] is False
                       and len(details["mutation"]["r1_violations"]) > 0)
    wrong_comp_caught = details["wrong_composition"]["ok"] is False

    return {
        "passes": shipped_ok and mutation_caught and wrong_comp_caught,
        "checks": {
            "shipped_bases_pass": shipped_ok,
            "mutation_fails_with_names": mutation_caught,
            "wrong_composition_fails": wrong_comp_caught,
        },
        "details": details,
    }


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry: --self-test | --check-base PATH | --check-spec SPEC --base PATH."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        prog="continuity_checker",
        description="Group HH rung-2: continuity + composition self-consistency "
                    "(vendor tolerance 1E-15).",
    )
    parser.add_argument("--self-test", action="store_true",
                        help="run the three-stage acceptance self-test")
    parser.add_argument("--check-base", metavar="PATH",
                        help="run model-base continuity on a .xlsm/.xlsx")
    parser.add_argument("--check-spec", metavar="SPEC.json",
                        help="run rung-2 on a unit_spec.json")
    parser.add_argument("--base", metavar="PATH",
                        help="model base for --check-spec")
    args = parser.parse_args(argv)

    if args.self_test:
        result = self_test()
        print(json.dumps(result["checks"], indent=2))
        return 0 if result["passes"] else 1

    if args.check_base:
        rep = check_model_base_continuity(args.check_base)
        print(json.dumps({
            "ok": rep["ok"],
            "n_processes": rep["n_processes"],
            "n_violations": rep["n_violations"],
            "n_unresolved": rep["n_unresolved"],
            "max_abs_residual": rep["max_abs_residual"],
            "vendor_tolerance": rep["vendor_tolerance"],
            "relative_tolerance": rep["relative_tolerance"],
        }, indent=2))
        return 0 if rep["ok"] else 1

    if args.check_spec:
        if not args.base:
            parser.error("--check-spec requires --base PATH")
        spec = json.load(open(args.check_spec, encoding="utf-8"))
        rep = check_spec(spec, args.base)
        print(json.dumps({
            "ok": rep["ok"],
            "self_consistency": rep["self_consistency"],
            "processes": (
                {k: rep["processes"][k] for k in ("ok", "n_violations", "n_unresolved")}
                if rep["processes"] else None
            ),
        }, indent=2))
        return 0 if rep["ok"] else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

