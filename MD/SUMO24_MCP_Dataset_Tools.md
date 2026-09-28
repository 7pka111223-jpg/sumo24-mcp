# SUMO24 MCP — Dataset Reading & Excel-to-SUMO Tools

## Context
This file adds **dataset-reading tools** to the existing MCP server at
`F:/UNI/SUMO/MCP/PY/server.py`. These tools read the `SUMO24_WWTP_Dataset_and_Tools.xlsx`
template (WWTP field/lab data for influent, primary clarifier, biological treatment,
secondary clarifier, final effluent, RAS/WAS) and apply the values to a SUMO24 model.

Capabilities added:
- Parse the Excel data-entry template into structured data
- Map measurement points (e.g. "Raw Influent") to SUMO unit names
- Map lab parameters (BOD, COD, TSS, NH4, etc.) to SUMO variable names
- Apply entire datasets to the model in one call
- Compare measured data against simulation results (calibration workflow)
- Validate measurements against Law 48/1982 limits
- Export simulation results back into the Excel template

> ⚠️ **Do not remove or modify any existing tools.**
> Insert all new code after the last existing `@server.tool()` function,
> before any `if __name__ == "__main__"` block.

> ℹ️ **Prerequisite:** `openpyxl` must be installed for the Python environment
> running the MCP server. If it isn't, run:
> ```powershell
> py -3 -m pip install openpyxl
> ```

---

## File to Edit
**`F:/UNI/SUMO/MCP/PY/server.py`**

---

## Step 1 — Verify or add imports

Find the import block near the top of `server.py`. Add these lines if they are not
already present:

```python
from openpyxl import load_workbook, Workbook
from openpyxl.styles import PatternFill, Font
from copy import deepcopy
```

`os`, `Path`, and `datetime` should already be imported from previous batches — if not,
add them too.

---

## Step 2 — Add the dataset schema and mapping registries

Insert this block **immediately after** the `RESEARCH_DEFAULTS` dict (or at module
level if `RESEARCH_DEFAULTS` is not present):

```python
# ═══════════════════════════════════════════════════════════════════════════
# DATASET SCHEMA — maps the Excel template to SUMO24 units & variables
# Template:  SUMO24_WWTP_Dataset_and_Tools.xlsx
# Reference: '💧 Data Entry' sheet, measurement points in col A,
#            parameters in cols B–P, Law 48 limits in row 6, data from row 7 down.
# ═══════════════════════════════════════════════════════════════════════════

DATASET_SCHEMA = {
    "sheet_name": "💧 Data Entry",
    "param_header_row": 4,
    "sumo_hint_row":    5,
    "law48_row":        6,
    "data_start_row":   7,

    # Column index (1-based) → parameter name (internal key)
    "columns": {
        1:  "label",
        2:  "Flow",
        3:  "BOD5",
        4:  "COD",
        5:  "TSS",
        6:  "VSS",
        7:  "NH4_N",
        8:  "NO3_N",
        9:  "TN",
        10: "TP",
        11: "pH",
        12: "Temp",
        13: "DO",
        14: "Turbidity",
        15: "Oil_Grease",
        16: "Notes",
    },

    # Internal parameter key → (unit, SUMO variable suffix candidates)
    # The actual SUMO variable pattern is: Sumo__Plant__<UnitName>__<suffix>
    "parameter_map": {
        "Flow":       {"unit": "m³/d",  "suffixes": ["param__Q"]},
        "BOD5":       {"unit": "mg/L",  "suffixes": ["param__S_S", "param__BOD5"]},
        "COD":        {"unit": "mg/L",  "suffixes": ["param__S_COD", "param__COD"]},
        "TSS":        {"unit": "mg/L",  "suffixes": ["param__X_TSS", "param__TSS"]},
        "VSS":        {"unit": "mg/L",  "suffixes": ["param__X_VSS", "param__VSS"]},
        "NH4_N":      {"unit": "mg/L",  "suffixes": ["param__S_NH4", "param__NH4"]},
        "NO3_N":      {"unit": "mg/L",  "suffixes": ["param__S_NO3", "param__NO3"]},
        "TN":         {"unit": "mg/L",  "suffixes": ["param__S_TN",  "param__TN"]},
        "TP":         {"unit": "mg/L",  "suffixes": ["param__S_TP",  "param__TP"]},
        "pH":         {"unit": "—",     "suffixes": ["param__pH"]},
        "Temp":       {"unit": "°C",    "suffixes": ["param__T"]},
        "DO":         {"unit": "mg/L",  "suffixes": ["param__S_O", "param__DO"]},
        "Turbidity":  {"unit": "NTU",   "suffixes": []},   # no SUMO equivalent
        "Oil_Grease": {"unit": "mg/L",  "suffixes": ["param__S_Oil"]},
    },

    # Measurement point label (from col A) → SUMO unit name + role
    # Role: 'input'  → influent to the named unit
    #       'output' → effluent / outlet of the named unit
    #       'tank'   → bulk tank value (reactor internal)
    #       'sludge' → underflow / sludge concentration
    #       'stream' → recycle / flow stream
    "point_map": {
        "Raw Influent":                  {"unit": "Influent",    "role": "tank"},
        "After Screens / Grit Removal":  {"unit": "Screens",     "role": "output"},
        "Primary Clarifier — Inlet":     {"unit": "PrimClar1",   "role": "input"},
        "Primary Clarifier — Effluent":  {"unit": "PrimClar1",   "role": "output"},
        "Primary Sludge (underflow)":    {"unit": "PrimClar1",   "role": "sludge"},
        "Bio Reactor — Inlet":           {"unit": "AerTank1",    "role": "input"},
        "Aeration Tank":                 {"unit": "AerTank1",    "role": "tank"},
        "Anoxic Zone":                   {"unit": "AnoxTank1",   "role": "tank"},
        "Bio Reactor — Outlet":          {"unit": "AerTank1",    "role": "output"},
        "Secondary Clarifier — Inlet":   {"unit": "SecClar1",    "role": "input"},
        "Secondary Clarifier — Outlet":  {"unit": "SecClar1",    "role": "output"},
        "Final Effluent":                {"unit": "Effluent",    "role": "tank"},
        "RAS (Return Activated Sludge)": {"unit": "RAS_Pump",    "role": "stream"},
        "WAS (Waste Activated Sludge)":  {"unit": "WAS_Pump",    "role": "stream"},
        "Reject / Sidestream Water":     {"unit": "Reject",      "role": "stream"},
    },
}
```

