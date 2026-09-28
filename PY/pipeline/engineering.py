"""
pipeline/engineering.py
───────────────────────
Stage 3 engineering checks: SRT, HRT, F:M, oxygen demand, aeration supply,
mass balance closure, alkalinity, Takacs settler hydraulics.

Each check returns a dict with:
    name        – check identifier
    ok          – True / False
    value       – computed value
    unit        – physical unit string
    range/min/max – acceptance thresholds
    fix         – plain-English corrective action (only when ok=False)

run_engineering_checks() chains all checks and writes engineering_checks.json.
"""
from __future__ import annotations

import json
import math
import pathlib
from datetime import datetime
from typing import Any


# ── Individual calculators ────────────────────────────────────────────────────

def check_srt(V_total_m3: float, MLSS_mgL: float,
              Q_WAS_m3d: float, X_R_mgL: float) -> dict:
    """SRT = V_total × MLSS / (Q_WAS × X_R).  Acceptable: 3–30 d."""
    if Q_WAS_m3d <= 0 or X_R_mgL <= 0:
        return _fail("srt_in_range", None, "d",
                     "Q_WAS and X_R must both be > 0 to compute SRT.")
    srt = (V_total_m3 * MLSS_mgL) / (Q_WAS_m3d * X_R_mgL)
    ok = 3.0 <= srt <= 30.0
    fix = (
        f"SRT = {srt:.1f} d is outside [3, 30] d. "
        + ("Increase reactor volume or reduce Q_WAS." if srt < 3 else
           "Increase Q_WAS or reduce MLSS / reactor volume.")
    ) if not ok else ""
    return _result("srt_in_range", ok, srt, "d", range_=(3.0, 30.0), fix=fix)


def check_hrt(V_reactor_m3: float, Q_avg_m3d: float) -> dict:
    """HRT = V_reactor / Q_avg.  Acceptable: 4–24 h."""
    if Q_avg_m3d <= 0:
        return _fail("hrt_in_range", None, "h", "Q_avg must be > 0.")
    hrt_h = (V_reactor_m3 / Q_avg_m3d) * 24.0
    ok = 4.0 <= hrt_h <= 24.0
    fix = (
        f"HRT = {hrt_h:.1f} h is outside [4, 24] h. "
        + ("Increase reactor volume or reduce flow." if hrt_h < 4 else
           "Decrease reactor volume or increase flow.")
    ) if not ok else ""
    return _result("hrt_in_range", ok, hrt_h, "h", range_=(4.0, 24.0), fix=fix)


def check_fm_ratio(Q_m3d: float, BOD_mgL: float,
                   V_m3: float, MLVSS_mgL: float) -> dict:
    """F:M = (Q × BOD) / (V × MLVSS).  Acceptable: 0.05–1.5 d⁻¹."""
    if V_m3 <= 0 or MLVSS_mgL <= 0:
        return _fail("fm_in_range", None, "d⁻¹", "V and MLVSS must be > 0.")
    fm = (Q_m3d * BOD_mgL) / (V_m3 * MLVSS_mgL)
    ok = 0.05 <= fm <= 1.5
    fix = (
        f"F:M = {fm:.3f} d⁻¹ is outside [0.05, 1.5]. "
        + ("Increase organic load or reduce reactor volume / MLVSS." if fm < 0.05 else
           "Reduce load, increase volume, or increase MLVSS.")
    ) if not ok else ""
    return _result("fm_in_range", ok, fm, "d⁻¹", range_=(0.05, 1.5), fix=fix)


def check_oxygen_demand(
    Q_m3d: float, BOD_mgL: float, TKN_mgL: float,
    NO3_removed_mgL: float = 0.0,
    f_BOD_oxidised: float = 0.55,
    Y_obs: float = 0.40,
) -> dict:
    """
    AOR ≈ (BOD oxidation demand) + (nitrification demand) − (denitrification credit).
    Returns AOR in kg O2/d.  Not an acceptance check — just computes for Stage 3 summary.
    """
    bod_demand   = Q_m3d * BOD_mgL * f_BOD_oxidised * 1e-3          # kg O2/d
    nitrif_demand = Q_m3d * TKN_mgL * 4.57 * 1e-3                    # kg O2/d
    denitrif_credit = Q_m3d * NO3_removed_mgL * 2.86 * 1e-3          # kg O2/d
    aor = max(bod_demand + nitrif_demand - denitrif_credit, 0.0)
    return {"name": "aor_computed", "ok": True,
            "aor_kgO2_d": round(aor, 1),
            "bod_demand_kgO2_d": round(bod_demand, 1),
            "nitrif_demand_kgO2_d": round(nitrif_demand, 1),
            "denitrif_credit_kgO2_d": round(denitrif_credit, 1)}


