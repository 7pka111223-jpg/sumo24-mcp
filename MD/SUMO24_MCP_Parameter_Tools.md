# SUMO24 MCP — Parameter Editing Tools with Research-Based Defaults

## Context
This file adds **parameter-editing tools** to the existing MCP server at
`F:/UNI/SUMO/MCP/PY/server.py`. These tools cover:
- Plant-wide and global parameters
- ASM1, ASM2d, and ASM3 biological kinetic parameters (with Arrhenius temperature correction)
- All unit process parameters (influent, screens, primary clarifier, aeration tank,
  anoxic zone, anaerobic zone, secondary clarifier, MBR, tertiary filter, thickener,
  aerobic and anaerobic digesters, RAS/WAS pumps, chemical dosing)
- Dynamic simulation tab parameters
- Auto-assumption from research when values are not specified (Egyptian warm-climate defaults)

> ⚠️ **Do not remove or modify any existing tools.**
> Insert all new code after the last existing `@server.tool()` function,
> before any `if __name__ == "__main__"` block.

---

## File to Edit
**`F:/UNI/SUMO/MCP/PY/server.py`**

---

## Step 1 — Add the research-based defaults registry

Find the `CONFIG = { ... }` dict and insert this block **immediately after it**.
This dict is the single source of truth for all Egyptian warm-climate defaults.

```python
# ═══════════════════════════════════════════════════════════════════════════
# RESEARCH-BASED DEFAULT PARAMETERS
# Source: IWA ASM1/ASM2d/ASM3 STR-9 (Henze et al. 2000),
#         Metcalf & Eddy 5th ed., BSM1 benchmark,
#         Egyptian Law 48/1982 (Decree 92/2013, 208/2018),
#         Warm-climate / Egyptian WWTP calibration literature
#         (IWA WPT 2022, MDPI Water 2022, Longdom El-Gharbia 2017)
# ═══════════════════════════════════════════════════════════════════════════
RESEARCH_DEFAULTS = {

    # ── Law 48/1982 Egyptian discharge limits (Decree 208/2018) ─────────────
    "law48_nile": {          # Discharge to Nile / main canals
        "BOD5":  30.0,       # mg/L
        "COD":   40.0,
        "TSS":   30.0,
        "NH3_N": 3.0,
        "NO3_N": 45.0,
        "TP":    1.0,
        "Oil":   5.0,
        "DO_min":4.0,
    },
    "law48_drain": {         # Discharge to agricultural drains
        "BOD5":  60.0,
        "COD":   80.0,
        "TSS":   50.0,
        "NH3_N": 5.0,
        "TN":    50.0,
        "TP":    3.0,
        "Oil":   10.0,
    },

    # ── Typical Egyptian municipal influent (raw, no primary) ───────────────
    # Sources: HCWW/NWRC data, El-Gharbia & Arab El-Madabegh audits
    "influent_egypt": {
        "Q_m3d":       28000,  # m³/d   (plant-scale default)
        "COD_mgL":     550,    # mg/L   (range 400–800)
        "BOD5_mgL":    280,    # mg/L   (range 200–400)
        "TSS_mgL":     300,    # mg/L   (range 200–400)
        "VSS_mgL":     240,    # mg/L
        "TKN_mgL":     55,     # mg/L   (range 40–70)
        "NH4_mgL":     35,     # mg/L
        "TP_mgL":      8,      # mg/L   (range 6–12)
        "pH":          7.4,
        "Temp_C":      25.0,   # summer; 18°C winter
        # COD fractionation (ASM convention)
        "fSI":         0.07,   # soluble inert fraction of COD
        "fSS":         0.20,   # readily biodegradable
        "fXS":         0.50,   # slowly biodegradable particulate
        "fXI":         0.15,   # particulate inert (high at plants with no primary)
        "fXBH":        0.08,   # active heterotroph biomass in influent
    },

    # ── ASM1 kinetic defaults at 20°C (IWA STR-9 / BSM1 endogenous set) ────
    # Arrhenius θ values included — apply k(T) = k(20) × θ^(T−20)
    "ASM1": {
        # Stoichiometric
        "Y_H":    {"val": 0.67,  "unit": "g COD/g COD", "theta": None},
        "Y_A":    {"val": 0.24,  "unit": "g COD/g N",   "theta": None},
        "f_P":    {"val": 0.08,  "unit": "—",            "theta": None},
        "i_XB":   {"val": 0.086, "unit": "g N/g COD",   "theta": None},
        "i_XP":   {"val": 0.06,  "unit": "g N/g COD",   "theta": None},
        # Kinetic — heterotrophs
        "mu_H":   {"val": 4.0,   "unit": "d⁻¹",          "theta": 1.072},
        "K_S":    {"val": 10.0,  "unit": "g COD/m³",     "theta": None},
        "K_OH":   {"val": 0.20,  "unit": "g O₂/m³",      "theta": None},
        "K_NO":   {"val": 0.50,  "unit": "g N/m³",       "theta": None},
        "b_H":    {"val": 0.30,  "unit": "d⁻¹",          "theta": 1.12},
        "eta_g":  {"val": 0.80,  "unit": "—",            "theta": None},
        "eta_h":  {"val": 0.80,  "unit": "—",            "theta": None},
        "k_h":    {"val": 3.0,   "unit": "g COD/(g COD·d)","theta": 1.072},
        "K_X":    {"val": 0.10,  "unit": "g COD/g COD", "theta": 1.116},
        # Kinetic — autotrophs (nitrifiers — most temperature-sensitive)
        "mu_A":   {"val": 0.50,  "unit": "d⁻¹",          "theta": 1.103},
        "K_NH":   {"val": 1.0,   "unit": "g N/m³",       "theta": 1.123},
        "K_OA":   {"val": 0.40,  "unit": "g O₂/m³",      "theta": None},
        "b_A":    {"val": 0.05,  "unit": "d⁻¹",          "theta": 1.116},
        "k_a":    {"val": 0.05,  "unit": "m³/(g COD·d)", "theta": 1.072},
    },

    # ── ASM2d kinetic defaults at 20°C (Henze et al. 2000, Table 4.2–4.3) ──
    "ASM2d": {
        # Stoichiometric
        "Y_H":      {"val": 0.625, "unit": "g COD/g COD", "theta": None},
        "Y_PAO":    {"val": 0.625, "unit": "g COD/g COD", "theta": None},
        "Y_PO4":    {"val": 0.40,  "unit": "g P/g COD",   "theta": None},
        "Y_PHA":    {"val": 0.20,  "unit": "g COD/g P",   "theta": None},
        "Y_A":      {"val": 0.24,  "unit": "g COD/g N",   "theta": None},
        "f_XI":     {"val": 0.10,  "unit": "—",           "theta": None},
        "i_N_BM":   {"val": 0.07,  "unit": "g N/g COD",   "theta": None},
        "i_P_BM":   {"val": 0.02,  "unit": "g P/g COD",   "theta": None},
        # Kinetic — hydrolysis
        "K_h":      {"val": 3.0,   "unit": "d⁻¹",         "theta": 1.041},
        "eta_NO3":  {"val": 0.60,  "unit": "—",           "theta": None},
        "eta_fe":   {"val": 0.40,  "unit": "—",           "theta": None},
        "K_O2_h":   {"val": 0.20,  "unit": "g O₂/m³",     "theta": None},
        "K_NO3_h":  {"val": 0.50,  "unit": "g N/m³",      "theta": None},
        "K_X_h":    {"val": 0.10,  "unit": "g COD/g COD", "theta": None},
        # Kinetic — heterotrophs
        "mu_H":     {"val": 6.0,   "unit": "d⁻¹",         "theta": 1.072},
        "q_fe":     {"val": 3.0,   "unit": "d⁻¹",         "theta": 1.072},
        "eta_NO3_H":{"val": 0.80,  "unit": "—",           "theta": None},
        "b_H":      {"val": 0.40,  "unit": "d⁻¹",         "theta": 1.12},
        "K_O2_H":   {"val": 0.20,  "unit": "g O₂/m³",     "theta": None},
        "K_F":      {"val": 4.0,   "unit": "g COD/m³",    "theta": None},
        "K_A_H":    {"val": 4.0,   "unit": "g COD/m³",    "theta": None},
        "K_NO3_H":  {"val": 0.50,  "unit": "g N/m³",      "theta": None},
        "K_NH4_H":  {"val": 0.05,  "unit": "g N/m³",      "theta": None},
        "K_P_H":    {"val": 0.01,  "unit": "g P/m³",      "theta": None},
        # Kinetic — PAOs
        "q_PHA":    {"val": 3.0,   "unit": "d⁻¹",         "theta": 1.072},
        "q_PP":     {"val": 1.5,   "unit": "d⁻¹",         "theta": 1.072},
        "mu_PAO":   {"val": 1.0,   "unit": "d⁻¹",         "theta": 1.072},
        "eta_NO3_PAO":{"val":0.60, "unit": "—",           "theta": None},
        "b_PAO":    {"val": 0.20,  "unit": "d⁻¹",         "theta": 1.072},
        "b_PP":     {"val": 0.20,  "unit": "d⁻¹",         "theta": 1.072},
        "b_PHA":    {"val": 0.20,  "unit": "d⁻¹",         "theta": 1.072},
        "K_O2_PAO": {"val": 0.20,  "unit": "g O₂/m³",     "theta": None},
        "K_NO3_PAO":{"val": 0.50,  "unit": "g N/m³",      "theta": None},
        "K_A_PAO":  {"val": 4.0,   "unit": "g COD/m³",    "theta": None},
        "K_NH4_PAO":{"val": 0.05,  "unit": "g N/m³",      "theta": None},
        "K_P_PAO":  {"val": 0.01,  "unit": "g P/m³",      "theta": None},
        "K_PS":     {"val": 0.20,  "unit": "g P/m³",      "theta": None},
        "K_MAX":    {"val": 0.34,  "unit": "g P/g COD",   "theta": None},
        # Kinetic — autotrophs
        "mu_AUT":   {"val": 1.0,   "unit": "d⁻¹",         "theta": 1.103},
        "b_AUT":    {"val": 0.15,  "unit": "d⁻¹",         "theta": 1.116},
        "K_O2_AUT": {"val": 0.50,  "unit": "g O₂/m³",     "theta": None},
        "K_NH4_AUT":{"val": 1.0,   "unit": "g N/m³",      "theta": 1.123},
        "K_P_AUT":  {"val": 0.01,  "unit": "g P/m³",      "theta": None},
        # Precipitation
        "k_PRE":    {"val": 1.0,   "unit": "m³/(g·d)",    "theta": None},
        "k_RED":    {"val": 0.60,  "unit": "d⁻¹",         "theta": None},
    },

    # ── ASM3 kinetic defaults at 20°C (Gujer et al. 1999; Koch et al. 2000) ─
    "ASM3": {
        "Y_STO_O2": {"val": 0.85, "unit": "g COD/g COD", "theta": None},
        "Y_STO_NO": {"val": 0.80, "unit": "g COD/g COD", "theta": None},
        "Y_H_O2":   {"val": 0.63, "unit": "g COD/g COD", "theta": None},
        "Y_H_NO":   {"val": 0.54, "unit": "g COD/g COD", "theta": None},
        "Y_A":      {"val": 0.24, "unit": "g COD/g N",   "theta": None},
        "f_XI":     {"val": 0.20, "unit": "—",           "theta": None},
        "k_h":      {"val": 3.0,  "unit": "d⁻¹",         "theta": 1.041},
        "K_X":      {"val": 1.0,  "unit": "g COD/g COD", "theta": None},
        "k_STO":    {"val": 5.0,  "unit": "d⁻¹",         "theta": 1.072},
        "eta_NO":   {"val": 0.60, "unit": "—",           "theta": None},
        "K_O2":     {"val": 0.20, "unit": "g O₂/m³",     "theta": None},
        "K_NO":     {"val": 0.50, "unit": "g N/m³",      "theta": None},
        "K_S":      {"val": 2.0,  "unit": "g COD/m³",    "theta": None},
        "K_STO":    {"val": 1.0,  "unit": "g COD/g COD", "theta": None},
        "mu_H":     {"val": 2.0,  "unit": "d⁻¹",         "theta": 1.072},
        "K_NH_H":   {"val": 0.01, "unit": "g N/m³",      "theta": None},
        "b_H_O2":   {"val": 0.20, "unit": "d⁻¹",         "theta": 1.072},
        "b_H_NO":   {"val": 0.10, "unit": "d⁻¹",         "theta": 1.072},
        "b_STO_O2": {"val": 0.20, "unit": "d⁻¹",         "theta": 1.072},
        "b_STO_NO": {"val": 0.10, "unit": "d⁻¹",         "theta": 1.072},
        "mu_A":     {"val": 1.0,  "unit": "d⁻¹",         "theta": 1.103},
        "K_A_NH":   {"val": 1.0,  "unit": "g N/m³",      "theta": 1.123},
        "K_A_O":    {"val": 0.50, "unit": "g O₂/m³",     "theta": None},
        "b_A_O":    {"val": 0.15, "unit": "d⁻¹",         "theta": 1.116},
        "b_A_NO":   {"val": 0.05, "unit": "d⁻¹",         "theta": 1.116},
    },

    # ── Takács secondary clarifier model (Takács et al. 1991) ───────────────
    "takacs": {
        "v0":    {"val": 474.0,  "unit": "m/d",    "note": "max theoretical settling velocity"},
        "v0_p":  {"val": 250.0,  "unit": "m/d",    "note": "max practical settling velocity"},
        "r_h":   {"val": 0.000576, "unit": "m³/g", "note": "hindrance settling coefficient"},
        "r_p":   {"val": 0.00286,  "unit": "m³/g", "note": "flocculant zone coefficient"},
        "f_ns":  {"val": 0.00228,  "unit": "—",    "note": "non-settleable fraction"},
    },

    # ── Dynamic simulation defaults ──────────────────────────────────────────
    "dynamics": {
        "duration_days":    14,
        "timestep_h":       0.25,
        "output_interval_h":1.0,
        "solver":           "Euler",
        "tolerance":        1e-4,
        "warm_up_days":     10,
        "diurnal_peak_factor": 1.8,   # peak/average flow
        "diurnal_min_factor":  0.4,   # night minimum
        "storm_peak_factor":   3.0,   # 3× for wet weather event
        "storm_duration_h":    6,
    },
}
```

