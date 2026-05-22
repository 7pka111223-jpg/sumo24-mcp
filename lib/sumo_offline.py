"""
sumo_offline.py — offline reader for SUMO24 .sumo project archives.

A .sumo file is a ZIP container. When the SUMO24 GUI / DTT is not running,
the MCP server's live-DTT inspection tools (get_state_variable, etc.) fail
with "'SumoScheduler' object has no attribute 'get'" or similar. This module
provides a pure-Python fallback that reads everything useful directly from
the zip:

    - parameters.txt           (constant inputs + dynamic input table list)
    - laststeadyrun.ss         (steady-state result snapshot)
    - lastdynamicrun.ss        (last-time-step dynamic result snapshot)
    - Influent*_Table*.tsv     (dynamic influent profiles)
    - sumoproject.dll          (presence + size, for completeness)

Public API:

    parse_ss_xml(xml_text)         -> {symbol: value or list}
    read_ss_member(sumo_path, name)-> {symbol: ...}     (zip member name)
    read_parameters_txt(text)      -> {symbol: float}   (constant inputs)
    read_influent_tsv(text)        -> list of dict rows  (col0=time_ms)
    influent_stats(rows, col)      -> {n, mean, min, max, p05, p50, p95}
    extract_sumo_data(sumo_path)   -> rich offline bundle (see docstring)

Designed to be cheap to import: no openpyxl / matplotlib / docx pulled in.
Reuses the regex from sumo_native._PARAM_LINE_RE for compatibility.
"""

from __future__ import annotations

import io
import re
import statistics
import zipfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union


# ─── parameters.txt ──────────────────────────────────────────────────────────

# Same shape as sumo_native._PARAM_LINE_RE but tolerant of array suffixes.
_PARAM_LINE_RE = re.compile(
    r"^(?P<sym>Sumo__Plant__[A-Za-z0-9_]+__param__[A-Za-z0-9_\[\]]+)"
    r"\t(?P<val>[^\t\r\n]*)"
)

# Section markers in parameters.txt
_CONSTANT_HDR = "[CONSTANT INPUT]"
_DYNAMIC_HDR  = "[DYNAMIC INPUT]"


def read_parameters_txt(text: str) -> Dict[str, Any]:
    """Parse the parameters.txt file body. Returns:

        {
          "constant": {symbol: float_or_str},
          "dynamic":  [{"table": name, "interpolation": str, "extra": str}, ...]
        }
    """
    constant: Dict[str, Any] = {}
    dynamic: List[Dict[str, str]] = []
    section = None
    for line in text.splitlines():
        s = line.strip()
        if s == _CONSTANT_HDR:
            section = "constant"; continue
        if s == _DYNAMIC_HDR:
            section = "dynamic"; continue
        if not s or s.startswith("Full Symbol"):
            continue
        if section == "constant":
            m = _PARAM_LINE_RE.match(line)
            if m:
                raw = m.group("val").strip()
                try:
                    constant[m.group("sym")] = float(raw)
                except ValueError:
                    constant[m.group("sym")] = raw
        elif section == "dynamic":
            parts = line.split("\t")
            if parts and parts[0].endswith(".tsv"):
                dynamic.append({
                    "table":         parts[0].strip(),
                    "interpolation": parts[1].strip() if len(parts) > 1 else "",
                    "extra":         parts[2].strip() if len(parts) > 2 else "",
                })
    return {"constant": constant, "dynamic": dynamic}


# ─── .ss XML ────────────────────────────────────────────────────────────────