---

## Step 3 — Add the Excel parsing helper functions

Insert this block **immediately after** `DATASET_SCHEMA`:

```python
def _open_dataset(xlsx_path: str):
    """Open the dataset workbook and return the data-entry worksheet.

    Raises a clear error if the expected sheet is missing.
    """
    p = Path(xlsx_path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset file not found: {xlsx_path}")
    wb = load_workbook(p, data_only=True)
    sheet_name = DATASET_SCHEMA["sheet_name"]
    if sheet_name not in wb.sheetnames:
        # Fall back to any sheet whose name contains "Data Entry"
        matches = [s for s in wb.sheetnames if "Data Entry" in s]
        if not matches:
            raise ValueError(
                f"No '{sheet_name}' sheet found. Available sheets: {wb.sheetnames}"
            )
        sheet_name = matches[0]
    return wb, wb[sheet_name]


def _parse_dataset_rows(ws) -> dict:
    """Parse the data-entry worksheet into a structured dict.

    Returns:
        {
          "points": {
            "Raw Influent": {"Flow": 28000, "COD": 550, ...},
            "Primary Clarifier — Inlet": {...},
            ...
          },
          "law48": {"BOD5": 60, "COD": 100, ...},
          "section_headers_found": [...],
        }
    """
    cols = DATASET_SCHEMA["columns"]
    param_cols = [(c, name) for c, name in cols.items()
                  if name not in ("label", "Notes")]

    result = {"points": {}, "law48": {}, "section_headers_found": []}

    # Law 48 limits (row 6)
    law_row = DATASET_SCHEMA["law48_row"]
    for c, pname in param_cols:
        v = ws.cell(row=law_row, column=c).value
        if isinstance(v, (int, float)):
            result["law48"][pname] = float(v)

    # Measurement points
    for r in range(DATASET_SCHEMA["data_start_row"], ws.max_row + 1):
        label_val = ws.cell(row=r, column=1).value
        if label_val is None:
            continue
        label = str(label_val).strip()

        # Skip section headers (centered, merged, or start with spaces and all-caps)
        if label.isupper() or label.strip().isupper() or label.startswith("  "):
            result["section_headers_found"].append({"row": r, "label": label})
            continue

        point_data = {"_row": r}
        for c, pname in param_cols:
            v = ws.cell(row=r, column=c).value
            if v is None or v == "":
                continue
            if isinstance(v, (int, float)):
                point_data[pname] = float(v)
            else:
                # String values (e.g. in Notes) are skipped for numeric data
                continue

        # Also capture notes if present
        notes_v = ws.cell(row=r, column=16).value
        if notes_v:
            point_data["Notes"] = str(notes_v)

        if len(point_data) > 1:   # more than just _row
            result["points"][label] = point_data

    return result


def _resolve_sumo_variable(unit: str, param_key: str, all_vars: list) -> str:
    """Find the actual SUMO variable name for a given unit and parameter.

    Tries all candidate suffixes from DATASET_SCHEMA.parameter_map until one
    matches a name in all_vars. Returns None if no match.
    """
    pmap = DATASET_SCHEMA["parameter_map"].get(param_key)
    if not pmap:
        return None
    for suffix in pmap["suffixes"]:
        candidate = f"Sumo__Plant__{unit}__{suffix}"
        if candidate in all_vars:
            return candidate
    # Fuzzy fallback: search for any variable containing both the unit and suffix substring
    for suffix in pmap["suffixes"]:
        short = suffix.replace("param__", "")
        matches = [v for v in all_vars
                   if unit.lower() in v.lower() and short.lower() in v.lower()
                   and "param" in v]
        if matches:
            return matches[0]
    return None
```

---

## Step 4 — Insert all new dataset tools

Find the **last** `@server.tool()` function and insert this block **immediately after** it:

