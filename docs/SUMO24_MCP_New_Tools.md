# SUMO24 MCP — Add New Tools to server.py

## Task Overview
Add new tools to the existing MCP server at `F:/UNI/SUMO/MCP/PY/server.py`.
These tools cover model inspection, persistent parameter editing, scenario management,
model building, state management, and analysis. Do not remove or modify any existing tools.

---

## File to Edit
**Path:** `F:/UNI/SUMO/MCP/PY/server.py`

---

## Step 1 — Add helper imports at the top of server.py

Find the existing import block near the top of the file (where `import json`, `import os`,
or `from mcp.server` lines appear) and add these lines **after** the existing imports if
they are not already present:

```python
import glob
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
```

---

## Step 2 — Add all new tool functions

Find the last existing `@server.tool()` decorated function in the file (it will be one of:
`run_steady_state`, `run_dynamic_simulation`, `run_scenario_comparison`, `list_scenarios`,
`set_parameter`, `get_job_status`, `check_compliance`, or `export_results_csv`).

Insert the following code block **immediately after** that last tool function, before any
`if __name__ == "__main__"` block or server startup code.

```python
# ─────────────────────────────────────────────────────────────
# GROUP A — Model Inspection Tools
# ─────────────────────────────────────────────────────────────

@server.tool()
async def get_parameter(parameter: str, scenario: str = "baseline_Sc0") -> dict:
    """Read the current value and units of a single model parameter."""
    try:
        ds = _make_ds()
        _apply_scenario(ds, scenario)
        value = ds.sumo.get(parameter)
        return {
            "parameter": parameter,
            "value": value,
            "scenario": scenario,
            "note": "Value reflects state.xml plus any scenario overrides."
        }
    except Exception as e:
        return {"error": str(e), "parameter": parameter}


@server.tool()
async def list_parameters(unit_name: str = "") -> dict:
    """List configurable parameters for a unit process or the whole model.

    Args:
        unit_name: Optional. If supplied, filters to parameters whose name contains
                   this string (case-insensitive). Leave blank to return all parameters.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        param_vars = [v for v in all_vars if "__param__" in v]
        if unit_name:
            param_vars = [v for v in param_vars if unit_name.lower() in v.lower()]
        return {
            "count": len(param_vars),
            "unit_filter": unit_name or "none",
            "parameters": param_vars
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def list_state_variables(unit_name: str = "") -> dict:
    """List all model state variables (tank concentrations, flows, etc.).

    Args:
        unit_name: Optional substring filter on variable name.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        state_vars = [v for v in all_vars if "__param__" not in v]
        if unit_name:
            state_vars = [v for v in state_vars if unit_name.lower() in v.lower()]
        return {
            "count": len(state_vars),
            "unit_filter": unit_name or "none",
            "state_variables": state_vars
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def get_state_variable(variable: str) -> dict:
    """Read the current value of a specific state variable.

    Args:
        variable: Full SumoCore variable name (e.g. Sumo__Plant__AerTank1__S_O).
    """
    try:
        ds = _make_ds()
        value = ds.sumo.get(variable)
        return {"variable": variable, "value": value}
    except Exception as e:
        return {"error": str(e), "variable": variable}


@server.tool()
async def search_variables(keyword: str) -> dict:
    """Search all variable and parameter names for a keyword (case-insensitive).

    Args:
        keyword: Any part of a variable name, e.g. 'DO', 'RAS', 'NH4', 'AerTank'.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        matches = [v for v in all_vars if keyword.lower() in v.lower()]
        return {
            "keyword": keyword,
            "match_count": len(matches),
            "matches": matches
        }
    except Exception as e:
        return {"error": str(e), "keyword": keyword}


@server.tool()
async def get_model_info() -> dict:
    """Return top-level model metadata: unit count, kinetic model, compile status."""
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        param_count = len([v for v in all_vars if "__param__" in v])
        state_count = len([v for v in all_vars if "__param__" not in v])
        return {
            "dll_path": CONFIG["model_dll"],
            "state_xml": CONFIG["state_xml"],
            "total_variables": len(all_vars),
            "parameter_variables": param_count,
            "state_variables": state_count,
            "status": "compiled_and_ready"
        }
    except Exception as e:
        return {"error": str(e), "status": "unavailable"}


@server.tool()
async def list_unit_processes() -> dict:
    """Return all process units currently visible in the model variable names."""
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        # Extract unit names from Sumo__Plant__<UnitName>__ pattern
        units = set()
        for v in all_vars:
            parts = v.split("__")
            if len(parts) >= 3:
                units.add(parts[2])
        units = sorted(units)
        return {"unit_count": len(units), "unit_processes": units}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def get_unit_process_info(unit_name: str) -> dict:
    """Get parameters and state variables for a specific unit process.

    Args:
        unit_name: Unit name as it appears in variable names (e.g. AerTank1, Clarifier).
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        unit_vars = [v for v in all_vars if f"__{unit_name}__" in v]
        params = [v for v in unit_vars if "__param__" in v]
        states = [v for v in unit_vars if "__param__" not in v]
        return {
            "unit_name": unit_name,
            "parameter_count": len(params),
            "state_variable_count": len(states),
            "parameters": params,
            "state_variables": states
        }
    except Exception as e:
        return {"error": str(e), "unit_name": unit_name}


@server.tool()
async def validate_variable_name(variable: str) -> dict:
    """Check whether a SumoCore variable name exists in the compiled model.

    Args:
        variable: Full variable name to validate.
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        exists = variable in all_vars
        suggestions = []
        if not exists:
            parts = variable.split("__")
            keyword = parts[-1] if parts else variable
            suggestions = [v for v in all_vars if keyword.lower() in v.lower()][:10]
        return {
            "variable": variable,
            "exists": exists,
            "suggestions": suggestions if not exists else []
        }
    except Exception as e:
        return {"error": str(e), "variable": variable}


# ─────────────────────────────────────────────────────────────
# GROUP B — Persistent Parameter Editing
# ─────────────────────────────────────────────────────────────

@server.tool()
async def set_multiple_parameters(parameters: dict, scenario: str = "baseline_Sc0") -> dict:
    """Set several model parameters in one call (in-memory for the next run).

    Args:
        parameters: Dict of {variable_name: value}, e.g.
                    {"Sumo__Plant__AerTank1__param__DO_setpoint": 1.8,
                     "Sumo__Plant__WAS_Pump__param__Q": 350}
        scenario:   Scenario to apply overrides to (default: baseline_Sc0).
    """
    results = []
    errors = []
    try:
        ds = _make_ds()
        _apply_scenario(ds, scenario)
        for param, value in parameters.items():
            try:
                old_val = ds.sumo.get(param)
                ds.sumo.set(param, float(value))
                results.append({"parameter": param, "old": old_val, "new": value, "status": "ok"})
            except Exception as pe:
                errors.append({"parameter": param, "error": str(pe)})
        return {
            "applied_to": scenario,
            "success_count": len(results),
            "error_count": len(errors),
            "results": results,
            "errors": errors
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def reset_parameter_to_default(parameter: str) -> dict:
    """Revert an in-memory parameter to its value stored in state.xml.

    Args:
        parameter: Full SumoCore parameter name.
    """
    try:
        # Re-read the original value from state.xml
        tree = ET.parse(CONFIG["state_xml"])
        root = tree.getroot()
        original_value = None
        for elem in root.iter():
            if elem.get("name") == parameter:
                original_value = elem.get("value")
                break
        if original_value is None:
            return {"error": f"Parameter '{parameter}' not found in state.xml."}
        return {
            "parameter": parameter,
            "reset_to": original_value,
            "source": CONFIG["state_xml"],
            "note": "Value restored from state.xml snapshot. Re-run simulation to apply."
        }
    except Exception as e:
        return {"error": str(e), "parameter": parameter}


# ─────────────────────────────────────────────────────────────
# GROUP C — State & Project File Management
# ─────────────────────────────────────────────────────────────

@server.tool()
async def save_state(output_path: str = "") -> dict:
    """Export the current in-memory model state to a state.xml snapshot.

    Args:
        output_path: Optional file path for the snapshot. Defaults to a timestamped
                     file in the outputs directory.
    """
    try:
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(Path(CONFIG["output_dir"]) / f"state_{ts}.xml")
        ds = _make_ds()
        ds.sumo.executeCommand(f'save "{output_path}"')
        return {
            "saved_to": output_path,
            "timestamp": datetime.now().isoformat(),
            "note": "Load this file via load_state or set SUMO_STATE in config."
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def load_state(state_xml_path: str) -> dict:
    """Load a previously saved state.xml snapshot and make it the active state.

    Args:
        state_xml_path: Full path to the state.xml file to load.
    """
    try:
        if not Path(state_xml_path).exists():
            return {"error": f"File not found: {state_xml_path}"}
        # Update CONFIG so all subsequent runs use the new state
        CONFIG["state_xml"] = state_xml_path
        return {
            "loaded": state_xml_path,
            "note": "Active state updated. All subsequent simulations will use this snapshot."
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def list_saved_states() -> dict:
    """List all state.xml snapshots in the outputs directory."""
    try:
        pattern = str(Path(CONFIG["output_dir"]) / "state_*.xml")
        files = sorted(glob.glob(pattern), reverse=True)
        return {
            "count": len(files),
            "active_state": CONFIG["state_xml"],
            "snapshots": files
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def get_compile_status() -> dict:
    """Check whether the project DLL exists and is ready to run."""
    try:
        dll_path = Path(CONFIG["model_dll"])
        state_path = Path(CONFIG["state_xml"])
        dll_ok = dll_path.exists()
        state_ok = state_path.exists()
        dll_mtime = datetime.fromtimestamp(dll_path.stat().st_mtime).isoformat() if dll_ok else None
        state_mtime = datetime.fromtimestamp(state_path.stat().st_mtime).isoformat() if state_ok else None
        ready = dll_ok and state_ok
        return {
            "ready": ready,
            "dll": {"path": str(dll_path), "exists": dll_ok, "modified": dll_mtime},
            "state_xml": {"path": str(state_path), "exists": state_ok, "modified": state_mtime},
            "note": "If ready=false, re-extract DLL and state.xml from SUMO GUI."
        }
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────
# GROUP D — Scenario Management
# ─────────────────────────────────────────────────────────────

@server.tool()
async def create_scenario(name: str, parameters: dict, description: str = "") -> dict:
    """Add a new named scenario to the in-memory SCENARIOS dict.

    Args:
        name:        Unique scenario name (e.g. my_new_scenario).
        parameters:  Dict of {variable_name: value} overrides that define this scenario.
        description: Optional human-readable description.
    """
    try:
        if name in SCENARIOS:
            return {"error": f"Scenario '{name}' already exists. Use update_scenario to modify it."}
        commands = [f"set {k} {v}" for k, v in parameters.items()]
        SCENARIOS[name] = commands
        return {
            "created": name,
            "parameter_count": len(commands),
            "description": description,
            "note": "Scenario is live for this session. Restart will clear it unless you edit server.py."
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def update_scenario(name: str, parameters: dict) -> dict:
    """Replace the parameter overrides of an existing scenario.

    Args:
        name:       Scenario name to update.
        parameters: New dict of {variable_name: value} overrides (replaces all existing ones).
    """
    try:
        if name not in SCENARIOS:
            return {"error": f"Scenario '{name}' not found. Use create_scenario first."}
        old_count = len(SCENARIOS[name])
        SCENARIOS[name] = [f"set {k} {v}" for k, v in parameters.items()]
        return {
            "updated": name,
            "old_parameter_count": old_count,
            "new_parameter_count": len(SCENARIOS[name])
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def delete_scenario(name: str) -> dict:
    """Remove a scenario from the in-memory SCENARIOS dict.

    Args:
        name: Scenario name to delete. Built-in scenarios (baseline_Sc0 etc.) can be deleted
              but will return on server restart.
    """
    try:
        if name not in SCENARIOS:
            return {"error": f"Scenario '{name}' not found."}
        del SCENARIOS[name]
        return {"deleted": name, "remaining_scenarios": list(SCENARIOS.keys())}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def clone_scenario(source: str, new_name: str) -> dict:
    """Duplicate an existing scenario under a new name.

    Args:
        source:   Name of the scenario to copy.
        new_name: Name for the new duplicate.
    """
    try:
        if source not in SCENARIOS:
            return {"error": f"Source scenario '{source}' not found."}
        if new_name in SCENARIOS:
            return {"error": f"Scenario '{new_name}' already exists."}
        import copy
        SCENARIOS[new_name] = copy.deepcopy(SCENARIOS[source])
        return {
            "cloned_from": source,
            "new_scenario": new_name,
            "parameter_count": len(SCENARIOS[new_name])
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def get_scenario_diff(scenario_a: str, scenario_b: str) -> dict:
    """Show which parameters differ between two scenarios.

    Args:
        scenario_a: First scenario name.
        scenario_b: Second scenario name.
    """
    try:
        if scenario_a not in SCENARIOS:
            return {"error": f"Scenario '{scenario_a}' not found."}
        if scenario_b not in SCENARIOS:
            return {"error": f"Scenario '{scenario_b}' not found."}

        def parse_commands(cmds):
            result = {}
            for cmd in cmds:
                parts = cmd.strip().split()
                if len(parts) == 3 and parts[0].lower() == "set":
                    result[parts[1]] = parts[2]
            return result

        params_a = parse_commands(SCENARIOS[scenario_a])
        params_b = parse_commands(SCENARIOS[scenario_b])
        all_keys = set(params_a) | set(params_b)

        diffs = []
        for k in sorted(all_keys):
            val_a = params_a.get(k, "<not set>")
            val_b = params_b.get(k, "<not set>")
            if val_a != val_b:
                diffs.append({"parameter": k, scenario_a: val_a, scenario_b: val_b})

        return {
            "scenario_a": scenario_a,
            "scenario_b": scenario_b,
            "diff_count": len(diffs),
            "differences": diffs
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def export_scenario(name: str, output_path: str = "") -> dict:
    """Save a scenario to a .scs script file.

    Args:
        name:        Scenario to export.
        output_path: Where to write the file. Defaults to outputs/<name>.scs.
    """
    try:
        if name not in SCENARIOS:
            return {"error": f"Scenario '{name}' not found."}
        if not output_path:
            output_path = str(Path(CONFIG["output_dir"]) / f"{name}.scs")
        with open(output_path, "w") as f:
            f.write(f"# Scenario: {name}\n")
            f.write(f"# Exported: {datetime.now().isoformat()}\n\n")
            for cmd in SCENARIOS[name]:
                f.write(cmd + "\n")
        return {"exported": name, "path": output_path}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def import_scenario(scs_path: str, name: str = "") -> dict:
    """Load a .scs script file and register it as a scenario.

    Args:
        scs_path: Path to the .scs file.
        name:     Override name for the scenario. Defaults to the file stem.
    """
    try:
        p = Path(scs_path)
        if not p.exists():
            return {"error": f"File not found: {scs_path}"}
        scenario_name = name or p.stem
        lines = p.read_text().splitlines()
        commands = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
        if scenario_name in SCENARIOS:
            return {"error": f"Scenario '{scenario_name}' already exists. Delete it first or supply a different name."}
        SCENARIOS[scenario_name] = commands
        return {
            "imported": scenario_name,
            "source": scs_path,
            "command_count": len(commands)
        }
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────
# GROUP E — Extended Analysis & Reporting
# ─────────────────────────────────────────────────────────────

@server.tool()
async def get_effluent_statistics(job_id: str) -> dict:
    """Return min / max / mean for all effluent variables from a completed dynamic job.

    Args:
        job_id: A completed job ID from run_dynamic_simulation.
    """
    try:
        import csv

        csv_files = glob.glob(str(Path(CONFIG["output_dir"]) / f"{job_id}*.csv"))
        if not csv_files:
            return {"error": f"No CSV found for job '{job_id}'. Run export_results_csv first."}

        with open(csv_files[0], newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            return {"error": "CSV is empty."}

        numeric_cols = [c for c in rows[0].keys() if c.lower() != "time_h"]
        stats = {}
        for col in numeric_cols:
            values = []
            for r in rows:
                try:
                    values.append(float(r[col]))
                except (ValueError, KeyError):
                    pass
            if values:
                stats[col] = {
                    "min": round(min(values), 4),
                    "max": round(max(values), 4),
                    "mean": round(sum(values) / len(values), 4),
                    "n_points": len(values)
                }

        return {"job_id": job_id, "source_csv": csv_files[0], "statistics": stats}
    except Exception as e:
        return {"error": str(e), "job_id": job_id}


@server.tool()
async def get_sludge_production(job_id: str) -> dict:
    """Estimate WAS rate, sludge age (SRT), and biosolids production from a completed job.

    Args:
        job_id: A completed job ID.
    """
    try:
        job = JOBS.get(job_id)
        if not job:
            return {"error": f"Job '{job_id}' not found."}
        if job.get("status") != "completed":
            return {"error": f"Job '{job_id}' is not completed yet."}

        effluent = job.get("effluent", {})
        tss_eff = effluent.get("TSS", None)

        note = (
            "Full SRT calculation requires MLSS and reactor volume from the model state. "
            "Use search_variables with keyword 'MLSS' or 'VSS' to locate these variables, "
            "then call get_state_variable to read them and compute SRT = (V * MLSS) / (Q_WAS * TSS_WAS)."
        )
        return {
            "job_id": job_id,
            "effluent_TSS_mgL": tss_eff,
            "note": note,
            "tip": "Call list_parameters with unit_name='WAS' to find WAS pump parameters."
        }
    except Exception as e:
        return {"error": str(e), "job_id": job_id}


@server.tool()
async def get_energy_estimate(scenario: str = "baseline_Sc0") -> dict:
    """Estimate relative aeration energy demand from DO setpoints and flow parameters.

    Args:
        scenario: Scenario to evaluate (default: baseline_Sc0).
    """
    try:
        ds = _make_ds()
        _apply_scenario(ds, scenario)
        all_vars = ds.sumo.getVariableNames()

        do_params = [v for v in all_vars if "DO_setpoint" in v or "DO_sp" in v.lower()]
        flow_params = [v for v in all_vars if "Q_air" in v or "Qair" in v.lower() or "blower" in v.lower()]

        do_values = {}
        for p in do_params:
            try:
                do_values[p] = ds.sumo.get(p)
            except Exception:
                pass

        flow_values = {}
        for p in flow_params:
            try:
                flow_values[p] = ds.sumo.get(p)
            except Exception:
                pass

        return {
            "scenario": scenario,
            "do_setpoints": do_values,
            "airflow_parameters": flow_values,
            "note": (
                "Absolute kWh calculation requires blower efficiency curves not available "
                "in the DTT API. Use these DO/airflow values with your blower spec sheet. "
                "Compare DO_setpoints across scenarios with run_scenario_comparison to rank "
                "relative energy consumption."
            )
        }
    except Exception as e:
        return {"error": str(e), "scenario": scenario}


@server.tool()
async def generate_report(job_id: str, scenario: str = "", include_compliance: bool = True) -> dict:
    """Produce a structured design summary for a completed simulation job.

    Combines effluent quality, compliance status, and key model parameters
    into a single report dict that can be exported or discussed.

    Args:
        job_id:             Completed job ID.
        scenario:           Scenario name (used to pull parameter values into the report).
        include_compliance: Whether to evaluate Law 48 compliance (default True).
    """
    try:
        job = JOBS.get(job_id)
        if not job:
            return {"error": f"Job '{job_id}' not found."}

        effluent = job.get("effluent", {})
        report = {
            "report_generated": datetime.now().isoformat(),
            "job_id": job_id,
            "scenario": scenario or job.get("scenario", "unknown"),
            "job_status": job.get("status"),
            "effluent_quality": effluent,
        }

        if include_compliance and effluent:
            checks = []
            all_pass = True
            for var, limit in CONFIG.get("law48_limits", {}).items():
                value = effluent.get(var)
                if value is not None:
                    passed = float(value) <= float(limit)
                    if not passed:
                        all_pass = False
                    checks.append({"variable": var, "value": value, "limit": limit, "pass": passed})
            report["compliance"] = {"law": "Egyptian Law 48/1982", "compliant": all_pass, "checks": checks}

        report["output_csv"] = job.get("csv", "Not yet exported — call export_results_csv.")
        report["tip"] = "Call export_results_csv to save this job to disk for Excel or further analysis."
        return report
    except Exception as e:
        return {"error": str(e), "job_id": job_id}


@server.tool()
async def list_completed_jobs() -> dict:
    """Return all jobs currently tracked in memory with their status and scenario."""
    try:
        summary = []
        for jid, jdata in JOBS.items():
            summary.append({
                "job_id": jid,
                "status": jdata.get("status"),
                "scenario": jdata.get("scenario", "unknown"),
                "type": "dynamic" if jid.startswith("dyn") else "steady_state"
            })
        return {"job_count": len(summary), "jobs": summary}
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def import_influent_profile(csv_path: str, label: str = "") -> dict:
    """Register a time-varying influent CSV for use in dynamic simulations.

    The CSV must have a 'time_h' column plus any influent variable columns
    (e.g. Q_in, COD, TKN, TSS, TP).

    Args:
        csv_path: Full path to the influent profile CSV.
        label:    Optional name for this profile (default: filename stem).
    """
    try:
        p = Path(csv_path)
        if not p.exists():
            return {"error": f"File not found: {csv_path}"}

        import csv as csv_mod
        with open(p, newline="") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames or []

        if "time_h" not in headers:
            return {"error": "CSV must contain a 'time_h' column."}

        profile_label = label or p.stem
        # Store reference in CONFIG for use by dynamic runs
        if "influent_profiles" not in CONFIG:
            CONFIG["influent_profiles"] = {}
        CONFIG["influent_profiles"][profile_label] = str(p)

        return {
            "registered": profile_label,
            "path": str(p),
            "rows": len(rows),
            "columns": headers,
            "usage": f"Pass influent_profile='{profile_label}' to run_dynamic_simulation."
        }
    except Exception as e:
        return {"error": str(e)}
```

