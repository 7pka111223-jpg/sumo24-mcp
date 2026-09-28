"""Preflight for DynaSand's empirical single-coagulant capture law."""
import math
import re


def validate_parameters(values: dict) -> None:
    """Check a mapping of compiled symbols (or short parameter names) to values.

    Separate units are checked independently. Missing doses default to zero; callers
    must merge saved state/defaults and pending edits before calling this function.
    """
    units = {}
    for key, value in values.items():
        match = re.match(r"^(.*?)(?:param__)?Dose(?:,|__)\s*(alum|fe)$", str(key))
        if not match:
            continue
        dose = float(value)
        if not math.isfinite(dose) or dose < 0:
            raise ValueError(f"{key} must be a finite, nonnegative dose")
        units.setdefault(match[1], {})[match[2]] = dose
    for prefix, doses in units.items():
        if doses.get("alum", 0) > 0 and doses.get("fe", 0) > 0:
            raise ValueError(f"{prefix or 'DynaSand'}: choose alum OR ferric dosing; simultaneous dosing is unsupported")