```python
# ═══════════════════════════════════════════════════════════════════════════
# GROUP A — Reading the Dataset
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def read_dataset_excel(xlsx_path: str = "") -> dict:
    """Read the WWTP data-entry Excel file and return a structured summary.

    Parses the '💧 Data Entry' sheet of the SUMO24_WWTP_Dataset_and_Tools.xlsx
    template. Returns every measurement point with its numeric values,
    plus the Law 48/1982 limits row.

    Args:
        xlsx_path: Full path to the Excel file. If blank, looks for
                   SUMO24_WWTP_Dataset_and_Tools.xlsx in the MCP project root.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        return {
            "file":              xlsx_path,
            "sheet":             ws.title,
            "points_found":      len(parsed["points"]),
            "law48_params":      list(parsed["law48"].keys()),
            "measurement_points":list(parsed["points"].keys()),
            "law48_limits":      parsed["law48"],
            "section_headers":   parsed["section_headers_found"],
            "tip": "Call get_measurement_point_data(label=...) for details of any point.",
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def list_dataset_measurement_points(xlsx_path: str = "") -> dict:
    """List every measurement point in the dataset and which SUMO unit it maps to.

    Useful for discovery before applying data to the model.

    Args:
        xlsx_path: Path to the dataset file.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        table = []
        for label, data in parsed["points"].items():
            mapping = DATASET_SCHEMA["point_map"].get(label, {})
            numeric_params = sorted([k for k, v in data.items()
                                     if k not in ("_row", "Notes")
                                     and isinstance(v, (int, float))])
            table.append({
                "label":          label,
                "row":            data.get("_row"),
                "sumo_unit":      mapping.get("unit", "⚠️ unmapped"),
                "role":           mapping.get("role", "—"),
                "params_present": numeric_params,
                "param_count":    len(numeric_params),
            })

        unmapped = [t["label"] for t in table if t["sumo_unit"] == "⚠️ unmapped"]

        return {
            "file":              xlsx_path,
            "total_points":      len(table),
            "points":            table,
            "unmapped_points":   unmapped,
            "tip": (
                f"{len(unmapped)} points have no SUMO unit mapping. "
                "Update DATASET_SCHEMA['point_map'] in server.py if needed."
            ) if unmapped else "All points mapped to SUMO units."
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def get_measurement_point_data(label: str, xlsx_path: str = "") -> dict:
    """Get all measured parameters for a specific measurement point.

    Args:
        label:     Measurement point name exactly as it appears in col A
                   (e.g. "Raw Influent", "Primary Clarifier — Effluent").
        xlsx_path: Path to the dataset file.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        if label not in parsed["points"]:
            close = [p for p in parsed["points"]
                     if label.lower() in p.lower() or p.lower() in label.lower()]
            return {
                "error": f"Point '{label}' not found in dataset.",
                "available_points": list(parsed["points"].keys()),
                "closest_matches":  close,
            }

        data    = parsed["points"][label]
        mapping = DATASET_SCHEMA["point_map"].get(label, {})
        numeric = {k: v for k, v in data.items()
                   if k not in ("_row", "Notes") and isinstance(v, (int, float))}

        # Flag any value exceeding Law 48 limits
        flags = []
        for pname, val in numeric.items():
            limit = parsed["law48"].get(pname)
            if limit is not None and val > limit:
                flags.append({
                    "param": pname, "value": val, "limit": limit,
                    "exceedance_pct": round((val - limit) / limit * 100, 1),
                })

        return {
            "label":            label,
            "sumo_unit":        mapping.get("unit", "unmapped"),
            "role":             mapping.get("role", "—"),
            "measured_values":  numeric,
            "notes":            data.get("Notes", ""),
            "law48_exceedances":flags,
            "row":              data.get("_row"),
        }
    except Exception as e:
        return {"error": str(e), "label": label}


@server.tool()
async def get_parameter_across_points(parameter: str, xlsx_path: str = "") -> dict:
    """Return the value of a single parameter across every measurement point.

    Useful for tracking a pollutant through the plant (e.g. COD at influent,
    primary clarifier effluent, aeration tank, secondary clarifier effluent).

    Args:
        parameter: One of Flow, BOD5, COD, TSS, VSS, NH4_N, NO3_N, TN, TP, pH,
                   Temp, DO, Turbidity, Oil_Grease.
        xlsx_path: Path to the dataset file.
    """
    try:
        if parameter not in DATASET_SCHEMA["parameter_map"]:
            return {
                "error": f"Unknown parameter '{parameter}'.",
                "valid_parameters": list(DATASET_SCHEMA["parameter_map"].keys()),
            }

        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        trace = []
        for label, data in parsed["points"].items():
            if parameter in data:
                trace.append({
                    "point": label,
                    "sumo_unit": DATASET_SCHEMA["point_map"].get(label, {}).get("unit"),
                    "value": data[parameter],
                })

        limit = parsed["law48"].get(parameter)

        # Compute simple removal % if both influent and effluent values exist
        removal = None
        inf_pt  = next((t for t in trace if "Raw Influent" in t["point"]), None)
        eff_pt  = next((t for t in trace if "Final Effluent" in t["point"]), None)
        if inf_pt and eff_pt and inf_pt["value"] > 0:
            removal = round((inf_pt["value"] - eff_pt["value"]) / inf_pt["value"] * 100, 1)

        return {
            "parameter":     parameter,
            "unit":          DATASET_SCHEMA["parameter_map"][parameter]["unit"],
            "law48_limit":   limit,
            "data_points":   len(trace),
            "trace":         trace,
            "overall_removal_pct": removal,
        }
    except Exception as e:
        return {"error": str(e), "parameter": parameter}


@server.tool()
async def get_law48_limits_from_excel(xlsx_path: str = "") -> dict:
    """Return the Law 48/1982 limit row from the Excel template as a dict.

    These are the limits the user has configured in row 6 of the Data Entry
    sheet. Use this to keep the server's CONFIG['law48_limits'] in sync with
    what the user has put in the spreadsheet.

    Args:
        xlsx_path: Path to the dataset file.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        # Optionally sync into CONFIG
        CONFIG["law48_limits_from_dataset"] = parsed["law48"]

        return {
            "file":   xlsx_path,
            "law48_limits": parsed["law48"],
            "param_count": len(parsed["law48"]),
            "note": (
                "Values synced into CONFIG['law48_limits_from_dataset']. "
                "Call check_compliance or generate_report to use these limits."
            )
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP B — Mapping & Validation
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def map_dataset_to_sumo_variables(xlsx_path: str = "") -> dict:
    """Resolve every measurement point + parameter to a concrete SUMO variable name.

    For every numeric cell in the dataset, try to find the matching SUMO variable
    in the currently loaded compiled model. Returns a full mapping plus a list of
    unresolved cells.

    Args:
        xlsx_path: Path to the dataset file.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        resolved, unresolved = [], []

        for label, data in parsed["points"].items():
            mapping = DATASET_SCHEMA["point_map"].get(label)
            if not mapping:
                unresolved.append({"point": label, "reason": "unit not mapped in schema"})
                continue

            unit = mapping["unit"]

            for param_key, value in data.items():
                if param_key in ("_row", "Notes") or not isinstance(value, (int, float)):
                    continue
                var = _resolve_sumo_variable(unit, param_key, all_vars)
                if var:
                    resolved.append({
                        "point":    label,
                        "unit":     unit,
                        "param":    param_key,
                        "value":    value,
                        "variable": var,
                    })
                else:
                    unresolved.append({
                        "point": label, "unit": unit, "param": param_key,
                        "value": value,
                        "reason":"No matching SUMO variable — unit may not exist in compiled model"
                    })

        return {
            "file":       xlsx_path,
            "resolved":   len(resolved),
            "unresolved": len(unresolved),
            "resolved_mappings":   resolved[:50],    # cap for readability
            "unresolved_mappings": unresolved,
            "tip": (
                "Use search_variables to confirm unit names in the compiled model. "
                "Update DATASET_SCHEMA['point_map'] if your SUMO units have "
                "different names."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def validate_dataset(xlsx_path: str = "") -> dict:
    """Run sanity checks on the dataset before applying it to a model.

    Checks:
    - Mass balance: COD(in) > COD(out) across the plant
    - Flow continuity: Q(influent) ≈ Q(effluent) + Q(WAS)
    - Physical ranges: pH 5–9, temp 5–40°C, DO 0–10 mg/L
    - Missing critical parameters: Flow and COD at minimum

    Args:
        xlsx_path: Path to the dataset file.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)
        pts    = parsed["points"]

        issues, warnings, passes = [], [], []

        # 1. Missing critical parameters at influent
        inf = pts.get("Raw Influent", {})
        for must_have in ("Flow", "COD"):
            if must_have not in inf:
                issues.append(f"Raw Influent is missing '{must_have}' — required for modeling.")
            else:
                passes.append(f"Raw Influent {must_have} present: {inf[must_have]}")

        # 2. Physical ranges
        for label, data in pts.items():
            if "pH" in data and not (5.0 <= data["pH"] <= 9.5):
                issues.append(f"{label}: pH {data['pH']} outside physical range 5–9.5")
            if "Temp" in data and not (5.0 <= data["Temp"] <= 45.0):
                warnings.append(f"{label}: Temp {data['Temp']}°C is unusual")
            if "DO" in data and not (0.0 <= data["DO"] <= 15.0):
                warnings.append(f"{label}: DO {data['DO']} mg/L outside 0–15 range")

        # 3. COD trend: should decrease from influent → effluent
        cod_inf = pts.get("Raw Influent", {}).get("COD")
        cod_eff = pts.get("Final Effluent", {}).get("COD")
        if cod_inf and cod_eff:
            if cod_eff >= cod_inf:
                issues.append(
                    f"Effluent COD ({cod_eff}) ≥ Influent COD ({cod_inf}) — "
                    "plant is not removing COD. Check measurements."
                )
            else:
                removal = round((cod_inf - cod_eff) / cod_inf * 100, 1)
                passes.append(f"COD removal = {removal}% ({cod_inf} → {cod_eff} mg/L)")

        # 4. Flow continuity
        q_inf = pts.get("Raw Influent", {}).get("Flow")
        q_eff = pts.get("Final Effluent", {}).get("Flow")
        q_was = pts.get("WAS (Waste Activated Sludge)", {}).get("Flow", 0)
        if q_inf and q_eff:
            expected_eff = q_inf - q_was
            delta_pct = abs(q_eff - expected_eff) / q_inf * 100
            if delta_pct > 10:
                warnings.append(
                    f"Flow continuity off by {delta_pct:.1f}%: "
                    f"Q_inf={q_inf}, Q_eff={q_eff}, Q_WAS={q_was}"
                )
            else:
                passes.append(
                    f"Flow continuity OK: Q_inf {q_inf} ≈ Q_eff {q_eff} + Q_WAS {q_was}"
                )

        # 5. Law 48 exceedances at final effluent
        law48_exceedances = []
        for pname, val in pts.get("Final Effluent", {}).items():
            if pname in ("_row", "Notes") or not isinstance(val, (int, float)):
                continue
            limit = parsed["law48"].get(pname)
            if limit is not None and val > limit:
                law48_exceedances.append({
                    "param": pname, "value": val, "limit": limit
                })

        status = "PASS" if not issues else ("FAIL" if len(issues) > 2 else "WARNINGS")

        return {
            "file":              xlsx_path,
            "overall_status":    status,
            "issue_count":       len(issues),
            "warning_count":     len(warnings),
            "passes":            len(passes),
            "issues":            issues,
            "warnings":          warnings,
            "passes_summary":    passes,
            "law48_exceedances": law48_exceedances,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def check_dataset_against_law48(xlsx_path: str = "") -> dict:
    """Compare every point's measured values against the Law 48 limit row.

    Flags each exceedance at each measurement point (not just final effluent).

    Args:
        xlsx_path: Path to the dataset file.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        report = []
        for label, data in parsed["points"].items():
            exceedances = []
            for pname, val in data.items():
                if pname in ("_row", "Notes") or not isinstance(val, (int, float)):
                    continue
                limit = parsed["law48"].get(pname)
                if limit is not None and val > limit:
                    exceedances.append({
                        "param": pname,
                        "value": val,
                        "limit": limit,
                        "exceedance_pct": round((val - limit) / limit * 100, 1),
                    })
            if exceedances:
                report.append({
                    "point": label,
                    "exceedance_count": len(exceedances),
                    "exceedances": exceedances,
                })

        effluent_compliant = not any(r["point"] == "Final Effluent" for r in report)

        return {
            "file":               xlsx_path,
            "law48_limits":       parsed["law48"],
            "points_with_issues": len(report),
            "effluent_compliant": effluent_compliant,
            "detailed_report":    report,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP C — Applying Data to the SUMO Model
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def apply_influent_from_dataset(xlsx_path: str = "",
                                      row_label: str = "Raw Influent") -> dict:
    """Read the influent row from the Excel dataset and apply it to the model.

    Writes Flow, COD, BOD5, TSS, VSS, TKN (from NH4_N+), NH4, TN, TP, pH, Temp,
    and DO to the corresponding Influent unit parameters in SUMO.

    Args:
        xlsx_path: Path to the dataset file.
        row_label: Which row to read as influent. Default is "Raw Influent".
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        if row_label not in parsed["points"]:
            return {
                "error": f"Row '{row_label}' not found in dataset.",
                "available": list(parsed["points"].keys()),
            }

        data = parsed["points"][row_label]
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        unit = DATASET_SCHEMA["point_map"][row_label]["unit"]

        applied, failed = [], []
        for pkey, value in data.items():
            if pkey in ("_row", "Notes") or not isinstance(value, (int, float)):
                continue
            var = _resolve_sumo_variable(unit, pkey, all_vars)
            if var:
                try:
                    ds.sumo.set(var, float(value))
                    applied.append({"param": pkey, "value": value, "variable": var})
                except Exception as e:
                    failed.append({"param": pkey, "error": str(e)})
            else:
                failed.append({"param": pkey,
                                "reason": f"No SUMO variable found for {unit}/{pkey}"})

        return {
            "source_row":  row_label,
            "sumo_unit":   unit,
            "applied":     len(applied),
            "failed":      len(failed),
            "results":     applied,
            "failed_list": failed,
            "tip": (
                "If parameters failed, call search_variables with the parameter suffix "
                "(e.g. 'S_COD') to find the actual variable name, then update "
                "DATASET_SCHEMA['parameter_map'] in server.py."
            )
        }
    except Exception as e:
        return {"error": str(e), "row_label": row_label}


@server.tool()
async def apply_point_to_unit(point_label: str, unit_override: str = "",
                              xlsx_path: str = "") -> dict:
    """Apply the measurements from a single point to a SUMO unit.

    By default, the unit is looked up in DATASET_SCHEMA['point_map'].
    Pass unit_override to target a different unit (useful when your SUMO
    model uses different unit names).

    Args:
        point_label:   Measurement point label (e.g. "Primary Clarifier — Effluent").
        unit_override: Optional SUMO unit name to write to instead of the default.
        xlsx_path:     Path to the dataset file.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        if point_label not in parsed["points"]:
            return {"error": f"Point '{point_label}' not found."}

        data    = parsed["points"][point_label]
        mapping = DATASET_SCHEMA["point_map"].get(point_label, {})
        unit    = unit_override or mapping.get("unit")
        if not unit:
            return {"error": f"No SUMO unit mapping for '{point_label}'. "
                              "Pass unit_override."}

        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        applied, failed = [], []
        for pkey, value in data.items():
            if pkey in ("_row", "Notes") or not isinstance(value, (int, float)):
                continue
            var = _resolve_sumo_variable(unit, pkey, all_vars)
            if var:
                try:
                    ds.sumo.set(var, float(value))
                    applied.append({"param": pkey, "value": value, "variable": var})
                except Exception as e:
                    failed.append({"param": pkey, "error": str(e)})
            else:
                failed.append({"param": pkey, "reason": "variable not found"})

        return {
            "point":      point_label,
            "sumo_unit":  unit,
            "applied":    len(applied),
            "failed":     len(failed),
            "results":    applied,
            "failed_list":failed,
        }
    except Exception as e:
        return {"error": str(e), "point_label": point_label}


@server.tool()
async def apply_dataset_to_model(xlsx_path: str = "",
                                 only_influent: bool = False,
                                 dry_run: bool = False) -> dict:
    """Apply ALL numeric values from the dataset to the SUMO model in one call.

    This is the main 'import dataset into SUMO' workflow. Iterates through every
    measurement point, looks up its SUMO unit, resolves each parameter to a
    variable name, and writes the measured value.

    Args:
        xlsx_path:     Path to the dataset file.
        only_influent: If True, only applies the Raw Influent row (safer default
                       for calibration work).
        dry_run:       If True, resolves everything but does not actually write
                       to the model. Returns the proposed changes for review.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        applied, failed = [], []

        for label, data in parsed["points"].items():
            if only_influent and label != "Raw Influent":
                continue

            mapping = DATASET_SCHEMA["point_map"].get(label)
            if not mapping:
                continue
            unit = mapping["unit"]

            for pkey, value in data.items():
                if pkey in ("_row", "Notes") or not isinstance(value, (int, float)):
                    continue
                var = _resolve_sumo_variable(unit, pkey, all_vars)
                if not var:
                    failed.append({
                        "point": label, "param": pkey, "value": value,
                        "reason": f"no SUMO variable found for {unit}"
                    })
                    continue

                if dry_run:
                    applied.append({
                        "point": label, "param": pkey, "value": value,
                        "variable": var, "status": "would_apply"
                    })
                else:
                    try:
                        ds.sumo.set(var, float(value))
                        applied.append({
                            "point": label, "param": pkey, "value": value,
                            "variable": var, "status": "applied"
                        })
                    except Exception as e:
                        failed.append({
                            "point": label, "param": pkey, "error": str(e)
                        })

        return {
            "file":           xlsx_path,
            "dry_run":        dry_run,
            "only_influent":  only_influent,
            "applied_count":  len(applied),
            "failed_count":   len(failed),
            "applied":        applied[:100],    # cap output
            "failed":         failed,
            "next_step": (
                "Run run_steady_state() to simulate with these values, then "
                "compare_dataset_vs_simulation to check calibration fit."
            ) if not dry_run else "dry_run mode — nothing was actually written. "
                                   "Re-run with dry_run=False to apply."
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP D — Calibration & Comparison Workflow
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def compare_dataset_vs_simulation(job_id: str,
                                        xlsx_path: str = "",
                                        points_to_compare: list = None) -> dict:
    """Compare measured values from the Excel dataset against a simulation job.

    For each measurement point, reads the measured value from the Excel file
    and the simulated value from the SUMO model state (or job effluent dict),
    and reports percentage delta.

    Args:
        job_id:            Completed job ID (from run_steady_state or run_dynamic).
        xlsx_path:         Path to the dataset file.
        points_to_compare: Optional list of point labels to restrict to.
                            Default compares all points.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)

        # Find the simulation results
        job = JOBS.get(job_id)
        if not job:
            return {"error": f"Job '{job_id}' not found."}

        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        comparisons = []
        fit_errors  = []

        for label, measured in parsed["points"].items():
            if points_to_compare and label not in points_to_compare:
                continue
            mapping = DATASET_SCHEMA["point_map"].get(label)
            if not mapping:
                continue
            unit = mapping["unit"]

            for pkey, m_val in measured.items():
                if pkey in ("_row", "Notes") or not isinstance(m_val, (int, float)):
                    continue
                var = _resolve_sumo_variable(unit, pkey, all_vars)
                if not var:
                    continue
                try:
                    s_val = float(ds.sumo.get(var))
                except Exception:
                    continue

                delta     = s_val - m_val
                delta_pct = round(delta / m_val * 100, 1) if m_val != 0 else None
                comparisons.append({
                    "point":     label,
                    "param":     pkey,
                    "measured":  m_val,
                    "simulated": round(s_val, 3),
                    "delta":     round(delta, 3),
                    "delta_pct": delta_pct,
                })
                if delta_pct is not None:
                    fit_errors.append(abs(delta_pct))

        # Overall calibration fit metrics
        mape    = round(sum(fit_errors) / len(fit_errors), 2) if fit_errors else None
        bad_fit = [c for c in comparisons
                   if c["delta_pct"] is not None and abs(c["delta_pct"]) > 20]

        return {
            "file":              xlsx_path,
            "job_id":            job_id,
            "comparisons":       len(comparisons),
            "mean_abs_pct_error":mape,
            "poor_fit_count":    len(bad_fit),
            "poor_fit_points":   bad_fit,
            "all_comparisons":   comparisons[:100],
            "interpretation": (
                "MAPE < 10% = excellent fit, 10–20% = acceptable, "
                "> 20% = poor fit (calibration needed)."
            ) if mape is not None else "Not enough comparable points for MAPE."
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def compute_removal_efficiencies_from_dataset(xlsx_path: str = "") -> dict:
    """Compute removal efficiencies across the plant from Excel data alone.

    Calculates % removal for each parameter between each pair of adjacent
    measurement points plus the overall influent → effluent removal.

    Args:
        xlsx_path: Path to the dataset file.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        wb, ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(ws)
        pts    = parsed["points"]

        # Sequence of points to trace for efficiency
        sequence = [
            "Raw Influent",
            "Primary Clarifier — Effluent",
            "Bio Reactor — Outlet",
            "Secondary Clarifier — Outlet",
            "Final Effluent",
        ]
        params_to_track = ["BOD5", "COD", "TSS", "NH4_N", "TN", "TP"]

        stepwise = []
        for i in range(len(sequence) - 1):
            a, b = sequence[i], sequence[i + 1]
            if a not in pts or b not in pts:
                continue
            stage = {"from": a, "to": b, "removals": {}}
            for p in params_to_track:
                if p in pts[a] and p in pts[b] and pts[a][p] > 0:
                    rem = round((pts[a][p] - pts[b][p]) / pts[a][p] * 100, 1)
                    stage["removals"][p] = rem
            if stage["removals"]:
                stepwise.append(stage)

        # Overall
        overall = {}
        inf = pts.get("Raw Influent", {})
        eff = pts.get("Final Effluent", {})
        for p in params_to_track:
            if p in inf and p in eff and inf[p] > 0:
                overall[p] = {
                    "influent": inf[p],
                    "effluent": eff[p],
                    "removal_pct": round((inf[p] - eff[p]) / inf[p] * 100, 1),
                    "law48_limit": parsed["law48"].get(p),
                    "compliant":   (eff[p] <= parsed["law48"][p])
                                    if p in parsed["law48"] else None,
                }

        return {
            "file":              xlsx_path,
            "stepwise_removals": stepwise,
            "overall_removals":  overall,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP E — Exporting Simulation Results Back to the Template
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def export_simulation_to_dataset(xlsx_path: str = "",
                                       output_path: str = "") -> dict:
    """Create a new Excel file (copy of the template) with simulation values
    filled in for every measurement point.

    For each cell in the Data Entry sheet that has a mapped SUMO variable,
    reads the current value from the model and writes it to the new workbook.
    The original measurement file is not modified.

    Args:
        xlsx_path:   Source template path. Defaults to project template.
        output_path: Destination file path. Defaults to a timestamped copy
                     in the outputs directory.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        src = Path(xlsx_path)
        if not src.exists():
            return {"error": f"Template not found: {xlsx_path}"}

        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(Path(CONFIG["output_dir"]) /
                               f"simulation_results_{ts}.xlsx")

        # Copy template and open for editing
        shutil.copy2(src, output_path)
        wb = load_workbook(output_path)
        ws = wb[DATASET_SCHEMA["sheet_name"]]

        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        param_cols = {v: k for k, v in DATASET_SCHEMA["columns"].items()
                      if v not in ("label", "Notes")}

        written, skipped = [], []

        for r in range(DATASET_SCHEMA["data_start_row"], ws.max_row + 1):
            label_val = ws.cell(row=r, column=1).value
            if label_val is None:
                continue
            label = str(label_val).strip()
            if label.isupper() or label.startswith("  "):
                continue
            mapping = DATASET_SCHEMA["point_map"].get(label)
            if not mapping:
                continue
            unit = mapping["unit"]

            for pkey, col_idx in param_cols.items():
                var = _resolve_sumo_variable(unit, pkey, all_vars)
                if not var:
                    continue
                try:
                    sim_val = float(ds.sumo.get(var))
                    # Write with 2 dp formatting
                    ws.cell(row=r, column=col_idx,
                             value=round(sim_val, 3))
                    # Highlight the cell to indicate it was filled by simulation
                    ws.cell(row=r, column=col_idx).fill = PatternFill(
                        "solid", fgColor="FFF2CC"
                    )
                    written.append({
                        "point": label, "param": pkey,
                        "variable": var, "value": round(sim_val, 3),
                    })
                except Exception as e:
                    skipped.append({"point": label, "param": pkey, "error": str(e)})

        # Add a note to the Sampling Date cell
        ws.cell(row=2, column=2,
                 value=f"Simulation export {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        ws.cell(row=2, column=2).font = Font(bold=True, color="0066CC")

        wb.save(output_path)

        return {
            "output_file":   output_path,
            "cells_written": len(written),
            "cells_skipped": len(skipped),
            "preview":       written[:20],
            "note": (
                "Simulation values written in cream-coloured cells. "
                "The source file was not modified."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def export_comparison_report(job_id: str,
                                   xlsx_path: str = "",
                                   output_path: str = "") -> dict:
    """Create an Excel comparison report with measured / simulated / delta columns.

    Much more useful than export_simulation_to_dataset for calibration work.
    Adds a new 'Calibration Comparison' sheet to a copy of the template.

    Args:
        job_id:      Completed simulation job ID.
        xlsx_path:   Source template.
        output_path: Destination file path.
    """
    try:
        if not xlsx_path:
            xlsx_path = str(Path(CONFIG.get("project_dir", ".")) /
                             "SUMO24_WWTP_Dataset_and_Tools.xlsx")

        src = Path(xlsx_path)
        if not src.exists():
            return {"error": f"Template not found: {xlsx_path}"}

        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(Path(CONFIG["output_dir"]) /
                               f"calibration_comparison_{ts}.xlsx")

        shutil.copy2(src, output_path)
        wb = load_workbook(output_path)

        # Create / overwrite a Comparison sheet
        if "Calibration Comparison" in wb.sheetnames:
            del wb["Calibration Comparison"]
        cmp_ws = wb.create_sheet("Calibration Comparison")

        # Parse dataset and fetch simulation values
        _, data_ws = _open_dataset(xlsx_path)
        parsed = _parse_dataset_rows(data_ws)

        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()

        # Headers
        headers = ["Measurement Point", "SUMO Unit", "Parameter",
                   "Measured", "Simulated", "Δ", "Δ %", "Fit Quality"]
        for i, h in enumerate(headers, start=1):
            cell = cmp_ws.cell(row=1, column=i, value=h)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F3864")

        r = 2
        total_abs_err, comparable = 0.0, 0
        for label, data in parsed["points"].items():
            mapping = DATASET_SCHEMA["point_map"].get(label)
            if not mapping:
                continue
            unit = mapping["unit"]
            for pkey, m_val in data.items():
                if pkey in ("_row", "Notes") or not isinstance(m_val, (int, float)):
                    continue
                var = _resolve_sumo_variable(unit, pkey, all_vars)
                if not var:
                    continue
                try:
                    s_val = float(ds.sumo.get(var))
                except Exception:
                    continue

                delta     = s_val - m_val
                delta_pct = (delta / m_val * 100) if m_val != 0 else None

                if delta_pct is not None:
                    total_abs_err += abs(delta_pct)
                    comparable += 1

                if delta_pct is None:
                    quality = "—"
                    color   = "DDDDDD"
                elif abs(delta_pct) < 10:
                    quality = "✅ excellent"
                    color   = "C6EFCE"
                elif abs(delta_pct) < 20:
                    quality = "⚠ acceptable"
                    color   = "FFF2CC"
                else:
                    quality = "❌ poor"
                    color   = "FFC7CE"

                cmp_ws.cell(row=r, column=1, value=label)
                cmp_ws.cell(row=r, column=2, value=unit)
                cmp_ws.cell(row=r, column=3, value=pkey)
                cmp_ws.cell(row=r, column=4, value=round(m_val, 3))
                cmp_ws.cell(row=r, column=5, value=round(s_val, 3))
                cmp_ws.cell(row=r, column=6, value=round(delta, 3))
                cmp_ws.cell(row=r, column=7,
                             value=round(delta_pct, 1) if delta_pct is not None else None)
                q_cell = cmp_ws.cell(row=r, column=8, value=quality)
                q_cell.fill = PatternFill("solid", fgColor=color)
                r += 1

        # MAPE summary row
        mape = round(total_abs_err / comparable, 2) if comparable else None
        cmp_ws.cell(row=r + 1, column=1,
                     value=f"MAPE (Mean Absolute % Error): {mape}%" if mape
                           else "No comparable points.")
        cmp_ws.cell(row=r + 1, column=1).font = Font(bold=True)

        # Column widths
        widths = [32, 16, 14, 14, 14, 10, 10, 16]
        for i, w in enumerate(widths, start=1):
            cmp_ws.column_dimensions[cmp_ws.cell(row=1, column=i).column_letter].width = w

        wb.save(output_path)

        return {
            "output_file":     output_path,
            "rows_compared":   comparable,
            "mean_abs_pct_error": mape,
            "tip": (
                "Open the 'Calibration Comparison' sheet in the output file. "
                "Green = excellent fit (< 10%), yellow = acceptable, red = poor."
            )
        }
    except Exception as e:
        return {"error": str(e)}
```

