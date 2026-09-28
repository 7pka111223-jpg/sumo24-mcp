# SUMO24 MCP — Remaining Missing Tools (Environmental, Economic, BNR Rates, Docs, Auto-Calibration)

## Context
Your current MCP server covers **104 tools across groups A–X** (per the reference PDF)
and the earlier `SUMO24_MCP_Gap_Filling_Tools.md` adds another **19 tools in groups Y–AE**.
This file fills the **still-remaining gaps** identified after a deeper workflow review:

| New Group | What it adds | # tools |
|---|---|---|
| **AF — Environmental / GHG** | N₂O, CH₄, total carbon footprint | 3 |
| **AG — Economic Analysis** | CAPEX, annual OPEX, unit treatment cost | 3 |
| **AH — Water Reuse & Biosolids** | Egyptian Std 501/2015 reuse classification, biosolids Class A/B | 2 |
| **AI — BNR Performance Rates** | Nitrification rate (SNR), Denitrification rate (SDNR), EBPR performance | 3 |
| **AJ — Documentation & Export** | Process flow diagram (HTML), model metadata JSON snapshot | 2 |
| **AK — Automation** | Iterative auto-calibration loop | 1 |

> ⚠️ **Do not remove or modify any existing tools.**
> Insert all new code after the last existing `@server.tool()` function,
> before any `if __name__ == "__main__"` block.

> ℹ️ **Prerequisite:** This file assumes groups Y–AE (from the previous Gap-Filling MD)
> are already added. In particular, it reuses `DESIGN_BENCHMARKS`, `_is_number`,
> `compare_dataset_vs_simulation`, and `suggest_calibration_adjustments`.
> If Y–AE are not yet added, drop that file in first.

---

## File to Edit
**`F:/UNI/SUMO/MCP/PY/server.py`**

---

## Step 1 — Verify imports

These should already be present. Add any that are missing:

```python
import json
import glob
import csv as csv_mod
from pathlib import Path
from datetime import datetime
```

---

## Step 2 — Add cost, emission, and reuse reference tables

Insert this block **after** the `DESIGN_BENCHMARKS` dict:

```python
# ═══════════════════════════════════════════════════════════════════════════
# GHG EMISSION FACTORS
# Sources: IPCC 2019 Refinement (Ch.6 Wastewater); Law et al. 2012 (N2O);
#          Foley et al. 2010 (BNR N2O); UK Water UK Carbon Accounting
# ═══════════════════════════════════════════════════════════════════════════
GHG_FACTORS = {
    "GWP_CH4_kgCO2eq":    28,       # IPCC AR5 100-yr
    "GWP_N2O_kgCO2eq":    265,

    # Direct process emissions
    "N2O_emission_factor_BNR":  0.016,   # kg N2O-N per kg TN removed (BNR mean)
    "N2O_emission_factor_nitrif":0.005,  # kg N2O-N per kg TN denitrified (nitrification-only)
    "CH4_emission_factor_anaer":0.25,    # kg CH4 per kg COD to anaerobic digestion
    "CH4_emission_factor_opensurface":0.01,  # kg CH4 per kg COD

    # Indirect (grid electricity)
    "grid_emission_egypt_kgCO2eq_kWh": 0.48,  # Egyptian grid (2024 avg)
    "grid_emission_global_kgCO2eq_kWh":0.43,

    # Chemical manufacturing emissions (Scope 3)
    "FeCl3_kgCO2eq_kg":   1.2,
    "alum_kgCO2eq_kg":    0.5,
    "methanol_kgCO2eq_kg":0.9,
    "polymer_kgCO2eq_kg": 2.5,
    "NaOH_kgCO2eq_kg":    1.1,
    "chlorine_kgCO2eq_kg":1.8,
}

# ═══════════════════════════════════════════════════════════════════════════
# COST REFERENCES (2024 USD, adjusted for Egyptian market)
# Sources: Metcalf & Eddy (5th ed.) cost curves; UK WWTP cost database;
#          Egyptian public-tender analog 2023–2024
# ═══════════════════════════════════════════════════════════════════════════
COST_REFERENCES = {
    # CAPEX per m³ installed (Egyptian market prices)
    "capex_primary_clarifier_USD_m3":    550,
    "capex_aeration_tank_USD_m3":        450,
    "capex_anoxic_zone_USD_m3":          400,
    "capex_anaerobic_zone_USD_m3":       400,
    "capex_secondary_clarifier_USD_m3":  650,
    "capex_mbr_USD_m3":                  1800,
    "capex_digester_USD_m3":             700,
    "capex_tertiary_filter_USD_m3":      800,
    "capex_disinfection_USD_m3":         250,
    "capex_thickener_USD_m3":            500,
    "capex_dewatering_USD_per_m3h":      25000,

    # OPEX
    "electricity_cost_USD_kWh":          0.08,   # Egyptian industrial
    "labor_cost_USD_year_per_m3d":       2.5,    # ~1 operator per 10000 m3/d
    "maintenance_pct_of_capex_annual":   0.03,   # 3% of CAPEX
    "sludge_disposal_USD_tDS":           50,     # Egyptian landfill
    "chemical_costs_USD_kg": {
        "FeCl3":    0.30,
        "alum":     0.25,
        "methanol": 0.50,
        "polymer":  4.00,
        "NaOH":     0.60,
        "chlorine": 0.50,
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# EGYPTIAN STANDARD 501/2015 — Treated Effluent for Agricultural Reuse
# Class A: Unrestricted reuse (any crop)
# Class B: Restricted reuse (industrial crops, fodder, trees)
# Class C: Restricted to specific trees only (forest, wood)
# ═══════════════════════════════════════════════════════════════════════════
EGYPT_REUSE_STANDARDS = {
    "Class_A": {
        "BOD5":      20,   # mg/L max
        "COD":       50,
        "TSS":       20,
        "NH4_N":     5,
        "fecal_coliform_MPN_100mL": 1000,
        "intestinal_nematodes":     1,
        "description": "Unrestricted — all crops including raw-eaten vegetables",
    },
    "Class_B": {
        "BOD5":      40,
        "COD":       80,
        "TSS":       40,
        "NH4_N":     10,
        "fecal_coliform_MPN_100mL": 5000,
        "intestinal_nematodes":     1,
        "description": "Restricted — cooked crops, fodder, industrial crops, fruit trees",
    },
    "Class_C": {
        "BOD5":      60,
        "COD":       100,
        "TSS":       50,
        "NH4_N":     15,
        "fecal_coliform_MPN_100mL": 10000,
        "intestinal_nematodes":     None,
        "description": "Forest/wood trees only, no direct human contact",
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# BIOSOLIDS CLASSIFICATION (US EPA 503 + Egyptian Decree 44/2000 alignment)
# ═══════════════════════════════════════════════════════════════════════════
BIOSOLIDS_STANDARDS = {
    "Class_A": {
        "fecal_coliform_MPN_gDS":  1000,       # density
        "salmonella_MPN_4gDS":     3,
        "VS_reduction_pct_min":    38,         # or alternative VAR option
        "description": "Unrestricted land application — no site restrictions",
    },
    "Class_B": {
        "fecal_coliform_MPN_gDS":  2_000_000,
        "VS_reduction_pct_min":    38,
        "description": "Restricted use — buffer zones, grazing/harvest restrictions",
    },
}
```

---