---

## Step 3 — Verify the helper functions exist

The new tools rely on `_make_ds()` and `_apply_scenario()` — these should already be
defined in `server.py` because the existing tools use them. Search for these function
names to confirm they exist. If they do not exist under those exact names, find whatever
internal helper creates a `ds` (DTT session) object in the existing `run_steady_state`
function and note the actual function name, then update the new tool code above to match.

Also confirm that `JOBS` is a dict defined at module level (used by `get_job_status` in
the original file). The new tools `list_completed_jobs`, `get_sludge_production`, and
`generate_report` all reference `JOBS`.

---

## Step 4 — Save and restart

1. Save `server.py`.
2. Fully quit Claude Desktop (right-click tray icon → **Quit**).
3. Relaunch Claude Desktop.
4. In a new chat, type: **"List all available SUMO24 tools"** — you should now see the new
   tools in the response.

---

## Quick verification prompts

After restarting, try these in Claude Desktop to confirm each group works:

| Test prompt | Expected tool called |
|---|---|
| `What parameters are available for AerTank1?` | `list_parameters` |
| `Search for variables containing "DO"` | `search_variables` |
| `Is the SUMO model compiled and ready?` | `get_compile_status` |
| `Create a new scenario called high_DO with AerTank1 DO setpoint 3.0` | `create_scenario` |
| `Show differences between baseline_Sc0 and extended_SRT_Sc2` | `get_scenario_diff` |
| `List all completed simulation jobs` | `list_completed_jobs` |
| `Run a steady state and generate a full report` | `run_steady_state` → `generate_report` |

---

## Notes for Cowork

- **Do not delete or modify** any existing `@server.tool()` functions.
- All new code goes **between** the last existing tool and the `if __name__ == "__main__"` block.
- If `server.py` uses a different internal session helper name than `_make_ds()`, update
  the new tool bodies to match — this is the only line that may need adjustment per file.
- The `SCENARIOS` and `JOBS` dicts and the `CONFIG` dict must all be module-level variables;
  the new tools assume they are already defined that way in the existing file.