---

## Step 5 — Save and restart

1. Save `server.py`.
2. Fully quit Claude Desktop (right-click tray icon → **Quit**).
3. Relaunch Claude Desktop.
4. Confirm the new tools are visible: ask **"List all SUMO24 tools related to dataset"**.

---

## Step 6 — Verification prompts

Test each group with these prompts in Claude Desktop:

| Prompt | Expected tool |
|---|---|
| `Read my WWTP dataset from F:/UNI/SUMO/MCP/SUMO24_WWTP_Dataset_and_Tools.xlsx` | `read_dataset_excel` |
| `List all measurement points in the dataset and which SUMO unit they map to` | `list_dataset_measurement_points` |
| `Show me all parameters for the Raw Influent row` | `get_measurement_point_data` |
| `Trace COD through every measurement point in the dataset` | `get_parameter_across_points` |
| `What are the Law 48 limits set in my Excel template?` | `get_law48_limits_from_excel` |
| `Map every dataset cell to its SUMO variable name` | `map_dataset_to_sumo_variables` |
| `Validate my dataset for mass-balance and range errors` | `validate_dataset` |
| `Check every point against Law 48 limits` | `check_dataset_against_law48` |
| `Apply just the influent row from my dataset to the SUMO model` | `apply_influent_from_dataset` |
| `Apply the Aeration Tank row to AerTank2 (override the default unit)` | `apply_point_to_unit` |
| `Dry-run applying the whole dataset — show me what would change` | `apply_dataset_to_model` (dry_run=True) |
| `Compare my dataset to simulation job ss_001 and tell me the fit quality` | `compare_dataset_vs_simulation` |
| `Compute removal efficiencies across the plant from the Excel data` | `compute_removal_efficiencies_from_dataset` |
| `Export current simulation values into a copy of my Excel template` | `export_simulation_to_dataset` |
| `Create an Excel calibration report comparing measured vs simulated for job ss_001` | `export_comparison_report` |

