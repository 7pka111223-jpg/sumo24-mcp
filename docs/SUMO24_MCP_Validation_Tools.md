# SUMO24 MCP — Model Validation Tools

## Context
This file adds **comprehensive validation tools** to the existing MCP server at
`F:/UNI/SUMO/MCP/PY/server.py`. These tools verify that a SUMO24 model remains
healthy and will simulate successfully after any edits made by the other tools
in this chat (parameter edits, unit additions, stream connections, scenario
changes, dataset imports, etc.).

Validation coverage:
- **Pre-flight structural checks** — does the model have what it needs to run?
- **Mass balance validation** — COD, N, P, TSS balances across the plant
- **MLSS / biomass health** — MLSS in range, SVI sanity, F/M ratio, SRT feasibility
- **DO and aeration checks** — DO setpoints, KLa, oxygen demand coverage
- **Hydraulic validation** — flow continuity, HRT reasonableness, RAS/WAS ratios
- **Kinetic parameter validation** — ASM rates within physically sensible ranges
- **Convergence diagnostics** — identify why a simulation failed or gave odd output
- **Full pre-run check** — a single "is my model safe to simulate" gate
- **Post-run sanity check** — are the simulation results physically plausible?

> ⚠️ **Do not remove or modify any existing tools.**
> Insert all new code after the last existing `@server.tool()` function,
> before any `if __name__ == "__main__"` block.

---

## File to Edit
**`F:/UNI/SUMO/MCP/PY/server.py`**

---

## Step 1 — Verify imports

All imports used by these tools should already be present from previous additions.
If any are missing, add at the top of the file:

```python
import glob
import csv as csv_mod
from pathlib import Path
from datetime import datetime
```

---

## Step 2 — Add the validation thresholds registry

Insert this block **immediately after** the `RESEARCH_DEFAULTS` dict (or at the
end of the module-level constants block if `RESEARCH_DEFAULTS` is not present):

```python
# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION THRESHOLDS
# Sources: Metcalf & Eddy 5th ed., IWA STR-9, BSM1, Egyptian practice
# Thresholds define the "green" / "yellow" / "red" bands for each parameter
# used across all validation tools below.
# ═══════════════════════════════════════════════════════════════════════════
VALIDATION_THRESHOLDS = {

    # ── MLSS & biomass ──────────────────────────────────────────────────────
    "MLSS_mgL": {
        "green":  (2000, 4000),    # healthy CAS operating range
        "yellow": (1500, 5000),    # acceptable but sub-optimal
        "red":    (800,  8000),    # outside this → operational failure
        "unit":   "mg/L",
        "note":   "Metcalf & Eddy: 2000–4000 for CAS, 3000–6000 for CMAS, "
                  "8000–12000 for MBR",
    },
    "MLVSS_MLSS_ratio": {
        "green":  (0.70, 0.85),
        "yellow": (0.60, 0.90),
        "red":    (0.50, 0.95),
        "unit":   "—",
        "note":   "Typical healthy municipal sludge. Low ratio = inorganic load",
    },
    "SVI_mLg": {
        "green":  (50,  150),
        "yellow": (30,  200),
        "red":    (10,  400),
        "unit":   "mL/g",
        "note":   "Sludge Volume Index. >150 = bulking risk",
    },
    "FM_ratio": {                  # food-to-microorganism ratio
        "green":  (0.15, 0.40),
        "yellow": (0.05, 0.60),
        "red":    (0.02, 1.0),
        "unit":   "kg BOD/(kg VSS·d)",
        "note":   "Conventional CAS: 0.2–0.4. Extended aeration: 0.05–0.15",
    },
    "SRT_d": {
        "green":  (8,  20),        # typical for municipal BNR
        "yellow": (5,  40),
        "red":    (3,  60),
        "unit":   "d",
        "note":   "Minimum SRT for nitrification at 20°C ≈ 5 d; "
                  "3–5 d at 25°C (Egyptian summer)",
    },
    "HRT_h": {
        "green":  (4,  12),
        "yellow": (2,  36),
        "red":    (1,  72),
        "unit":   "h",
        "note":   "Conventional CAS: 4–8 h. Extended aeration: 18–36 h",
    },

    # ── DO & aeration ───────────────────────────────────────────────────────
    "DO_aerobic_mgL": {
        "green":  (1.5, 2.5),
        "yellow": (1.0, 4.0),
        "red":    (0.5, 8.0),
        "unit":   "mg/L",
        "note":   "Aerobic zones. <1 mg/L impairs nitrification",
    },
    "DO_anoxic_mgL": {
        "green":  (0.0, 0.2),
        "yellow": (0.0, 0.5),
        "red":    (0.0, 1.0),
        "unit":   "mg/L",
        "note":   "Anoxic zones — must stay low for denitrification",
    },
    "DO_anaerobic_mgL": {
        "green":  (0.0, 0.02),
        "yellow": (0.0, 0.05),
        "red":    (0.0, 0.2),
        "unit":   "mg/L",
        "note":   "Anaerobic zones — critical for EBPR",
    },
    "KLa_h": {
        "green":  (50,  250),
        "yellow": (20,  400),
        "red":    (5,   800),
        "unit":   "h⁻¹",
        "note":   "Oxygen transfer coefficient. Wildly out-of-range = sensor error",
    },

    # ── Hydraulic / flow ────────────────────────────────────────────────────
    "RAS_ratio": {
        "green":  (0.50, 1.00),
        "yellow": (0.25, 1.50),
        "red":    (0.10, 3.00),
        "unit":   "—",
        "note":   "RAS flow / influent flow. Too low = sludge washout",
    },
    "overflow_rate_sec_clar": {
        "green":  (16, 32),
        "yellow": (8,  48),
        "red":    (4,  80),
        "unit":   "m³/(m²·d)",
        "note":   "Secondary clarifier surface overflow rate",
    },
    "overflow_rate_prim_clar": {
        "green":  (30, 48),
        "yellow": (20, 60),
        "red":    (10, 100),
        "unit":   "m³/(m²·d)",
        "note":   "Primary clarifier surface overflow rate",
    },
    "underflow_conc_sec_clar": {
        "green":  (8,   12),
        "yellow": (6,   15),
        "red":    (3,   20),
        "unit":   "g/L",
        "note":   "RAS sludge concentration. <6 g/L = poor thickening",
    },
    "flow_continuity_error_pct": {
        "green":  (0,  5),
        "yellow": (5,  10),
        "red":    (10, 100),
        "unit":   "%",
        "note":   "|Q_in − Q_out − Q_WAS| / Q_in",
    },

    # ── Influent / load ──────────────────────────────────────────────────────
    "BOD_COD_ratio": {
        "green":  (0.40, 0.70),
        "yellow": (0.30, 0.85),
        "red":    (0.10, 0.95),
        "unit":   "—",
        "note":   "Biodegradability. Egyptian domestic: 0.49–0.88 (mean 0.67)",
    },
    "VSS_TSS_ratio": {
        "green":  (0.70, 0.85),
        "yellow": (0.60, 0.95),
        "red":    (0.40, 1.00),
        "unit":   "—",
        "note":   "Volatile fraction of TSS. Higher = more organic load",
    },
    "COD_N_ratio": {               # for denitrification feasibility
        "green":  (8,  15),
        "yellow": (5,  20),
        "red":    (3,  30),
        "unit":   "—",
        "note":   "COD:TKN. <5 = external carbon needed for denitrification",
    },
    "pH": {
        "green":  (6.8, 7.8),
        "yellow": (6.0, 8.5),
        "red":    (5.0, 9.5),
        "unit":   "—",
        "note":   "Biological activity severely impaired outside green range",
    },
    "Temp_C": {
        "green":  (15, 30),        # Egyptian range
        "yellow": (10, 35),
        "red":    (5,  45),
        "unit":   "°C",
        "note":   "Egyptian plants typically 18–32°C year-round",
    },

    # ── Mass balance tolerances ─────────────────────────────────────────────
    "mass_balance_error_pct": {
        "green":  (0,  5),
        "yellow": (5,  10),
        "red":    (10, 100),
        "unit":   "%",
        "note":   "|Σ in − Σ out − accumulation − reaction| / Σ in",
    },

    # ── ASM kinetic sanity bounds ───────────────────────────────────────────
    "ASM_kinetic_bounds": {
        "mu_H":  {"min": 1.0,    "max": 13.2, "unit": "d⁻¹"},
        "K_S":   {"min": 1.0,    "max": 300.0,"unit": "g COD/m³"},
        "b_H":   {"min": 0.05,   "max": 1.6,  "unit": "d⁻¹"},
        "Y_H":   {"min": 0.30,   "max": 0.95, "unit": "g COD/g COD"},
        "mu_A":  {"min": 0.2,    "max": 2.0,  "unit": "d⁻¹"},
        "K_NH":  {"min": 0.1,    "max": 5.0,  "unit": "g N/m³"},
        "b_A":   {"min": 0.02,   "max": 0.3,  "unit": "d⁻¹"},
        "Y_A":   {"min": 0.07,   "max": 0.30, "unit": "g COD/g N"},
        "k_h":   {"min": 0.5,    "max": 10.0, "unit": "d⁻¹"},
        "K_X":   {"min": 0.005,  "max": 1.0,  "unit": "g COD/g COD"},
    },
}


# Helper: classify a value against thresholds
def _classify(value, threshold_key):
    """Return ('green'|'yellow'|'red'|'unknown', message)."""
    t = VALIDATION_THRESHOLDS.get(threshold_key)
    if t is None or value is None:
        return ("unknown", f"No threshold or value for {threshold_key}")
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ("unknown", f"Non-numeric value for {threshold_key}")

    g_lo, g_hi = t["green"]
    y_lo, y_hi = t["yellow"]
    r_lo, r_hi = t["red"]

    if g_lo <= v <= g_hi:
        return ("green",  f"{v} {t['unit']} — healthy")
    if y_lo <= v <= y_hi:
        return ("yellow", f"{v} {t['unit']} — acceptable but sub-optimal")
    if r_lo <= v <= r_hi:
        return ("red",    f"{v} {t['unit']} — outside design envelope")
    return ("red", f"{v} {t['unit']} — far outside physical limits")
```