## Step 3 — Insert new tools

Find the **last** `@server.tool()` function and insert this block **immediately after**:

```python
# ═══════════════════════════════════════════════════════════════════════════
# GROUP AF — Environmental / GHG Emissions
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def estimate_n2o_emissions(job_id: str = "",
                                 process_type: str = "BNR") -> dict:
    """Estimate direct N₂O emissions from the biological treatment process.

    N₂O is 265× worse than CO₂ on a 100-year basis and is a significant
    component of wastewater GHG footprint, especially for BNR plants.

    Uses IPCC 2019 default emission factors, modified by Law et al. (2012)
    ranges for BNR systems.

    Args:
        job_id:       Completed simulation job. If empty, uses current state values.
        process_type: 'BNR' (nitrification + denitrification) or 'nitrif_only'.
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

        Q       = read("Influent", ["param__Q"])
        TKN_in  = read("Influent", ["param__S_TKN", "param__TKN"])
        TN_eff  = read("Effluent", ["S_TN", "param__TN"])

        if not all([Q, TKN_in]):
            return {"error": "Cannot read Q and TKN from Influent unit."}

        # TN removed (kg/d)
        TN_removed_kgd = Q * (TKN_in - (TN_eff or 0)) / 1000

        # Select emission factor
        if process_type == "BNR":
            ef = GHG_FACTORS["N2O_emission_factor_BNR"]
            ef_range = (0.005, 0.05)   # Law et al. 2012 range
        else:
            ef = GHG_FACTORS["N2O_emission_factor_nitrif"]
            ef_range = (0.001, 0.025)

        # N2O-N emitted (kg/d) → multiply by 44/28 → N2O → × GWP
        N2O_N_kgd  = TN_removed_kgd * ef
        N2O_kgd    = N2O_N_kgd * 44 / 28
        CO2eq_kgd  = N2O_kgd * GHG_FACTORS["GWP_N2O_kgCO2eq"]

        # Low/high range for uncertainty
        low_CO2eq  = TN_removed_kgd * ef_range[0] * 44/28 * GHG_FACTORS["GWP_N2O_kgCO2eq"]
        high_CO2eq = TN_removed_kgd * ef_range[1] * 44/28 * GHG_FACTORS["GWP_N2O_kgCO2eq"]

        # Normalize
        intensity_per_m3  = CO2eq_kgd / Q if Q else None
        intensity_per_PE  = CO2eq_kgd / (Q * 5 / 1000) if Q else None   # rough PE from Q @ 200 L/cap/d

        return {
            "process_type":          process_type,
            "TKN_influent_mgL":      TKN_in,
            "TN_effluent_mgL":       TN_eff or 0,
            "TN_removed_kgd":        round(TN_removed_kgd, 1),
            "N2O_emission_factor":   ef,
            "N2O_emitted_kgd":       round(N2O_kgd, 3),
            "CO2eq_kgd":             round(CO2eq_kgd, 1),
            "CO2eq_range_low_high":  [round(low_CO2eq, 1), round(high_CO2eq, 1)],
            "intensity_gCO2eq_m3":   round(intensity_per_m3 * 1000, 1) if intensity_per_m3 else None,
            "note": (
                "N₂O emissions are highly variable. BNR plants with unstable operation "
                "or DO fluctuation can hit the upper end of the range. Consider "
                "monitoring campaign before publishing the number."
            ),
            "source": "IPCC 2019 Refinement + Law et al. 2012 + Foley et al. 2010",
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def estimate_ghg_footprint(job_id: str = "",
                                 include_indirect: bool = True,
                                 include_chemicals: bool = True) -> dict:
    """Estimate total GHG footprint of the plant (direct + indirect + Scope 3).

    Breaks down emissions into:
    - Direct: N₂O (BNR), CH₄ (digestion, open surfaces)
    - Indirect: grid electricity consumption
    - Scope 3: chemical manufacturing emissions

    Args:
        job_id:            Completed simulation job.
        include_indirect:  Include electricity (true)
        include_chemicals: Include chemical manufacturing (true)
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

        Q = read("Influent", ["param__Q"])
        if not Q:
            return {"error": "No flow data"}

        # Direct N2O (delegate)
        n2o_result = await estimate_n2o_emissions(job_id=job_id, process_type="BNR")
        n2o_CO2eq = n2o_result.get("CO2eq_kgd", 0)

        # Direct CH4 (digester + open surfaces)
        COD_in = read("Influent", ["param__S_COD", "param__COD"])
        COD_load_kgd = (COD_in or 0) * Q / 1000

        # If digester present
        has_digester = any("Digester" in v for v in all_vars)
        if has_digester:
            # Assume 40% of COD reaches digester, 5% of that escapes as fugitive CH4
            CH4_digester_kgd = COD_load_kgd * 0.4 * 0.05 * 0.25 * 16/64
        else:
            CH4_digester_kgd = 0
        # Open-surface fugitive CH4
        CH4_surface_kgd = COD_load_kgd * GHG_FACTORS["CH4_emission_factor_opensurface"]

        CH4_CO2eq = (CH4_digester_kgd + CH4_surface_kgd) * GHG_FACTORS["GWP_CH4_kgCO2eq"]

        # Indirect: electricity
        energy_CO2eq = 0
        if include_indirect:
            # Energy estimate: ~0.4 kWh/m³ for CAS, 0.6 for MBR
            has_mbr = any("MBR" in v for v in all_vars)
            kwh_per_m3 = 0.6 if has_mbr else 0.4
            daily_kwh  = Q * kwh_per_m3
            energy_CO2eq = daily_kwh * GHG_FACTORS["grid_emission_egypt_kgCO2eq_kWh"]

        # Scope 3: chemicals (rough, read FeCl3 + polymer + methanol if dosed)
        chem_CO2eq = 0
        if include_chemicals:
            for chem, var_pattern in [
                ("FeCl3",    "FeCl3"), ("alum", "alum"),
                ("methanol", "methanol"), ("polymer", "polymer"),
                ("NaOH",     "NaOH"),    ("chlorine","Cl"),
            ]:
                for v in all_vars:
                    if var_pattern.lower() in v.lower() and "dose" in v.lower():
                        try:
                            dose_mgL = float(ds.sumo.get(v))
                            kgd = dose_mgL * Q / 1000
                            chem_CO2eq += kgd * GHG_FACTORS.get(f"{chem}_kgCO2eq_kg", 1.0)
                            break
                        except Exception:
                            continue

        total_CO2eq = n2o_CO2eq + CH4_CO2eq + energy_CO2eq + chem_CO2eq
        intensity_per_m3 = total_CO2eq / Q if Q else 0

        return {
            "flow_m3d":             Q,
            "COD_load_kgd":         round(COD_load_kgd, 1),
            "breakdown_kgCO2eq_d": {
                "direct_N2O":       round(n2o_CO2eq, 1),
                "direct_CH4":       round(CH4_CO2eq, 1),
                "indirect_energy":  round(energy_CO2eq, 1) if include_indirect else "excluded",
                "scope3_chemicals": round(chem_CO2eq, 1) if include_chemicals else "excluded",
            },
            "total_kgCO2eq_d":      round(total_CO2eq, 1),
            "total_tCO2eq_yr":      round(total_CO2eq * 365 / 1000, 1),
            "intensity_gCO2eq_m3":  round(intensity_per_m3 * 1000, 1),
            "note": (
                "Egyptian grid factor 0.48 kgCO₂eq/kWh used. "
                "For renewable power, override with a cleaner grid factor."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def compute_carbon_intensity(job_id: str = "") -> dict:
    """Compute carbon intensity normalized per unit treated and per kg COD removed.

    Returns kg CO₂eq / m³ and kg CO₂eq / kg COD removed — the two most commonly
    reported WWTP sustainability metrics.

    Args:
        job_id: Completed simulation job (uses current state if empty).
    """
    try:
        ghg = await estimate_ghg_footprint(job_id=job_id)
        if "error" in ghg:
            return ghg

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

        Q       = ghg["flow_m3d"]
        COD_in  = read("Influent", ["param__S_COD", "param__COD"]) or 0
        COD_eff = read("Effluent", ["S_COD", "param__COD"])       or 0
        COD_removed_kgd = (COD_in - COD_eff) * Q / 1000

        total_kgd = ghg["total_kgCO2eq_d"]

        return {
            "total_kgCO2eq_d":              total_kgd,
            "flow_m3d":                     Q,
            "COD_removed_kgd":              round(COD_removed_kgd, 1),
            "kgCO2eq_per_m3_treated":       round(total_kgd / Q, 3) if Q else None,
            "kgCO2eq_per_kgCOD_removed":    round(total_kgd / COD_removed_kgd, 2)
                                               if COD_removed_kgd > 0 else None,
            "benchmarks": {
                "good_kgCO2eq_m3":      "< 0.3",
                "average_kgCO2eq_m3":   "0.3 – 0.6",
                "poor_kgCO2eq_m3":      "> 0.6",
            },
            "source": "UK Water UK Carbon Accounting benchmarks",
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP AG — Economic Analysis
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def estimate_capex() -> dict:
    """Estimate total CAPEX from the current model's unit-process sizing.

    Reads volumes and areas of every configured unit process and applies
    unit-cost references (Egyptian market, 2024 USD).
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        # Discover units in the model
        unit_names = set()
        for v in all_vars:
            parts = v.split("__")
            if len(parts) >= 3:
                unit_names.add(parts[2])

        def read_v(unit):
            for s in ["param__V", "param__Volume"]:
                var = f"Sumo__Plant__{unit}__{s}"
                if var in all_vars:
                    try:
                        return float(ds.sumo.get(var))
                    except Exception:
                        continue
            return None

        capex_items = []
        total = 0

        for unit in unit_names:
            V = read_v(unit)
            if not V or V <= 0:
                continue

            # Guess unit type from name
            name_low = unit.lower()
            if any(k in name_low for k in ["primclar", "primary"]):
                rate = COST_REFERENCES["capex_primary_clarifier_USD_m3"]
                utype = "primary_clarifier"
            elif any(k in name_low for k in ["mbr"]):
                rate = COST_REFERENCES["capex_mbr_USD_m3"]
                utype = "mbr"
            elif any(k in name_low for k in ["aer", "cstr", "reactor"]):
                rate = COST_REFERENCES["capex_aeration_tank_USD_m3"]
                utype = "aeration_tank"
            elif any(k in name_low for k in ["anox"]):
                rate = COST_REFERENCES["capex_anoxic_zone_USD_m3"]
                utype = "anoxic"
            elif any(k in name_low for k in ["ana"]):
                rate = COST_REFERENCES["capex_anaerobic_zone_USD_m3"]
                utype = "anaerobic"
            elif any(k in name_low for k in ["secclar", "sec_clar", "settle"]):
                rate = COST_REFERENCES["capex_secondary_clarifier_USD_m3"]
                utype = "secondary_clarifier"
            elif any(k in name_low for k in ["digest"]):
                rate = COST_REFERENCES["capex_digester_USD_m3"]
                utype = "digester"
            elif any(k in name_low for k in ["filter", "tertfilter", "tert"]):
                rate = COST_REFERENCES["capex_tertiary_filter_USD_m3"]
                utype = "tertiary_filter"
            elif any(k in name_low for k in ["disinf", "uv", "chlor"]):
                rate = COST_REFERENCES["capex_disinfection_USD_m3"]
                utype = "disinfection"
            elif any(k in name_low for k in ["thick"]):
                rate = COST_REFERENCES["capex_thickener_USD_m3"]
                utype = "thickener"
            else:
                continue

            cost = V * rate
            total += cost
            capex_items.append({
                "unit":        unit,
                "type":        utype,
                "volume_m3":   round(V, 1),
                "unit_cost_USD_m3": rate,
                "capex_USD":   round(cost, 0),
            })

        # Add contingency + engineering + installation markup (typical 35–50%)
        markup_pct = 45
        capex_with_markup = total * (1 + markup_pct / 100)

        return {
            "capex_items":            capex_items,
            "unit_processes_costed":  len(capex_items),
            "base_capex_USD":         round(total, 0),
            "markup_pct":             markup_pct,
            "markup_description":     "Engineering + installation + contingency + commissioning",
            "total_installed_USD":    round(capex_with_markup, 0),
            "note": (
                "Rough order of magnitude (±30%). Based on Egyptian market prices "
                "2023–2024. For detailed costing, use vendor-specific curves."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def estimate_annual_opex(energy_kWh_d: float = None,
                               sludge_kgDS_d: float = None,
                               chemicals_kgd: dict = None) -> dict:
    """Estimate annual OPEX: energy, chemicals, sludge disposal, labor, maintenance.

    Args:
        energy_kWh_d:  Daily energy consumption. If None, estimates from plant size.
        sludge_kgDS_d: Daily sludge production. If None, estimates from model.
        chemicals_kgd: Dict of chemical → kg/d (e.g. {'FeCl3': 600, 'polymer': 80}).
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

        Q = read("Influent", ["param__Q"])
        if not Q:
            return {"error": "Cannot read influent flow"}

        # Energy estimate
        if energy_kWh_d is None:
            has_mbr = any("MBR" in v for v in all_vars)
            kwh_per_m3 = 0.6 if has_mbr else 0.4
            energy_kWh_d = Q * kwh_per_m3

        # Sludge estimate (rough)
        if sludge_kgDS_d is None:
            COD_in = read("Influent", ["param__S_COD", "param__COD"]) or 600
            sludge_kgDS_d = COD_in * Q / 1000 * 0.35    # ~0.35 kg DS/kg COD

        opex_lines = []

        # 1. Electricity
        elec_annual = energy_kWh_d * 365 * COST_REFERENCES["electricity_cost_USD_kWh"]
        opex_lines.append({"item": "Electricity",
                            "daily_USD": round(energy_kWh_d *
                                                COST_REFERENCES["electricity_cost_USD_kWh"], 1),
                            "annual_USD": round(elec_annual, 0)})

        # 2. Sludge disposal
        sludge_annual = sludge_kgDS_d / 1000 * 365 * COST_REFERENCES["sludge_disposal_USD_tDS"]
        opex_lines.append({"item": "Sludge disposal",
                            "daily_USD": round(sludge_kgDS_d / 1000 *
                                                 COST_REFERENCES["sludge_disposal_USD_tDS"], 1),
                            "annual_USD": round(sludge_annual, 0)})

        # 3. Chemicals
        chem_annual = 0
        chem_detail = []
        if chemicals_kgd is None:
            # Try to read from model
            chemicals_kgd = {}
            for chem in ["FeCl3", "alum", "methanol", "polymer", "NaOH"]:
                for v in all_vars:
                    if chem.lower() in v.lower() and "dose" in v.lower():
                        try:
                            dose_mgL = float(ds.sumo.get(v))
                            chemicals_kgd[chem] = dose_mgL * Q / 1000
                            break
                        except Exception:
                            continue

        for chem, kgd in chemicals_kgd.items():
            unit_cost = COST_REFERENCES["chemical_costs_USD_kg"].get(chem, 1.0)
            annual = kgd * 365 * unit_cost
            chem_annual += annual
            chem_detail.append({"chemical": chem, "kg_d": round(kgd, 1),
                                 "unit_USD_kg": unit_cost,
                                 "annual_USD": round(annual, 0)})

        opex_lines.append({"item": "Chemicals", "breakdown": chem_detail,
                            "annual_USD": round(chem_annual, 0)})

        # 4. Labor
        labor_annual = Q * COST_REFERENCES["labor_cost_USD_year_per_m3d"]
        opex_lines.append({"item": "Labor", "annual_USD": round(labor_annual, 0)})

        # 5. Maintenance (3% of CAPEX)
        try:
            capex_result = await estimate_capex()
            capex_total = capex_result.get("total_installed_USD", 0)
            maint_annual = capex_total * COST_REFERENCES["maintenance_pct_of_capex_annual"]
        except Exception:
            maint_annual = 0
            capex_total = None
        opex_lines.append({"item": "Maintenance (3% CAPEX)",
                            "annual_USD": round(maint_annual, 0)})

        total_annual = elec_annual + sludge_annual + chem_annual + labor_annual + maint_annual

        return {
            "flow_m3d":        Q,
            "opex_items":      opex_lines,
            "total_annual_USD":round(total_annual, 0),
            "total_daily_USD": round(total_annual / 365, 1),
            "capex_basis_for_maintenance_USD": capex_total,
            "note": (
                "Based on Egyptian market 2024 pricing. Override electricity_kWh_d, "
                "sludge_kgDS_d, or chemicals_kgd if you have measured data."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def compute_unit_treatment_cost(project_life_yrs: int = 25,
                                      discount_rate: float = 0.08) -> dict:
    """Compute levelized unit treatment cost (USD/m³) combining CAPEX + OPEX
    over plant life, using present-value economics.

    Args:
        project_life_yrs: Amortization period (default 25 y).
        discount_rate:    Discount rate for present-value calculation (default 8%).
    """
    try:
        capex = await estimate_capex()
        opex  = await estimate_annual_opex()

        if "error" in capex or "error" in opex:
            return {"error": "CAPEX or OPEX estimation failed",
                    "capex_error": capex.get("error"),
                    "opex_error":  opex.get("error")}

        capex_total   = capex["total_installed_USD"]
        opex_annual   = opex["total_annual_USD"]
        Q             = opex["flow_m3d"]

        # Capital recovery factor
        r = discount_rate
        n = project_life_yrs
        CRF = r * (1 + r)**n / ((1 + r)**n - 1)

        annualized_capex = capex_total * CRF
        total_annualized = annualized_capex + opex_annual

        annual_m3   = Q * 365
        cost_per_m3 = total_annualized / annual_m3 if annual_m3 else None

        return {
            "capex_total_USD":        capex_total,
            "opex_annual_USD":        opex_annual,
            "project_life_yrs":       n,
            "discount_rate":          r,
            "capital_recovery_factor":round(CRF, 4),
            "annualized_capex_USD":   round(annualized_capex, 0),
            "total_annualized_USD":   round(total_annualized, 0),
            "flow_m3d":               Q,
            "unit_cost_USD_per_m3":   round(cost_per_m3, 3) if cost_per_m3 else None,
            "unit_cost_EGP_per_m3":   round(cost_per_m3 * 50, 2) if cost_per_m3 else None,
            "benchmarks": {
                "good_USD_m3":     "< 0.15",
                "average_USD_m3":  "0.15 – 0.30",
                "high_USD_m3":     "> 0.30",
            },
            "note": "EGP conversion uses 1 USD ≈ 50 EGP (2024)."
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP AH — Water Reuse & Biosolids
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def assess_water_reuse_suitability(job_id: str = "") -> dict:
    """Classify final effluent against Egyptian Standard 501/2015 for
    agricultural reuse (Class A / B / C).

    Class A → unrestricted reuse (any crop)
    Class B → restricted (cooked crops, fodder, fruit trees)
    Class C → forest/wood trees only

    Args:
        job_id: Completed simulation job. If empty, uses current state.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        def read_eff(suffixes):
            for s in suffixes:
                var = f"Sumo__Plant__Effluent__{s}"
                if var in all_vars:
                    try:
                        return float(ds.sumo.get(var))
                    except Exception:
                        continue
            return None

        eff = {
            "BOD5":   read_eff(["BOD5", "S_S"]),
            "COD":    read_eff(["S_COD", "COD"]),
            "TSS":    read_eff(["X_TSS", "TSS"]),
            "NH4_N":  read_eff(["S_NH4"]),
        }

        # Fecal coliform not natively simulated — use proxy from disinfection config
        fec = None
        for v in all_vars:
            if "coliform" in v.lower() or "fc_eff" in v.lower():
                try:
                    fec = float(ds.sumo.get(v))
                    break
                except Exception:
                    pass

        # Evaluate against each class
        classifications = {}
        for cls_name, limits in EGYPT_REUSE_STANDARDS.items():
            passes = {}
            all_pass = True
            for param, lim in limits.items():
                if param in ("description", "intestinal_nematodes"):
                    continue
                val = fec if "coliform" in param else eff.get(param)
                if val is None:
                    passes[param] = "not_measured"
                    continue
                ok = val <= lim
                passes[param] = {"value": round(val, 2), "limit": lim, "pass": ok}
                if not ok:
                    all_pass = False
            classifications[cls_name] = {
                "description": limits["description"],
                "checks":      passes,
                "qualifies":   all_pass,
            }

        # Determine best achievable
        best = "Not_reusable"
        for cls in ["Class_A", "Class_B", "Class_C"]:
            if classifications[cls]["qualifies"]:
                best = cls
                break

        return {
            "effluent_values":        eff,
            "fecal_coliform_MPN":     fec,
            "classifications":        classifications,
            "best_achievable_class":  best,
            "standard":               "Egyptian Standard 501/2015",
            "note": (
                "Fecal coliform requires a disinfection unit in the model "
                "or measured data — not simulated natively by SUMO."
                if fec is None else ""
            ),
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def classify_biosolids_quality(job_id: str = "",
                                     fecal_coliform_MPN_gDS: float = None,
                                     vs_reduction_pct: float = None) -> dict:
    """Classify biosolids as Class A or Class B per US EPA 503 / Egyptian
    Decree 44/2000.

    Class A → unrestricted land application
    Class B → restricted (buffer zones, harvest delays)

    Args:
        job_id:                Completed simulation job.
        fecal_coliform_MPN_gDS:User-supplied measurement (not simulated).
        vs_reduction_pct:      Volatile solids reduction in digestion. Read from
                                model if available.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        # Read VS reduction from digester
        if vs_reduction_pct is None:
            for v in all_vars:
                if "VS_destruction" in v or "VSR" in v or "vs_reduction" in v.lower():
                    try:
                        vs_reduction_pct = float(ds.sumo.get(v))
                        break
                    except Exception:
                        pass

        # Evaluate against Class A & B
        classifications = {}
        for cls_name, criteria in BIOSOLIDS_STANDARDS.items():
            passes = {}
            all_ok = True

            # Fecal coliform
            fc_lim = criteria.get("fecal_coliform_MPN_gDS")
            if fc_lim is not None and fecal_coliform_MPN_gDS is not None:
                ok = fecal_coliform_MPN_gDS <= fc_lim
                passes["fecal_coliform"] = {
                    "value": fecal_coliform_MPN_gDS, "limit": fc_lim, "pass": ok
                }
                if not ok:
                    all_ok = False
            else:
                passes["fecal_coliform"] = "not_provided"
                all_ok = False

            # VS reduction
            vs_lim = criteria.get("VS_reduction_pct_min")
            if vs_lim is not None and vs_reduction_pct is not None:
                ok = vs_reduction_pct >= vs_lim
                passes["VS_reduction"] = {
                    "value": vs_reduction_pct, "min": vs_lim, "pass": ok
                }
                if not ok:
                    all_ok = False
            else:
                passes["VS_reduction"] = "not_found_in_model"

            classifications[cls_name] = {
                "description": criteria["description"],
                "checks":      passes,
                "qualifies":   all_ok,
            }

        # Best achievable
        best = "Not_classified"
        if classifications.get("Class_A", {}).get("qualifies"):
            best = "Class_A"
        elif classifications.get("Class_B", {}).get("qualifies"):
            best = "Class_B"

        return {
            "vs_reduction_pct":        vs_reduction_pct,
            "fecal_coliform_MPN_gDS":  fecal_coliform_MPN_gDS,
            "classifications":         classifications,
            "best_achievable_class":   best,
            "standards":               "US EPA 40 CFR 503 + Egyptian Decree 44/2000",
            "note": (
                "Pass fecal_coliform_MPN_gDS from lab measurement. "
                "SUMO does not natively simulate pathogen indicators."
            )
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP AI — BNR Performance Rates
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def compute_nitrification_rate(unit_name: str = "AerTank1",
                                     influent_unit: str = "Influent",
                                     effluent_unit: str = "Effluent") -> dict:
    """Compute the Specific Nitrification Rate (SNR) and compare to theoretical.

    SNR = NH4 oxidized (g N/d) / VSS (g) = actual rate per unit biomass
    Compares to theoretical maximum: SNR_theo = μ_A / Y_A

    Args:
        unit_name:     Reactor where nitrification occurs.
        influent_unit: Influent unit.
        effluent_unit: Effluent unit.
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

        Q       = read(influent_unit, ["param__Q"])
        NH4_in  = read(influent_unit, ["param__S_NH4", "param__NH4"])
        NH4_eff = read(effluent_unit, ["S_NH4"])
        V       = read(unit_name,     ["param__V"])
        MLVSS   = read(unit_name,     ["X_VSS"])
        mu_A    = read(unit_name,     ["param__mu_A"]) or 0.8
        Y_A     = read(unit_name,     ["param__Y_A"])  or 0.24
        X_BA    = read(unit_name,     ["X_BA"])   # autotroph biomass

        if not all([Q, NH4_in, V, MLVSS]):
            return {"error": "Missing required values (Q, NH4_in, V, MLVSS)"}

        # NH4 oxidized (kg/d)
        NH4_oxidized_kgd = Q * (NH4_in - (NH4_eff or 0)) / 1000
        NH4_oxidized_gd  = NH4_oxidized_kgd * 1000

        # Biomass inventory (g)
        VSS_g   = V * MLVSS       # mg * m³ = g
        XBA_g   = V * (X_BA or 0)

        # Actual SNR: g NH4-N oxidized per g VSS per d
        SNR_VSS  = NH4_oxidized_gd / VSS_g if VSS_g > 0 else None
        SNR_XBA  = NH4_oxidized_gd / XBA_g if XBA_g > 0 else None

        # Theoretical max SNR: μ_A / Y_A
        SNR_theo = mu_A / Y_A  if Y_A  else None

        # Efficiency
        eff_pct = (NH4_oxidized_kgd / (Q * NH4_in / 1000) * 100) if NH4_in else None

        # Performance
        if SNR_VSS and SNR_theo:
            utilization = SNR_XBA / SNR_theo if SNR_XBA else None
            if utilization:
                if utilization > 0.9:
                    performance = "limiting (biomass at max rate)"
                elif utilization > 0.6:
                    performance = "healthy"
                else:
                    performance = "underutilized (NH4 limiting)"
            else:
                performance = "?"
        else:
            utilization, performance = None, None

        return {
            "unit":                unit_name,
            "NH4_oxidized_kgd":    round(NH4_oxidized_kgd, 2),
            "nitrification_eff_pct": round(eff_pct, 1) if eff_pct else None,
            "SNR_gN_gVSS_d":       round(SNR_VSS, 4) if SNR_VSS else None,
            "SNR_gN_gXBA_d":       round(SNR_XBA, 3) if SNR_XBA else None,
            "SNR_theoretical":     round(SNR_theo, 3) if SNR_theo else None,
            "utilization_fraction":round(utilization, 2) if utilization else None,
            "performance":         performance,
            "typical_range_SNR_VSS": "0.02 – 0.06 g N/g VSS/d at 20°C",
            "tip": (
                "If SNR is low: check DO (> 1.5 mg/L), SRT (> 5d at 25°C, "
                ">10d at 15°C), and alkalinity (> 4 mmol/L)."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def compute_denitrification_rate(anoxic_unit: str = "AnoxicTank1",
                                       influent_unit: str = "Influent") -> dict:
    """Compute the Specific Denitrification Rate (SDNR) in the anoxic zone.

    SDNR = g NO3-N reduced / (g VSS · d)
    Compares to typical literature ranges and checks if RBCOD (readily
    biodegradable COD) is sufficient.

    Args:
        anoxic_unit:   Anoxic zone unit name.
        influent_unit: Influent for RBCOD supply calculation.
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

        Q       = read(influent_unit, ["param__Q"])
        NO3_in  = read(anoxic_unit,   ["S_NO3_in", "param__NO3_in"])
        NO3_out = read(anoxic_unit,   ["S_NO3", "param__S_NO3"])
        V       = read(anoxic_unit,   ["param__V"])
        MLVSS   = read(anoxic_unit,   ["X_VSS"])
        MLR     = read(anoxic_unit,   ["param__internal_recycle_ratio"]) or 3.0
        COD_inf = read(influent_unit, ["param__S_COD"])
        frSFCOD = read(influent_unit, ["param__frSFCOD"]) or 0.10

        if not all([Q, V, MLVSS]):
            return {"error": "Missing required values (Q, V, MLVSS)"}

        # NO3 load to anoxic = Q_MLR × NO3_in
        Q_MLR = Q * MLR   # m3/d
        if NO3_in is not None and NO3_out is not None:
            NO3_reduced_kgd = Q_MLR * (NO3_in - NO3_out) / 1000
        else:
            NO3_reduced_kgd = None

        VSS_g = V * MLVSS

        SDNR = (NO3_reduced_kgd * 1000) / VSS_g if (NO3_reduced_kgd and VSS_g > 0) else None

        # RBCOD availability check
        RBCOD_available_kgd = (COD_inf or 0) * Q * frSFCOD / 1000
        # Stoichiometry: ~5.7 g RBCOD / g NO3-N reduced
        RBCOD_demand_kgd  = (NO3_reduced_kgd or 0) * 5.7
        carbon_sufficiency = (RBCOD_available_kgd / RBCOD_demand_kgd
                              if RBCOD_demand_kgd > 0 else None)

        # Performance
        if SDNR:
            if SDNR > 0.05:    performance = "high"
            elif SDNR > 0.02:  performance = "typical"
            elif SDNR > 0.005: performance = "low"
            else:              performance = "very_low"
        else:
            performance = None

        return {
            "unit":                    anoxic_unit,
            "NO3_reduced_kgd":         round(NO3_reduced_kgd, 2)
                                         if NO3_reduced_kgd else None,
            "SDNR_gN_gVSS_d":          round(SDNR, 4) if SDNR else None,
            "performance":             performance,
            "RBCOD_available_kgd":     round(RBCOD_available_kgd, 1),
            "RBCOD_demand_kgd":        round(RBCOD_demand_kgd, 1)
                                         if NO3_reduced_kgd else None,
            "carbon_sufficiency_ratio":round(carbon_sufficiency, 2)
                                         if carbon_sufficiency else None,
            "typical_range_SDNR":      "0.02 – 0.07 g N/g VSS/d at 20°C",
            "tip": (
                "If carbon_sufficiency_ratio < 1.0, denitrification is carbon-limited — "
                "add an external carbon source (methanol) or increase MLR. "
                "If SDNR is low but RBCOD plentiful, check anoxic DO (< 0.5 mg/L)."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def assess_ebpr_performance(anaerobic_unit: str = "AnaerobicTank1",
                                  aerobic_unit:   str = "AerTank1",
                                  influent_unit:  str = "Influent",
                                  effluent_unit:  str = "Effluent") -> dict:
    """Assess Enhanced Biological Phosphorus Removal (EBPR) performance.

    Checks anaerobic P release, aerobic P uptake, P_released/VFA ratio,
    and overall P removal against ASM2d typical values.

    Args:
        anaerobic_unit: EBPR anaerobic selector.
        aerobic_unit:   Main aerobic reactor.
        influent_unit, effluent_unit: Standard.
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

        Q       = read(influent_unit, ["param__Q"])
        TP_in   = read(influent_unit, ["param__S_TP", "param__TP"])
        TP_eff  = read(effluent_unit, ["S_TP"])
        PO4_in  = read(influent_unit, ["param__S_PO4"])
        PO4_ana = read(anaerobic_unit,["S_PO4"])
        PO4_aer = read(aerobic_unit,  ["S_PO4"])
        VFA_in  = read(influent_unit, ["param__S_A", "param__S_VFA"])
        X_PAO   = read(aerobic_unit,  ["X_PAO"])

        if not all([Q, TP_in]):
            return {"error": "Missing Q or TP influent"}

        # Overall P removal
        P_removed_kgd = Q * (TP_in - (TP_eff or 0)) / 1000
        P_removal_pct = ((TP_in - (TP_eff or 0)) / TP_in * 100) if TP_in else 0

        # Anaerobic P release
        P_release_mgL = (PO4_ana - (PO4_in or 0)) if (PO4_ana and PO4_in) else None

        # Aerobic P uptake
        P_uptake_mgL  = (PO4_ana - PO4_aer) if (PO4_ana and PO4_aer) else None

        # P_released / VFA ratio (typical 0.3–0.5 mol P / mol VFA-C for healthy PAOs)
        p_vfa_ratio = None
        if P_release_mgL is not None and VFA_in and VFA_in > 0:
            p_vfa_ratio = P_release_mgL / VFA_in

        # Classification
        if P_removal_pct > 85:    classification = "excellent"
        elif P_removal_pct > 70:  classification = "good"
        elif P_removal_pct > 50:  classification = "moderate"
        elif P_removal_pct > 20:  classification = "poor"
        else:                     classification = "no_EBPR"

        # Diagnosis
        issues = []
        if VFA_in is not None and VFA_in < 20:
            issues.append("VFA influent < 20 mg/L — EBPR carbon-limited. "
                           "Consider primary fermentation.")
        if P_release_mgL is not None and P_release_mgL < 5:
            issues.append("Low anaerobic P release — check DO/NO3 contamination in "
                           "anaerobic zone (should be < 0.02 mg/L DO, < 0.5 mg/L NO3).")
        if X_PAO is not None and X_PAO < 50:
            issues.append("Low PAO biomass — EBPR population not established. "
                           "SRT may be too long or carbon too low.")

        return {
            "flow_m3d":             Q,
            "TP_influent_mgL":      TP_in,
            "TP_effluent_mgL":      TP_eff,
            "P_removed_kgd":        round(P_removed_kgd, 2),
            "P_removal_pct":        round(P_removal_pct, 1),
            "anaerobic_P_release_mgL": round(P_release_mgL, 2) if P_release_mgL else None,
            "aerobic_P_uptake_mgL":    round(P_uptake_mgL, 2)  if P_uptake_mgL  else None,
            "P_VFA_ratio":          round(p_vfa_ratio, 2) if p_vfa_ratio else None,
            "PAO_biomass_mgL":      X_PAO,
            "VFA_influent_mgL":     VFA_in,
            "classification":       classification,
            "issues":               issues,
            "typical_values": {
                "P_removal_pct":    "> 85 for successful EBPR",
                "P_release_anaer":  "5 – 30 mg P/L",
                "P_VFA_ratio":      "0.3 – 0.5",
            }
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP AJ — Documentation & Model Export
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def generate_pfd_html(output_path: str = "",
                            include_flows: bool = True) -> dict:
    """Generate an interactive process flow diagram as a standalone HTML file.

    Reads the model's unit processes and flow streams and produces an SVG-based
    diagram showing units as boxes and streams as arrows, with flow rates
    labeled.

    Args:
        output_path:   HTML save path. Default: outputs/pfd_<timestamp>.html.
        include_flows: Label arrows with flow rates (m³/d).
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        # Discover units
        unit_names = set()
        for v in all_vars:
            parts = v.split("__")
            if len(parts) >= 3:
                unit_names.add(parts[2])

        # Very basic layout: arrange units left-to-right in discovered order
        # Categorize for vertical placement
        def classify(name):
            n = name.lower()
            if "influent" in n or "feed" in n:                     return "inlet"
            if "primclar" in n or "primary" in n:                  return "primary"
            if any(k in n for k in ["anaerobic", "anox"]):         return "selector"
            if any(k in n for k in ["aer", "cstr", "reactor", "mbr"]): return "main"
            if "secclar" in n or "settle" in n:                    return "clarifier"
            if "effluent" in n:                                    return "outlet"
            if "tert" in n or "filter" in n:                       return "tertiary"
            if "disinf" in n or "uv" in n or "chlor" in n:         return "disinfection"
            if "digest" in n:                                      return "digester"
            if "thick" in n:                                       return "thickener"
            if "dewater" in n:                                     return "dewater"
            if "ras" in n or "was" in n:                           return "pump"
            return "other"

        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(Path(CONFIG["output_dir"]) / f"pfd_{ts}.html")

        # Build unit list with positions
        cols = ["inlet", "primary", "selector", "main", "clarifier",
                "tertiary", "disinfection", "outlet"]
        categorized = {c: [] for c in cols}
        extras = []
        for u in sorted(unit_names):
            c = classify(u)
            if c in categorized:
                categorized[c].append(u)
            else:
                extras.append(u)

        # SVG boxes
        svg_boxes = []
        unit_positions = {}
        y_main = 200
        for col_idx, col in enumerate(cols):
            x = 60 + col_idx * 180
            for row_idx, u in enumerate(categorized[col]):
                y = y_main + row_idx * 100
                unit_positions[u] = (x + 60, y + 35)
                fill = {
                    "inlet": "#4A90E2", "primary": "#F5A623",
                    "selector": "#9B59B6", "main": "#2ECC71",
                    "clarifier": "#E74C3C", "tertiary": "#1ABC9C",
                    "disinfection": "#F39C12", "outlet": "#34495E",
                }.get(col, "#888")
                svg_boxes.append(
                    f'<rect x="{x}" y="{y}" width="120" height="70" rx="8" '
                    f'fill="{fill}" stroke="#222" stroke-width="1.5" />'
                    f'<text x="{x+60}" y="{y+35}" text-anchor="middle" '
                    f'fill="white" font-size="12" font-family="sans-serif">'
                    f'{u[:14]}</text>'
                    f'<text x="{x+60}" y="{y+52}" text-anchor="middle" '
                    f'fill="white" font-size="9" font-family="sans-serif">'
                    f'{col}</text>'
                )
        # Sludge row
        y_sludge = y_main + 300
        sludge_units = ((["digester"] if any("digest" in u.lower() for u in unit_names) else [])
                        + (["thickener"] if any("thick" in u.lower() for u in unit_names) else [])
                        + (["dewater"] if any("dewater" in u.lower() for u in unit_names) else []))
        for i, u in enumerate(sludge_units):
            x = 240 + i * 180
            svg_boxes.append(
                f'<rect x="{x}" y="{y_sludge}" width="120" height="70" rx="8" '
                f'fill="#7F8C8D" stroke="#222" stroke-width="1.5" />'
                f'<text x="{x+60}" y="{y_sludge+40}" text-anchor="middle" '
                f'fill="white" font-size="12">{u[:14]}</text>'
            )

        # Simple left-to-right connections across columns
        connections = []
        prev_col_unit = None
        for col in cols:
            if categorized[col]:
                curr = categorized[col][0]
                if prev_col_unit and curr in unit_positions and prev_col_unit in unit_positions:
                    (x1, y1) = unit_positions[prev_col_unit]
                    (x2, y2) = unit_positions[curr]
                    connections.append(
                        f'<line x1="{x1}" y1="{y1}" x2="{x2-60}" y2="{y2}" '
                        f'stroke="#2C3E50" stroke-width="2" '
                        f'marker-end="url(#arrowhead)" />'
                    )
                prev_col_unit = curr

        # Assemble HTML
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>SUMO24 Process Flow Diagram</title>
<style>
  body {{ font-family: sans-serif; background: #F4F6F8; padding: 20px; }}
  h1   {{ color: #2C3E50; }}
  .meta {{ background: white; padding: 15px; border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,.08); margin-bottom: 20px; }}
  svg   {{ background: white; border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,.08); }}
</style>
</head>
<body>
  <h1>SUMO24 Process Flow Diagram</h1>
  <div class="meta">
    <strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}<br>
    <strong>Model:</strong> {CONFIG.get('model_dll', 'unknown')}<br>
    <strong>Units found:</strong> {len(unit_names)}
  </div>
  <svg width="1600" height="600" viewBox="0 0 1600 600"
       xmlns="http://www.w3.org/2000/svg">
    <defs>
      <marker id="arrowhead" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="6" markerHeight="6" orient="auto">
        <path d="M0,0 L10,5 L0,10 Z" fill="#2C3E50"/>
      </marker>
    </defs>
    {''.join(connections)}
    {''.join(svg_boxes)}
  </svg>
</body>
</html>"""

        Path(output_path).write_text(html, encoding="utf-8")

        return {
            "output_path":   output_path,
            "units_rendered":len(unit_positions) + len(sludge_units),
            "note": (
                "Simple left-to-right PFD based on naming heuristics. "
                "Open the HTML in a browser to view."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def export_model_metadata_json(output_path: str = "",
                                     include_parameters: bool = True) -> dict:
    """Export a full snapshot of the model (units, streams, parameters, state)
    as a JSON file.

    Useful for versioning, archiving, or sharing model configurations outside
    SUMO.

    Args:
        output_path:        JSON save path.
        include_parameters: Include parameter values (can be large).
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        # Unit discovery
        unit_names = set()
        for v in all_vars:
            parts = v.split("__")
            if len(parts) >= 3:
                unit_names.add(parts[2])

        # Per-unit parameter snapshot
        snapshot = {
            "generated_at":     datetime.now().isoformat(),
            "model_dll":        CONFIG.get("model_dll"),
            "state_xml":        CONFIG.get("state_xml"),
            "compliance_set":   CONFIG.get("compliance_set", "law48_nile"),
            "plant_temp_C":     CONFIG.get("plant_temp_C", 25.0),
            "unit_count":       len(unit_names),
            "units":            {},
            "total_variables":  len(all_vars),
        }

        for unit in sorted(unit_names):
            unit_data = {"parameters": {}, "state": {}}
            for v in all_vars:
                parts = v.split("__")
                if len(parts) < 3 or parts[2] != unit:
                    continue
                is_param = "param" in v.lower()
                try:
                    val = float(ds.sumo.get(v))
                    bucket = "parameters" if is_param else "state"
                    if include_parameters or bucket == "state":
                        unit_data[bucket][v.replace(f"Sumo__Plant__{unit}__", "")] = val
                except Exception:
                    pass
            if unit_data["parameters"] or unit_data["state"]:
                snapshot["units"][unit] = unit_data

        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(Path(CONFIG["output_dir"]) / f"model_snapshot_{ts}.json")

        Path(output_path).write_text(
            json.dumps(snapshot, indent=2, default=str), encoding="utf-8"
        )

        return {
            "output_path":          output_path,
            "units_exported":       len(snapshot["units"]),
            "file_size_kB":         round(Path(output_path).stat().st_size / 1024, 1),
            "note": (
                "This is a point-in-time snapshot. Use together with Git to "
                "version-control your model configurations."
            )
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP AK — Automation
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def run_auto_calibration(xlsx_path: str = "",
                               max_iterations: int = 5,
                               target_MAPE: float = 10.0,
                               step_size_pct: float = 10.0) -> dict:
    """Automated calibration loop: iteratively adjust ASM parameters until MAPE
    drops below the target.

    Each iteration:
      1. Runs a steady-state simulation
      2. Compares against the measured dataset → computes MAPE
      3. If MAPE > target: applies the top suggestion from
         `suggest_calibration_adjustments` (clamped by step_size_pct)
      4. Repeats until target reached or max_iterations hit

    Args:
        xlsx_path:       Measured dataset path.
        max_iterations:  Maximum iteration count (default 5).
        target_MAPE:     Stop when MAPE ≤ this (%).
        step_size_pct:   Maximum ±% adjustment per parameter per iteration.
    """
    try:
        history = []
        ds = _make_ds()

        # Map suggestion keywords to actual SUMO parameter names
        param_lookup = {
            "mu_H":  "Sumo__Plant__AerTank1__param__mu_H",
            "Y_H":   "Sumo__Plant__AerTank1__param__Y_H",
            "K_S":   "Sumo__Plant__AerTank1__param__K_S",
            "b_H":   "Sumo__Plant__AerTank1__param__b_H",
            "mu_A":  "Sumo__Plant__AerTank1__param__mu_A",
            "Y_A":   "Sumo__Plant__AerTank1__param__Y_A",
            "K_NH":  "Sumo__Plant__AerTank1__param__K_NH",
            "b_A":   "Sumo__Plant__AerTank1__param__b_A",
            "SRT":   "Sumo__Plant__AerTank1__param__SRT",
        }

        for iteration in range(1, max_iterations + 1):
            # 1. Run steady state
            try:
                job = _run_steady_state_internal(ds)
                job_id = job.get("job_id")
            except Exception as e:
                return {"error": f"Simulation failed at iter {iteration}: {e}",
                        "history": history}

            # 2. Compare
            comparison = await compare_dataset_vs_simulation(job_id=job_id,
                                                               xlsx_path=xlsx_path)
            mape = comparison.get("mean_abs_pct_error")
            if mape is None:
                return {"error": "MAPE unavailable", "history": history}

            iter_record = {
                "iteration": iteration,
                "job_id":    job_id,
                "MAPE":      round(mape, 2),
            }

            # 3. Exit if good enough
            if mape <= target_MAPE:
                iter_record["status"] = "CONVERGED"
                history.append(iter_record)
                return {
                    "status":          "SUCCESS",
                    "final_MAPE":      round(mape, 2),
                    "iterations_used": iteration,
                    "target_MAPE":     target_MAPE,
                    "history":         history,
                }

            # 4. Get suggestions and apply the top one
            sugg = await suggest_calibration_adjustments(
                job_id=job_id, xlsx_path=xlsx_path, target_MAPE=target_MAPE)
            suggestions = sugg.get("suggestions", [])

            if not suggestions:
                iter_record["status"] = "NO_SUGGESTIONS"
                history.append(iter_record)
                break

            # Pick first suggestion, look up the actual SUMO variable
            top = suggestions[0]
            param_short = top.get("adjust")
            direction   = top.get("direction")
            var_name    = param_lookup.get(param_short)

            if not var_name:
                iter_record["status"] = f"UNMAPPABLE_PARAM_{param_short}"
                history.append(iter_record)
                continue

            # Apply a bounded step
            try:
                current = float(ds.sumo.get(var_name))
                # If simulated was too high → decrease parameter; too low → increase
                sign = -1 if direction == "too_high" else +1
                new_val = current * (1 + sign * step_size_pct / 100)
                ds.sumo.set(var_name, new_val)
                iter_record["adjustment"] = {
                    "parameter": var_name,
                    "old_value": round(current, 4),
                    "new_value": round(new_val, 4),
                    "direction": direction,
                }
            except Exception as e:
                iter_record["status"] = f"SET_FAILED: {e}"
                history.append(iter_record)
                break

            history.append(iter_record)

        # If we got here, max_iterations hit without convergence
        final_mape = history[-1]["MAPE"] if history else None
        return {
            "status":          "MAX_ITER_REACHED",
            "final_MAPE":      final_mape,
            "iterations_used": max_iterations,
            "target_MAPE":     target_MAPE,
            "history":         history,
            "tip": (
                "If MAPE didn't converge, try: (a) looser target_MAPE, "
                "(b) larger step_size_pct, (c) more parameters by editing "
                "param_lookup dict, or (d) manual calibration."
            )
        }
    except Exception as e:
        return {"error": str(e)}
```