---

## Step 2 — Add the Arrhenius temperature correction helper

Insert this function **immediately after** the `RESEARCH_DEFAULTS` dict
(still before any `@server.tool()` functions):

```python
def _arrhenius(k20: float, theta: float, T: float) -> float:
    """Return Arrhenius-corrected rate: k(T) = k20 × θ^(T−20)."""
    if theta is None or theta == 1.0:
        return k20
    return k20 * (theta ** (T - 20.0))


def _correct_asm_params(model_key: str, temp_C: float) -> dict:
    """
    Return the full parameter dict for an ASM model, temperature-corrected
    to temp_C using per-parameter Arrhenius θ values.

    Args:
        model_key: 'ASM1', 'ASM2d', or 'ASM3'
        temp_C:    Operating temperature in °C
    """
    raw = RESEARCH_DEFAULTS.get(model_key, {})
    corrected = {}
    for param, info in raw.items():
        val   = info["val"]
        theta = info.get("theta")
        if theta:
            corrected[param] = round(_arrhenius(val, theta, temp_C), 6)
        else:
            corrected[param] = val
    return corrected
```

---

## Step 3 — Insert all new tools

Find the **last** `@server.tool()` function and insert the entire block below
**immediately after** it, before any `if __name__ == "__main__"` block.

```python
# ═══════════════════════════════════════════════════════════════════════════
# GROUP A — Biological Kinetic Parameter Tools
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def set_asm1_kinetics(
    unit_name:  str   = "AerTank1",
    temp_C:     float = 20.0,
    # Heterotrophic kinetics — pass None to use research default
    mu_H:   float = None,
    K_S:    float = None,
    K_OH:   float = None,
    K_NO:   float = None,
    b_H:    float = None,
    Y_H:    float = None,
    eta_g:  float = None,
    eta_h:  float = None,
    k_h:    float = None,
    K_X:    float = None,
    # Autotrophic kinetics (nitrifiers)
    mu_A:   float = None,
    K_NH:   float = None,
    K_OA:   float = None,
    b_A:    float = None,
    k_a:    float = None,
    # Stoichiometric
    Y_A:    float = None,
    f_P:    float = None,
    i_XB:   float = None,
    i_XP:   float = None,
) -> dict:
    """Set ASM1 kinetic and stoichiometric parameters on a biological unit.

    Any argument left as None is filled from the IWA/Egyptian research defaults,
    Arrhenius-corrected to temp_C.

    Args:
        unit_name: SUMO unit process name (e.g. 'AerTank1').
        temp_C:    Operating temperature for Arrhenius correction (°C).
        mu_H … i_XP: Individual parameter overrides (None = use research default).

    Returns:
        Dict showing applied values, source (user / research default), and
        the SUMO variable name attempted for each parameter.
    """
    try:
        ds = _make_ds()
        defaults = _correct_asm_params("ASM1", temp_C)

        # Map tool argument name → (value supplied, SUMO variable name candidates)
        param_map = {
            "mu_H":  (mu_H,  [f"Sumo__Plant__{unit_name}__param__mu_H",
                               f"Sumo__Plant__{unit_name}__param__muH"]),
            "K_S":   (K_S,   [f"Sumo__Plant__{unit_name}__param__K_S",
                               f"Sumo__Plant__{unit_name}__param__Ks"]),
            "K_OH":  (K_OH,  [f"Sumo__Plant__{unit_name}__param__K_OH",
                               f"Sumo__Plant__{unit_name}__param__KO_H"]),
            "K_NO":  (K_NO,  [f"Sumo__Plant__{unit_name}__param__K_NO",
                               f"Sumo__Plant__{unit_name}__param__KNO"]),
            "b_H":   (b_H,   [f"Sumo__Plant__{unit_name}__param__b_H",
                               f"Sumo__Plant__{unit_name}__param__bH"]),
            "Y_H":   (Y_H,   [f"Sumo__Plant__{unit_name}__param__Y_H",
                               f"Sumo__Plant__{unit_name}__param__YH"]),
            "eta_g": (eta_g, [f"Sumo__Plant__{unit_name}__param__eta_g",
                               f"Sumo__Plant__{unit_name}__param__etag"]),
            "eta_h": (eta_h, [f"Sumo__Plant__{unit_name}__param__eta_h",
                               f"Sumo__Plant__{unit_name}__param__etah"]),
            "k_h":   (k_h,   [f"Sumo__Plant__{unit_name}__param__k_h",
                               f"Sumo__Plant__{unit_name}__param__kh"]),
            "K_X":   (K_X,   [f"Sumo__Plant__{unit_name}__param__K_X",
                               f"Sumo__Plant__{unit_name}__param__KX"]),
            "mu_A":  (mu_A,  [f"Sumo__Plant__{unit_name}__param__mu_A",
                               f"Sumo__Plant__{unit_name}__param__muA"]),
            "K_NH":  (K_NH,  [f"Sumo__Plant__{unit_name}__param__K_NH",
                               f"Sumo__Plant__{unit_name}__param__KNH"]),
            "K_OA":  (K_OA,  [f"Sumo__Plant__{unit_name}__param__K_OA",
                               f"Sumo__Plant__{unit_name}__param__KO_A"]),
            "b_A":   (b_A,   [f"Sumo__Plant__{unit_name}__param__b_A",
                               f"Sumo__Plant__{unit_name}__param__bA"]),
            "k_a":   (k_a,   [f"Sumo__Plant__{unit_name}__param__k_a",
                               f"Sumo__Plant__{unit_name}__param__ka"]),
            "Y_A":   (Y_A,   [f"Sumo__Plant__{unit_name}__param__Y_A",
                               f"Sumo__Plant__{unit_name}__param__YA"]),
            "f_P":   (f_P,   [f"Sumo__Plant__{unit_name}__param__f_P",
                               f"Sumo__Plant__{unit_name}__param__fP"]),
            "i_XB":  (i_XB,  [f"Sumo__Plant__{unit_name}__param__i_XB",
                               f"Sumo__Plant__{unit_name}__param__iXB"]),
            "i_XP":  (i_XP,  [f"Sumo__Plant__{unit_name}__param__i_XP",
                               f"Sumo__Plant__{unit_name}__param__iXP"]),
        }

        all_vars = ds.sumo.getVariableNames()
        applied, skipped, failed = [], [], []

        for pname, (user_val, candidates) in param_map.items():
            final_val = user_val if user_val is not None else defaults.get(pname)
            source    = "user" if user_val is not None else f"research_default@{temp_C}°C"
            set_ok    = False
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(final_val))
                        applied.append({
                            "param": pname, "value": final_val,
                            "variable": var, "source": source
                        })
                        set_ok = True
                        break
                    except Exception as e:
                        failed.append({"param": pname, "variable": var, "error": str(e)})
                        break
            if not set_ok and not any(f["param"] == pname for f in failed):
                skipped.append({
                    "param": pname, "value": final_val, "source": source,
                    "reason": "Variable not found — use search_variables to locate exact name"
                })

        return {
            "model": "ASM1", "unit": unit_name, "temp_C": temp_C,
            "applied": len(applied), "skipped": len(skipped), "failed": len(failed),
            "results": applied, "skipped_list": skipped, "failed_list": failed,
            "tip": "Run search_variables with 'mu_H' or 'mu_A' to find exact variable names."
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_asm2d_kinetics(
    unit_name:   str   = "AerTank1",
    temp_C:      float = 20.0,
    # Pass individual overrides; None = use research default
    mu_H:        float = None,
    b_H:         float = None,
    Y_H:         float = None,
    q_fe:        float = None,
    eta_NO3_H:   float = None,
    K_h:         float = None,
    eta_NO3_hyd: float = None,
    mu_PAO:      float = None,
    b_PAO:       float = None,
    q_PHA:       float = None,
    q_PP:        float = None,
    Y_PAO:       float = None,
    Y_PO4:       float = None,
    mu_AUT:      float = None,
    b_AUT:       float = None,
    K_NH4_AUT:   float = None,
    K_O2_AUT:    float = None,
    k_PRE:       float = None,
    k_RED:       float = None,
) -> dict:
    """Set ASM2d kinetic and stoichiometric parameters on a biological unit.

    Covers heterotrophic, PAO, autotrophic, and chemical precipitation
    sub-models. Any argument left as None uses the IWA/Egyptian research
    default, Arrhenius-corrected to temp_C.

    Args:
        unit_name:  SUMO unit process name.
        temp_C:     Operating temperature for Arrhenius correction (°C).
        mu_H … k_RED: Parameter overrides (None = research default).
    """
    try:
        ds = _make_ds()
        defaults = _correct_asm_params("ASM2d", temp_C)

        param_map = {
            "mu_H":        (mu_H,        [f"Sumo__Plant__{unit_name}__param__mu_H"]),
            "b_H":         (b_H,         [f"Sumo__Plant__{unit_name}__param__b_H"]),
            "Y_H":         (Y_H,         [f"Sumo__Plant__{unit_name}__param__Y_H"]),
            "q_fe":        (q_fe,        [f"Sumo__Plant__{unit_name}__param__q_fe"]),
            "eta_NO3_H":   (eta_NO3_H,   [f"Sumo__Plant__{unit_name}__param__eta_NO3_H"]),
            "K_h":         (K_h,         [f"Sumo__Plant__{unit_name}__param__K_h"]),
            "eta_NO3":     (eta_NO3_hyd, [f"Sumo__Plant__{unit_name}__param__eta_NO3"]),
            "mu_PAO":      (mu_PAO,      [f"Sumo__Plant__{unit_name}__param__mu_PAO"]),
            "b_PAO":       (b_PAO,       [f"Sumo__Plant__{unit_name}__param__b_PAO"]),
            "q_PHA":       (q_PHA,       [f"Sumo__Plant__{unit_name}__param__q_PHA"]),
            "q_PP":        (q_PP,        [f"Sumo__Plant__{unit_name}__param__q_PP"]),
            "Y_PAO":       (Y_PAO,       [f"Sumo__Plant__{unit_name}__param__Y_PAO"]),
            "Y_PO4":       (Y_PO4,       [f"Sumo__Plant__{unit_name}__param__Y_PO4"]),
            "mu_AUT":      (mu_AUT,      [f"Sumo__Plant__{unit_name}__param__mu_AUT",
                                           f"Sumo__Plant__{unit_name}__param__mu_A"]),
            "b_AUT":       (b_AUT,       [f"Sumo__Plant__{unit_name}__param__b_AUT",
                                           f"Sumo__Plant__{unit_name}__param__b_A"]),
            "K_NH4_AUT":   (K_NH4_AUT,   [f"Sumo__Plant__{unit_name}__param__K_NH4_AUT",
                                           f"Sumo__Plant__{unit_name}__param__K_NH"]),
            "K_O2_AUT":    (K_O2_AUT,    [f"Sumo__Plant__{unit_name}__param__K_O2_AUT",
                                           f"Sumo__Plant__{unit_name}__param__K_OA"]),
            "k_PRE":       (k_PRE,       [f"Sumo__Plant__{unit_name}__param__k_PRE"]),
            "k_RED":       (k_RED,       [f"Sumo__Plant__{unit_name}__param__k_RED"]),
        }

        all_vars = ds.sumo.getVariableNames()
        applied, skipped, failed = [], [], []

        for pname, (user_val, candidates) in param_map.items():
            final_val = user_val if user_val is not None else defaults.get(pname)
            if final_val is None:
                continue
            source = "user" if user_val is not None else f"research_default@{temp_C}°C"
            set_ok = False
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(final_val))
                        applied.append({"param": pname, "value": final_val,
                                        "variable": var, "source": source})
                        set_ok = True
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            if not set_ok and not any(f["param"] == pname for f in failed):
                skipped.append({"param": pname, "value": final_val,
                                 "reason": "Variable not found"})

        return {
            "model": "ASM2d", "unit": unit_name, "temp_C": temp_C,
            "applied": len(applied), "skipped": len(skipped), "failed": len(failed),
            "results": applied, "skipped_list": skipped, "failed_list": failed,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_asm3_kinetics(
    unit_name:  str   = "AerTank1",
    temp_C:     float = 20.0,
    mu_H:       float = None,
    b_H_O2:     float = None,
    b_H_NO:     float = None,
    k_STO:      float = None,
    Y_STO_O2:   float = None,
    Y_STO_NO:   float = None,
    Y_H_O2:     float = None,
    Y_H_NO:     float = None,
    k_h:        float = None,
    K_X:        float = None,
    K_S:        float = None,
    K_STO:      float = None,
    eta_NO:     float = None,
    mu_A:       float = None,
    b_A_O:      float = None,
    b_A_NO:     float = None,
    K_A_NH:     float = None,
    K_A_O:      float = None,
    Y_A:        float = None,
    f_XI:       float = None,
) -> dict:
    """Set ASM3 kinetic and stoichiometric parameters on a biological unit.

    ASM3 uses endogenous respiration and internal storage (X_STO).
    Any argument left as None uses the IWA research default,
    Arrhenius-corrected to temp_C.

    Args:
        unit_name: SUMO unit process name.
        temp_C:    Operating temperature for Arrhenius correction (°C).
    """
    try:
        ds = _make_ds()
        defaults = _correct_asm_params("ASM3", temp_C)

        param_map = {
            "mu_H":     (mu_H,     [f"Sumo__Plant__{unit_name}__param__mu_H"]),
            "b_H_O2":   (b_H_O2,   [f"Sumo__Plant__{unit_name}__param__b_H_O2"]),
            "b_H_NO":   (b_H_NO,   [f"Sumo__Plant__{unit_name}__param__b_H_NO"]),
            "k_STO":    (k_STO,    [f"Sumo__Plant__{unit_name}__param__k_STO"]),
            "Y_STO_O2": (Y_STO_O2, [f"Sumo__Plant__{unit_name}__param__Y_STO_O2"]),
            "Y_STO_NO": (Y_STO_NO, [f"Sumo__Plant__{unit_name}__param__Y_STO_NO"]),
            "Y_H_O2":   (Y_H_O2,   [f"Sumo__Plant__{unit_name}__param__Y_H_O2"]),
            "Y_H_NO":   (Y_H_NO,   [f"Sumo__Plant__{unit_name}__param__Y_H_NO"]),
            "k_h":      (k_h,      [f"Sumo__Plant__{unit_name}__param__k_h"]),
            "K_X":      (K_X,      [f"Sumo__Plant__{unit_name}__param__K_X"]),
            "K_S":      (K_S,      [f"Sumo__Plant__{unit_name}__param__K_S"]),
            "K_STO":    (K_STO,    [f"Sumo__Plant__{unit_name}__param__K_STO"]),
            "eta_NO":   (eta_NO,   [f"Sumo__Plant__{unit_name}__param__eta_NO"]),
            "mu_A":     (mu_A,     [f"Sumo__Plant__{unit_name}__param__mu_A"]),
            "b_A_O":    (b_A_O,    [f"Sumo__Plant__{unit_name}__param__b_A_O",
                                     f"Sumo__Plant__{unit_name}__param__b_A"]),
            "b_A_NO":   (b_A_NO,   [f"Sumo__Plant__{unit_name}__param__b_A_NO"]),
            "K_A_NH":   (K_A_NH,   [f"Sumo__Plant__{unit_name}__param__K_A_NH",
                                     f"Sumo__Plant__{unit_name}__param__K_NH"]),
            "K_A_O":    (K_A_O,    [f"Sumo__Plant__{unit_name}__param__K_A_O",
                                     f"Sumo__Plant__{unit_name}__param__K_OA"]),
            "Y_A":      (Y_A,      [f"Sumo__Plant__{unit_name}__param__Y_A"]),
            "f_XI":     (f_XI,     [f"Sumo__Plant__{unit_name}__param__f_XI"]),
        }

        all_vars = ds.sumo.getVariableNames()
        applied, skipped, failed = [], [], []

        for pname, (user_val, candidates) in param_map.items():
            final_val = user_val if user_val is not None else defaults.get(pname)
            if final_val is None:
                continue
            source = "user" if user_val is not None else f"research_default@{temp_C}°C"
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(final_val))
                        applied.append({"param": pname, "value": final_val,
                                        "variable": var, "source": source})
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            else:
                skipped.append({"param": pname, "value": final_val,
                                 "reason": "Variable not found"})

        return {
            "model": "ASM3", "unit": unit_name, "temp_C": temp_C,
            "applied": len(applied), "skipped": len(skipped), "failed": len(failed),
            "results": applied, "skipped_list": skipped,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def apply_temperature_correction(
    model: str  = "ASM1",
    temp_C: float = 25.0,
    unit_name: str = "AerTank1",
) -> dict:
    """Re-apply all Arrhenius temperature corrections for an ASM model at a new temperature.

    Useful when switching between Egyptian summer (25–30°C) and winter (15–18°C)
    operating conditions. Corrects all rate parameters with θ values defined in
    RESEARCH_DEFAULTS.

    Args:
        model:     'ASM1', 'ASM2d', or 'ASM3'
        temp_C:    New operating temperature (°C)
        unit_name: SUMO unit to apply corrections to
    """
    try:
        corrected = _correct_asm_params(model, temp_C)
        raw       = RESEARCH_DEFAULTS.get(model, {})

        summary = []
        for pname, new_val in corrected.items():
            old_val  = raw[pname]["val"]
            theta    = raw[pname].get("theta")
            if theta:
                summary.append({
                    "param":   pname,
                    "theta":   theta,
                    "val_20C": old_val,
                    f"val_{int(temp_C)}C": new_val,
                    "change_pct": round((new_val - old_val) / old_val * 100, 1),
                })

        # Identify parameters most affected (flag >20% change)
        high_impact = [s for s in summary if abs(s["change_pct"]) > 20]

        return {
            "model":      model,
            "temp_C":     temp_C,
            "unit_name":  unit_name,
            "corrected_params": len(summary),
            "high_impact_params": high_impact,
            "all_corrections": summary,
            "note": (
                f"Call set_{model.lower()}_kinetics(unit_name='{unit_name}', temp_C={temp_C}) "
                f"to apply these corrected values to the model."
            )
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP B — Plant-Wide & Influent Parameters
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def set_plant_wide_parameters(
    temp_C:        float = None,
    law48_target:  str   = "drain",   # 'nile' or 'drain'
) -> dict:
    """Set the global plant temperature and update the Law 48 compliance limits
    in CONFIG to match the chosen discharge target.

    Args:
        temp_C:       Plant operating temperature (°C). If None, uses Egyptian
                      summer default (25°C).
        law48_target: 'nile' (stricter Nile limits) or 'drain' (agricultural
                      drain limits). Updates CONFIG['law48_limits'].
    """
    try:
        t = temp_C if temp_C is not None else RESEARCH_DEFAULTS["influent_egypt"]["Temp_C"]
        limits_key = "law48_nile" if law48_target == "nile" else "law48_drain"
        CONFIG["law48_limits"] = RESEARCH_DEFAULTS[limits_key].copy()
        CONFIG["plant_temp_C"] = t

        # Attempt to set global temperature variable in the model
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        temp_candidates = [
            "Sumo__Plant__param__T",
            "Sumo__Plant__Influent__param__T",
            "Sumo__param__T",
        ]
        temp_set = False
        for var in temp_candidates:
            if var in all_vars:
                try:
                    ds.sumo.set(var, float(t))
                    temp_set = True
                    break
                except Exception:
                    pass

        return {
            "plant_temp_C":    t,
            "law48_target":    law48_target,
            "law48_limits_applied": CONFIG["law48_limits"],
            "temp_variable_set": temp_set,
            "note": (
                "Run apply_temperature_correction for each biological unit to "
                "update ASM kinetics to this temperature."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_influent_parameters(
    unit_name:   str   = "Influent",
    Q_m3d:       float = None,
    COD_mgL:     float = None,
    BOD5_mgL:    float = None,
    TSS_mgL:     float = None,
    VSS_mgL:     float = None,
    TKN_mgL:     float = None,
    NH4_mgL:     float = None,
    TP_mgL:      float = None,
    pH:          float = None,
    Temp_C:      float = None,
    # COD fractionation — leave None to use Egyptian defaults
    fSI:         float = None,
    fSS:         float = None,
    fXS:         float = None,
    fXI:         float = None,
    fXBH:        float = None,
) -> dict:
    """Set influent flow, composition, and COD fractionation.

    All arguments default to typical Egyptian municipal wastewater values
    (HCWW/NWRC / El-Gharbia / Arab El-Madabegh literature).

    Args:
        unit_name:  SUMO influent unit name.
        Q_m3d … fXBH: Influent parameters. None = Egyptian research default.
    """
    try:
        ds = _make_ds()
        eg = RESEARCH_DEFAULTS["influent_egypt"]

        raw_map = {
            "Q":    (Q_m3d    or eg["Q_m3d"],    ["param__Q"]),
            "S_COD":(COD_mgL  or eg["COD_mgL"],  ["param__S_COD", "param__COD"]),
            "X_TSS":(TSS_mgL  or eg["TSS_mgL"],  ["param__X_TSS", "param__TSS"]),
            "X_VSS":(VSS_mgL  or eg["VSS_mgL"],  ["param__X_VSS"]),
            "S_TKN":(TKN_mgL  or eg["TKN_mgL"],  ["param__S_TKN", "param__TKN"]),
            "S_NH4":(NH4_mgL  or eg["NH4_mgL"],  ["param__S_NH4", "param__NH4"]),
            "S_TP": (TP_mgL   or eg["TP_mgL"],   ["param__S_TP",  "param__TP"]),
            "pH":   (pH       or eg["pH"],        ["param__pH"]),
            "T":    (Temp_C   or eg["Temp_C"],    ["param__T"]),
            # Fractionation
            "fSI":  (fSI  or eg["fSI"],  ["param__fSI",  "param__f_SI"]),
            "fSS":  (fSS  or eg["fSS"],  ["param__fSS",  "param__f_SS"]),
            "fXS":  (fXS  or eg["fXS"],  ["param__fXS",  "param__f_XS"]),
            "fXI":  (fXI  or eg["fXI"],  ["param__fXI",  "param__f_XI"]),
            "fXBH": (fXBH or eg["fXBH"], ["param__fXBH", "param__f_XBH"]),
        }

        all_vars = ds.sumo.getVariableNames()
        applied, failed = [], []

        for short_name, (value, suffixes) in raw_map.items():
            candidates = [f"Sumo__Plant__{unit_name}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": short_name, "value": value,
                                        "variable": var})
                        break
                    except Exception as e:
                        failed.append({"param": short_name, "error": str(e)})
                        break
            else:
                failed.append({"param": short_name,
                                "reason": "Variable not found in compiled model"})

        return {
            "unit": unit_name, "applied": len(applied), "failed": len(failed),
            "results": applied, "failed_list": failed,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP C — Unit Process Parameter Tools
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def set_primary_clarifier_parameters(
    unit_name:             str   = "PrimClar1",
    surface_area_m2:       float = None,
    overflow_rate_m3m2d:   float = None,
    solids_loading_kgm2d:  float = None,
    capture_efficiency:    float = None,
    sludge_concentration_gL: float = None,
    HRT_h:                 float = None,
) -> dict:
    """Set primary clarifier design parameters.

    Research defaults (Metcalf & Eddy 5th ed.):
      overflow rate   = 32–48 m³/(m²·d)  → default 40
      solids loading  = 100–150 kg/(m²·d) → default 120
      capture efficiency = 50–70%          → default 60%
      sludge concentration = 2–6% TS      → default 40 g/L

    Args:
        unit_name: SUMO unit name.
        All others: design parameters; None = research default.
    """
    try:
        ds  = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        param_map = {
            "A":           (surface_area_m2      or None, ["param__A", "param__Area"]),
            "SOR":         (overflow_rate_m3m2d   or 40.0, ["param__SOR", "param__overflow_rate"]),
            "SLR":         (solids_loading_kgm2d  or 120.0,["param__SLR", "param__solids_loading"]),
            "eff_removal": (capture_efficiency     or 0.60, ["param__eff_removal", "param__eta_TSS"]),
            "C_sludge":    (sludge_concentration_gL or 40.0,["param__C_sludge","param__X_underflow"]),
            "HRT":         (HRT_h                  or 2.0,  ["param__HRT","param__tau"]),
        }

        applied, failed = [], []
        for pname, (value, suffixes) in param_map.items():
            if value is None:
                continue
            candidates = [f"Sumo__Plant__{unit_name}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": pname, "value": value, "variable": var})
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            else:
                failed.append({"param": pname, "reason": "not found"})

        return {"unit": unit_name, "applied": len(applied), "results": applied,
                "failed": failed}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_aeration_tank_parameters(
    unit_name:   str   = "AerTank1",
    volume_m3:   float = None,
    HRT_h:       float = None,
    SRT_d:       float = None,
    DO_setpoint_mgL: float = None,
    KLa_h:       float = None,
    SOTE_pct:    float = None,
    MLSS_mgL:    float = None,
    temp_C:      float = None,
) -> dict:
    """Set aeration tank hydraulic, process, and aeration parameters.

    Egyptian warm-climate design guidance (Metcalf & Eddy 5th / field audits):
      SRT    = 10–20 d (longer for reliable nitrification at summer temps)
      HRT    = 4–8 h  (conventional CAS)
      DO     = 1.5–2.5 mg/L  (lower for energy saving; never < 1.0)
      MLSS   = 2000–4000 mg/L
      SOTE   = 10–25% (fine-bubble diffusers typical in Egypt)
      KLa    = 50–200 h⁻¹ (design; adjusted by blower control)

    Args:
        unit_name: SUMO unit name.
        All others: design parameters; None = research default.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        t = temp_C or CONFIG.get("plant_temp_C", 25.0)

        param_map = {
            "V":          (volume_m3        or None,  ["param__V",   "param__Volume"]),
            "HRT":        (HRT_h            or 6.0,   ["param__HRT", "param__tau"]),
            "SRT":        (SRT_d            or 15.0,  ["param__SRT", "param__sludge_age"]),
            "DO_sp":      (DO_setpoint_mgL  or 2.0,   ["param__DO_setpoint","param__DO_sp",
                                                        "param__S_O_sp"]),
            "KLa":        (KLa_h            or 100.0, ["param__KLa", "param__kLa"]),
            "SOTE":       (SOTE_pct         or 20.0,  ["param__SOTE","param__OTE"]),
            "MLSS":       (MLSS_mgL         or 3000.0,["param__MLSS","param__X_TSS_set"]),
            "T":          (t,                         ["param__T"]),
        }

        applied, failed = [], []
        for pname, entry in param_map.items():
            # entry is either (value, suffixes) or just suffixes with value prepended
            if isinstance(entry, tuple) and len(entry) == 2:
                value, suffixes = entry
            else:
                continue
            if value is None:
                continue
            candidates = [f"Sumo__Plant__{unit_name}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": pname, "value": value, "variable": var})
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            else:
                failed.append({"param": pname, "reason": "not found"})

        return {
            "unit": unit_name, "temp_C": t,
            "applied": len(applied), "failed": len(failed),
            "results": applied, "failed_list": failed,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_anoxic_zone_parameters(
    unit_name:      str   = "AnoxTank1",
    volume_m3:      float = None,
    HRT_h:          float = None,
    NO3_recycle_ratio: float = None,
    DO_max_mgL:     float = None,
) -> dict:
    """Set anoxic zone parameters for pre- or post-denitrification.

    Research defaults:
      HRT            = 1–3 h  (pre-denitrification)
      NO3 recycle    = 2–4× Q (internal recycle to anoxic)
      DO in anoxic   ≤ 0.2 mg/L (must be kept low)

    Args:
        unit_name:          SUMO unit name.
        volume_m3:          Zone volume.
        HRT_h:              Hydraulic retention time (h).
        NO3_recycle_ratio:  Internal recycle flow / influent flow ratio.
        DO_max_mgL:         Maximum allowable DO in anoxic zone (mg/L).
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        param_map = {
            "V":          (volume_m3          or None,  ["param__V"]),
            "HRT":        (HRT_h              or 2.0,   ["param__HRT","param__tau"]),
            "IR_ratio":   (NO3_recycle_ratio   or 3.0,   ["param__IR","param__recycle_ratio",
                                                           "param__Q_IR_ratio"]),
            "DO_max":     (DO_max_mgL          or 0.2,   ["param__DO_max","param__S_O_max"]),
        }

        applied, failed = [], []
        for pname, (value, suffixes) in param_map.items():
            if value is None:
                continue
            candidates = [f"Sumo__Plant__{unit_name}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": pname, "value": value, "variable": var})
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            else:
                failed.append({"param": pname, "reason": "not found"})

        return {"unit": unit_name, "applied": len(applied),
                "results": applied, "failed": failed}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_anaerobic_zone_parameters(
    unit_name:   str   = "AnaTank1",
    volume_m3:   float = None,
    HRT_h:       float = None,
    DO_max_mgL:  float = None,
    VFA_target_mgL: float = None,
) -> dict:
    """Set anaerobic zone parameters (for EBPR / P-release zone).

    Research defaults (ASM2d calibration, Metcalf & Eddy):
      HRT          = 1–2 h
      DO in zone   ≤ 0.02 mg/L
      VFA target   ≥ 25 mg COD/L (minimum for stable PAO activity)

    Args:
        unit_name:      SUMO unit name.
        volume_m3:      Zone volume (m³).
        HRT_h:          HRT (h).
        DO_max_mgL:     Maximum DO (must be < 0.05 mg/L for EBPR).
        VFA_target_mgL: Target VFA (acetate) concentration (mg COD/L).
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        param_map = {
            "V":          (volume_m3       or None,  ["param__V"]),
            "HRT":        (HRT_h           or 1.5,   ["param__HRT","param__tau"]),
            "DO_max":     (DO_max_mgL      or 0.02,  ["param__DO_max","param__S_O_max"]),
            "VFA_target": (VFA_target_mgL  or 30.0,  ["param__VFA_target","param__S_A_sp"]),
        }

        applied, failed = [], []
        for pname, (value, suffixes) in param_map.items():
            if value is None:
                continue
            candidates = [f"Sumo__Plant__{unit_name}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": pname, "value": value, "variable": var})
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            else:
                failed.append({"param": pname, "reason": "not found"})

        return {"unit": unit_name, "applied": len(applied),
                "results": applied, "failed": failed}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_secondary_clarifier_parameters(
    unit_name:        str   = "SecClar1",
    surface_area_m2:  float = None,
    overflow_rate_m3m2d: float = None,
    sludge_blanket_m: float = None,
    underflow_conc_gL:   float = None,
    # Takács settler model parameters
    v0:    float = None,
    v0_p:  float = None,
    r_h:   float = None,
    r_p:   float = None,
    f_ns:  float = None,
) -> dict:
    """Set secondary clarifier hydraulic and Takács settler model parameters.

    Takács defaults (Takács et al. 1991 / BSM1):
      v0    = 474 m/d   (max theoretical settling)
      v0_p  = 250 m/d   (max practical settling)
      r_h   = 0.000576 m³/g  (hindrance zone)
      r_p   = 0.00286  m³/g  (flocculant zone)
      f_ns  = 0.00228        (non-settleable fraction)

    Hydraulic defaults (Metcalf & Eddy 5th ed.):
      overflow rate  = 16–32 m³/(m²·d)  → default 24
      underflow conc = 8–12 g TSS/L     → default 10
      sludge blanket depth ≤ 1 m

    Args:
        unit_name: SUMO unit name.
        All others: design or Takács parameters; None = research default.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        td = RESEARCH_DEFAULTS["takacs"]

        param_map = {
            "A":         (surface_area_m2     or None,  ["param__A","param__Area"]),
            "SOR":       (overflow_rate_m3m2d or 24.0,  ["param__SOR","param__overflow_rate"]),
            "h_blanket": (sludge_blanket_m    or 0.5,   ["param__h_blanket","param__sludge_depth"]),
            "X_R":       (underflow_conc_gL   or 10.0,  ["param__X_R","param__C_underflow"]),
            "v0":        (v0   or td["v0"]["val"],   ["param__v0",  "param__Veiling_0"]),
            "v0_p":      (v0_p or td["v0_p"]["val"],["param__v0_p", "param__vmax_p"]),
            "r_h":       (r_h  or td["r_h"]["val"], ["param__r_h",  "param__rh"]),
            "r_p":       (r_p  or td["r_p"]["val"], ["param__r_p",  "param__rp"]),
            "f_ns":      (f_ns or td["f_ns"]["val"],["param__f_ns", "param__fns"]),
        }

        applied, failed = [], []
        for pname, (value, suffixes) in param_map.items():
            if value is None:
                continue
            candidates = [f"Sumo__Plant__{unit_name}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": pname, "value": value, "variable": var})
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            else:
                failed.append({"param": pname, "reason": "not found"})

        return {"unit": unit_name, "applied": len(applied),
                "results": applied, "failed": failed,
                "takacs_note": "v0, v0_p, r_h, r_p, f_ns control the Takács settling model."}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_mbr_parameters(
    unit_name:       str   = "MBR1",
    flux_Lm2h:       float = None,
    TMP_kPa:         float = None,
    permeability_LM2hbar: float = None,
    backwash_interval_min: float = None,
    backwash_duration_s:   float = None,
    MLSS_mgL:        float = None,
) -> dict:
    """Set membrane bioreactor (MBR) operating parameters.

    Research defaults (Metcalf & Eddy 5th ed. / Judd MBR Book):
      flux            = 15–25 L/(m²·h)    → default 20
      TMP             = 10–40 kPa         → default 20
      permeability    = 150–400 LMH/bar   → default 250
      backwash interval = 8–12 min        → default 10
      backwash duration = 30–60 s         → default 30
      MLSS            = 8,000–12,000 mg/L → default 10,000

    Args:
        unit_name: SUMO MBR unit name.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        param_map = {
            "J":        (flux_Lm2h              or 20.0,  ["param__J","param__flux"]),
            "TMP":      (TMP_kPa                or 20.0,  ["param__TMP"]),
            "K_mem":    (permeability_LM2hbar   or 250.0, ["param__K_mem","param__permeability"]),
            "t_BW":     (backwash_interval_min  or 10.0,  ["param__t_BW","param__backwash_interval"]),
            "dt_BW":    (backwash_duration_s    or 30.0,  ["param__dt_BW","param__backwash_duration"]),
            "MLSS":     (MLSS_mgL               or 10000.0,["param__MLSS","param__X_TSS_set"]),
        }

        applied, failed = [], []
        for pname, (value, suffixes) in param_map.items():
            candidates = [f"Sumo__Plant__{unit_name}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": pname, "value": value, "variable": var})
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            else:
                failed.append({"param": pname, "reason": "not found"})

        return {"unit": unit_name, "applied": len(applied),
                "results": applied, "failed": failed}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_ras_was_parameters(
    ras_unit:    str   = "RAS_Pump",
    was_unit:    str   = "WAS_Pump",
    Q_RAS_m3d:   float = None,
    RAS_ratio:   float = None,
    Q_WAS_m3d:   float = None,
    SRT_target_d:float = None,
    Q_influent_m3d: float = None,
) -> dict:
    """Set RAS (return activated sludge) and WAS (waste activated sludge) pump parameters.

    Egyptian practice defaults:
      RAS ratio      = 0.5–1.0 × Q_influent  → default 0.75
      SRT target     = 10–20 d                → default 15 d
      WAS calculated from SRT: Q_WAS ≈ V_reactor × MLSS / (SRT × X_R)

    Args:
        ras_unit:      SUMO RAS pump unit name.
        was_unit:      SUMO WAS pump unit name.
        Q_RAS_m3d:     RAS flow rate (m³/d). If None, calculated from RAS_ratio × Q_influent.
        RAS_ratio:     RAS/Q ratio (—). Default 0.75.
        Q_WAS_m3d:     WAS flow rate (m³/d). If None, use SRT_target to back-calculate.
        SRT_target_d:  Target sludge retention time (d). Used to set WAS flow.
        Q_influent_m3d: Influent flow for ratio calculation. Uses CONFIG default if None.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        eg = RESEARCH_DEFAULTS["influent_egypt"]

        Q_inf   = Q_influent_m3d or eg["Q_m3d"]
        ras_r   = RAS_ratio or 0.75
        Q_ras   = Q_RAS_m3d if Q_RAS_m3d is not None else round(Q_inf * ras_r, 1)
        SRT_t   = SRT_target_d or 15.0
        Q_was   = Q_WAS_m3d   # may remain None — set only if provided or SRT given

        applied, failed = [], []

        def try_set(unit, suffixes, value, label):
            candidates = [f"Sumo__Plant__{unit}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": label, "value": value, "variable": var})
                        return True
                    except Exception as e:
                        failed.append({"param": label, "error": str(e)})
                        return False
            failed.append({"param": label, "reason": "not found"})
            return False

        # RAS
        try_set(ras_unit, ["param__Q", "param__Q_RAS"], Q_ras, "Q_RAS")
        try_set(ras_unit, ["param__RAS_ratio", "param__ratio"], ras_r, "RAS_ratio")

        # WAS
        if Q_was is not None:
            try_set(was_unit, ["param__Q", "param__Q_WAS"], Q_was, "Q_WAS")
        try_set(was_unit, ["param__SRT_sp", "param__SRT_target","param__sludge_age_sp"],
                SRT_t, "SRT_target")

        return {
            "Q_RAS_m3d":    Q_ras,
            "RAS_ratio":    ras_r,
            "Q_WAS_m3d":    Q_was,
            "SRT_target_d": SRT_t,
            "applied": len(applied), "failed": len(failed),
            "results": applied, "failed_list": failed,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_digester_parameters(
    unit_name:        str   = "Digester1",
    digester_type:    str   = "aerobic",   # 'aerobic' or 'anaerobic'
    volume_m3:        float = None,
    SRT_d:            float = None,
    temp_C:           float = None,
    DO_setpoint_mgL:  float = None,  # aerobic only
    OLR_kgVSSm3d:     float = None,  # anaerobic only
    biogas_yield_m3kg:float = None,  # anaerobic only
    VSS_reduction_pct:float = None,
) -> dict:
    """Set aerobic or anaerobic digester parameters.

    Aerobic digester defaults (Metcalf & Eddy):
      SRT     = 15–60 d  → default 20 d
      DO      = 1.0–2.0 mg/L
      VSS reduction = 35–50%

    Anaerobic digester defaults:
      SRT     = 15–30 d  (mesophilic, 35°C)
      temp    = 35°C (mesophilic) or 55°C (thermophilic)
      OLR     = 1.6–3.2 kg VSS/(m³·d)
      biogas  = 0.75–1.12 m³/kg VSS destroyed
      VSS reduction = 50–65%

    Args:
        unit_name:     SUMO digester unit name.
        digester_type: 'aerobic' or 'anaerobic'.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        if digester_type == "aerobic":
            t   = temp_C or CONFIG.get("plant_temp_C", 25.0)
            param_map = {
                "V":          (volume_m3          or None, ["param__V"]),
                "SRT":        (SRT_d              or 20.0, ["param__SRT","param__sludge_age"]),
                "T":          (t,                          ["param__T"]),
                "DO_sp":      (DO_setpoint_mgL    or 1.5,  ["param__DO_setpoint","param__DO_sp"]),
                "VSS_red":    (VSS_reduction_pct  or 40.0, ["param__VSS_reduction","param__eta_VSS"]),
            }
        else:  # anaerobic
            t   = temp_C or 35.0
            param_map = {
                "V":          (volume_m3          or None, ["param__V"]),
                "SRT":        (SRT_d              or 20.0, ["param__SRT","param__HRT"]),
                "T":          (t,                          ["param__T"]),
                "OLR":        (OLR_kgVSSm3d       or 2.0,  ["param__OLR"]),
                "biogas_yield":(biogas_yield_m3kg  or 0.85, ["param__biogas_yield","param__Y_biogas"]),
                "VSS_red":    (VSS_reduction_pct  or 55.0, ["param__VSS_reduction","param__eta_VSS"]),
            }

        applied, failed = [], []
        for pname, (value, suffixes) in param_map.items():
            if value is None:
                continue
            candidates = [f"Sumo__Plant__{unit_name}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": pname, "value": value, "variable": var})
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            else:
                failed.append({"param": pname, "reason": "not found"})

        return {"unit": unit_name, "type": digester_type, "temp_C": t,
                "applied": len(applied), "results": applied, "failed": failed}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_chemical_dosing_parameters(
    unit_name:       str   = "ChemDosing1",
    coagulant_type:  str   = "alum",    # 'alum' (Al₂(SO₄)₃) or 'ferric' (FeCl₃)
    dose_mgL:        float = None,
    molar_ratio:     float = None,
    target_TP_mgL:   float = None,
) -> dict:
    """Set chemical precipitation / coagulant dosing parameters.

    Research defaults (Metcalf & Eddy 5th ed.):
      Alum  dose = 75–250 mg/L; Al:P molar ratio ≈ 1.5–3.0
      Ferric dose = 40–120 mg/L; Fe:P molar ratio ≈ 1.5–3.0
      Target TP after dosing ≤ 1 mg/L (Nile limit per Law 48)

    Args:
        unit_name:      SUMO chemical dosing unit name.
        coagulant_type: 'alum' or 'ferric'.
        dose_mgL:       Coagulant dose (mg/L). None = estimate from target TP.
        molar_ratio:    Metal:P molar ratio. None = 2.0 (conservative default).
        target_TP_mgL:  Target effluent TP (mg/L). Used to estimate dose if dose_mgL=None.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        mr   = molar_ratio or 2.0
        tp_t = target_TP_mgL or 1.0
        # Estimate dose if not given: dose = mr × TP_influent × MW_metal / MW_P
        MW   = {"alum": 27.0, "ferric": 55.85}.get(coagulant_type, 27.0)
        if dose_mgL is None:
            eg_TP  = RESEARCH_DEFAULTS["influent_egypt"]["TP_mgL"]
            dose_mgL = round(mr * eg_TP * MW / 31.0, 1)

        param_map = {
            "dose":        (dose_mgL,  ["param__dose","param__C_coag","param__Q_chem"]),
            "molar_ratio": (mr,        ["param__molar_ratio","param__Me_P_ratio"]),
            "TP_target":   (tp_t,      ["param__TP_target","param__S_PO4_sp"]),
        }

        applied, failed = [], []
        for pname, (value, suffixes) in param_map.items():
            candidates = [f"Sumo__Plant__{unit_name}__{s}" for s in suffixes]
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({"param": pname, "value": value, "variable": var})
                        break
                    except Exception as e:
                        failed.append({"param": pname, "error": str(e)})
                        break
            else:
                failed.append({"param": pname, "reason": "not found"})

        return {
            "unit": unit_name, "coagulant": coagulant_type,
            "estimated_dose_mgL": dose_mgL, "molar_ratio": mr,
            "target_TP_mgL": tp_t,
            "applied": len(applied), "results": applied, "failed": failed,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP D — Dynamic Simulation Tab Parameters
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def set_dynamic_simulation_parameters(
    duration_days:       float = None,
    timestep_h:          float = None,
    output_interval_h:   float = None,
    solver:              str   = None,
    tolerance:           float = None,
    warm_up_days:        float = None,
    # Diurnal load variation
    diurnal_peak_factor: float = None,
    diurnal_min_factor:  float = None,
    # Storm / wet-weather event (applied at midpoint of simulation)
    storm_peak_factor:   float = None,
    storm_start_day:     float = None,
    storm_duration_h:    float = None,
    # Temperature variation
    summer_temp_C:       float = None,
    winter_temp_C:       float = None,
) -> dict:
    """Configure the dynamic simulation tab parameters in SUMO24.

    Egyptian climate defaults:
      warm-up period     = 10 d (reach pseudo-steady state)
      diurnal peak       = 1.8× (morning peak typical in Egyptian cities)
      diurnal minimum    = 0.4× (night-time)
      storm peak         = 3.0× for wet-weather event
      storm duration     = 6 h
      summer temp        = 28°C,  winter temp = 18°C

    Args:
        All arguments correspond to SUMO dynamic simulation settings.
        None = use Egyptian research default from RESEARCH_DEFAULTS['dynamics'].
    """
    try:
        ds = _make_ds()
        dd = RESEARCH_DEFAULTS["dynamics"]

        # Build the values dict merging user args with defaults
        settings = {
            "duration_days":       duration_days     or dd["duration_days"],
            "timestep_h":          timestep_h        or dd["timestep_h"],
            "output_interval_h":   output_interval_h or dd["output_interval_h"],
            "solver":              solver             or dd["solver"],
            "tolerance":           tolerance          or dd["tolerance"],
            "warm_up_days":        warm_up_days       or dd["warm_up_days"],
            "diurnal_peak_factor": diurnal_peak_factor or dd["diurnal_peak_factor"],
            "diurnal_min_factor":  diurnal_min_factor  or dd["diurnal_min_factor"],
            "storm_peak_factor":   storm_peak_factor   or dd["storm_peak_factor"],
            "storm_start_day":     storm_start_day     or round(settings.get("duration_days", dd["duration_days"]) / 2, 1)
                                                           if storm_peak_factor else None,
            "storm_duration_h":    storm_duration_h    or dd["storm_duration_h"],
            "summer_temp_C":       summer_temp_C       or 28.0,
            "winter_temp_C":       winter_temp_C       or 18.0,
        }

        # SUMO dynamic parameters — attempt to set via executeCommand
        applied, not_applicable = [], []
        set_cmds = {
            "duration_days":     f"set Sumo__Simulator__param__t_end {settings['duration_days']}",
            "timestep_h":        f"set Sumo__Simulator__param__dt {settings['timestep_h'] / 24}",
            "output_interval_h": f"set Sumo__Simulator__param__dt_out {settings['output_interval_h'] / 24}",
            "tolerance":         f"set Sumo__Simulator__param__tol {settings['tolerance']}",
            "warm_up_days":      f"set Sumo__Simulator__param__t_warmup {settings['warm_up_days']}",
        }

        for pname, cmd in set_cmds.items():
            try:
                ds.sumo.executeCommand(cmd)
                applied.append({"param": pname, "value": settings[pname],
                                 "command": cmd})
            except Exception:
                not_applicable.append({"param": pname,
                    "note": "Set manually in SUMO GUI → Simulate → Dynamic Settings"})

        # Store settings in CONFIG for reference by other tools
        CONFIG["dynamic_settings"] = settings

        return {
            "settings_applied":       settings,
            "sumo_commands_applied":  len(applied),
            "manual_settings_needed": not_applicable,
            "applied_list":           applied,
            "tip": (
                "For diurnal profiles and storm events, use import_influent_profile "
                "with a time-series CSV. The diurnal/storm factors above are stored "
                "in CONFIG['dynamic_settings'] for reference."
            ),
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def assume_parameters_from_research(
    unit_type:   str   = "full_plant",
    temp_C:      float = None,
    asm_model:   str   = "ASM1",
    plant_scale: str   = "medium",   # 'small' (<10k m³/d), 'medium', 'large' (>50k)
) -> dict:
    """Auto-populate research-based defaults for a unit type or the full plant.

    Chooses values based on:
    - Operating temperature (Egyptian summer = 25–30°C, winter = 15–18°C)
    - ASM model selected (ASM1, ASM2d, ASM3)
    - Plant scale

    Returns a complete parameter recommendation dict without applying to the model.
    Use the specific set_* tools to apply individual sections.

    Args:
        unit_type:   'full_plant', 'aeration_tank', 'secondary_clarifier',
                     'influent', 'asm_kinetics', 'dynamic'.
        temp_C:      Operating temperature. If None, uses Egyptian summer (25°C).
        asm_model:   'ASM1', 'ASM2d', or 'ASM3'.
        plant_scale: 'small', 'medium', or 'large'.
    """
    t = temp_C if temp_C is not None else 25.0
    is_warm = t >= 22.0

    # Scale factors for sizing
    scale_Q = {"small": 8000, "medium": 28000, "large": 80000}.get(plant_scale, 28000)
    scale_V_factor = {"small": 0.30, "medium": 1.0, "large": 2.8}.get(plant_scale, 1.0)

    # Temperature-corrected ASM kinetics
    asm_corrected = _correct_asm_params(asm_model, t)

    # Egyptian warm-climate notes
    warm_notes = []
    if is_warm and asm_model == "ASM1":
        if asm_corrected.get("mu_A", 0) > 0.8:
            warm_notes.append(
                f"mu_A @ {t}°C = {asm_corrected['mu_A']:.3f} d⁻¹ — nitrification kinetics "
                "accelerated vs 20°C default. Reduce design SRT to 8–12 d is feasible."
            )
        warm_notes.append(
            "Egyptian practice: raise Y_H to 0.75–0.90 for warm-climate calibration. "
            "IWA default 0.67 underestimates sludge production."
        )
        warm_notes.append(
            "COD fractionation: fXI often 15–20% (higher than European default) "
            "due to absence of primary clarifiers at many Egyptian plants."
        )

    result = {
        "unit_type":   unit_type,
        "temp_C":      t,
        "asm_model":   asm_model,
        "plant_scale": plant_scale,
        "warm_climate_notes": warm_notes,
    }

    if unit_type in ("full_plant", "influent"):
        eg = RESEARCH_DEFAULTS["influent_egypt"].copy()
        eg["Q_m3d"] = scale_Q
        result["influent_defaults"] = eg
        result["law48_limits_nile"]  = RESEARCH_DEFAULTS["law48_nile"]
        result["law48_limits_drain"] = RESEARCH_DEFAULTS["law48_drain"]

    if unit_type in ("full_plant", "asm_kinetics"):
        result["asm_kinetics"] = {
            "model":          asm_model,
            "reference_temp": "20°C (IWA STR-9)",
            "operating_temp": f"{t}°C (Arrhenius corrected)",
            "parameters":     asm_corrected,
        }

    if unit_type in ("full_plant", "aeration_tank"):
        srt = 12.0 if is_warm else 15.0
        hrt = 6.0
        result["aeration_tank"] = {
            "SRT_d":          srt,
            "HRT_h":          hrt,
            "DO_setpoint_mgL":2.0,
            "MLSS_mgL":       3000,
            "volume_m3":      round(scale_Q / 24 * hrt, 0),
            "SOTE_pct":       20,
            "note": f"SRT={srt}d chosen for {'warm-climate' if is_warm else 'moderate temp'} nitrification",
        }

    if unit_type in ("full_plant", "secondary_clarifier"):
        result["secondary_clarifier"] = {
            "overflow_rate_m3m2d": 24,
            "underflow_conc_gL":   10,
            "RAS_ratio":           0.75,
            **{k: v["val"] for k, v in RESEARCH_DEFAULTS["takacs"].items()},
        }

    if unit_type in ("full_plant", "dynamic"):
        result["dynamic_simulation"] = RESEARCH_DEFAULTS["dynamics"].copy()
        result["dynamic_simulation"]["recommended_summer_temp_C"] = 28.0
        result["dynamic_simulation"]["recommended_winter_temp_C"] = 18.0

    result["next_steps"] = [
        f"1. Call set_plant_wide_parameters(temp_C={t}) to set global temperature.",
        f"2. Call set_influent_parameters() to apply Egyptian influent defaults.",
        f"3. Call set_{asm_model.lower()}_kinetics(temp_C={t}) on each biological unit.",
        "4. Call set_aeration_tank_parameters(), set_secondary_clarifier_parameters(), etc.",
        "5. Call set_dynamic_simulation_parameters() for transient runs.",
        "6. Run run_steady_state() and check_compliance() to verify Law 48 compliance.",
    ]

    return result
```