---

## Step 3 — Insert all new validation tools

Find the **last** `@server.tool()` function and insert this block
**immediately after** it, before any `if __name__ == "__main__"` block.

```python
# ═══════════════════════════════════════════════════════════════════════════
# GROUP A — Structural / Pre-flight Validation
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def validate_model_structure() -> dict:
    """Structural pre-flight check: does the model have what it needs to simulate?

    Verifies DLL + state.xml exist and are consistent, and that the
    minimum required unit processes are present (influent, at least one
    reactor, at least one clarifier, effluent).
    """
    try:
        issues, warnings, passes = [], [], []

        dll_path   = Path(CONFIG.get("model_dll", ""))
        state_path = Path(CONFIG.get("state_xml", ""))

        # DLL exists
        if not dll_path.exists():
            issues.append(f"sumoproject.dll not found at {dll_path} — compile in SUMO GUI.")
        else:
            passes.append(f"DLL present: {dll_path.name}")

        # state.xml exists
        if not state_path.exists():
            issues.append(f"state.xml not found at {state_path} — extract from SUMO GUI.")
        else:
            passes.append(f"state.xml present: {state_path.name}")

        # DLL/state version consistency (mtime)
        if dll_path.exists() and state_path.exists():
            dll_mt   = dll_path.stat().st_mtime
            state_mt = state_path.stat().st_mtime
            if abs(dll_mt - state_mt) > 3600:
                warnings.append(
                    "DLL and state.xml timestamps differ by > 1h — they may be "
                    "out of sync. Re-run maptoic; save in SUMO GUI."
                )
            else:
                passes.append("DLL and state.xml timestamps consistent")

        # Can we instantiate a DTT session?
        try:
            ds = _make_ds()
            all_vars = ds.sumo.getVariableNames()
            passes.append(f"DTT session opened ({len(all_vars)} variables)")
        except Exception as e:
            issues.append(f"Cannot open DTT session: {e}")
            return {"status": "FAIL", "issues": issues, "warnings": warnings,
                     "passes": passes}

        # Required unit types (based on naming convention)
        unit_names = set()
        for v in all_vars:
            parts = v.split("__")
            if len(parts) >= 3:
                unit_names.add(parts[2])

        required_patterns = {
            "Influent":  ["influent", "inlet", "feed"],
            "Reactor":   ["aer", "reactor", "tank", "mbr", "ditch", "sbr"],
            "Clarifier": ["clar", "settler", "settling"],
            "Effluent":  ["effluent", "outlet", "final"],
        }

        for role, patterns in required_patterns.items():
            found = [u for u in unit_names
                     if any(p in u.lower() for p in patterns)]
            if not found:
                warnings.append(f"No '{role}' unit detected (looked for: {patterns})")
            else:
                passes.append(f"{role} unit(s) present: {found[:3]}")

        status = "PASS" if not issues else ("FAIL" if len(issues) > 1 else "WARNINGS")

        return {
            "status":       status,
            "dll":          str(dll_path),
            "state_xml":    str(state_path),
            "unit_count":   len(unit_names),
            "units":        sorted(unit_names),
            "issue_count":  len(issues),
            "warning_count":len(warnings),
            "pass_count":   len(passes),
            "issues":       issues,
            "warnings":     warnings,
            "passes":       passes,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def validate_influent_configuration(unit_name: str = "Influent") -> dict:
    """Check that the influent is configured with sensible, non-zero values.

    Confirms flow > 0, COD > 0, temperature set, and pH within biological range.

    Args:
        unit_name: SUMO influent unit name.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        checks = {}
        issues, warnings, passes = [], [], []

        def read(param_suffixes):
            for s in param_suffixes:
                var = f"Sumo__Plant__{unit_name}__{s}"
                if var in all_vars:
                    try:
                        return float(ds.sumo.get(var)), var
                    except Exception:
                        continue
            return None, None

        q,    q_var   = read(["param__Q"])
        cod,  cod_var = read(["param__S_COD", "param__COD"])
        tss,  tss_var = read(["param__X_TSS", "param__TSS"])
        tkn,  tkn_var = read(["param__S_TKN", "param__TKN"])
        tp,   tp_var  = read(["param__S_TP",  "param__TP"])
        ph,   ph_var  = read(["param__pH"])
        t,    t_var   = read(["param__T"])

        # Required non-zero
        if q is None or q <= 0:
            issues.append(f"Influent flow (Q) is missing or ≤ 0 at {unit_name}")
        else:
            checks["flow_m3d"] = q
            passes.append(f"Flow = {q} m³/d")
        if cod is None or cod <= 0:
            issues.append(f"Influent COD is missing or ≤ 0 at {unit_name}")
        else:
            checks["COD_mgL"] = cod
            passes.append(f"COD = {cod} mg/L")

        # Physical ranges
        if t is not None:
            cat, msg = _classify(t, "Temp_C")
            checks["temp_C"] = t
            (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                .append(f"Temperature: {msg}")
        else:
            warnings.append("Influent temperature not set — model will use default")

        if ph is not None:
            cat, msg = _classify(ph, "pH")
            checks["pH"] = ph
            (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                .append(f"pH: {msg}")

        # Compute BOD/COD and COD/N ratios if possible
        if cod and tkn:
            cn = cod / tkn if tkn > 0 else None
            if cn is not None:
                cat, msg = _classify(cn, "COD_N_ratio")
                checks["COD_TKN_ratio"] = round(cn, 2)
                (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                    .append(f"COD:TKN ratio: {msg}")

        status = "PASS" if not issues else "FAIL"
        return {
            "unit_name":    unit_name,
            "status":       status,
            "checks":       checks,
            "issues":       issues,
            "warnings":     warnings,
            "passes":       passes,
        }
    except Exception as e:
        return {"error": str(e), "unit_name": unit_name}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP B — Mass Balance Validation
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def validate_mass_balance_pre_run(tolerance_pct: float = 5.0) -> dict:
    """Quick pre-simulation mass balance sanity check on the current model state.

    Pulls the currently set influent load and compares against any effluent
    values in state.xml to flag obvious configuration errors. Not a substitute
    for a full post-run mass balance — use validate_mass_balance_post_run for
    that.

    Args:
        tolerance_pct: Acceptable pre-run drift. Default 5%.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        def get_load(unit, param_suffixes):
            q_var = f"Sumo__Plant__{unit}__param__Q"
            if q_var not in all_vars:
                return None
            try:
                q = float(ds.sumo.get(q_var))
            except Exception:
                return None
            for s in param_suffixes:
                var = f"Sumo__Plant__{unit}__{s}"
                if var in all_vars:
                    try:
                        c = float(ds.sumo.get(var))
                        return q * c / 1000.0   # kg/d if c in mg/L and Q in m³/d
                    except Exception:
                        continue
            return None

        balances = {}
        for element, suffixes in [
            ("COD",   ["param__S_COD", "param__COD"]),
            ("TSS",   ["param__X_TSS", "param__TSS"]),
            ("TKN",   ["param__S_TKN", "param__TKN"]),
            ("TP",    ["param__S_TP",  "param__TP"]),
        ]:
            inf = get_load("Influent", suffixes)
            eff = get_load("Effluent", suffixes)
            if inf is not None and eff is not None:
                reduction_pct = (inf - eff) / inf * 100 if inf > 0 else None
                balances[element] = {
                    "influent_kgd":  round(inf, 2),
                    "effluent_kgd":  round(eff, 2),
                    "reduction_pct": round(reduction_pct, 1)
                                      if reduction_pct is not None else None,
                }

        issues = []
        for elem, b in balances.items():
            r = b.get("reduction_pct")
            if r is None:
                continue
            if r < 0:
                issues.append(f"{elem}: effluent load > influent load (impossible)")
            if elem == "COD" and r < 50:
                issues.append(f"COD reduction only {r}% — plant under-performing")

        return {
            "tolerance_pct":  tolerance_pct,
            "balances":       balances,
            "issue_count":    len(issues),
            "issues":         issues,
            "status":         "PASS" if not issues else "CHECK",
            "note": (
                "This is pre-run — effluent values are from state.xml initial "
                "conditions, not a simulation. Run run_steady_state then "
                "validate_mass_balance_post_run for a real balance."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def validate_mass_balance_post_run(job_id: str,
                                         elements: list = None,
                                         tolerance_pct: float = 5.0) -> dict:
    """Full mass balance validation on a completed simulation.

    For each element (COD, N, P, TSS), computes:
      Σ in − Σ out (effluent + WAS) − reaction = closure error

    A well-behaved plant should close within ±5% for each element.

    Args:
        job_id:        Completed job ID.
        elements:      List of elements to check. Default ['COD', 'N', 'P', 'TSS'].
        tolerance_pct: Acceptable closure error. Default 5%.
    """
    try:
        if elements is None:
            elements = ["COD", "N", "P", "TSS"]

        # Find job CSV
        csv_files = glob.glob(str(Path(CONFIG["output_dir"]) / f"{job_id}*.csv"))
        if not csv_files:
            return {"error": f"No CSV for job '{job_id}'. Run export_results_csv first."}

        with open(csv_files[0], newline="") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
        if not rows:
            return {"error": "CSV is empty"}

        headers = list(rows[0].keys())

        # Column-matching dictionary
        element_cols = {
            "COD": {
                "in":  ["COD_in", "Inf_COD", "S_COD_in", "Influent_COD"],
                "out": ["COD_eff", "Eff_COD", "S_COD_eff", "COD_out"],
                "WAS": ["COD_WAS", "WAS_COD"],
            },
            "N": {
                "in":  ["TKN_in", "TN_in", "Inf_TKN"],
                "out": ["TN_eff", "Eff_TN"],
                "WAS": ["TN_WAS"],
            },
            "P": {
                "in":  ["TP_in", "Inf_TP"],
                "out": ["TP_eff", "Eff_TP"],
                "WAS": ["TP_WAS"],
            },
            "TSS": {
                "in":  ["TSS_in", "Inf_TSS"],
                "out": ["TSS_eff", "Eff_TSS"],
                "WAS": ["TSS_WAS"],
            },
        }

        def match(cands):
            for c in cands:
                for h in headers:
                    if c.lower() in h.lower():
                        return h
            return None

        def col_mean(col):
            vals = []
            for r in rows:
                try:
                    vals.append(float(r[col]))
                except Exception:
                    pass
            return sum(vals) / len(vals) if vals else None

        results = {}
        summary_issues = []

        for elem in elements:
            if elem not in element_cols:
                continue
            cols = element_cols[elem]
            in_col  = match(cols["in"])
            out_col = match(cols["out"])
            was_col = match(cols["WAS"])

            in_load  = col_mean(in_col)  if in_col  else None
            out_load = col_mean(out_col) if out_col else None
            was_load = col_mean(was_col) if was_col else None

            closure_pct = None
            if in_load and out_load is not None:
                accounted = out_load + (was_load or 0)
                error     = in_load - accounted
                closure_pct = round(error / in_load * 100, 1) if in_load > 0 else None

            results[elem] = {
                "in_load":     round(in_load, 3)  if in_load  else "not found",
                "out_load":    round(out_load, 3) if out_load else "not found",
                "was_load":    round(was_load, 3) if was_load else "not found",
                "closure_error_pct": closure_pct,
            }
            if closure_pct is not None and abs(closure_pct) > tolerance_pct:
                cat, msg = _classify(abs(closure_pct), "mass_balance_error_pct")
                summary_issues.append(f"{elem} balance closure {closure_pct}% — {cat}")

        status = "PASS" if not summary_issues else \
                 ("WARNINGS" if all(abs(r.get("closure_error_pct") or 0) < 10
                                     for r in results.values()) else "FAIL")

        return {
            "job_id":        job_id,
            "tolerance_pct": tolerance_pct,
            "balances":      results,
            "issues":        summary_issues,
            "status":        status,
            "interpretation": (
                "< 5%  = excellent closure; 5–10% = acceptable (typical for "
                "steady-state); > 10% = investigate — likely a missing "
                "stream or incorrect fractionation."
            )
        }
    except Exception as e:
        return {"error": str(e), "job_id": job_id}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP C — MLSS & Biomass Health
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def validate_mlss_health(unit_name: str = "AerTank1") -> dict:
    """Check MLSS, MLVSS/MLSS ratio, and biomass composition in a reactor.

    Reads current state values and classifies against Metcalf & Eddy ranges.

    Args:
        unit_name: SUMO reactor unit name.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        def read_any(suffixes):
            for s in suffixes:
                var = f"Sumo__Plant__{unit_name}__{s}"
                if var in all_vars:
                    try:
                        return float(ds.sumo.get(var)), var
                    except Exception:
                        continue
            return None, None

        mlss, mlss_var = read_any(["X_TSS", "MLSS", "param__MLSS", "param__X_TSS_set"])
        mlvss, _       = read_any(["X_VSS", "MLVSS"])
        xbh, _         = read_any(["X_BH"])  # active heterotrophs
        xba, _         = read_any(["X_BA"])  # active autotrophs
        xi, _          = read_any(["X_I"])   # inert

        checks = {"unit": unit_name}
        issues, warnings, passes = [], [], []

        if mlss is None:
            issues.append(f"Cannot read MLSS for {unit_name} — variable not found.")
        else:
            cat, msg = _classify(mlss, "MLSS_mgL")
            checks["MLSS_mgL"] = mlss
            (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                .append(f"MLSS: {msg}")

        if mlss and mlvss:
            ratio = mlvss / mlss if mlss > 0 else None
            if ratio:
                cat, msg = _classify(ratio, "MLVSS_MLSS_ratio")
                checks["MLVSS_MLSS_ratio"] = round(ratio, 3)
                (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                    .append(f"MLVSS/MLSS ratio: {msg}")

        if xbh is not None and mlvss and mlvss > 0:
            active_frac = xbh / mlvss
            checks["active_heterotroph_fraction"] = round(active_frac, 3)
            if active_frac < 0.15:
                warnings.append(
                    f"Active heterotroph fraction {active_frac:.1%} is low — "
                    "suggests high inert biomass accumulation"
                )
            else:
                passes.append(f"Active heterotroph fraction {active_frac:.1%}")

        if xba is not None and mlvss and mlvss > 0:
            nitrifier_frac = xba / mlvss
            checks["nitrifier_fraction"] = round(nitrifier_frac, 4)
            if nitrifier_frac < 0.01:
                warnings.append(
                    f"Nitrifier fraction {nitrifier_frac:.2%} is very low — "
                    "nitrification may be unstable"
                )
            else:
                passes.append(f"Nitrifier fraction {nitrifier_frac:.2%}")

        status = "PASS" if not issues else ("FAIL" if len(issues) > 1 else "WARNINGS")
        return {
            "status":   status,
            "checks":   checks,
            "issues":   issues,
            "warnings": warnings,
            "passes":   passes,
        }
    except Exception as e:
        return {"error": str(e), "unit_name": unit_name}


@server.tool()
async def validate_srt_fm_feasibility(unit_name: str = "AerTank1",
                                      influent_unit: str = "Influent",
                                      was_unit: str = "WAS_Pump") -> dict:
    """Check whether the configured SRT and F/M ratio are feasible for the
    design conditions.

    Computes actual SRT from reactor volume, MLSS, WAS flow, and RAS underflow
    concentration, and compares with target SRT. Also computes F/M and checks
    against range.

    Args:
        unit_name:     Aeration tank unit name.
        influent_unit: Influent unit name.
        was_unit:      WAS pump unit name.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        def read(unit, suffixes):
            for s in suffixes:
                var = f"Sumo__Plant__{unit}__{s}"
                if var in all_vars:
                    try:
                        return float(ds.sumo.get(var))
                    except Exception:
                        continue
            return None

        V       = read(unit_name,     ["param__V", "param__Volume"])
        MLSS    = read(unit_name,     ["X_TSS", "MLSS", "param__X_TSS_set"])
        MLVSS   = read(unit_name,     ["X_VSS"])
        SRT_set = read(unit_name,     ["param__SRT", "param__SRT_set"])
        Q_was   = read(was_unit,      ["param__Q"])
        X_R     = read("SecClar1",    ["param__X_underflow", "X_R"])
        Q_in    = read(influent_unit, ["param__Q"])
        BOD_in  = read(influent_unit, ["param__BOD5", "param__S_S"])

        checks, issues, warnings, passes = {}, [], [], []

        # SRT computation: SRT = V·MLSS / (Q_WAS · X_R + Q_eff · X_eff)
        if V and MLSS and Q_was and X_R:
            SRT_actual = (V * MLSS) / (Q_was * X_R * 1000) if (Q_was * X_R) > 0 else None
            checks["SRT_actual_d"] = round(SRT_actual, 2) if SRT_actual else None
            if SRT_set:
                checks["SRT_target_d"] = SRT_set
                if SRT_actual:
                    deviation = abs(SRT_actual - SRT_set) / SRT_set * 100
                    if deviation > 30:
                        issues.append(
                            f"Actual SRT {SRT_actual:.1f}d differs from target "
                            f"{SRT_set}d by {deviation:.0f}% — adjust Q_WAS"
                        )
                    else:
                        passes.append(
                            f"SRT target {SRT_set}d ≈ actual {SRT_actual:.1f}d"
                        )
            if SRT_actual:
                cat, msg = _classify(SRT_actual, "SRT_d")
                (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                    .append(f"SRT: {msg}")
        else:
            warnings.append(
                "Cannot compute actual SRT — missing one of V, MLSS, Q_WAS, X_R"
            )

        # F/M ratio: F/M = Q·BOD / (V·MLVSS)
        if Q_in and BOD_in and V and MLVSS:
            FM = (Q_in * BOD_in) / (V * MLVSS) if (V * MLVSS) > 0 else None
            checks["F_M_ratio"] = round(FM, 3) if FM else None
            if FM:
                cat, msg = _classify(FM, "FM_ratio")
                (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                    .append(f"F/M ratio: {msg}")
        else:
            warnings.append("Cannot compute F/M — missing one of Q, BOD, V, MLVSS")

        # HRT
        if V and Q_in:
            HRT = V / Q_in * 24   # hours
            checks["HRT_h"] = round(HRT, 2)
            cat, msg = _classify(HRT, "HRT_h")
            (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                .append(f"HRT: {msg}")

        status = "PASS" if not issues else ("WARNINGS" if len(issues) <= 1 else "FAIL")
        return {
            "status":   status,
            "checks":   checks,
            "issues":   issues,
            "warnings": warnings,
            "passes":   passes,
            "tip": "Adjust Q_WAS to match target SRT. Adjust V or MLSS to tune F/M.",
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP D — DO & Aeration Validation
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def validate_do_levels(zone_units: dict = None) -> dict:
    """Verify DO levels are within the correct range for each zone type.

    Args:
        zone_units: Dict mapping zone type → unit name, e.g.
                    {"aerobic": "AerTank1",
                     "anoxic":  "AnoxTank1",
                     "anaerobic": "AnaTank1"}
                    If None, uses sensible defaults.
    """
    try:
        if zone_units is None:
            zone_units = {"aerobic": "AerTank1",
                          "anoxic":  "AnoxTank1",
                          "anaerobic": "AnaTank1"}

        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        def read_do(unit):
            for s in ["S_O", "DO", "param__DO_setpoint", "param__DO_sp", "param__S_O_sp"]:
                var = f"Sumo__Plant__{unit}__{s}"
                if var in all_vars:
                    try:
                        return float(ds.sumo.get(var)), var
                    except Exception:
                        continue
            return None, None

        results, issues, warnings, passes = {}, [], [], []

        for zone_type, unit in zone_units.items():
            do_val, do_var = read_do(unit)
            if do_val is None:
                warnings.append(f"DO not found for {zone_type} zone ({unit})")
                continue
            results[zone_type] = {"unit": unit, "DO_mgL": do_val, "variable": do_var}

            threshold_key = {
                "aerobic":   "DO_aerobic_mgL",
                "anoxic":    "DO_anoxic_mgL",
                "anaerobic": "DO_anaerobic_mgL",
            }.get(zone_type)

            if threshold_key:
                cat, msg = _classify(do_val, threshold_key)
                line = f"{zone_type.capitalize()} zone ({unit}) DO: {msg}"
                (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                    .append(line)

        # Warn about KLa if set
        for unit in zone_units.values():
            kla_var = f"Sumo__Plant__{unit}__param__KLa"
            if kla_var in all_vars:
                try:
                    kla = float(ds.sumo.get(kla_var))
                    cat, msg = _classify(kla, "KLa_h")
                    results.setdefault(f"KLa_{unit}", {})["KLa_h"] = kla
                    (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                        .append(f"{unit} KLa: {msg}")
                except Exception:
                    pass

        status = "PASS" if not issues else ("WARNINGS" if not any(
            "anoxic" in i.lower() or "anaerobic" in i.lower() for i in issues
        ) else "FAIL")

        return {
            "status":   status,
            "zones":    results,
            "issues":   issues,
            "warnings": warnings,
            "passes":   passes,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def validate_oxygen_demand_vs_supply(unit_name: str = "AerTank1",
                                            influent_unit: str = "Influent") -> dict:
    """Check that aeration supply is sufficient for oxygen demand.

    Estimates O₂ demand from influent BOD + nitrification load, compares
    against supply implied by KLa × volume × (DO_sat − DO_operating).

    Args:
        unit_name:     Aeration tank unit.
        influent_unit: Influent unit name.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        def read(unit, suffixes):
            for s in suffixes:
                var = f"Sumo__Plant__{unit}__{s}"
                if var in all_vars:
                    try:
                        return float(ds.sumo.get(var))
                    except Exception:
                        continue
            return None

        V      = read(unit_name,     ["param__V"])
        KLa    = read(unit_name,     ["param__KLa"])
        DO_op  = read(unit_name,     ["param__DO_setpoint", "S_O"]) or 2.0
        T      = read(unit_name,     ["param__T"]) or CONFIG.get("plant_temp_C", 25.0)
        Q      = read(influent_unit, ["param__Q"])
        BOD    = read(influent_unit, ["param__BOD5", "param__S_S"])
        TKN    = read(influent_unit, ["param__S_TKN", "param__TKN"])

        # DO saturation at T (Benson-Krause approximation)
        DO_sat = round(14.652 - 0.41022 * T + 0.007991 * T**2 - 7.7774e-5 * T**3, 2)

        issues, passes = [], []
        checks = {"DO_sat_mgL": DO_sat, "DO_operating_mgL": DO_op, "Temp_C": T}

        # O₂ demand (simplified): 1.2 kg O₂/kg BOD + 4.57 kg O₂/kg N nitrified
        if Q and BOD:
            AOR_BOD = Q * BOD * 1.2 / 1000  # kg O₂/d for carbon
            checks["AOR_carbon_kgOd"] = round(AOR_BOD, 1)
        else:
            AOR_BOD = None
        if Q and TKN:
            AOR_N   = Q * TKN * 4.57 / 1000  # kg O₂/d for nitrification
            checks["AOR_nitrification_kgOd"] = round(AOR_N, 1)
        else:
            AOR_N = None

        AOR_total = (AOR_BOD or 0) + (AOR_N or 0)
        checks["AOR_total_kgOd"] = round(AOR_total, 1)

        # O₂ supply: OTR = KLa × V × (DO_sat − DO_op) × 24 / 1000  [kg/d]
        OTR = None
        if KLa and V:
            OTR = KLa * V * (DO_sat - DO_op) * 24 / 1000
            checks["OTR_supply_kgOd"] = round(OTR, 1)

            if AOR_total > 0:
                ratio = OTR / AOR_total
                checks["supply_demand_ratio"] = round(ratio, 2)
                if ratio < 1.0:
                    issues.append(
                        f"Oxygen supply ({OTR:.0f}) < demand ({AOR_total:.0f} kg/d) — "
                        "increase KLa or reduce DO setpoint"
                    )
                elif ratio < 1.2:
                    issues.append(
                        f"Oxygen supply margin only {(ratio-1)*100:.0f}% — "
                        "no buffer for peak loads"
                    )
                else:
                    passes.append(f"Oxygen supply/demand ratio {ratio:.2f} (healthy)")

        status = "PASS" if not issues else "CHECK"
        return {
            "status": status, "checks": checks, "issues": issues, "passes": passes,
            "note":   "Simplified demand = 1.2·BOD + 4.57·TKN. Refine with ASM yields.",
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP E — Hydraulic & Flow Validation
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def validate_hydraulic_balance(influent_unit: str = "Influent",
                                     effluent_unit: str = "Effluent",
                                     was_unit: str = "WAS_Pump",
                                     ras_unit: str = "RAS_Pump",
                                     sec_clar_unit: str = "SecClar1") -> dict:
    """Validate flow continuity, RAS ratio, and clarifier hydraulic loading.

    Args:
        influent_unit, effluent_unit, was_unit, ras_unit, sec_clar_unit:
            SUMO unit names for the corresponding plant components.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        def read_q(unit):
            for s in ["param__Q"]:
                var = f"Sumo__Plant__{unit}__{s}"
                if var in all_vars:
                    try:
                        return float(ds.sumo.get(var))
                    except Exception:
                        continue
            return None

        q_in  = read_q(influent_unit)
        q_eff = read_q(effluent_unit)
        q_was = read_q(was_unit)
        q_ras = read_q(ras_unit)

        checks, issues, warnings, passes = {}, [], [], []

        # Flow continuity: Q_in ≈ Q_eff + Q_WAS
        if q_in and q_eff is not None:
            expected = q_in - (q_was or 0)
            error_pct = abs(q_eff - expected) / q_in * 100
            checks["flow_continuity_error_pct"] = round(error_pct, 1)
            cat, msg = _classify(error_pct, "flow_continuity_error_pct")
            (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                .append(f"Flow continuity: {msg}")

        # RAS ratio
        if q_ras and q_in and q_in > 0:
            ras_r = q_ras / q_in
            checks["RAS_ratio"] = round(ras_r, 2)
            cat, msg = _classify(ras_r, "RAS_ratio")
            (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                .append(f"RAS ratio: {msg}")

        # Secondary clarifier hydraulic loading
        A_sec = None
        for s in ["param__A", "param__Area", "param__surface_area"]:
            var = f"Sumo__Plant__{sec_clar_unit}__{s}"
            if var in all_vars:
                try:
                    A_sec = float(ds.sumo.get(var))
                    break
                except Exception:
                    pass

        if A_sec and q_in:
            SOR = q_in / A_sec
            checks["sec_clar_SOR_m3m2d"] = round(SOR, 1)
            cat, msg = _classify(SOR, "overflow_rate_sec_clar")
            (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                .append(f"Secondary clarifier SOR: {msg}")

        # Underflow concentration
        for s in ["param__X_underflow", "X_R", "param__C_underflow"]:
            var = f"Sumo__Plant__{sec_clar_unit}__{s}"
            if var in all_vars:
                try:
                    X_R = float(ds.sumo.get(var))
                    # Normalize to g/L if in mg/L
                    if X_R > 100:
                        X_R = X_R / 1000
                    checks["underflow_conc_gL"] = round(X_R, 1)
                    cat, msg = _classify(X_R, "underflow_conc_sec_clar")
                    (passes if cat == "green" else warnings if cat == "yellow" else issues)\
                        .append(f"Underflow concentration: {msg}")
                    break
                except Exception:
                    continue

        status = "PASS" if not issues else "CHECK"
        return {
            "status": status, "checks": checks,
            "issues": issues, "warnings": warnings, "passes": passes,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP F — Kinetic Parameter Sanity Check
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def validate_asm_kinetics(unit_name: str = "AerTank1") -> dict:
    """Check that ASM kinetic parameters are within physically sensible ranges.

    Flags any parameter outside IWA / Henze et al. (2000) reported bounds.
    Catches user input errors like Y_H = 6.7 (should be 0.67).

    Args:
        unit_name: Reactor unit name.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        bounds = VALIDATION_THRESHOLDS["ASM_kinetic_bounds"]

        results, issues, passes = [], [], []

        for param, b in bounds.items():
            # Try several suffix patterns
            for s in [f"param__{param}", f"param__{param.replace('_','')}"]:
                var = f"Sumo__Plant__{unit_name}__{s}"
                if var in all_vars:
                    try:
                        v = float(ds.sumo.get(var))
                        in_bounds = b["min"] <= v <= b["max"]
                        results.append({
                            "param":     param,
                            "value":     v,
                            "unit":      b["unit"],
                            "min":       b["min"],
                            "max":       b["max"],
                            "in_bounds": in_bounds,
                        })
                        if in_bounds:
                            passes.append(f"{param} = {v} {b['unit']} (OK)")
                        else:
                            issues.append(
                                f"{param} = {v} {b['unit']} outside "
                                f"[{b['min']}, {b['max']}] — likely input error "
                                "(check decimal placement)"
                            )
                    except Exception:
                        pass
                    break

        status = "PASS" if not issues else "FAIL"
        return {
            "unit":    unit_name,
            "status":  status,
            "checks":  len(results),
            "out_of_bounds": len(issues),
            "details": results,
            "issues":  issues,
            "passes":  passes[:5],
            "tip":     "Out-of-bounds values are almost always typos. "
                        "Call reset_parameter_to_default to revert.",
        }
    except Exception as e:
        return {"error": str(e), "unit_name": unit_name}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP G — Post-Simulation Convergence & Plausibility
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def validate_simulation_convergence(job_id: str,
                                          stability_window_pct: float = 10.0) -> dict:
    """Check if a simulation reached steady state (for steady-state runs) or
    is dynamically stable (for dynamic runs).

    Reads the last 10% of the time series and checks for convergence.

    Args:
        job_id:               Completed job ID.
        stability_window_pct: Last N% of the run used to judge stability.
    """
    try:
        csv_files = glob.glob(str(Path(CONFIG["output_dir"]) / f"{job_id}*.csv"))
        if not csv_files:
            return {"error": f"No CSV for job '{job_id}'"}

        with open(csv_files[0], newline="") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
        if len(rows) < 10:
            return {"error": "Not enough rows to assess convergence"}

        # Take last N% of rows
        n_tail = max(5, int(len(rows) * stability_window_pct / 100))
        tail   = rows[-n_tail:]

        # Key effluent parameters to check
        key_patterns = ["COD_eff", "BOD_eff", "TSS_eff", "NH4_eff", "TN_eff"]
        headers = list(rows[0].keys())

        convergence = []
        issues, passes = [], []

        for pat in key_patterns:
            col = next((h for h in headers if pat.lower() in h.lower()), None)
            if not col:
                continue
            vals = []
            for r in tail:
                try:
                    vals.append(float(r[col]))
                except Exception:
                    pass
            if len(vals) < 3:
                continue
            mean = sum(vals) / len(vals)
            if mean == 0:
                continue
            rel_std = (max(vals) - min(vals)) / mean * 100
            stable  = rel_std < 5.0

            convergence.append({
                "parameter":     pat,
                "column":        col,
                "tail_mean":     round(mean, 3),
                "tail_range_pct":round(rel_std, 1),
                "converged":     stable,
            })
            if stable:
                passes.append(f"{pat} stable (±{rel_std:.1f}%)")
            else:
                issues.append(
                    f"{pat} fluctuating ±{rel_std:.1f}% in final {n_tail} steps — "
                    "may need longer warm-up or solver may be oscillating"
                )

        status = "PASS" if not issues else ("CHECK" if len(issues) <= 1 else "FAIL")
        return {
            "job_id":           job_id,
            "status":           status,
            "rows_analyzed":    n_tail,
            "convergence":      convergence,
            "issues":           issues,
            "passes":           passes,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def validate_simulation_plausibility(job_id: str) -> dict:
    """Sanity-check simulation output for physically impossible values.

    Flags negative concentrations, pH outside 4–10, oversaturated DO,
    effluent concentrations higher than influent for conserved quantities, etc.

    Args:
        job_id: Completed job ID.
    """
    try:
        csv_files = glob.glob(str(Path(CONFIG["output_dir"]) / f"{job_id}*.csv"))
        if not csv_files:
            return {"error": f"No CSV for job '{job_id}'"}

        with open(csv_files[0], newline="") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
        if not rows:
            return {"error": "CSV empty"}

        headers = list(rows[0].keys())
        issues, warnings, passes = [], [], []

        def col_vals(col):
            out = []
            for r in rows:
                try:
                    out.append(float(r[col]))
                except Exception:
                    pass
            return out

        # 1. Negative concentrations
        for h in headers:
            if any(t in h.lower() for t in ["cod", "bod", "tss", "nh4", "no3", "tn", "tp"]):
                vals = col_vals(h)
                if vals and min(vals) < 0:
                    issues.append(
                        f"{h} has negative values (min = {min(vals):.2f}) — "
                        "numerical instability"
                    )

        # 2. pH out of range
        ph_col = next((h for h in headers if h.lower() == "ph" or h.endswith("_pH")), None)
        if ph_col:
            vals = col_vals(ph_col)
            if vals:
                if min(vals) < 4.0 or max(vals) > 10.0:
                    issues.append(
                        f"{ph_col} goes outside [4, 10] — range [{min(vals):.1f}, "
                        f"{max(vals):.1f}]"
                    )
                else:
                    passes.append(f"{ph_col} within biological range")

        # 3. Oversaturated DO
        for h in headers:
            if "do" in h.lower() or "s_o" in h.lower():
                vals = col_vals(h)
                if vals and max(vals) > 14.0:
                    issues.append(
                        f"{h} exceeds oxygen saturation (14 mg/L) — "
                        "KLa or DO setpoint may be mis-set"
                    )

        # 4. Effluent > influent for conserved substances (should never happen)
        for pair in [("COD_in", "COD_eff"), ("TSS_in", "TSS_eff")]:
            c_in  = next((h for h in headers if pair[0].lower() in h.lower()), None)
            c_out = next((h for h in headers if pair[1].lower() in h.lower()), None)
            if c_in and c_out:
                in_vals  = col_vals(c_in)
                out_vals = col_vals(c_out)
                if in_vals and out_vals:
                    if sum(out_vals)/len(out_vals) > sum(in_vals)/len(in_vals):
                        warnings.append(
                            f"Mean effluent {pair[1]} > mean influent {pair[0]} — "
                            "plant is generating mass (check fractionation)"
                        )

        status = "PASS" if not issues else ("FAIL" if len(issues) > 2 else "WARNINGS")
        return {
            "job_id":       job_id,
            "status":       status,
            "issue_count":  len(issues),
            "warning_count":len(warnings),
            "issues":       issues,
            "warnings":     warnings,
            "passes":       passes,
        }
    except Exception as e:
        return {"error": str(e), "job_id": job_id}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP H — Full Validation Orchestrator
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def validate_full_model(aer_tank: str = "AerTank1",
                              influent_unit: str = "Influent",
                              effluent_unit: str = "Effluent",
                              sec_clar_unit: str = "SecClar1",
                              was_unit: str = "WAS_Pump",
                              ras_unit: str = "RAS_Pump") -> dict:
    """Run every pre-simulation validation in sequence and return a single report.

    Call this as the "is my model safe to simulate?" gate before any run_*
    tool, especially after applying parameter edits, adding units, or
    importing datasets.

    Args:
        aer_tank, influent_unit, effluent_unit, sec_clar_unit, was_unit, ras_unit:
            SUMO unit names. Defaults assume standard naming.
    """
    try:
        # Run each validation and collect status
        results = {}

        async def run(name, coro):
            try:
                results[name] = await coro
            except Exception as e:
                results[name] = {"status": "ERROR", "error": str(e)}

        await run("structure",      validate_model_structure())
        await run("influent",       validate_influent_configuration(influent_unit))
        await run("mass_balance",   validate_mass_balance_pre_run())
        await run("mlss_health",    validate_mlss_health(aer_tank))
        await run("srt_fm",         validate_srt_fm_feasibility(aer_tank,
                                                                  influent_unit,
                                                                  was_unit))
        await run("do_levels",      validate_do_levels())
        await run("oxygen_supply",  validate_oxygen_demand_vs_supply(aer_tank,
                                                                       influent_unit))
        await run("hydraulic",      validate_hydraulic_balance(influent_unit,
                                                                  effluent_unit,
                                                                  was_unit,
                                                                  ras_unit,
                                                                  sec_clar_unit))
        await run("asm_kinetics",   validate_asm_kinetics(aer_tank))

        # Aggregate
        fail_count = sum(1 for r in results.values()
                         if r.get("status") in ("FAIL", "ERROR"))
        warn_count = sum(1 for r in results.values()
                         if r.get("status") in ("WARNINGS", "CHECK"))
        pass_count = sum(1 for r in results.values()
                         if r.get("status") == "PASS")

        # Collect top-level issues
        all_issues = []
        for name, r in results.items():
            for issue in r.get("issues", []):
                all_issues.append(f"[{name}] {issue}")

        overall = "READY_TO_SIMULATE" if fail_count == 0 and warn_count <= 2 \
                  else "CHECK_WARNINGS" if fail_count == 0 \
                  else "DO_NOT_SIMULATE"

        return {
            "overall_status":       overall,
            "checks_passed":        pass_count,
            "checks_with_warnings": warn_count,
            "checks_failed":        fail_count,
            "summary":              {name: r.get("status", "?")
                                     for name, r in results.items()},
            "top_issues":           all_issues[:15],
            "detailed_results":     results,
            "recommendation": (
                "Model passes all checks — run_steady_state recommended."
                if overall == "READY_TO_SIMULATE" else
                "Review warnings before running — simulation may succeed but "
                "results may be suspect."
                if overall == "CHECK_WARNINGS" else
                "Fix critical issues before running — simulation likely to fail "
                "or produce nonsense."
            ),
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def validate_post_simulation(job_id: str) -> dict:
    """Run every post-simulation validation in sequence.

    Call this after run_steady_state or run_dynamic_simulation to confirm
    the results are physically plausible and balanced.

    Args:
        job_id: Completed job ID.
    """
    try:
        results = {}

        async def run(name, coro):
            try:
                results[name] = await coro
            except Exception as e:
                results[name] = {"status": "ERROR", "error": str(e)}

        await run("mass_balance",   validate_mass_balance_post_run(job_id))
        await run("convergence",    validate_simulation_convergence(job_id))
        await run("plausibility",   validate_simulation_plausibility(job_id))

        fail_count = sum(1 for r in results.values()
                         if r.get("status") in ("FAIL", "ERROR"))
        warn_count = sum(1 for r in results.values()
                         if r.get("status") in ("WARNINGS", "CHECK"))
        pass_count = sum(1 for r in results.values()
                         if r.get("status") == "PASS")

        all_issues = []
        for name, r in results.items():
            for issue in r.get("issues", []):
                all_issues.append(f"[{name}] {issue}")

        overall = "RESULTS_VALID" if fail_count == 0 and warn_count == 0 \
                  else "RESULTS_SUSPECT" if fail_count == 0 \
                  else "RESULTS_INVALID"

        return {
            "job_id":            job_id,
            "overall_status":    overall,
            "checks_passed":     pass_count,
            "checks_warnings":   warn_count,
            "checks_failed":     fail_count,
            "summary":           {n: r.get("status", "?") for n, r in results.items()},
            "top_issues":        all_issues[:10],
            "detailed_results":  results,
            "recommendation": (
                "Results are valid — safe to use for compliance and reporting."
                if overall == "RESULTS_VALID" else
                "Review warnings before trusting the numbers."
                if overall == "RESULTS_SUSPECT" else
                "Do not use these results — re-configure the model and re-run."
            ),
        }
    except Exception as e:
        return {"error": str(e), "job_id": job_id}
```