def check_aeration_supply(KLa_per_d: float, V_m3: float, AOR_kgO2_d: float,
                           DO_sat_mgL: float = 9.0, DO_op_mgL: float = 2.0,
                           alpha: float = 0.65, theta: float = 1.024,
                           T_C: float = 20.0) -> dict:
    """
    OTRf = KLa × V × (alpha × DO_sat_T − DO_op) / 1000   [kg O2/d]
    Ratio OTRf/AOR must be >= 1.0.
    """
    if AOR_kgO2_d <= 0:
        return _result("aeration_supply", True, float("inf"), "OTR/AOR",
                       min_=1.0, fix="")
    DO_sat_T = DO_sat_mgL * 1.126 ** (-(T_C - 20))   # rough temp correction
    otrf = KLa_per_d * V_m3 * (alpha * DO_sat_T - DO_op_mgL) / 1000.0
    ratio = otrf / AOR_kgO2_d
    ok = ratio >= 1.0
    fix = (
        f"OTR/AOR = {ratio:.2f} < 1.0 (aeration under-powered). "
        "Increase KLa, blower capacity, or reactor volume."
    ) if not ok else ""
    return _result("aeration_supply", ok, round(ratio, 3), "OTR/AOR",
                   min_=1.0, fix=fix)


def check_mass_balance(Q_in_m3d: float, COD_in_mgL: float,
                       Q_eff_m3d: float, COD_eff_mgL: float,
                       Q_WAS_m3d: float, COD_WAS_mgL: float) -> dict:
    """
    COD mass-balance rationality check for a biological WWTP.

    In activated sludge, typically 40–65% of influent COD is oxidised to CO2.
    So (M_eff + M_WAS) / M_in is expected to be ~35–65%.
    We flag:
      •  < 20%  → implausible (effluent + WAS too low; data error)
      •  > 100% → impossible (outputs exceed inputs)
    We also check Q balance (hydraulic closure): Q_eff + Q_WAS ≈ Q_in ± 5%.
    """
    m_in  = Q_in_m3d  * COD_in_mgL  * 1e-3   # kg/d
    m_eff = Q_eff_m3d * COD_eff_mgL * 1e-3
    m_was = Q_WAS_m3d * COD_WAS_mgL * 1e-3
    if m_in <= 0:
        return _fail("mass_balance_cod", None, "%",
                     "Influent COD or flow is zero — cannot compute mass balance.")

    # Ratio of recoverable COD (effluent + WAS) to influent COD.
    # Biological oxidation accounts for the remainder; 20–100% is acceptable.
    ratio = (m_eff + m_was) / m_in * 100.0
    ok = 20.0 <= ratio <= 100.0

    # Hydraulic balance: Q_eff + Q_WAS should be within 5% of Q_in
    q_out = Q_eff_m3d + Q_WAS_m3d
    q_closure = q_out / Q_in_m3d * 100.0 if Q_in_m3d > 0 else 0.0
    q_ok = 95.0 <= q_closure <= 105.0

    all_ok = ok and q_ok
    fixes = []
    if not ok:
        fixes.append(
            f"COD mass-balance ratio = {ratio:.1f}% is outside [20, 100]%. "
            "Check that effluent COD, WAS COD, and flows are entered correctly."
        )
    if not q_ok:
        fixes.append(
            f"Hydraulic balance: Q_eff + Q_WAS = {q_out:.0f} m³/d vs Q_in = {Q_in_m3d:.0f} m³/d "
            f"({q_closure:.1f}%). Adjust effluent or WAS flow."
        )
    fix = " | ".join(fixes)

    return _result("mass_balance_cod", all_ok, round(ratio, 2), "%",
                   range_=(20.0, 100.0), fix=fix,
                   extra={"m_in_kgd": round(m_in, 1),
                          "m_eff_kgd": round(m_eff, 1),
                          "m_was_kgd": round(m_was, 1),
                          "q_closure_pct": round(q_closure, 1),
                          "q_balance_ok": q_ok})