---

## Step 4 — Fix the storm_start_day self-reference bug

In the `set_dynamic_simulation_parameters` tool above, the `storm_start_day` line
references `settings` before it is fully built. Find this line in the code just inserted:

```python
"storm_start_day":     storm_start_day     or round(settings.get("duration_days", dd["duration_days"]) / 2, 1)
```

Replace it with:

```python
"storm_start_day":     storm_start_day     or round((duration_days or dd["duration_days"]) / 2, 1),
```

---

## Step 5 — Save and restart

1. Save `server.py`.
2. Fully quit Claude Desktop (right-click tray icon → **Quit**).
3. Relaunch Claude Desktop.
4. In a new chat type: **"List all SUMO24 tools"** — the new tools should appear.

---

## Step 6 — Verification prompts

Test each group with these prompts in Claude Desktop:

| Prompt | Expected tool |
|---|---|
| `What are the Egyptian warm-climate defaults for a full plant at 28°C?` | `assume_parameters_from_research` |
| `Set ASM1 kinetics on AerTank1 at 27°C — use research defaults` | `set_asm1_kinetics` |
| `Set ASM2d kinetics for AerTank1, I only want to override mu_PAO to 0.8` | `set_asm2d_kinetics` |
| `Apply Arrhenius temperature correction for ASM1 at 30°C vs 20°C` | `apply_temperature_correction` |
| `Set the plant to Egyptian summer conditions (28°C), discharge to Nile` | `set_plant_wide_parameters` |
| `Set influent to Egyptian municipal wastewater defaults` | `set_influent_parameters` |
| `Set the primary clarifier PrimClar1 with overflow rate 40 m³/m²/d` | `set_primary_clarifier_parameters` |
| `Set AerTank1: SRT 15 days, DO 2.0 mg/L, HRT 6 hours` | `set_aeration_tank_parameters` |
| `Set anoxic zone parameters on AnoxTank1 with NO3 recycle ratio 3` | `set_anoxic_zone_parameters` |
| `Set Takács settler model defaults on SecClar1` | `set_secondary_clarifier_parameters` |
| `Set MBR1 flux to 20 L/m²/h, TMP 25 kPa` | `set_mbr_parameters` |
| `Set RAS ratio to 0.8 and target SRT of 12 days` | `set_ras_was_parameters` |
| `Set up the aerobic digester with SRT 20 days` | `set_digester_parameters` |
| `Set alum dosing to target TP below 1 mg/L (Nile limit)` | `set_chemical_dosing_parameters` |
| `Configure dynamic simulation: 30 days, storm event on day 15, summer 28°C` | `set_dynamic_simulation_parameters` |