---

## Typical workflows

### Workflow 1 — Use Excel measurements as influent for a simulation
```
1. Read the dataset:        read_dataset_excel
2. Validate it:             validate_dataset
3. Apply influent only:     apply_influent_from_dataset
4. Run steady state:        run_steady_state
5. Check compliance:        check_compliance
```

### Workflow 2 — Full calibration against measured data
```
1. Read dataset:            read_dataset_excel
2. Apply influent:          apply_influent_from_dataset
3. Run simulation:          run_steady_state
4. Compare measured vs sim: compare_dataset_vs_simulation(job_id=...)
5. If MAPE > 20% — adjust ASM kinetics:
   apply_temperature_correction(temp_C=<measured>)
   set_asm1_kinetics(Y_H=0.80, ...)   (research-based adjustment)
6. Re-run and re-compare until MAPE < 10%
7. Export calibration report: export_comparison_report
```

### Workflow 3 — Using Excel limits as compliance target
```
1. Read Law 48 from Excel:  get_law48_limits_from_excel
   (this syncs them into CONFIG['law48_limits_from_dataset'])
2. Run simulation:          run_steady_state
3. Check compliance:        check_compliance
4. If failures — check_dataset_against_law48 tells you which stages
   already exceed limits before treatment even helps
```

---

## Notes for Cowork