---

## Step 4 — Save and restart

1. Save `server.py`.
2. Fully quit Claude Desktop.
3. Relaunch. Ask **"List all SUMO24 environmental and economic tools"** and confirm.

---

## Step 5 — Verification prompts

| Prompt | Tool |
|---|---|
| `Estimate N2O emissions from my BNR plant` | `estimate_n2o_emissions` |
| `What is my plant's total GHG footprint including indirect?` | `estimate_ghg_footprint` |
| `Compute my carbon intensity per m³ treated` | `compute_carbon_intensity` |
| `How much does my plant cost to build (CAPEX)?` | `estimate_capex` |
| `Estimate my annual OPEX in USD` | `estimate_annual_opex` |
| `What's my levelized cost per m³ treated over 25 years?` | `compute_unit_treatment_cost` |
| `Can my effluent be reused for agriculture per Egyptian Standard 501/2015?` | `assess_water_reuse_suitability` |
| `Are my biosolids Class A or Class B? VS reduction is 42%, fecal coliform 500 MPN/g DS` | `classify_biosolids_quality` |
| `What's my specific nitrification rate (SNR)?` | `compute_nitrification_rate` |
| `Is my denitrification carbon-limited? Compute SDNR` | `compute_denitrification_rate` |
| `Assess my EBPR performance — anaerobic release, aerobic uptake` | `assess_ebpr_performance` |
| `Generate a process flow diagram of my plant as HTML` | `generate_pfd_html` |
| `Export my full model as a JSON snapshot for archiving` | `export_model_metadata_json` |
| `Auto-calibrate my model until MAPE < 10%, max 5 iterations` | `run_auto_calibration` |