---

## Notes for Cowork

### Egyptian warm-climate calibration guidance
- **All kinetic rates are at 20°C** and must be corrected using `apply_temperature_correction`.
- In Egyptian summer (25–30°C), `mu_A` (autotrophic growth) can increase 65–100% vs 20°C default.
  This means shorter minimum SRT for nitrification — but also more sensitive to toxic shocks.
- **Y_H should be raised to 0.75–0.90** for warm-climate calibration (IWA default 0.67 underestimates
  sludge production observed in Egyptian plants).
- **fXI (inert particulate COD fraction)** is often 15–20% at Egyptian plants without primary
  clarifiers — much higher than the 10% European default. This inflates TSS predictions significantly.
- **COD is the binding constraint** at most Egyptian WWTPs (Nile limit 40 mg/L), not BOD₅.
  Calibrate `K_S`, `Y_H`, and fractionation first.

### SUMO24 variable naming
All tools try multiple SUMO variable name patterns. If a set fails, call
`search_variables(keyword='mu_H')` (or the relevant parameter name) to find
the exact compiled-model variable name, then use `set_parameter` directly.

### Model paradigm consistency
ASM1 has **two decay paradigms** — do not mix them:
- **BSM1 / endogenous**: `mu_H = 4.0`, `b_H = 0.30` — used by default in these tools
- **Death-regeneration**: `mu_H = 6.0`, `b_H = 0.62` — use if your SUMO model was built this way

If you switch paradigms, update both `mu_H` and `b_H` together.