---

## Step 4 — Save and restart

1. Save `server.py`.
2. Fully quit Claude Desktop (right-click tray icon → **Quit**).
3. Relaunch Claude Desktop.
4. Verify new tools: ask **"List all SUMO24 validation tools"**.

---

## Step 5 — Verification prompts

| Prompt | Expected tool |
|---|---|
| `Is my SUMO model structurally complete and ready to simulate?` | `validate_model_structure` |
| `Check that my influent is configured with valid values` | `validate_influent_configuration` |
| `Is my pre-run mass balance roughly correct?` | `validate_mass_balance_pre_run` |
| `Full mass balance check on job ss_001, tolerance 5%` | `validate_mass_balance_post_run` |
| `Check MLSS and biomass health in AerTank1` | `validate_mlss_health` |
| `Is my SRT feasible and my F/M ratio in range?` | `validate_srt_fm_feasibility` |
| `Check DO levels in all zone types` | `validate_do_levels` |
| `Is my aeration supply sufficient for the oxygen demand?` | `validate_oxygen_demand_vs_supply` |
| `Validate hydraulic balance and RAS ratio` | `validate_hydraulic_balance` |
| `Are my ASM kinetic parameters within physical bounds?` | `validate_asm_kinetics` |
| `Did my simulation converge to steady state?` | `validate_simulation_convergence` |
| `Is the output of job ss_001 physically plausible?` | `validate_simulation_plausibility` |
| `Run EVERY pre-simulation check and tell me if it's safe to run` | `validate_full_model` |
| `Run all post-simulation validations on job ss_001` | `validate_post_simulation` |