def check_alkalinity(TKN_removed_mgL: float, NO3_removed_mgL: float,
                     alk_in_mgCaCO3: float) -> dict:
    """
    Residual alkalinity after nitrification and partial denitrification.
    Consumed: 7.14 mg CaCO3 per mg NH4-N nitrified.
    Recovered: 3.57 mg CaCO3 per mg NO3-N denitrified.
    Minimum residual: 50 mg/L as CaCO3.
    """
    consumed  = TKN_removed_mgL * 7.14
    recovered = NO3_removed_mgL * 3.57
    residual  = alk_in_mgCaCO3 - consumed + recovered
    ok = residual >= 50.0
    fix = (
        f"Residual alkalinity = {residual:.0f} mg/L CaCO3 < 50 mg/L. "
        "Add chemical alkalinity (lime, soda ash) or increase denitrification."
    ) if not ok else ""
    return _result("alkalinity_residual", ok, round(residual, 1),
                   "mg CaCO3/L", min_=50.0, fix=fix)


def check_takacs_settler(Q_m3d: float, A_m2: float,
                          MLSS_mgL: float, RAS_ratio: float = 0.6,
                          v0_m_h: float = 7.0) -> dict:
    """
    Takacs settler SOR and SLR checks.
    SOR ≤ 24 m³/m²/d,  SLR ≤ 5 kg TSS/m²/h.
    """
    if A_m2 <= 0:
        return _fail("takacs_sor", None, "m³/m²/d",
                     "Clarifier surface area must be > 0.")
    Q_eff_m3d  = Q_m3d / (1 + RAS_ratio)   # approximate
    SOR = Q_eff_m3d / A_m2                  # m³/m²/d (= m/d)
    SLR = (Q_m3d * MLSS_mgL * 1e-3) / (A_m2 * 24.0)   # kg/m²/h
    sor_ok = SOR <= 24.0
    slr_ok = SLR <= 5.0
    ok = sor_ok and slr_ok

    fixes = []
    if not sor_ok:
        need = math.ceil(Q_eff_m3d / 24.0)
        fixes.append(
            f"Clarifier SOR = {SOR:.1f} m³/m²/d > 24. "
            f"Increase clarifier surface area to ≥ {need} m²."
        )
    if not slr_ok:
        fixes.append(
            f"Clarifier SLR = {SLR:.2f} kg/m²/h > 5. "
            "Reduce MLSS or increase surface area."
        )
    fix = " ".join(fixes)
    return _result("takacs_sor", ok, round(SOR, 2), "m³/m²/d",
                   max_=24.0, fix=fix,
                   extra={"SLR_kg_m2_h": round(SLR, 3), "SLR_ok": slr_ok})


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_engineering_checks(
    params: dict,
    output_path: "str | pathlib.Path | None" = None,
) -> dict:
    """
    Run all engineering checks from the parameter dictionary extracted from
    the Excel template.

    params keys (all optional — missing values produce a warning not a crash):
        Q_avg_m3d, BOD_mgL, TKN_mgL, COD_in_mgL, TSS_mgL, T_C
        V_total_m3, V_reactor_m3, MLSS_mgL, MLVSS_mgL
        Q_WAS_m3d, X_R_mgL (return sludge TSS), COD_WAS_mgL
        Q_eff_m3d, COD_eff_mgL
        KLa_per_d, DO_sat_mgL, DO_op_mgL, alpha
        A_clarifier_m2, RAS_ratio
        Alk_in_mgCaCO3, NO3_removed_mgL
    """
    p = params
    checks: list[dict] = []
    warnings: list[str] = []

    def _require(*keys: str) -> bool:
        missing = [k for k in keys if k not in p or p[k] is None]
        if missing:
            warnings.append(f"Skipping check — missing params: {missing}")
            return False
        return True

    # 1. SRT
    if _require("V_total_m3", "MLSS_mgL", "Q_WAS_m3d", "X_R_mgL"):
        checks.append(check_srt(p["V_total_m3"], p["MLSS_mgL"],
                                 p["Q_WAS_m3d"], p["X_R_mgL"]))

    # 2. HRT
    if _require("V_reactor_m3", "Q_avg_m3d"):
        checks.append(check_hrt(p["V_reactor_m3"], p["Q_avg_m3d"]))

    # 3. F:M
    if _require("Q_avg_m3d", "BOD_mgL", "V_total_m3", "MLVSS_mgL"):
        checks.append(check_fm_ratio(p["Q_avg_m3d"], p["BOD_mgL"],
                                      p["V_total_m3"], p["MLVSS_mgL"]))

    # 4. Oxygen demand (informational only)
    if _require("Q_avg_m3d", "BOD_mgL", "TKN_mgL"):
        od = check_oxygen_demand(
            p["Q_avg_m3d"], p["BOD_mgL"], p["TKN_mgL"],
            p.get("NO3_removed_mgL", 0.0),
        )
        checks.append(od)
        # 5. Aeration supply (needs AOR from previous step)
        if _require("KLa_per_d", "V_total_m3"):
            checks.append(check_aeration_supply(
                p["KLa_per_d"], p["V_total_m3"], od.get("aor_kgO2_d", 1.0),
                p.get("DO_sat_mgL", 9.0), p.get("DO_op_mgL", 2.0),
                p.get("alpha", 0.65), T_C=p.get("T_C", 20.0),
            ))

    # 6. Mass balance
    if _require("Q_avg_m3d", "COD_in_mgL", "Q_eff_m3d", "COD_eff_mgL",
                "Q_WAS_m3d", "COD_WAS_mgL"):
        checks.append(check_mass_balance(
            p["Q_avg_m3d"], p["COD_in_mgL"],
            p["Q_eff_m3d"], p["COD_eff_mgL"],
            p["Q_WAS_m3d"], p["COD_WAS_mgL"],
        ))

    # 7. Alkalinity
    if _require("TKN_mgL", "Alk_in_mgCaCO3"):
        checks.append(check_alkalinity(
            p["TKN_mgL"],
            p.get("NO3_removed_mgL", 0.0),
            p["Alk_in_mgCaCO3"],
        ))

    # 8. Takacs settler
    if _require("Q_avg_m3d", "A_clarifier_m2", "MLSS_mgL"):
        checks.append(check_takacs_settler(
            p["Q_avg_m3d"], p["A_clarifier_m2"], p["MLSS_mgL"],
            p.get("RAS_ratio", 0.6),
        ))

    failed  = [c for c in checks if not c.get("ok")]
    passed  = [c for c in checks if c.get("ok")]
    overall = len(failed) == 0

    # Surface the worst failure's fix as the top-level message
    top_fix = failed[0].get("fix", "") if failed else ""

    result = {
        "ok": overall,
        "stage": 3,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "computed": _extract_summary(checks),
        "checks": checks,
        "passed": len(passed),
        "failed": len(failed),
        "warnings": warnings,
        "top_fix": top_fix,
    }

    if output_path:
        pathlib.Path(output_path).write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )

    return result