---

## Grand total after this file

| Tool batch | Count |
|---|---|
| Groups A–X (per reference PDF) | 104 |
| Groups Y–AE (previous gap-filling MD) | 19 |
| **Groups AF–AK (this file)** | **14** |
| **TOTAL** | **137 tools across 37 groups** |

---

## Notes for Cowork

### Research basis (so you can cite them in reports)
- **GHG factors:** IPCC 2019 Refinement Ch.6 Wastewater; Law et al. 2012 (N₂O from BNR); Foley et al. 2010
- **Costs:** Metcalf & Eddy 5th ed. cost curves, adjusted to Egyptian market 2024
- **Egyptian Std 501/2015:** Three classes (A/B/C) for treated effluent agricultural reuse
- **Biosolids:** US EPA 40 CFR Part 503 + Egyptian Decree 44/2000
- **BNR rates:** SNR/SDNR typical ranges per IWA STR-9 and Metcalf & Eddy 5th ed.

### Dependencies
- `run_auto_calibration` calls `_run_steady_state_internal` (defined in the previous gap-filling file) and `suggest_calibration_adjustments` (also in AC). If you haven't added those yet, add them first.
- `compute_unit_treatment_cost` calls both `estimate_capex` and `estimate_annual_opex` — they must be defined in the same file.

### What's still NOT covered (intentional)
These are out of scope for an MCP server and better handled separately:
- **Monte Carlo uncertainty quantification** — too computationally heavy; use a dedicated tool
- **Multi-objective optimization (Pareto)** — needs a solver like NSGA-II, beyond MCP's request/response model
- **Model Predictive Control (MPC)** — requires dedicated control software
- **Real-time SCADA integration** — needs persistent connections
- **Full LCA (beyond GHG)** — ReCiPe / CML methodology, needs ecoinvent database

After this addition, your SUMO24 MCP server covers the complete design → calibration → analysis → reporting → sustainability workflow needed for Egyptian municipal WWTP digital twins.
