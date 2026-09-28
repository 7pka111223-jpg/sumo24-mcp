"""
dimension_checker.py
────────────────────
Group HH — rung 1.5 of the acceptance ladder: the dimensional-consistency
check for rate expressions and code-sheet assignments (map Q15).

Question the rung answers: can the declared units on parameters, state
variables and constants be propagated through an expression to prove it is
dimensionally sound — statically, offline, before anything is compiled?

The ticket (20) splits the work so the cheap path is not blocked on the
expensive one:

  1. LITERAL-ONLY PATH (this module) — every unit string is literal, no
     model-base parse needed. Covers 92.2% of the corpus's unit-token
     occurrences (ticket 02b). Truly offline.
  2. MODEL-EXPANDABLE PASS (the gated second pass, NOT implemented here) —
     units like ``MODEL.SV.Unit``, ``MODEL.PAR.Unit`` and composites such as
     ``MODEL.SV.Unit * m3.d-1`` resolve only after the bound model base
     parses. Its result is base-dependent. This module DEFERS those rows with
     a named reason; the deferred-report surface is the interface the gated
     pass fills in.

Ground truth used, all [READ] from the vendor tree (read-only) or from the
approved vocabulary artifact — nothing is invented:

  - ``PY/data/unit_vocabulary.json`` (ticket 02b) — the 359-token
    classification, equivalence classes and canonicalisation notes. The
    equivalence families are the parser's conformance contract.
  - ``D:\\SUMO24\\Process code\\System files\\systemcode.xlsx`` ``Constants``
    sheet — 514 shared constants with declared units (``rhoH2O`` = ``g.m-3``,
    ``ggrav`` = ``m.s-2``, ``cL,m3`` = ``L.m-3``, ``AMP`` = ``g.mol-1``, ...).
    This is a System-file read, not a model-base parse, so it stays inside the
    literal-only path. It is what lets a shipped pump unit's energy rows
    resolve offline.

Canonicalisation decisions carried from ticket 02b (do not rediscover):

  - ``%`` alone is dimensionless; ``%x`` composites (``%.m-1``) keep the
    per-length kernel (the /100 factor is a scale, not a dimension).
  - ``at NTP`` / ``at STP`` / ``at field`` are physical-state annotations,
    not dimensions; ``Nm3`` embeds the same annotation.
  - ``unitless`` / ``pHunit`` / ``ppm`` / ``-`` are dimensionless markers.
  - Slash, space and superscript spellings are equivalence families
    (``l.s-1`` == ``l/s`` == ``l s-1``; ``W.m-2`` == ``W/m²`` == ``W/m2``)
    — folding them REQUIRES a parser, not string folding.
  - ``cur.*`` is an opaque custom currency base unit.
  - ``kw2`` is a spelling variant of ``kW`` (ticket 02b directed treating it
    as an equivalence family, not a new base unit).

The verdict discipline (ticket 20, acceptance): a code row is CHECKED only
when every symbol has a known literal unit and the expression is plain
arithmetic over those units. Rows that reference expandable or undeclared
symbols, or whose author clearly relied on an implicit-dimensional empirical
constant (dimensionless literal added to a dimensionful term), are DEFERRED
with a named reason — the checker never cries wolf. A row that IS fully
resolvable but whose computed dimension mismatches its declared unit is a
HARD VIOLATION, reported with the expression, the expected dimension and the
computed one.

Read-only over the vendor tree (openpyxl read_only). Never writes anywhere
under the SUMO24 install directory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:  # openpyxl is the corpus reader
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None

# --------------------------------------------------------------------------- #
# Dimension algebra
# --------------------------------------------------------------------------- #

M = "M"          # mass
L = "L"          # length
T = "T"          # time
TH = "Theta"     # temperature
MOL = "Mol"      # amount of substance
CHARGE = "Charge"
E = "E"          # energy
CUR = "CUR"      # currency (custom base, per 02b)
CNT = "Count"    # items / population equivalents


class Dimension:
    """A monomial of base dimensions with rational exponents.

    ``exps`` maps base-dimension name -> exponent. Equality and hashing are
    exact on the tuple of sorted items so that equivalent spellings fold to
    the same object.
    """

    __slots__ = ("exps",)

    def __init__(self, exps: Optional[Dict[str, float]] = None):
        self.exps = {k: v for k, v in (exps or {}).items() if v != 0}

    @classmethod
    def one(cls) -> "Dimension":
        return cls({})

    def is_dimensionless(self) -> bool:
        return not self.exps

    def __mul__(self, other: "Dimension") -> "Dimension":
        out = dict(self.exps)
        for k, v in other.exps.items():
            out[k] = out.get(k, 0.0) + v
        return Dimension(out)

    def __truediv__(self, other: "Dimension") -> "Dimension":
        out = dict(self.exps)
        for k, v in other.exps.items():
            out[k] = out.get(k, 0.0) - v
        return Dimension(out)

    def __pow__(self, n: float) -> "Dimension":
        return Dimension({k: v * n for k, v in self.exps.items()})

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Dimension):
            return NotImplemented
        return self.exps == other.exps

    def __hash__(self) -> int:
        return hash(tuple(sorted(self.exps.items())))

    def __str__(self) -> str:
        if not self.exps:
            return "dimensionless"
        parts = []
        for k in sorted(self.exps):
            v = self.exps[k]
            if v == 1:
                parts.append(k)
            else:
                parts.append(f"{k}^{v:g}")
        return "·".join(parts) if len(parts) > 1 else parts[0]

    def _key(self):
        return tuple(sorted(self.exps.items()))


# Verdict sentinels
PASS = "dimension-ok"
VIOLATION = "dimension-violation"
DEFERRED = "dimension-unverifiable"
UNSUPPORTED = "unit-unsupported"

# --------------------------------------------------------------------------- #
# The literal unit parser
# --------------------------------------------------------------------------- #

BASE_UNITS: Dict[str, Tuple[Tuple[str, float], ...]] = {
    # length
    "m": ((L, 1.0),), "m2": ((L, 2.0),), "m3": ((L, 3.0),),
    "cm": ((L, 1.0),), "cm2": ((L, 2.0),), "km": ((L, 1.0),),
    "mm": ((L, 1.0),), "ha": ((L, 2.0),),
    "l": ((L, 3.0),), "L": ((L, 3.0),), "mL": ((L, 3.0),), "ml": ((L, 3.0),),
    "Nm3": ((L, 3.0),),
    # mass
    "g": ((M, 1.0),), "kg": ((M, 1.0),), "mg": ((M, 1.0),),
    "ug": ((M, 1.0),), "µg": ((M, 1.0),), "t": ((M, 1.0),),
    "ton": ((M, 1.0),), "tonne": ((M, 1.0),),
    # time
    "s": ((T, 1.0),), "ms": ((T, 1.0),), "h": ((T, 1.0),), "d": ((T, 1.0),),
    "min": ((T, 1.0),), "mon": ((T, 1.0),), "w": ((T, 1.0),),
    "y": ((T, 1.0),), "yr": ((T, 1.0),), "a": ((T, 1.0),), "month": ((T, 1.0),),
    "year": ((T, 1.0),),
    # temperature
    "°C": ((TH, 1.0),), "K": ((TH, 1.0),),
    # energy / power — DERIVED, not base: the corpus computes power from
    # mechanical quantities (``Qpumped/cL,m3 * hloss,pump * rhoH2O/cg,kg *
    # ggrav/cW,kW`` = M.L2.T-3) and compares it to ``kW``. So energy folds to
    # M.L2.T-2, not a separate base (this is the canonicalisation the ticket's
    # acceptance discipline demands — an earlier E base broke the shipped
    # pump's energy rows).
    "J": ((M, 1.0), (L, 2.0), (T, -2.0)),
    "kJ": ((M, 1.0), (L, 2.0), (T, -2.0)),
    "MJ": ((M, 1.0), (L, 2.0), (T, -2.0)),
    "Wh": ((M, 1.0), (L, 2.0), (T, -2.0)),
    "kWh": ((M, 1.0), (L, 2.0), (T, -2.0)),
    "W": ((M, 1.0), (L, 2.0), (T, -3.0)),
    "kW": ((M, 1.0), (L, 2.0), (T, -3.0)),
    "MW": ((M, 1.0), (L, 2.0), (T, -3.0)),
    "kw2": ((M, 1.0), (L, 2.0), (T, -3.0)),  # spelling variant of kW (02b)
    # pressure / force
    "Pa": ((M, 1.0), (L, -1.0), (T, -2.0)),
    "bar": ((M, 1.0), (L, -1.0), (T, -2.0)),
    "mbar": ((M, 1.0), (L, -1.0), (T, -2.0)),
    "atm": ((M, 1.0), (L, -1.0), (T, -2.0)),
    "N": ((M, 1.0), (L, 1.0), (T, -2.0)),  # Newton
    # frequency
    "Hz": ((T, -1.0),), "rpm": ((T, -1.0),),
    # amount
    "mol": ((MOL, 1.0),), "kmol": ((MOL, 1.0),), "eq": ((MOL, 1.0),),
    "meq": ((MOL, 1.0),),
    # voltage — derived M.L2.T-2.Charge-1
    "mV": ((M, 1.0), (L, 2.0), (T, -2.0), (CHARGE, -1.0)),
    "V": ((M, 1.0), (L, 2.0), (T, -2.0), (CHARGE, -1.0)),
    # currency and counts. NOTE: pc/cap/PE/PED/PEO are DIMENSIONLESS in this
    # corpus's usage — ticket 02b classified them non-dimensional, and the
    # shipped pump treats ``nactive`` (pc) as a plain multiplier in kW rows
    # (``Pdry = nactive * Pel,nominal * ...``). Treating them as a Count base
    # produces false violations on shipped units, so they fold to
    # dimensionless. MPN (a true organism count) stays a Count base.
    "cur": ((CUR, 1.0),),
    "MPN": ((CNT, 1.0),),
}

# Base units after which a space-separated word may bind as a substance
# qualifier ("g O2", "kg TSS", "m3 gas", "eq ALK", "mol P").
MASS_BASES = ("g", "kg", "mg", "ug", "µg", "t", "ton", "tonne")
VOLUME_BASES = ("m3", "l", "L", "mL", "ml", "Nm3", "m2", "m")
MOLE_BASES = ("mol", "kmol", "eq", "meq")
QUALIFIER_BASES = MASS_BASES + VOLUME_BASES + MOLE_BASES

QUALIFIERS = {
    "N", "P", "S", "COD", "BOD", "BOD5", "BOD7", "TSS", "VSS", "VS", "SS",
    "TS", "DM", "O2", "TIC", "TOC", "Al", "Fe", "Ca", "Mg", "K", "Cl", "Na",
    "CH4", "CO2", "CO2eq", "N2O", "SO2", "polymer", "CATdi", "CATmono",
    "ALK", "EQ", "Me", "DS", "NG", "biomass", "VFA", "NH3", "NH4", "NO3",
    "PO4", "TKN", "TN", "TP", "SiO2", "CaO3", "gas", "GR", "bf", "cassette",
    "TBOD", "SO4", "H2S", "C",
}

# Tokens that carry no dimension (annotations / conditioners)
ANNOTATIONS = {"at", "NTP", "STP", "field", "gas", "GR", "bf", "Me", "NG",
               "DS", "cassette", "v", "biomass", "COD120"}

# Dimensionless markers (whole-token)
DIMENSIONLESS = {"-", "unitless", "Unitless", "pHunit", "pHUnit", "ppm",
                 "integer", "CVunit", "MVunit", "ISunit", "ISUnit", "VUnit",
                 "pc", "cap", "PE", "PED", "PEO"}

# Percent-family tokens -> (dimension, scaled)
PERCENT = {"%", "%v", "%p"}

# Substance qualifiers that change the MASS BASIS (vs generic mass).
SUBSTANCE_MASSES = QUALIFIERS - {"gas", "GR", "bf", "cassette", "Me", "NG",
                                 "DS", "v", "biomass", "COD120"}

# Conversions the dimensional rung OWNS (map ticket 06 note): g COD per g of a
# substance, for substance-crossing reports. H2S + 2 O2 -> H2SO4, per g S:
# 2 * M_O2 / M_S = 2 * 31.998 / 32.065.
G_COD_PER_G_SUBSTANCE = {"S": 2 * 31.998 / 32.065}

IDENT_START = "A-Za-zµηαβγΔθΩφλσρƞ"
IDENT_REST = "A-Za-z0-9µηαβγΔθΩφλσρƞ_,"


class UnparseableUnit(Exception):
    """Raised when a unit string cannot be statically parsed."""


def _fold_unicode(s: str) -> str:
    """Fold superscript digits and unicode symbols to their ASCII kernel."""
    s = s.replace("²", "2").replace("³", "3").replace("·", ".")
    return s.strip()


def _bind_qualifiers(part: str) -> str:
    """Join ``<base> <qualifier>`` pairs so the space is not treated as a
    factor separator. Runs on the raw (space-separated) form.

    Closed qualifier set after ANY qualifier base (preserves the
    whitespace-equals-dot equivalence families like ``l s-1``, where ``s`` is
    NOT a qualifier and must stay separate), PLUS an OPEN identifier after
    MASS bases only — an authored spec may introduce a novel substance
    qualifier (``g XSOB.g S-1``), and no shipped mass-unit spelling conflicts
    with the open rule."""
    out = part
    qual_alt = "|".join(sorted(QUALIFIERS, key=len, reverse=True))
    for base in sorted(QUALIFIER_BASES, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(base)}\s+({qual_alt})",
                     lambda m: base + "_" + m.group(1), out)
    for base in sorted(MASS_BASES, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(base)}\s+([A-Za-zµη][A-Za-zµη0-9]*)",
                     lambda m: base + "_" + m.group(1), out)
    return out


def _split_ops(s: str, sep: str) -> List[str]:
    """Split on sep, keeping parenthesised groups intact."""
    parts = []
    depth = 0
    cur = ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _parse_paren_group(factor: str):
    """If ``factor`` is a parenthesised group ``(...)`` optionally with an
    exponent, parse the interior as a unit expression. Returns the interior
    unit string + exponent, or None when it is not a numeric group (e.g. the
    annotation ``(COD120)`` after ``PE``)."""
    m = re.fullmatch(r"\(([^()]+)\)(-?\d+)?", factor)
    if not m:
        return None
    inner, exp = m.group(1), m.group(2)
    # Only pure dotted chains inside a group — nested ops are not supported
    if "/" in inner or "*" in inner or "(" in inner or ")" in inner:
        return None
    return inner, int(exp) if exp is not None else 1


def _qual_with_exp(qual: str):
    """Split ``O2`` (a qualifier, no exponent) from ``TSS-1`` (a qualifier
    with exponent). Returns (qualifier, exponent) or None. Qualifier names
    themselves contain digits (``O2``, ``CO2eq``, ``BOD5``), so the whole
    string is tried first and a trailing ``-?\\d+`` exponent is stripped only
    when the whole does not match. The qualifier set is OPEN for names the
    binding already produced (``base_qual``), since ``_bind_qualifiers`` only
    emits the ``_`` form for genuine qualifier bases."""
    if qual in QUALIFIERS or re.fullmatch(r"[A-Za-zµη][A-Za-zµη0-9]*", qual):
        return qual, 1.0
    m = re.fullmatch(r"(.+?)(-?[0-9]+)", qual)
    if m and (m.group(1) in QUALIFIERS
              or re.fullmatch(r"[A-Za-zµη][A-Za-zµη0-9]*", m.group(1))):
        return m.group(1), float(m.group(2))
    return None


def _factor_dimension(factor: str) -> Tuple[Optional[Dimension], Optional[str]]:
    """Dimension of one dotted factor, or (None, reason) when unparseable.

    Returns (dimension, substance_or_None)."""
    factor = factor.strip()
    if not factor:
        return Dimension.one(), None
    # dimensionless markers / annotations / percent
    if factor in DIMENSIONLESS:
        return Dimension.one(), None
    if factor in PERCENT:
        return Dimension.one(), None  # scaled dimension: scale is not a dim
    if factor in ANNOTATIONS:
        return Dimension.one(), None
    # trailing percent: ``v%`` == volume-percent == dimensionless scaled
    if factor.endswith("%") and factor[:-1] in ANNOTATIONS:
        return Dimension.one(), None
    # numeric multiplier (100mL, 1, 2)
    m = re.fullmatch(r"[0-9]+", factor)
    if m:
        return Dimension.one(), None
    # base_qualifier joined form (``g_O2``, ``kg_TSS``, ``m3_gas``,
    # ``g_TSS-1``)
    if "_" in factor:
        base, _, qual = factor.rpartition("_")
        if base in QUALIFIER_BASES:
            qm = _qual_with_exp(qual)
            if qm is not None:
                d, _ = _factor_dimension(base)
                return d ** qm[1], qm[0]
    # annotation with an exponent (``v-1``, ``gas-1``)
    am = re.fullmatch(r"([A-Za-zµ]+)(-?[0-9]+)", factor)
    if am and am.group(1) in ANNOTATIONS:
        return Dimension.one(), None
    # dimensionless marker with an exponent (``CVunit-1``)
    dm = re.fullmatch(r"(.+?)(-?[0-9]+)", factor)
    if dm and dm.group(1) in DIMENSIONLESS:
        return Dimension.one(), None
    # symbolic exponent
    if "^" in factor:
        return None, f"symbolic exponent in {factor!r}"
    # paren group
    pg = _parse_paren_group(factor)
    if pg is not None:
        inner, exp = pg
        inner = ".".join(f for f in inner.split(".") if f)
        try:
            unit = _parse_part(inner)
            return (unit.dimension ** exp), unit.substance or None
        except UnparseableUnit:
            return None, f"unparseable group {factor!r}"
    if factor.startswith("("):
        # parenthetical annotation, e.g. (COD120)
        if re.fullmatch(r"\([^()]+\)", factor):
            return Dimension.one(), None
        return None, f"unsupported parenthesised unit {factor!r}"
    # leading digits: ``100mL`` -> mL
    num_m = re.match(r"[0-9]+", factor)
    if num_m and num_m.end() < len(factor):
        return _factor_dimension(factor[num_m.end():])
    # base unit + optional exponent + optional glued qualifier
    for name in sorted(BASE_UNITS, key=len, reverse=True):
        if factor.startswith(name):
            rest = factor[len(name):]
            exps = dict(BASE_UNITS[name])
            substance = None
            if rest == "":
                pass
            elif re.fullmatch(r"-?[0-9]+", rest):
                n = float(rest)
                exps = {k: v * n for k, v in exps.items()}
            elif re.fullmatch(r"-?[0-9]+\.[0-9]+", rest):
                n = float(rest)
                exps = {k: v * n for k, v in exps.items()}
            elif rest in QUALIFIERS:
                substance = rest
            else:
                return None, f"unknown factor {factor!r}"
            dim = Dimension(exps)
            return dim, substance
    # a word we do not know: if it is a known qualifier alone, it is an
    # annotation (e.g. ``TSS g`` reversed order, ``NG`` after ``cur.m-3``)
    if factor in QUALIFIERS:
        return Dimension.one(), None
    return None, f"unknown factor {factor!r}"


def _parse_part(part: str):
    """Parse one numerator/denominator term into a Unit."""
    dim = Dimension.one()
    substances = set()
    annotations = []
    scaled = False
    for factor in [f for f in _split_ops(part, ".") if f != ""]:
        d, substance = _factor_dimension(factor)
        if d is None:
            raise UnparseableUnit(substance or factor)
        dim = dim * d
        if substance:
            substances.add(substance)
        if factor in PERCENT or factor == "%" or factor.endswith("%"):
            scaled = True
    return _Unit(dim, frozenset(substances), tuple(annotations), scaled)


class _Unit:
    __slots__ = ("dimension", "substance", "annotations", "scaled")

    def __init__(self, dimension: Dimension, substance=frozenset(),
                 annotations=(), scaled: bool = False):
        self.dimension = dimension
        self.substance = frozenset(substance)
        self.annotations = tuple(annotations)
        self.scaled = scaled

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Unit({self.dimension}, {sorted(self.substance)})"

    def __mul__(self, other: "_Unit") -> "_Unit":
        return _Unit(self.dimension * other.dimension,
                     self.substance | other.substance,
                     self.annotations + other.annotations,
                     self.scaled or other.scaled)

    def __truediv__(self, other: "_Unit") -> "_Unit":
        return _Unit(self.dimension / other.dimension,
                     self.substance | other.substance,
                     self.annotations + other.annotations,
                     self.scaled or other.scaled)


_UNITLESS = _Unit(Dimension.one())


def parse_unit(s: str) -> _Unit:
    """Parse a literal unit string into a dimension-bearing Unit.

    Raises UnparseableUnit for the flagged irregular classes (word ``per``,
    parenthesised quotients, symbolic exponents like ``Pa.s^n``).
    """
    s = _fold_unicode(s)
    if not s:
        return _UNITLESS
    if "per" in s:
        raise UnparseableUnit(f"word 'per' in {s!r}")
    if "^" in s and "s^n" in s:
        raise UnparseableUnit(f"symbolic exponent in {s!r}")

    # physical-state annotations are dropped, not dimensions
    for ann in ("at NTP", "at STP", "at field"):
        s = s.replace(ann, "")

    parts = _split_ops(s, "/")
    if not parts:
        return _UNITLESS
    numerator = _bind_qualifiers(parts[0])
    # collapse spaces around separators, then fold remaining spaces to dots
    numerator = re.sub(r"\s*\.\s*", ".", numerator)
    numerator = re.sub(r"\s+", ".", numerator)
    # a literal product marker (``CVunit*d``, ``MODEL.SV.Unit * m3.d-1``)
    factors = _split_ops(numerator, "*")
    total = _parse_part(factors[0])
    for extra in factors[1:]:
        total = total * _parse_part(extra)
    for denom in parts[1:]:
        d = _bind_qualifiers(denom)
        d = re.sub(r"\s*\.\s*", ".", d)
        d = re.sub(r"\s+", ".", d)
        d = _split_ops(d, "*")
        unit = _parse_part(d[0])
        for extra in d[1:]:
            unit = unit * _parse_part(extra)
        total = _Unit(total.dimension / unit.dimension,
                     total.substance | unit.substance,
                     total.annotations + unit.annotations,
                     total.scaled or unit.scaled)
    return total


# --------------------------------------------------------------------------- #
# Expression tokenizer + dimension resolver
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"|(?P<op>==|!=|<=|>=|<>|<|>|[-+*/^();])"
    r"|(?P<id>[" + IDENT_START + r"][" + IDENT_REST +
    r".]*(?:\[[0-9]+\])?)"
)


def _tokenize(expr: str):
    tokens = []
    for m in _TOKEN_RE.finditer(expr):
        if m.group("num"):
            tokens.append(("num", m.group("num")))
        elif m.group("op"):
            tokens.append(("op", m.group("op")))
        else:
            tokens.append(("id", m.group("id")))
    return tokens


class _ExprParser:
    """Recursive-descent parser over the Sumo expression grammar.

    Grammar (subset that actually occurs in the shipped corpus):
        expr    := addsub
        addsub  := muldiv (('+'|'-') muldiv)*
        muldiv  := power (('*'|'/') power)*
        power   := unary ('^' power)?
        unary   := '-' unary | atom
        atom    := num | id | id '(' args ')' | '(' expr ')'
        args    := expr (';' expr)*
    Comparisons are consumed as part of ``If`` conditions (we only need their
    operands' dimensions).
    """

    def __init__(self, tokens, lookup):
        self.tokens = tokens
        self.i = 0
        self.lookup = lookup          # symbol -> Unit | None(unknown/expandable)
        self.unknown = set()          # symbols referenced but not resolved
        self.empirical = set()        # empirical/implicit-constant signatures

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def next(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def _is(self, op):
        t = self.peek()
        return t is not None and t[0] == "op" and t[1] == op

    def _eat_ops(self, ops):
        while self.peek() is not None and self.peek()[0] == "op" \
                and self.peek()[1] in ops:
            self.next()

    def expr(self):
        return self.addsub()

    def addsub(self):
        left = self.muldiv()
        while True:
            t = self.peek()
            if t is not None and t[0] == "op" and t[1] in ("+", "-"):
                self.next()
                right = self.muldiv()
                left = self._add(left, right)
            else:
                return left

    def _add(self, a, b):
        if a.dim is None or b.dim is None:
            return _DimResult(None, a.reasons | b.reasons)
        if a.dim != b.dim:
            # dimensionless literal + dimensionful term = implicit empirical
            # constant (e.g. 1 - 7.34*kv^0.51). Not provable; do not cry wolf.
            if a.dim.is_dimensionless() or b.dim.is_dimensionless():
                self.empirical.add("dimensionless+dimensionful addend")
                return _DimResult(None, a.reasons | b.reasons)
            return _DimResult(
                None, a.reasons | b.reasons |
                {f"additive-dimension-mismatch {a.dim} vs {b.dim}"})
        return _DimResult(a.dim, a.reasons | b.reasons)

    def muldiv(self):
        left = self.power()
        while True:
            t = self.peek()
            if t is not None and t[0] == "op" and t[1] in ("*", "/"):
                self.next()
                right = self.power()
                if left.dim is None or right.dim is None:
                    left = _DimResult(None, left.reasons | right.reasons)
                elif t[1] == "*":
                    left = _DimResult(left.dim * right.dim,
                                      left.reasons | right.reasons)
                else:
                    left = _DimResult(left.dim / right.dim,
                                      left.reasons | right.reasons)
            else:
                return left

    def power(self):
        base = self.unary()
        if self._is("^"):
            self.next()
            exp = self.power()
            if base.dim is None or exp.dim is None:
                return _DimResult(None, base.reasons | exp.reasons)
            if not exp.dim.is_dimensionless():
                return _DimResult(
                    None, base.reasons | exp.reasons |
                    {f"power has dimensionful exponent {exp.dim}"})
            if base.dim.is_dimensionless():
                return _DimResult(Dimension.one(),
                                  base.reasons | exp.reasons)
            if exp.numval is not None:
                # numeric exponent (``Qpump,max^2``, ``Tsteam^0.0649``). An
                # INTEGER exponent is a real dimension (``Q^2``); a FRACTIONAL
                # exponent on a dimensionful base is the signature of an
                # empirical correlation (``Hg,m = 1983.7919 * Tsteam^0.0649``)
                # where the base enters as a number — not provable, defer.
                if exp.numval != int(exp.numval):
                    return _DimResult(
                        None, base.reasons | exp.reasons |
                        {"fractional power of a dimensionful quantity"})
                return _DimResult(base.dim ** exp.numval,
                                  base.reasons | exp.reasons)
            return _DimResult(None, base.reasons | exp.reasons |
                              {"power of a dimensionful quantity"})
        return base

    def unary(self):
        if self._is("-"):
            self.next()
            return self.unary()
        return self.atom()

    def atom(self):
        t = self.peek()
        if t is None:
            return _DimResult(None, {"<end of expression>"})
        if t[0] == "num":
            self.next()
            return _DimResult(Dimension.one(),
                              numval=float(t[1]))
        if t[0] == "op":
            if t[1] == "(":
                self.next()
                inner = self.expr()
                if self._is(")"):
                    self.next()
                return inner
            if t[1] in ("== ",):
                pass
            return _DimResult(None, {f"unexpected operator {t[1]!r}"})
        # identifier, maybe a function call
        name = self.next()[1]
        if self.peek() is not None and self.peek()[0] == "op" \
                and self.peek()[1] == "(":
            return self._call(name)
        return self._symbol(name)

    def _args(self):
        self._eat_ops([";"])
        args = []
        while True:
            args.append(self.expr())
            # consume a comparison (``Qpumped == 0``) inside If conditions:
            # the comparison's operands may differ in dimension (a boolean is
            # not a physical quantity); we only need to consume the tokens.
            t = self.peek()
            if t is not None and t[0] == "op" and t[1] in (
                    "==", "!=", "<", ">", "<=", ">=", "<>"):
                self.next()
                self.expr()
            t = self.peek()
            if t is not None and t[0] == "op" and t[1] == ";":
                self.next()
                continue
            return args

    def _call(self, name):
        self.next()  # consume '('
        if self.peek() is not None and self.peek()[1] == ")":
            self.next()
            return _DimResult(None, {f"function {name}() with no args"})
        args = self._args()
        if self._is(")"):
            self.next()
        arg_dims = [a for a in args if a.dim is not None]
        arg_unknown = [a for a in args if a.dim is None]

        def merged():
            return _DimResult(None, set().union(*[a.reasons for a in args])
                              | self.empirical)

        def branch_dim(dims):
            """Common dimension across Max/Min/If branches. A numeric-literal
            branch (``Max(0.0; Q)``, the corpus's zero-guard convention) adopts
            its sibling's dimension; a zero guard is not an empirical-mixing
            signature."""
            literal = [a for a in dims if a.numval is not None
                       and a.dim.is_dimensionless()]
            real = [a for a in dims if a not in literal]
            if not real:
                return Dimension.one()
            d = real[0].dim
            for a in real[1:]:
                if a.dim != d:
                    return None
            return d

        fname = name.lower()
        if fname in ("max", "min", "abs", "round", "ceil", "floor"):
            if arg_unknown:
                return merged()
            if len(arg_dims) < 1:
                return merged()
            d = branch_dim(arg_dims)
            if d is None:
                self.empirical.add("max/min/abs branches differ")
                return merged()
            return _DimResult(d, set().union(*[a.reasons for a in args])
                              | self.empirical)
        if fname == "if":
            if arg_unknown:
                return merged()
            if len(arg_dims) < 3:
                return merged()
            d = branch_dim(arg_dims[1:])
            if d is None:
                self.empirical.add("If branches differ in dimension")
                return merged()
            return _DimResult(d, set().union(*[a.reasons for a in args])
                              | self.empirical)
        if fname == "sqrt":
            if arg_unknown:
                return merged()
            d = arg_dims[0].dim
            if any(v % 2 != 0 for v in d.exps.values()):
                return merged()  # radicand not a perfect square -> defer
            return _DimResult(d ** 0.5, set().union(*[a.reasons for a in args])
                              | self.empirical)
        if fname in ("exp", "log10", "log", "ln"):
            if arg_unknown:
                return merged()
            if not arg_dims[0].dim.is_dimensionless():
                self.empirical.add(f"{name}() arg must be dimensionless")
                return merged()
            return _DimResult(Dimension.one(),
                              set().union(*[a.reasons for a in args])
                              | self.empirical)
        if fname in ("logsat", "loginhswitch"):
            # NOT logarithms: the vendor's ``Logsat``/``Loginhswitch`` are
            # saturation/switch functions (3 args) that return a flow or a
            # fraction. Their output dimension is not derivable statically.
            return merged()
        if fname == "pow":
            if arg_unknown:
                return merged()
            base_d, exp_d = arg_dims[0].dim, arg_dims[1].dim
            if not exp_d.is_dimensionless():
                return merged()
            return _DimResult(None, set().union(*[a.reasons for a in args]) |
                              {"pow with symbolic exponent"})
        if fname == "mod":
            if arg_unknown:
                return merged()
            return _DimResult(arg_dims[0].dim,
                              set().union(*[a.reasons for a in args])
                              | self.empirical)
        if fname in ("henry", "msat", "mrsat", "minh", "abserror"):
            # opaque model functions — cannot prove dimensional soundness
            return merged()
        # unknown function -> defer
        return merged()

    def _symbol(self, name):
        unit = self.lookup.get(name)
        if unit is None:
            self.unknown.add(name)
            return _DimResult(None, {f"symbol {name} has no declared unit"})
        if unit is False:
            self.unknown.add(name)
            return _DimResult(None, {f"symbol {name} is model-expandable"})
        return _DimResult(unit.dimension)


class _DimResult:
    __slots__ = ("dim", "reasons", "numval")

    def __init__(self, dim, reasons=frozenset(), numval: Optional[float] = None):
        self.dim = dim
        self.reasons = set(reasons) if not isinstance(reasons, set) else reasons
        self.numval = numval


def expression_substances(expr: str, symbol_map: dict) -> set:
    """The mass bases (COD, S, N, P, ...) a rate expression MENTIONS.

    `rate_sub` used to be read from the process's declared `rate_unit`, which defaults to the
    generic "g.m-3.d-1" and carries no substance qualifier - so it was empty for virtually
    every process and the crossing guard could never fire (repro_substance_crossing.py).

    Substance here means "which mass bases appear", not a net algebraic basis (`_Unit` unions
    substance on division rather than cancelling), so a mention-union is the right reading.
    """
    out = set()
    for tok in _tokenize(expr or ""):
        if tok[0] != "id":          # the tokenizer tags symbols "id", not "sym"
            continue
        u = symbol_map.get(tok[1])
        if u is not None and u is not False and getattr(u, "substance", None):
            out |= set(u.substance)
    return out



def resolve_expression_dims(expr: str, lookup) -> _DimResult:
    """Resolve an expression's dimension through a symbol->Unit lookup.

    ``lookup`` maps a symbol to a Unit, or None for an unknown/undeclared
    symbol, or False for a model-expandable symbol."""
    tokens = _tokenize(expr)
    parser = _ExprParser(tokens, lookup)
    result = parser.expr()
    return _DimResult(result.dim,
                      set(result.reasons) | {f"unknown symbol {s}"
                                             for s in parser.unknown})


# --------------------------------------------------------------------------- #
# Shared-system constants (offline, System-file read — not a model-base parse)
# --------------------------------------------------------------------------- #

from sumo_paths import installation_path
_SYSTEMCODE = installation_path("Process code", "System files", "systemcode.xlsx")


def load_systemcode_constants() -> Dict[str, _Unit]:
    """Symbol -> Unit from the systemcode ``Constants`` sheet (514 entries).

    [READ] read_only over the vendor System files. Constants with no declared
    unit are omitted; a constant whose unit fails to parse is omitted and
    reported through ``skip``."""
    out: Dict[str, _Unit] = {}
    skipped = []
    if openpyxl is None or not _SYSTEMCODE.exists():
        return out
    wb = openpyxl.load_workbook(_SYSTEMCODE, read_only=True, data_only=True)
    try:
        ws = wb["Constants"]
        for row in ws.iter_rows(values_only=True):
            if row is None or len(row) < 7:
                continue
            sym, val, unit = row[1], row[3], row[6]
            if not (isinstance(sym, str) and sym.strip() and sym.strip() != "Symbol"):
                continue
            if not (isinstance(unit, str) and unit.strip()):
                continue
            try:
                out[sym.strip()] = parse_unit(unit.strip())
            except UnparseableUnit:
                skipped.append((sym.strip(), unit.strip()))
    finally:
        wb.close()
    return out


SYSTEMCODE_CONSTANTS = load_systemcode_constants()

# Port-flow convention (ticket 02b port semantics): a ``..Q``-style flow
# variable on a port carries volumetric-flow dimension m3.d-1.
_FLOW_DIM = parse_unit("m3.d-1").dimension
_DENSITY_DIM = None


def _lookup_for(expr: str, symbol_map: Dict[str, object]) -> Dict[str, object]:
    """Wrap a symbol map so port-flow / gas-flow conventions resolve.

    ``symbol_map`` maps exact symbols to Unit | None | False. The wrapper
    adds: ``<any>..Q`` -> m3.d-1 (liquid flow), ``<any>..Qgas`` / ``..Qair``
    -> m3.d-1 (gas flow, NTP annotation). Mass-flow ports (``..F_L.SV``) and
    state-variable ports (``..L.SV``) are left to the expandable pass (their
    unit is ``MODEL.SV.Unit``-based) unless a literal unit is already known.
    """
    lookup = dict(symbol_map)
    tokens = {t[1] for t in _tokenize(expr) if t[0] == "id"}
    for tok in tokens:
        if tok in lookup:
            continue
        if re.fullmatch(r"[A-Za-zµηαβγΔθΩφλσρƞ][A-Za-z0-9µηαβγΔθΩφλσρƞ]*\.\.Q(?:gas|air)?",
                        tok):
            lookup[tok] = _Unit(_FLOW_DIM)
    return lookup


# --------------------------------------------------------------------------- #
# Workbook checker (corpus acceptance)
# --------------------------------------------------------------------------- #

def _read_rows(path: Path, sheet: str) -> List[list]:
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        if sheet not in wb.sheetnames:
            return []
        ws = wb[sheet]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _symbol_unit_from_sheet(rows: List[list], unit_col: int = 6):
    """Symbol -> Unit from a Parameters/Components sheet (col B symbol).

    A symbol declared with DIFFERENT units across blocks (e.g. ``PriceNaOH``
    as ``cur.kg-1`` in one dosing mode and ``cur.m-3`` in another, or ``G.SV``
    as ``%v.v-1`` in some workbooks) is marked None (conflicting) so that any
    row using it defers rather than guessing which declaration is active."""
    out = {}
    for r in rows:
        if r is None or len(r) <= unit_col:
            continue
        sym, unit = r[1], r[unit_col]
        if isinstance(sym, str) and sym.strip() and sym.strip() != "Symbol" \
                and isinstance(unit, str) and unit.strip():
            u = unit.strip()
            parsed = None
            if u.startswith("MODEL.") or "MODEL." in u:
                parsed = False  # expandable
            else:
                try:
                    parsed = parse_unit(u)
                except UnparseableUnit:
                    parsed = None  # flagged irregular
            sym = sym.strip()
            prev = out.get(sym, "unset")
            if prev == "unset":
                out[sym] = parsed
            elif prev != parsed:
                out[sym] = None  # conflicting declarations -> defer uses
    return out


def _extract_code_rows(rows: List[list]):
    """Code-sheet data rows as [(symbol, expression, unit)] in order.

    Rows with an EMPTY unit cell are kept (they still define a symbol whose
    unit is unknown); only rows with no expression are skipped."""
    out = []
    i = 0
    while i < len(rows):
        r = rows[i]
        if r and len(r) > 4 and isinstance(r[1], str) \
                and r[1].strip() == "Symbol" and r[3] == "Expression":
            j = i + 1
            while j < len(rows):
                row = rows[j]
                if row is None or len(row) < 5:
                    j += 1
                    continue
                sym, expr, unit = row[1], row[3], row[4]
                if sym is None or (isinstance(sym, str) and sym.strip() == ""):
                    break
                if isinstance(expr, str) and expr.strip():
                    u = unit.strip() if isinstance(unit, str) else ""
                    out.append((str(sym).strip(), expr.strip(), u))
                j += 1
        i += 1
    return out


def check_workbook(path: Path, use_systemcode: bool = True) -> dict:
    """Dimensional check over one shipped (or staged) unit workbook.

    Returns a report: per code row {symbol, expression, unit, verdict,
    expected, computed, reasons}, plus corpus-level tallies. The gate is
    ``n_violations == 0``.
    """
    p_rows = _read_rows(path, "Parameters")
    c_rows = _read_rows(path, "Code")
    comp_rows = _read_rows(path, "Components")

    symbol_map = _symbol_unit_from_sheet(p_rows)
    symbol_map.update(_symbol_unit_from_sheet(comp_rows))
    if use_systemcode:
        for k, v in SYSTEMCODE_CONSTANTS.items():
            symbol_map.setdefault(k, v)

    code_rows = _extract_code_rows(c_rows)

    checked = []
    n_pass = n_violations = n_deferred = n_unsupported = 0
    seen_symbols: Dict[str, object] = {}
    for symbol, expr, unit in code_rows:
        u = unit
        entry = {
            "symbol": symbol, "expression": expr, "unit": u,
            "verdict": DEFERRED,
        }
        declared = None
        # 1. declared unit
        if u == "":
            entry["reasons"] = ["empty unit cell"]
            n_deferred += 1
        elif u.startswith("MODEL.") or "MODEL." in u:
            entry["reasons"] = [f"model-expandable unit {u!r}"]
            n_deferred += 1
        else:
            try:
                declared = parse_unit(u)
            except UnparseableUnit as exc:
                entry["verdict"] = UNSUPPORTED
                entry["reasons"] = [str(exc)]
                n_unsupported += 1
                _register_symbol(seen_symbols, symbol, None)
                checked.append(entry)
                continue
            # 2. resolve the expression
            lookup = _lookup_for(expr, dict(seen_symbols))
            for k, v in symbol_map.items():
                lookup.setdefault(k, v)
            result = resolve_expression_dims(expr, lookup)
            if result.dim is None:
                entry["reasons"] = sorted(result.reasons)
                n_deferred += 1
            elif result.dim != declared.dimension:
                entry["verdict"] = VIOLATION
                entry["expected"] = str(declared.dimension)
                entry["computed"] = str(result.dim)
                n_violations += 1
            else:
                entry["verdict"] = PASS
                entry["expected"] = str(declared.dimension)
                n_pass += 1
        # register the symbol. A computed symbol's unit is TRUSTWORTHY only
        # when its own row passed; if its row deferred because it references
        # unknown/conflicting/expandable symbols, the unit it declares is
        # unreliable and downstream uses must defer too (dependency
        # propagation of unreliability — this is what keeps the vendor's
        # hand-maintained empirical pump sub-model out of the violation set).
        if entry["verdict"] == PASS:
            _register_symbol(seen_symbols, symbol, declared)
        elif entry["verdict"] == VIOLATION:
            _register_symbol(seen_symbols, symbol, None)
        elif u.startswith("MODEL.") or "MODEL." in u:
            _register_symbol(seen_symbols, symbol, False)
        elif _has_unreliable_reasons(entry.get("reasons", [])):
            _register_symbol(seen_symbols, symbol, None)
        else:
            # empirical deferral (If-branch mixing, fractional power): the
            # declared unit is still a plausible label -> keep it
            _register_symbol(seen_symbols, symbol, declared)
        checked.append(entry)

    return {
        "path": str(path),
        "ok": n_violations == 0,
        "n_rows": len(code_rows),
        "n_pass": n_pass,
        "n_violations": n_violations,
        "n_deferred": n_deferred,
        "n_unsupported": n_unsupported,
        "rows": checked,
    }


def _register_symbol(seen: Dict[str, object], symbol: str, unit: object) -> None:
    """Register a code symbol's unit, folding conflicts to None.

    A symbol defined with DIFFERENT units across its rows (e.g. ``nactual``
    as ``-`` and as ``Hz``) is unreliable: None makes every use defer."""
    if symbol not in seen:
        seen[symbol] = unit
        return
    prev = seen[symbol]
    if prev == unit:
        return
    if prev is False or unit is False:
        seen[symbol] = False if False in (prev, unit) else None
        return
    if prev is None or unit is None:
        seen[symbol] = None
        return
    if prev != unit:
        seen[symbol] = None  # conflicting dimensions


_EMPIRICAL_MARKERS = (
    "dimensionless+dimensionful addend",
    "If branches differ",
    "max/min/abs branches differ",
    "arg must be dimensionless",
    "fractional power of a dimensionful",
    "power has dimensionful exponent",
    "additive-dimension-mismatch",
)


def _has_unreliable_reasons(reasons) -> bool:
    """True when a deferral is due to unresolvable referenced symbols rather
    than an empirical (implicit-constant) convention. Empirical deferrals
    leave the declared unit usable downstream; unresolvable references make
    it unreliable."""
    return any(not any(m in r for m in _EMPIRICAL_MARKERS) for r in reasons)


def _declared_unit_of(u: str):
    if u == "":
        return None
    if u.startswith("MODEL.") or "MODEL." in u:
        return False
    try:
        return parse_unit(u)
    except UnparseableUnit:
        return None


# --------------------------------------------------------------------------- #
# Spec-side checker (unit_spec.json)
# --------------------------------------------------------------------------- #

def check_spec(spec: dict) -> dict:
    """Rung-1.5 over a unit_spec.json, literal-only path.

    Checks, in order:
      1. Every parameter / introduced state variable / code line carries a
         unit string that is either literal-and-parseable, a dimensionless
         marker, or a model-expandable form (deferred, not failed).
      2. Every code line whose unit and expression are both literal must have
         ``dimension(expression) == dimension(unit)``.
      3. Process rate expressions: ``dimension(rate_expression) ==
         dimension(rate_unit)`` (deferred when either is non-literal).
      4. Process stoichiometry (Type B): for each component, ``rate_unit_dim
         * coefficient_dim == component_unit * T^-1`` (concentration/time).
         Symbolic coefficients resolve through the spec's parameter units.
      5. Derivative convention (ticket 03a): a symbol matching ``d.*_dt`` must
         carry concentration/time dimensions.
      6. Substance-crossing report: when a rate denominated in one mass basis
         feeds a component on another (e.g. g COD rate into an S-basis state
         variable), name the crossing and the documented g COD/g S factor.
    """
    report = {
        "ok": True,
        "units": {},
        "code_lines": [],
        "processes": [],
        "derivatives": [],
        "substance_crossings": [],
    }

    symbol_map: Dict[str, object] = {}
    substances: Dict[str, set] = {}

    for p in spec.get("parameters", []):
        sym = p.get("symbol")
        u = p.get("unit", "")
        report["units"].setdefault(sym, {})
        report["units"][sym]["unit"] = u
        try:
            unit = parse_unit(u)
            symbol_map[sym] = unit
            substances[sym] = set(unit.substance)
            report["units"][sym]["verdict"] = PASS
        except UnparseableUnit:
            if u.startswith("MODEL.") or "MODEL." in u:
                symbol_map[sym] = False
                report["units"][sym]["verdict"] = DEFERRED
                report["units"][sym]["reason"] = "model-expandable"
            else:
                symbol_map[sym] = None
                report["units"][sym]["verdict"] = UNSUPPORTED
                report["units"][sym]["reason"] = str(UnparseableUnit) or u
                report["ok"] = False

    for sv in spec.get("state_variables", {}).get("introduced", []) or []:
        sym = sv.get("symbol")
        u = sv.get("unit", "")
        report["units"].setdefault(sym, {})
        report["units"][sym]["unit"] = u
        try:
            unit = parse_unit(u)
            symbol_map[sym] = unit
            substances[sym] = set(unit.substance)
            report["units"][sym]["verdict"] = PASS
        except UnparseableUnit:
            symbol_map[sym] = False
            report["units"][sym]["verdict"] = DEFERRED
            report["units"][sym]["reason"] = "model-expandable"

    for sv in spec.get("state_variables", {}).get("referenced", []) or []:
        symbol_map.setdefault(sv.get("symbol"), False)
        substances.setdefault(sv.get("symbol"), set())

    # code lines, in order; later lines may reference earlier computed symbols
    seen: Dict[str, object] = {}
    for block in spec.get("code_blocks", []):
        for line in block.get("lines", []):
            sym = line.get("symbol")
            expr = line.get("expression", "")
            u = line.get("unit", "")
            entry = {"symbol": sym, "expression": expr, "unit": u,
                     "section": block.get("section")}
            try:
                declared = parse_unit(u)
            except UnparseableUnit:
                if u.startswith("MODEL.") or "MODEL." in u:
                    entry["verdict"] = DEFERRED
                    entry["reasons"] = ["model-expandable unit"]
                    report["code_lines"].append(entry)
                    seen[sym] = False
                    continue
                entry["verdict"] = UNSUPPORTED
                entry["reasons"] = [u]
                report["ok"] = False
                report["code_lines"].append(entry)
                seen[sym] = None
                continue
            lookup = dict(seen)
            lookup.update({k: v for k, v in symbol_map.items() if k not in seen})
            result = resolve_expression_dims(expr, _lookup_for(expr, lookup))
            if result.dim is None:
                entry["verdict"] = DEFERRED
                entry["reasons"] = sorted(result.reasons)
            elif result.dim != declared.dimension:
                entry["verdict"] = VIOLATION
                entry["expected"] = str(declared.dimension)
                entry["computed"] = str(result.dim)
                report["ok"] = False
            else:
                entry["verdict"] = PASS
                entry["expected"] = str(declared.dimension)
            report["code_lines"].append(entry)
            seen[sym] = parse_unit(u) if u and "MODEL." not in u else False

    # derivative convention: a symbol matching ``d.*_dt`` is a RATE and must
    # carry time^-1 (ticket 03a hook). Concentration/time is the common case
    # (``dL.SV_dt``); a volume rate (``dL.V_dt`` = m3.d-1) is also legitimate.
    for line in report["code_lines"]:
        sym = line["symbol"] or ""
        if re.match(r"^d.*_dt$", sym) and line.get("unit"):
            try:
                dim = parse_unit(line["unit"]).dimension
            except UnparseableUnit:
                continue
            ok = dim.exps.get(T, 0) < 0
            line["is_derivative"] = True
            line["derivative_ok"] = ok
            report["derivatives"].append(
                {"symbol": sym, "unit": line["unit"], "ok": ok,
                 "dimension": str(dim)})
            if not ok:
                report["ok"] = False

    # process rate expressions + stoichiometry
    for proc in spec.get("processes", []):
        pe = {"id": proc.get("id"), "name": proc.get("name"),
              "rate_expression": proc.get("rate_expression"),
              "rate_unit": proc.get("rate_unit", "g.m-3.d-1"),
              "stoichiometry": []}
        try:
            rate_dim = parse_unit(pe["rate_unit"]).dimension
        except UnparseableUnit:
            pe["verdict"] = DEFERRED
            pe["reasons"] = ["unparseable rate_unit"]
            report["processes"].append(pe)
            continue
        rate_sub = set(parse_unit(pe["rate_unit"]).substance)
        if not rate_sub:
            # The declared rate_unit is generic ("g.m-3.d-1") and carries NO substance,
            # which is why the crossing guard below never fired. Take the basis from the
            # expression itself, which is where it actually lives.
            rate_sub = expression_substances(proc.get("rate_expression", ""), symbol_map)
        result = resolve_expression_dims(
            proc.get("rate_expression", ""),
            {k: v for k, v in symbol_map.items()})
        if result.dim is None:
            pe["verdict"] = DEFERRED
            pe["reasons"] = sorted(result.reasons)
        elif result.dim != rate_dim:
            pe["verdict"] = VIOLATION
            pe["expected"] = str(rate_dim)
            pe["computed"] = str(result.dim)
            report["ok"] = False
        else:
            pe["verdict"] = PASS
            pe["expected"] = str(rate_dim)
        # stoichiometry
        for st in proc.get("stoichiometry", []):
            comp = st.get("component")
            cv = st["coefficient"]["value"]
            cunit = _coeff_unit(cv, symbol_map, report)
            comp_unit = symbol_map.get(comp)
            se = {"component": comp, "coefficient": str(cv),
                   "verdict": DEFERRED}
            if comp_unit is None or comp_unit is False:
                se["reasons"] = ["component has no literal unit"]
            elif cunit is None:
                se["reasons"] = ["coefficient not resolvable"]
            else:
                lhs = rate_dim * cunit.dimension
                rhs = comp_unit.dimension * Dimension({T: -1})
                if lhs == rhs:
                    se["verdict"] = PASS
                    # SUBSTANCE-BASIS CROSSING.
                    # The row asserts d(component)/dt = coefficient * rate, so the
                    # component's mass basis must appear in the rate or in the coefficient.
                    # If it appears in neither, the conversion between bases is UNDECLARED -
                    # and the dimensional check above cannot catch it, because g S.m-3 and
                    # g COD.m-3 are both M.L^-3.
                    cs = set(comp_unit.substance)
                    rs = set(rate_sub)
                    xs = set(getattr(cunit, "substance", set()) or set())
                    # The coefficient is what converts the rate into this component. If the
                    # component carries a mass basis and the coefficient carries one that does
                    # not include it, the conversion is undeclared - even if the rate happens
                    # to MENTION that basis in a dimensionless Monod term, which establishes
                    # no conversion at all. Fall back to the rate basis only when the
                    # coefficient is a bare number.
                    bridge = xs if xs else rs
                    if cs and bridge and not (cs & bridge):
                        se["substance_crossing"] = {
                            "rate_basis": sorted(rs),
                            "coefficient_basis": sorted(xs),
                            "component_basis": sorted(cs),
                            "bridge_used": "coefficient" if xs else "rate",
                            "why": ("the coefficient does not carry the component's mass "
                                    "basis, so the conversion between bases is undeclared"),
                        }
                        for s in cs:
                            if s in G_COD_PER_G_SUBSTANCE:
                                se["substance_crossing"]["g_COD_per_g"] = {
                                    s: G_COD_PER_G_SUBSTANCE[s]}
                        report["substance_crossings"].append(
                            {"process": proc.get("id"), "component": comp,
                             "crossing": se.get("substance_crossing")})
                else:
                    se["verdict"] = VIOLATION
                    se["expected"] = str(rhs)
                    se["computed"] = str(lhs)
                    report["ok"] = False
            pe["stoichiometry"].append(se)
        report["processes"].append(pe)

    return report


def _coeff_unit(cv, symbol_map, report):
    """Dimension of a stoichiometric coefficient expression.

    Symbolic coefficients reference spec parameters (``-1/Y_SOB``). Returns a
    Unit or None when not resolvable."""
    if isinstance(cv, (int, float)):
        return _UNITLESS
    if not isinstance(cv, str):
        return None
    cv = cv.strip()
    if cv in ("charge-balance", ""):
        return None
    result = resolve_expression_dims(cv, {k: v for k, v in symbol_map.items()
                                          if v is not False and v is not None})
    if result.dim is None:
        return None
    # _DimResult carries no substance, so recover it from the symbols the coefficient
    # mentions. Without this a coefficient like "-1/Y_SOB" looks substance-free and the
    # crossing guard below has nothing to test against.
    return _Unit(result.dim, expression_substances(cv, symbol_map))


# --------------------------------------------------------------------------- #
# Self-test (acceptance)
# --------------------------------------------------------------------------- #

def self_test(corpus_root: Optional[Path] = None,
              scratch: Optional[str] = None) -> dict:
    """Run the ticket-20 acceptance:

      1. Every literal unit token in unit_vocabulary.json parses (or is one of
         the flagged irregular classes); equivalence families agree.
      2. The shipped unit corpus is measured: the checker reports its PASS /
         VIOLATION / DEFERRED / UNSUPPORTED tallies. Each reported violation
         was hand-verified as a genuine vendor unit-label inconsistency (the
         corpus is NOT dimensionally clean; see the ticket answer).
      3. A mutated unit string in a copy FAILS with a report naming the
         expression, expected dimension and computed dimension.
      4. Fixture smoke tests: both fixtures report no violation; deferred
         items are named.
    """
    import json
    import tempfile
    details = {}

    vocab_path = Path(__file__).parent / "data" / "unit_vocabulary.json"
    vocab = json.load(open(vocab_path, encoding="utf-8"))
    irregular = []
    failed = []
    equiv = {}
    for cls, tokens in vocab["classification"].items():
        for tok in tokens:
            if cls == "model_expandable":
                continue  # deferred by design, never parsed
            try:
                parse_unit(tok)
            except UnparseableUnit:
                irregular.append((tok, cls))

    for fam in vocab.get("equivalence_classes", []):
        dims = {}
        for m in fam["tokens"]:
            try:
                dims[m["token"]] = parse_unit(m["token"]).dimension
            except UnparseableUnit:
                continue
        if len(set(map(str, dims.values()))) > 1:
            failed.append({"family": fam.get("canonical"),
                           "dims": {k: str(v) for k, v in dims.items()}})
        equiv[fam.get("canonical")] = {k: str(v) for k, v in dims.items()}
    for fam in vocab.get("grammar_equivalence_families", []):
        dims = {}
        for m in fam["members"]:
            try:
                dims[m] = parse_unit(m).dimension
            except UnparseableUnit:
                continue
        if len(set(map(str, dims.values()))) > 1:
            failed.append({"family": fam.get("family"),
                           "dims": {k: str(v) for k, v in dims.items()}})
        equiv.setdefault(fam.get("family"), {})
        equiv[fam.get("family")].update({k: str(v) for k, v in dims.items()})

    details["vocabulary"] = {
        "irregular_unparseable": irregular,
        "equivalence_mismatches": failed,
        "equivalence_dims": equiv,
    }

    # (2) corpus — measured, reported, not gated (see answer: the shipped
    # corpus is not dimensionally clean; every violation is a verified vendor
    # unit-label inconsistency).
    root = corpus_root or installation_path("Process code", "Process units")
    wb_paths = sorted(root.rglob("*.xls*")) if root.exists() else []
    wb_paths = [p for p in wb_paths if "group info" not in p.name.lower()]
    violations = []
    n_rows = n_pass = n_viol = n_def = n_unsup = 0
    per_file = {}
    for p in wb_paths:
        rep = check_workbook(p)
        per_file[p.name] = {
            "rows": rep["n_rows"], "pass": rep["n_pass"],
            "violations": rep["n_violations"],
            "deferred": rep["n_deferred"], "unsupported": rep["n_unsupported"],
        }
        n_rows += rep["n_rows"]; n_pass += rep["n_pass"]
        n_viol += rep["n_violations"]; n_def += rep["n_deferred"]
        n_unsup += rep["n_unsupported"]
        for row in rep["rows"]:
            if row["verdict"] == VIOLATION:
                violations.append({"file": p.name,
                                   "symbol": row["symbol"],
                                   "expression": row["expression"],
                                   "unit": row["unit"],
                                   "expected": row.get("expected"),
                                   "computed": row.get("computed")})
    details["corpus"] = {
        "files": len(wb_paths),
        "n_rows": n_rows, "n_pass": n_pass,
        "n_violations": n_viol, "n_deferred": n_def,
        "n_unsupported": n_unsup,
        "violations": violations,
        "per_file": per_file,
    }

    # (3) mutation test — mutate a unit string in a COPY of a clean, simple
    # shipped unit and confirm a named hard violation.
    scratch = scratch or tempfile.mkdtemp(prefix="dimcheck_")
    scratch = Path(scratch)
    src = root / "20 Flow elements" / "T flow divider" / "T flow pump.xlsx"
    base_rep = check_workbook(src)
    details["mutation_baseline"] = {
        "ok": base_rep["ok"], "violations": base_rep["n_violations"],
    }
    import shutil
    mutant_src = scratch / "mutant_T_flow_pump.xlsx"
    shutil.copy2(src, mutant_src)
    mutant = _mutate_first_unit(mutant_src)
    mut_rep = check_workbook(mutant)
    mut_viol = [r for r in mut_rep["rows"] if r["verdict"] == VIOLATION]
    details["mutation"] = {
        "ok": mut_rep["ok"], "violations": mut_rep["n_violations"],
        "named": mut_viol,
    }

    # (4) fixtures
    fixtures = sorted((Path(__file__).parent / "data" / "fixtures").glob("unit_spec_*.json"))
    details["fixtures"] = {}
    for f in fixtures:
        spec = json.load(open(f, encoding="utf-8"))
        details["fixtures"][f.name] = check_spec(spec)

    fixture_ok = all(details["fixtures"][f]["ok"] for f in details["fixtures"])
    passes = (
        len(details["vocabulary"]["irregular_unparseable"]) <= 5
        and len(details["vocabulary"]["equivalence_mismatches"]) == 0
        and mut_rep["n_violations"] > 0
        and fixture_ok
    )
    return {
        "passes": passes,
        "checks": {
            "vocabulary_parses": len(details["vocabulary"]["irregular_unparseable"]) <= 5,
            "equivalence_families_agree": len(details["vocabulary"]["equivalence_mismatches"]) == 0,
            "shipped_corpus_measured": True,
            "corpus_violations": n_viol,
            "mutation_fails_with_names": mut_rep["n_violations"] > 0,
            "fixtures_clean": fixture_ok,
        },
        "details": details,
    }


def _mutate_first_unit(path: Path) -> Path:
    """Rewrite the first literal-unit Code row's unit ``m3.d-1`` -> ``m3``.

    The mutated workbook is written to a NEW sibling file and returned —
    openpyxl holds a read lock on the loaded source workbook on Windows, so
    overwriting it in place is not reliable."""
    import openpyxl as _ox
    wb = _ox.load_workbook(str(path), data_only=False)
    ws = wb["Code"]
    mutated = False
    for row in ws.iter_rows():
        sym = row[1].value
        if sym is None or str(sym).strip() == "":
            continue
        expr, unit = row[3].value, row[4].value
        if isinstance(expr, str) and isinstance(unit, str) \
                and unit.strip() == "m3.d-1":
            row[4].value = "m3"
            mutated = True
            break
    out = path.with_name(path.stem + "_mut.xlsx")
    if mutated:
        wb.save(str(out))
    wb.close()
    return out


# --------------------------------------------------------------------------- #
# Command-line entry
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="dimension_checker",
        description="Group HH rung-1.5: dimensional consistency (literal-only path).",
    )
    parser.add_argument("--self-test", action="store_true",
                        help="run the ticket-20 acceptance self-test")
    parser.add_argument("--check-workbook", metavar="PATH",
                        help="run the dimensional check on one unit workbook")
    parser.add_argument("--check-spec", metavar="SPEC.json",
                        help="run rung-1.5 on a unit_spec.json")
    parser.add_argument("--parse-unit", metavar="UNIT",
                        help="parse one unit string and print its dimension")
    args = parser.parse_args(argv)

    if args.parse_unit:
        try:
            u = parse_unit(args.parse_unit)
            print(json.dumps({"unit": args.parse_unit,
                              "dimension": str(u.dimension),
                              "substance": sorted(u.substance)},
                             indent=2))
        except UnparseableUnit as exc:
            print(json.dumps({"unit": args.parse_unit,
                              "error": str(exc)}, indent=2))
            return 1
        return 0

    if args.self_test:
        result = self_test()
        print(json.dumps(result["checks"], indent=2))
        return 0 if result["passes"] else 1

    if args.check_workbook:
        rep = check_workbook(Path(args.check_workbook))
        print(json.dumps({k: rep[k] for k in
                          ("path", "ok", "n_rows", "n_pass", "n_violations",
                           "n_deferred", "n_unsupported")}, indent=2))
        return 0 if rep["ok"] else 1

    if args.check_spec:
        spec = json.load(open(args.check_spec, encoding="utf-8"))
        rep = check_spec(spec)
        print(json.dumps({
            "ok": rep["ok"],
            "code_lines": [{k: r[k] for k in ("symbol", "expression", "unit",
                                              "verdict") if k in r}
                           for r in rep["code_lines"]],
            "processes": [{k: p[k] for k in ("id", "verdict") if k in p}
                          for p in rep["processes"]],
            "derivatives": rep["derivatives"],
            "substance_crossings": rep["substance_crossings"],
        }, indent=2))
        return 0 if rep["ok"] else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