# ── Private helpers ───────────────────────────────────────────────────────────

def _result(name: str, ok: bool, value: Any, unit: str, *,
            range_: tuple | None = None, min_: float | None = None,
            max_: float | None = None, fix: str = "", extra: dict | None = None) -> dict:
    r: dict = {"name": name, "ok": ok, "value": value, "unit": unit}
    if range_:
        r["range"] = list(range_)
    if min_ is not None:
        r["min"] = min_
    if max_ is not None:
        r["max"] = max_
    if not ok and fix:
        r["fix"] = fix
    if extra:
        r.update(extra)
    return r


def _fail(name: str, value: Any, unit: str, fix: str) -> dict:
    return {"name": name, "ok": False, "value": value, "unit": unit, "fix": fix}


def _extract_summary(checks: list[dict]) -> dict:
    """Pull key computed values out of the check list for the manifest summary."""
    s: dict = {}
    for c in checks:
        n = c.get("name", "")
        v = c.get("value")
        if v is None:
            continue
        if n == "srt_in_range":       s["srt_d"] = v
        elif n == "hrt_in_range":     s["hrt_h"] = v
        elif n == "fm_in_range":      s["fm_d_inv"] = v
        elif n == "aor_computed":     s["aor_kgO2_d"] = c.get("aor_kgO2_d")
        elif n == "aeration_supply":  s["otr_aor_ratio"] = v
        elif n == "mass_balance_cod": s["mass_balance_closure_pct"] = v
        elif n == "alkalinity_residual": s["alk_residual_mgCaCO3"] = v
        elif n == "takacs_sor":       s["clarifier_sor"] = v
    return s
