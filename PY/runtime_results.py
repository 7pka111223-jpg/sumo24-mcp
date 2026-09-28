"""Model-aware observations and conservative checks, independent of native SUMO."""
import math
import re
from pathlib import Path

DAY = 86_400_000
HOUR = 3_600_000
METRICS = {"XTSS": "TSS_mgL", "TBOD_5": "BOD5_mgL", "TCOD": "COD_mgL",
           "SCOD": "sCOD_mgL", "SNHx": "NH4N_mgL", "SNOx": "NOxN_mgL",
           "SPO4": "PO4P_mgL", "Q": "Q_m3d"}


def effluent_mapping(symbols, unit=None):
    symbols = set(symbols)
    candidates = sorted({s.split("__")[2] for s in symbols
                         if s.startswith("Sumo__Plant__") and len(s.split("__")) == 4
                         and s.split("__")[2].lower().startswith("effluent")})
    if unit is None:
        if len(candidates) != 1:
            raise ValueError("Configure effluent_unit: model has zero or multiple effluent locations: " + repr(candidates))
        unit = candidates[0]
    mapping = {f"Sumo__Plant__{unit}__{suffix}": label for suffix, label in METRICS.items()
               if f"Sumo__Plant__{unit}__{suffix}" in symbols}
    if not mapping:
        raise ValueError(f"No verified effluent metrics for {unit}")
    return mapping


def model_mapping(state_path, unit=None):
    text = Path(state_path).read_text(encoding="utf-8", errors="replace")
    return effluent_mapping(re.findall(r"Sumo__Plant__[A-Za-z0-9_]+", text), unit)


def influent_commands(arguments, state_path, unit=None):
    """Resolve only supplied inputs against model symbols, with no guessed totals."""
    fields = {"influent_flow_m3d": ("Q",), "temperature_C": ("T",),
              "influent_cod_mgL": ("TCOD", "XCOD"), "influent_tkn_mgL": ("TKN", "XTKN")}
    supplied = {key: value for key, value in arguments.items() if key in fields}
    if not supplied:
        return []
    text = Path(state_path).read_text(encoding="utf-8", errors="replace")
    symbols = set(re.findall(r"Sumo__Plant__[A-Za-z0-9_]+", text))
    candidates = sorted({s.split("__")[2] for s in symbols
                         if s.startswith("Sumo__Plant__") and "__param__" in s
                         and s.split("__")[2].lower().startswith("influent")})
    if unit is None:
        if len(candidates) != 1:
            raise ValueError("Configure SUMO_INFLUENT_UNIT for ambiguous influent inputs")
        unit = candidates[0]
    commands = []
    for key, value in supplied.items():
        matches = [f"Sumo__Plant__{unit}__param__{suffix}" for suffix in fields[key]
                   if f"Sumo__Plant__{unit}__param__{suffix}" in symbols]
        if not matches:
            raise ValueError(f"{key} has no verified parameter in {unit}; use the model's supported influent characterization")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
        commands.append(f"set {matches[0]} {value}")
    return commands


def summarise(rows, unit=None):
    if not rows:
        return {"error": "No data rows returned from simulation."}
    row = rows[-1]
    try:
        mapping = effluent_mapping(row, unit)
    except ValueError as exc:
        return {"error": str(exc)}
    result = {}
    for symbol, label in mapping.items():
        value = row[symbol]
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            result[label] = float(value)
    if isinstance(row.get("Sumo__Time"), (int, float)) and math.isfinite(row["Sumo__Time"]):
        result["time_days"] = row["Sumo__Time"] / DAY
    result["observations"] = {label: {"symbol": symbol, "unit": "m3/d" if label == "Q_m3d" else "mg/L",
                                    "source": "native_datacomm", "quality": "observed"}
                              for symbol, label in mapping.items() if label in result}
    return result


def check_compliance(summary, limits):
    checks = {}
    for metric, key in (("TSS_mgL", "TSS"), ("BOD5_mgL", "BOD5"), ("COD_mgL", "COD")):
        value, limit = summary.get(metric), limits.get(key)
        valid = all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0
                    for x in (value, limit))
        checks[key] = {"metric": metric, "unit": "mg/L", "value": value if valid else None,
                       "limit": limit, "status": ("PASS" if value <= limit else "FAIL") if valid else "INSUFFICIENT_DATA",
                       "margin": round(limit - value, 2) if valid else None}
    return checks


def compliance_outcome(checks):
    states = [v["status"] for v in checks.values()]
    if not states or "INSUFFICIENT_DATA" in states:
        return "INSUFFICIENT_DATA"
    return "NON-COMPLIANT" if "FAIL" in states else "COMPLIANT"