---

## Recommended workflow around any model edit

```
1. Make edits with any of the tools from previous chats:
   - set_parameter / set_multiple_parameters / set_asm1_kinetics …
   - add_unit_process / connect_unit_processes …
   - apply_dataset_to_model …
   - create_scenario …

2. Pre-flight:
   validate_full_model()

3. If overall_status == "READY_TO_SIMULATE":
   run_steady_state() or run_dynamic_simulation()

4. Post-flight:
   validate_post_simulation(job_id=...)

5. If results valid:
   check_compliance() + generate_report()
```

---

## Notes for Cowork

### Traffic-light classification
Every numeric check uses `_classify()` against the `VALIDATION_THRESHOLDS` dict:
- **green** → healthy operating range, no action needed
- **yellow** → acceptable but sub-optimal, check if intentional
- **red** → outside design envelope or physically impossible, fix before simulating

### Custom thresholds for non-Egyptian climates
The defaults bias toward Egyptian warm-climate operation (e.g. SRT green band
8–20 d, Temp green band 15–30°C). For other climates, edit the relevant entries
in `VALIDATION_THRESHOLDS` at the top of `server.py`.

### Unit name resolution
All validation tools accept unit-name arguments with sensible defaults
(`AerTank1`, `SecClar1`, `Influent`, `Effluent`, `WAS_Pump`, `RAS_Pump`). If
your SUMO model uses different names, either pass them explicitly or edit the
defaults in the function signatures.

### What "PASS" means
Each tool returns one of: `PASS`, `WARNINGS`/`CHECK`, `FAIL`, or `ERROR`.
`validate_full_model` aggregates these into:
- `READY_TO_SIMULATE` — run the simulation
- `CHECK_WARNINGS` — run but review results carefully
- `DO_NOT_SIMULATE` — fix critical issues first

### Non-blocking by design
None of these tools modify model state — they only read variables and compute
diagnostics. You can run them as often as you like during model development
without side effects.