### Excel template assumptions
The tools assume the exact layout of `SUMO24_WWTP_Dataset_and_Tools.xlsx`:
- `'💧 Data Entry'` sheet exists (emoji included in the name)
- Row 4 has parameter headers, row 5 has SUMO variable hints, row 6 has Law 48 limits
- Data rows start at row 7, measurement points in column A
- Parameter order matches `DATASET_SCHEMA['columns']`

If your template layout differs, edit `DATASET_SCHEMA` constants at the top of
`server.py` — the tool code does not need to change.

### SUMO unit name mapping
The default unit names in `DATASET_SCHEMA['point_map']` are `Influent`, `PrimClar1`,
`AerTank1`, `AnoxTank1`, `SecClar1`, `Effluent`, `RAS_Pump`, `WAS_Pump`, `Reject`.
If your SUMO model uses different names (e.g. `Reactor_1` instead of `AerTank1`),
update this dict once and all tools pick up the change.

Alternatively, for ad-hoc runs, use `apply_point_to_unit` with `unit_override` to
target a different unit without editing the schema.

### Parameter resolution
`_resolve_sumo_variable` tries several suffix candidates (e.g. `param__S_COD`
or `param__COD`) to maximize compatibility with different SUMO kinetic models.
If a resolution fails, the tool reports `"variable not found"` in its
`failed_list` — at that point use `search_variables(keyword='COD')` to find
the actual name in your compiled model and add it to the `suffixes` list in
`DATASET_SCHEMA['parameter_map']`.

### Performance
The `apply_dataset_to_model` tool caps its output at 100 rows in the `applied`
list to avoid flooding the chat. All values are actually applied — only the
display is truncated. For full audit trails, pass `dry_run=True` first and
then run again with `dry_run=False`.
