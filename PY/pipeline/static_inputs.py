"""
pipeline/static_inputs.py
──────────────────────────
Stage 4: resolve influent fractionation into ASM2d state-variable initial
values and write:
  - static_inputs.json  (human-readable structured data)
  - static_inputs.scs   (SUMO Core-Window script to paste after apply_parameters.scs)

The fractionation comes from the Excel template's Influent_Fractionation sheet
(or from RESEARCH_DEFAULTS if not provided).

Conservation checks:
  • COD fractions must sum to 1.0 ± 0.01
  • N fractions must sum to 1.0 ± 0.05   (wider tolerance — some models omit X_ND)
  • P fractions for ASM2d must sum to 1.0 ± 0.05
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime
from typing import Any


# ── Default COD fractionation (ASM2d, warm-climate Egyptian WW) ───────────────
DEFAULT_FRACTIONS: dict[str, float] = {
    # COD fractions (sum = 1.0)
    "fSS":  0.20,   # soluble biodegradable COD
    "fSI":  0.07,   # soluble inert COD
    "fXS":  0.50,   # particulate slowly biodegradable COD
    "fXI":  0.15,   # particulate inert COD
    "fXBH": 0.08,   # active heterotrophs in influent
    # N distribution (fTKN sum ≈ 1.0)
    "fSNH_TKN":  0.64,   # S_NH4 / TKN
    "fSND_TKN":  0.05,   # S_ND  / TKN (soluble organic N)
    "fXND_TKN":  0.31,   # X_ND  / TKN (particulate organic N)
    # P distribution (fTP sum ≈ 1.0)
    "fSPO4_TP":  0.50,   # S_PO4 / TP
    "fXPP_TP":   0.30,   # X_PP  / TP
    "fXPHA_TP":  0.20,   # X_PHA / TP
}


def resolve_static_inputs(
    influent: dict,
    fractions: dict | None = None,
    reactors: list[dict] | None = None,
    kinetic_model: str = "ASM2d",
) -> dict:
    """
    Compute ASM state-variable initial values from influent characteristics
    and fractionation coefficients.

    influent keys:
        Q_m3d, COD_mgL, BOD_mgL, TKN_mgL, TP_mgL, TSS_mgL, T_C, pH, Alk_mgCaCO3

    fractions: override DEFAULT_FRACTIONS keys

    reactors: list of {name, V_m3, DO_setpoint, MLSS_mgL, type}
        type: "aerobic" | "anoxic" | "anaerobic"

    Returns a dict with:
        ok, influent_sv, reactor_setpoints, validation
    """
    f = dict(DEFAULT_FRACTIONS)
    if fractions:
        f.update(fractions)

    Q   = float(influent.get("Q_m3d",   1000.0))
    COD = float(influent.get("COD_mgL",  400.0))
    TKN = float(influent.get("TKN_mgL",  50.0))
    TP  = float(influent.get("TP_mgL",    7.0))
    TSS = float(influent.get("TSS_mgL",  250.0))
    T   = float(influent.get("T_C",       20.0))
    pH  = float(influent.get("pH",         7.4))
    Alk = float(influent.get("Alk_mgCaCO3", 300.0))

    # ── COD state variables ──────────────────────────────────────────────────
    S_S   = COD * f["fSS"]
    S_I   = COD * f["fSI"]
    X_S   = COD * f["fXS"]
    X_I   = COD * f["fXI"]
    X_BH  = COD * f["fXBH"]
    X_BA  = 0.0    # autotrophs negligible in raw influent

    cod_sum = f["fSS"] + f["fSI"] + f["fXS"] + f["fXI"] + f["fXBH"]

    # ── N state variables ────────────────────────────────────────────────────
    S_NH  = TKN * f["fSNH_TKN"]
    S_ND  = TKN * f["fSND_TKN"]
    X_ND  = TKN * f["fXND_TKN"]
    S_NO  = 0.0   # no nitrate in raw influent
    S_N2  = 0.0
    n_sum = f["fSNH_TKN"] + f["fSND_TKN"] + f["fXND_TKN"]

    # ── P state variables (ASM2d only) ───────────────────────────────────────
    S_PO4 = TP * f["fSPO4_TP"]
    X_PP  = TP * f["fXPP_TP"]
    X_PHA = TP * f["fXPHA_TP"]
    p_sum = f["fSPO4_TP"] + f["fXPP_TP"] + f["fXPHA_TP"]

    # ── Validation ───────────────────────────────────────────────────────────
    validation: list[dict] = []
    ok = True

    def _check_sum(name: str, value: float, target: float = 1.0,
                   tol: float = 0.01) -> None:
        nonlocal ok
        passed = abs(value - target) <= tol
        if not passed:
            ok = False
        validation.append({
            "check": name, "ok": passed,
            "sum": round(value, 4), "target": target, "tol": tol,
        })

    _check_sum("cod_fractions_sum", cod_sum, 1.0, tol=0.01)
    _check_sum("n_fractions_sum",   n_sum,   1.0, tol=0.05)
    if kinetic_model == "ASM2d":
        _check_sum("p_fractions_sum", p_sum, 1.0, tol=0.05)

    # Range checks
    range_checks = [
        ("pH",          pH,    6.0,  8.5),
        ("T_C",         T,    10.0, 40.0),
        ("COD_mgL",     COD,  50.0, 2000.0),
        ("TKN_mgL",     TKN,   5.0,  200.0),
        ("TP_mgL",      TP,    0.5,   50.0),
    ]
    for label, val, lo, hi in range_checks:
        passed = lo <= val <= hi
        if not passed:
            ok = False
        validation.append({
            "check": f"{label}_in_range",
            "ok": passed, "value": val, "range": [lo, hi],
        })

    # ── Influent state variables dict ────────────────────────────────────────
    influent_sv: dict[str, float] = {
        "S_S":   round(S_S,  2),
        "S_I":   round(S_I,  2),
        "X_S":   round(X_S,  2),
        "X_I":   round(X_I,  2),
        "X_BH":  round(X_BH, 2),
        "X_BA":  round(X_BA, 2),
        "S_NH":  round(S_NH, 2),
        "S_ND":  round(S_ND, 2),
        "X_ND":  round(X_ND, 2),
        "S_NO":  round(S_NO, 2),
        "S_N2":  round(S_N2, 2),
        "S_PO4": round(S_PO4, 2),
        "X_PP":  round(X_PP,  2),
        "X_PHA": round(X_PHA, 2),
        "Q":     round(Q, 1),
        "T":     round(T, 1),
        "S_ALK": round(Alk / 50.0, 3),   # convert mg CaCO3/L → mmol/L (×1/50)
    }

    # ── Reactor setpoints ────────────────────────────────────────────────────
    reactor_setpoints: list[dict] = []
    for r in (reactors or []):
        rtype = r.get("type", "aerobic")
        do_sp = r.get("DO_setpoint",
                      2.0 if rtype == "aerobic" else
                      0.1 if rtype == "anoxic" else 0.0)
        mlss_sp = r.get("MLSS_mgL", 3500.0)

        # Validate DO
        do_ok = True
        if rtype == "aerobic"   and not (0.5 <= do_sp <= 4.0):
            do_ok = False
        if rtype == "anoxic"    and do_sp > 0.3:
            do_ok = False
        if rtype == "anaerobic" and do_sp > 0.1:
            do_ok = False
        if not do_ok:
            ok = False
        validation.append({
            "check": f"do_setpoint_{r.get('name', 'reactor')}",
            "ok": do_ok, "value": do_sp, "type": rtype,
        })

        # Validate MLSS
        mlss_ok = 2000.0 <= mlss_sp <= 6000.0
        if not mlss_ok:
            ok = False
        validation.append({
            "check": f"mlss_setpoint_{r.get('name', 'reactor')}",
            "ok": mlss_ok, "value": mlss_sp,
        })

        reactor_setpoints.append({
            "name":         r.get("name", "reactor"),
            "type":         rtype,
            "DO_setpoint":  do_sp,
            "MLSS_mgL":     mlss_sp,
        })

    return {
        "ok": ok,
        "influent_sv": influent_sv,
        "reactor_setpoints": reactor_setpoints,
        "fractions_used": f,
        "validation": validation,
    }


def build_scs_script(
    plant_name: str,
    influent_unit: str,
    influent_sv: dict[str, float],
    reactor_setpoints: list[dict],
) -> str:
    """
    Build the static_inputs.scs SUMO Core-Window script.
    Maps resolved state variables to SUMO parameter names.
    """
    lines = [
        f"// static_inputs.scs — generated by SUMO24 MCP pipeline",
        f"// Plant: {plant_name}",
        f"// Generated: {datetime.utcnow().isoformat()}Z",
        f"// Paste in SUMO Core Window AFTER apply_parameters.scs",
        "",
        f"// ── Influent fractionation ({influent_unit}) ──",
    ]

    sv_to_param = {
        "S_S":   "param__S_S",
        "S_I":   "param__S_I",
        "X_S":   "param__X_S",
        "X_I":   "param__X_I",
        "X_BH":  "param__X_BH",
        "X_BA":  "param__X_BA",
        "S_NH":  "param__S_NH4",
        "S_ND":  "param__S_ND",
        "X_ND":  "param__X_ND",
        "S_NO":  "param__S_NO3",
        "S_PO4": "param__S_PO4",
        "X_PP":  "param__X_PP",
        "X_PHA": "param__X_PHA",
        "Q":     "param__Q",
        "T":     "param__T",
        "S_ALK": "param__S_ALK",
    }

    for sv, val in influent_sv.items():
        param = sv_to_param.get(sv, f"param__{sv}")
        lines.append(f'set "{influent_unit}__{param}" = {val};')

    lines.append("")
    lines.append("// ── Reactor setpoints ──")
    for r in reactor_setpoints:
        rname = r["name"]
        lines.append(f'set "{rname}__param__DO_setpoint" = {r["DO_setpoint"]};')
        lines.append(f'set "{rname}__param__MLSS_setpoint" = {r["MLSS_mgL"]};')

    lines.append("")
    lines.append('save "state.xml";')
    lines.append("")
    return "\n".join(lines)


def write_static_inputs(
    project_dir: "str | pathlib.Path",
    plant_name: str,
    influent: dict,
    fractions: dict | None = None,
    reactors: list[dict] | None = None,
    influent_unit: str = "Influent1",
    kinetic_model: str = "ASM2d",
) -> dict:
    """
    Resolve and write static_inputs.json + static_inputs.scs.
    Returns the resolve result with added file paths.
    """
    result = resolve_static_inputs(influent, fractions, reactors, kinetic_model)

    pd = pathlib.Path(project_dir)

    json_path = pd / "static_inputs.json"
    payload = {
        "ok": result["ok"],
        "stage": 4,
        "plant_name": plant_name,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "influent_sv": result["influent_sv"],
        "reactor_setpoints": result["reactor_setpoints"],
        "fractions_used": result["fractions_used"],
        "validation": result["validation"],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    scs_path = pd / "static_inputs.scs"
    scs_text = build_scs_script(
        plant_name, influent_unit,
        result["influent_sv"], result["reactor_setpoints"],
    )
    scs_path.write_text(scs_text, encoding="utf-8")

    result["json_path"] = str(json_path)
    result["scs_path"]  = str(scs_path)
    return result