def parse_ss_xml(xml_text: str) -> Dict[str, Any]:
    """Parse a SUMO24 .ss XML file body and return {symbol: value}.

    * <real symbol="X"><value>v</value></real>            -> X: float
    * <realarray symbol="X" sizes="N"><value>v1;v2;...</value></realarray>
                                                           -> X: [float, ...]
    Returns an empty dict on parse failure rather than raising — callers
    typically prefer "no data" over "crashed".
    """
    out: Dict[str, Any] = {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for el in root.iter():
        sym = el.get("symbol")
        if not sym:
            continue
        val_el = el.find("value")
        if val_el is None or val_el.text is None:
            continue
        raw = val_el.text.strip()
        if not raw:
            continue
        tag = el.tag.lower()
        if "array" in tag and ";" in raw:
            parts = raw.split(";")
            try:
                out[sym] = [float(p) for p in parts]
            except ValueError:
                out[sym] = parts
        else:
            try:
                out[sym] = float(raw)
            except ValueError:
                out[sym] = raw
    return out


# ─── influent TSV ───────────────────────────────────────────────────────────

def read_influent_tsv(text: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Parse a SUMO24 dynamic-input TSV (Influent*_Table*.tsv).

    Returns (headers, rows) where headers[0] is the time column ("t (ms)"
    in practice) and each row is a dict {header: float_or_None}. The token
    "?" used by SUMO for "no value at this time step" becomes None.
    """
    lines = text.splitlines()
    if not lines:
        return [], []
    headers = [h.strip() for h in lines[0].split("\t")]
    rows: List[Dict[str, Any]] = []
    for line in lines[1:]:
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        rec: Dict[str, Any] = {}
        for i, h in enumerate(headers):
            v = parts[i].strip() if i < len(parts) else ""
            if v in ("", "?"):
                rec[h] = None
            else:
                try:
                    rec[h] = float(v)
                except ValueError:
                    rec[h] = v
        rows.append(rec)
    return headers, rows


def influent_stats(rows: Iterable[Dict[str, Any]], column: str) -> Dict[str, Any]:
    """Summary statistics for one column across the time series."""
    vals = [r.get(column) for r in rows if r.get(column) is not None]
    vals = [float(v) for v in vals if isinstance(v, (int, float))]
    if not vals:
        return {"n": 0}
    vals_sorted = sorted(vals)
    n = len(vals_sorted)
    def pct(p: float) -> float:
        if n == 1:
            return vals_sorted[0]
        k = (n - 1) * p
        f, c = int(k), min(int(k) + 1, n - 1)
        return vals_sorted[f] + (vals_sorted[c] - vals_sorted[f]) * (k - f)
    return {
        "n":     n,
        "mean":  statistics.fmean(vals_sorted),
        "min":   vals_sorted[0],
        "max":   vals_sorted[-1],
        "p05":   pct(0.05),
        "p50":   pct(0.50),
        "p95":   pct(0.95),
        "std":   statistics.pstdev(vals_sorted) if n > 1 else 0.0,
    }


# ─── ZIP-aware readers ──────────────────────────────────────────────────────

def _read_member(sumo_path: Path, name: str) -> Optional[str]:
    if not zipfile.is_zipfile(sumo_path):
        return None
    with zipfile.ZipFile(sumo_path, "r") as zf:
        if name not in zf.namelist():
            return None
        return zf.read(name).decode("utf-8", errors="replace")


def read_ss_member(sumo_path: Union[str, Path], name: str) -> Dict[str, Any]:
    """Convenience: read & parse a .ss member directly from a .sumo zip."""
    text = _read_member(Path(sumo_path), name)
    return parse_ss_xml(text) if text else {}


@lru_cache(maxsize=8)
def _read_ss_cached(sumo_path: str, name: str, mtime_ns: int) -> Dict[str, Any]:
    """Cache .ss reads — keyed on path + member + mtime so the cache
    invalidates whenever the .sumo file is replaced."""
    return read_ss_member(sumo_path, name)


def read_ss_cached(sumo_path: Union[str, Path], name: str) -> Dict[str, Any]:
    """Public cached wrapper for read_ss_member; safe to call repeatedly."""
    p = Path(sumo_path)
    try:
        mt = p.stat().st_mtime_ns
    except OSError:
        return {}
    return _read_ss_cached(str(p), name, mt)


# ─── one-shot extractor ─────────────────────────────────────────────────────

# Sumo2 / ASM-family individually-tracked biomass component symbols.
# (These are stored in the .ss file; XTSS / XVSS are derived — see below.)
_BIOMASS_SYMBOLS = [
    "XOHO", "XAOB", "XNOB", "XPAO", "XAMX", "XACP", "XAMETO",
    "XALGAE", "XB", "XB_e", "XE", "XU", "XINORG", "XPP",
]

# Effluent / clarifier-overflow tracked species. Dissolved species (S*) are
# uniform across all clarifier layers, so layer index 0 is representative
# for them too.
_EFFLUENT_DISSOLVED = ["SNHx", "SNO2", "SNO3", "SPO4", "SO2", "SU", "SB"]
_EFFLUENT_PARTICULATE = ["XOHO", "XAOB", "XNOB", "XPAO",
                          "XE", "XU", "XINORG", "XB", "XB_e"]


def _is_solids_symbol(local_name: str) -> bool:
    """True if a Sumo X* symbol counts as a solid for the XTSS sum.

    Excludes:
      - XN_* / XP_*       (nitrogen/phosphorus content tracers within biomass)
      - anything ending _old (previous-time-step memory cells)
    Anything else starting with X is treated as a solid contributor.
    """
    if not local_name.startswith("X"):
        return False
    if local_name.startswith(("XN_", "XP_")):
        return False
    if local_name.endswith("_old"):
        return False
    return True


def _is_volatile_solids_symbol(local_name: str) -> bool:
    """True if a Sumo X* symbol counts as a VOLATILE solid (excludes XINORG)."""
    return _is_solids_symbol(local_name) and local_name != "XINORG"


def _unit_solids_sum(ss: Dict[str, Any], unit: str, layer_idx: int = 0,
                     volatile_only: bool = False) -> Optional[float]:
    """Sum of particulate components for one unit at one clarifier layer
    (defaults to layer 0 = top / overflow for clarifiers; CSTRs are zero-D)."""
    prefix = f"Sumo__Plant__{unit}__"
    total = 0.0
    seen = False
    for sym, val in ss.items():
        if not sym.startswith(prefix):
            continue
        local = sym[len(prefix):]
        if volatile_only:
            if not _is_volatile_solids_symbol(local):
                continue
        else:
            if not _is_solids_symbol(local):
                continue
        if isinstance(val, list):
            if layer_idx < len(val):
                total += val[layer_idx]
                seen = True
        elif isinstance(val, (int, float)):
            total += val
            seen = True
    return total if seen else None


def _layer0(value: Any) -> Optional[float]:
    """Return the first element of a layered array (overflow / top), or the
    value itself if it's already a scalar."""
    if isinstance(value, list) and value:
        try:
            return float(value[0])
        except (TypeError, ValueError):
            return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _avg(values: Iterable[Optional[float]]) -> Optional[float]:
    vs = [v for v in values if v is not None]
    return sum(vs) / len(vs) if vs else None


def _extract_effluent(ss: Dict[str, Any], clarifier_unit: str) -> Dict[str, Optional[float]]:
    """Pull all tracked effluent species from one clarifier unit name.
    Layer 0 = overflow (effluent) in SUMO's 1D layered Clarifier3.

    XTSS / XVSS are derived (sum of particulates at layer 0); they are not
    state variables in the .ss file.
    """
    eff: Dict[str, Optional[float]] = {}
    for sp in _EFFLUENT_DISSOLVED + _EFFLUENT_PARTICULATE:
        sym = f"Sumo__Plant__{clarifier_unit}__{sp}"
        eff[sp] = _layer0(ss.get(sym))
    eff["XTSS"] = _unit_solids_sum(ss, clarifier_unit, layer_idx=0,
                                    volatile_only=False)
    eff["XVSS"] = _unit_solids_sum(ss, clarifier_unit, layer_idx=0,
                                    volatile_only=True)
    return eff


def _list_clarifier_units(constant_params: Dict[str, Any]) -> List[str]:
    """Find every unit name that has an Atank_train param — these are the
    clarifiers in the plant."""
    out = set()
    for sym in constant_params.keys():
        m = re.match(r"^Sumo__Plant__([A-Za-z0-9_]+)__param__Atank_train$", sym)
        if m:
            out.add(m.group(1))
    return sorted(out)


def _list_cstr_units(constant_params: Dict[str, Any]) -> List[str]:
    """Find every CSTR-like unit name (has L_Vtrain param)."""
    out = set()
    for sym in constant_params.keys():
        m = re.match(r"^Sumo__Plant__([A-Za-z0-9_]+)__param__L_Vtrain$", sym)
        if m:
            out.add(m.group(1))
    return sorted(out)


def extract_sumo_data(sumo_path: Union[str, Path]) -> Dict[str, Any]:
    """One-shot offline extraction of a .sumo project archive.

    Returns a structured bundle covering every number an academic report
    typically needs: design parameters, dynamic influent stats, steady-state
    and dynamic-final effluent quality, bioreactor MLSS/DO per zone, biomass
    composition. Safe to call without SUMO24 GUI / DTT running.

    On a non-.sumo or missing file returns {"ok": False, "error": ...}.
    """
    p = Path(sumo_path)
    if not p.exists():
        return {"ok": False, "error": f"not found: {p}"}
    if not zipfile.is_zipfile(p):
        return {"ok": False, "error": f"not a zip container: {p}"}

    members: List[str] = []
    with zipfile.ZipFile(p, "r") as zf:
        members = zf.namelist()

    # parameters.txt
    params_text = _read_member(p, "parameters.txt") or ""
    parsed_params = read_parameters_txt(params_text)
    constant = parsed_params["constant"]
    dynamic_list = parsed_params["dynamic"]

    # influent design (the constant-input view)
    influent_design: Dict[str, float] = {}
    for sym, val in constant.items():
        m = re.match(r"^Sumo__Plant__(Influent\d+)__param__(.+)$", sym)
        if m and isinstance(val, (int, float)):
            influent_design[f"{m.group(1)}.{m.group(2)}"] = val

    # dynamic influent statistics
    influent_dynamic: Dict[str, Any] = {}
    for tsv_name in [m for m in members if re.match(r"^Influent\d+_\d+_Table\d+\.tsv$", m)]:
        text = _read_member(p, tsv_name) or ""
        headers, rows = read_influent_tsv(text)
        col_stats = {}
        for h in headers[1:]:
            s = influent_stats(rows, h)
            if s.get("n"):
                col_stats[h] = s
        influent_dynamic[tsv_name] = {
            "row_count": len(rows),
            "headers":   headers,
            "stats":     col_stats,
        }

    # steady & dynamic .ss snapshots
    ss_steady  = read_ss_cached(p, "laststeadyrun.ss")
    ss_dynamic = read_ss_cached(p, "lastdynamicrun.ss")

    # clarifier units → effluent
    clarifiers = _list_clarifier_units(constant)
    effluent_ss: Dict[str, Dict[str, Optional[float]]] = {}
    effluent_dyn: Dict[str, Dict[str, Optional[float]]] = {}
    for c in clarifiers:
        effluent_ss[c]  = _extract_effluent(ss_steady,  c)
        effluent_dyn[c] = _extract_effluent(ss_dynamic, c)

    # bioreactor zones (CSTRs)
    cstrs = _list_cstr_units(constant)
    bioreactor: Dict[str, Dict[str, Any]] = {}
    for c in cstrs:
        sym_do = f"Sumo__Plant__{c}__SO2"
        sym_v  = f"Sumo__Plant__{c}__param__L_Vtrain"
        bioreactor[c] = {
            "L_Vtrain":  constant.get(sym_v),
            "MLSS_ss":   _unit_solids_sum(ss_steady,  c, layer_idx=0,
                                          volatile_only=False),
            "MLSS_dyn":  _unit_solids_sum(ss_dynamic, c, layer_idx=0,
                                          volatile_only=False),
            "MLVSS_ss":  _unit_solids_sum(ss_steady,  c, layer_idx=0,
                                          volatile_only=True),
            "MLVSS_dyn": _unit_solids_sum(ss_dynamic, c, layer_idx=0,
                                          volatile_only=True),
            "DO_ss":     _layer0(ss_steady.get(sym_do)),
            "DO_dyn":    _layer0(ss_dynamic.get(sym_do)),
        }

    # biomass composition — averaged across all CSTR zones in steady state
    biomass: Dict[str, Optional[float]] = {}
    for sp in _BIOMASS_SYMBOLS:
        vals = []
        for c in cstrs:
            v = _layer0(ss_steady.get(f"Sumo__Plant__{c}__{sp}"))
            if v is not None:
                vals.append(v)
        biomass[sp] = _avg(vals)
    # derived aggregates (sum of solids, sum of volatile solids)
    biomass["XTSS"] = _avg([_unit_solids_sum(ss_steady, c, 0, False)
                             for c in cstrs])
    biomass["XVSS"] = _avg([_unit_solids_sum(ss_steady, c, 0, True)
                             for c in cstrs])

    return {
        "ok":                  True,
        "sumo_path":           str(p),
        "members":             members,
        "member_count":        len(members),
        "dll_present_in_zip":  "sumoproject.dll" in members,
        "has_steady":          bool(ss_steady),
        "has_dynamic":         bool(ss_dynamic),
        "ss_symbol_count":     len(ss_steady),
        "dyn_symbol_count":    len(ss_dynamic),
        "parameters":          constant,
        "dynamic_input_tables": dynamic_list,
        "influent_design":     influent_design,
        "influent_dynamic":    influent_dynamic,
        "clarifier_units":     clarifiers,
        "cstr_units":          cstrs,
        "bioreactor":          bioreactor,
        "biomass":             biomass,
        "effluent": {
            "steady_state":   effluent_ss,
            "dynamic_final":  effluent_dyn,
        },
    }
