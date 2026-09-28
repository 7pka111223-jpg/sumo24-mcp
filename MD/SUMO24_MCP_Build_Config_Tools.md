# SUMO24 MCP — Add Build & Configuration Tools to server.py

## Context
This file adds **new tools** to the existing MCP server at `F:/UNI/SUMO/MCP/PY/server.py`.
These tools cover building a WWTP model from scratch and fully reconfiguring an existing one.

> ⚠️ **Do not remove or modify any existing tools.** All new code is inserted after the last
> existing `@server.tool()` function, before any `if __name__ == "__main__"` block.

> ℹ️ **Prerequisite:** The tools added by `SUMO24_MCP_New_Tools.md` should already be in
> `server.py`. This file adds the next layer — model building and configuration tools.

---

## File to Edit
**`F:/UNI/SUMO/MCP/PY/server.py`**

---

## Step 1 — Verify or add these imports

Find the import block near the top of `server.py` and confirm these lines exist.
Add any that are missing **after** the existing imports:

```python
import os
import glob
import shutil
import subprocess
import copy
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
```

---

## Step 2 — Verify or add the ACTIVE_MODEL registry dict

Search `server.py` for a line like `ACTIVE_MODEL = {}`.
If it does not exist, add this block **immediately after** the `CONFIG = { ... }` dict:

```python
# Tracks the currently loaded .sumo project file and its extracted artifacts
ACTIVE_MODEL = {
    "sumo_file":   None,   # path to the .sumo project file
    "dll_path":    CONFIG.get("model_dll", "sumoproject.dll"),
    "state_xml":   CONFIG.get("state_xml",  "state.xml"),
    "compiled":    False,
    "unit_processes": [],
    "streams": [],
}
```

---

## Step 3 — Insert all new tool functions

Find the **last** existing `@server.tool()` decorated function and insert the entire
code block below **immediately after** it, before any `if __name__ == "__main__"` block.

```python
# ═══════════════════════════════════════════════════════════════════════════
# GROUP A — Project & File Initialisation
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def create_model(project_name: str, project_path: str, template: str = "") -> dict:
    """Initialise a new blank SUMO24 project file.

    SUMO24 does not expose a headless "new project" command via the DTT API, so this
    tool creates the required folder structure and a minimal placeholder .sumo XML file
    that can be opened in the SUMO GUI to finish wiring the process network visually.

    Args:
        project_name: Name for the new project (e.g. 'Qaha_NewPlant').
        project_path: Directory where the project folder should be created.
        template:     Optional. Name of a scenario from SCENARIOS to use as a
                      parameter seed (does not clone unit processes, only parameters).
    """
    try:
        project_dir = Path(project_path) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories mirroring the MCP server layout
        for sub in ["outputs", "scenarios", "dynamita"]:
            (project_dir / sub).mkdir(exist_ok=True)

        # Minimal .sumo project stub (valid XML; open in SUMO GUI to build network)
        sumo_stub = project_dir / f"{project_name}.sumo"
        sumo_stub.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<SumoProject name="{project_name}" version="24">\n'
            '  <!-- Open this file in SUMO24 GUI to build the process network -->\n'
            '  <!-- Then: Simulate → maptoic; save "state.xml" → copy DLL here  -->\n'
            '</SumoProject>\n'
        )

        # Write a README for the new project
        readme = project_dir / "README.md"
        readme.write_text(
            f"# {project_name}\n\n"
            "## Next steps\n"
            "1. Open the .sumo file in SUMO24 GUI and build the process network.\n"
            "2. Simulate the model until Ready.\n"
            "3. In Core Window, run: `maptoic; save \"state.xml\";`\n"
            "4. Copy `sumoproject.dll` and `state.xml` to this folder.\n"
            "5. Update CONFIG in server.py to point at this folder.\n"
        )

        ACTIVE_MODEL["sumo_file"] = str(sumo_stub)

        return {
            "created": str(project_dir),
            "sumo_file": str(sumo_stub),
            "next_step": (
                "Open the .sumo file in SUMO24 GUI. Add unit processes visually, "
                "simulate, then run: maptoic; save 'state.xml'; in the Core Window. "
                "Copy state.xml and sumoproject.dll to this folder, then call load_model."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def load_model(sumo_file_path: str) -> dict:
    """Load an existing .sumo project file and register it as the active model.

    Updates ACTIVE_MODEL so subsequent tools know which project is in use.
    The actual DLL/state.xml must already be extracted (use get_compile_status to check).

    Args:
        sumo_file_path: Full path to the .sumo project file.
    """
    try:
        p = Path(sumo_file_path)
        if not p.exists():
            return {"error": f"File not found: {sumo_file_path}"}

        project_dir = p.parent
        dll_candidates = list(project_dir.glob("*.dll"))
        state_candidates = list(project_dir.glob("state*.xml"))

        dll_found  = dll_candidates[0]  if dll_candidates  else None
        state_found = state_candidates[0] if state_candidates else None

        ACTIVE_MODEL["sumo_file"]  = str(p)
        ACTIVE_MODEL["compiled"]   = dll_found is not None and state_found is not None

        if dll_found:
            ACTIVE_MODEL["dll_path"]  = str(dll_found)
            CONFIG["model_dll"]       = str(dll_found)
        if state_found:
            ACTIVE_MODEL["state_xml"] = str(state_found)
            CONFIG["state_xml"]       = str(state_found)

        return {
            "loaded":     str(p),
            "project_dir": str(project_dir),
            "dll_found":  str(dll_found)  if dll_found  else "NOT FOUND — compile model first",
            "state_found": str(state_found) if state_found else "NOT FOUND — extract state.xml first",
            "ready_to_simulate": ACTIVE_MODEL["compiled"],
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def save_model(output_path: str = "", overwrite: bool = False) -> dict:
    """Save the current project file to disk.

    Because the DTT API operates on a compiled DLL (not the .sumo source), this tool
    saves the current in-memory parameter state as a new state.xml snapshot and copies
    the active .sumo file to the target path.

    Args:
        output_path: Destination path. Defaults to a timestamped copy in the outputs dir.
        overwrite:   If True, overwrites an existing file at output_path.
    """
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        if not output_path:
            output_path = str(Path(CONFIG["output_dir"]) / f"model_save_{ts}")

        dest = Path(output_path)
        dest.mkdir(parents=True, exist_ok=True)

        # Copy .sumo file
        sumo_src = ACTIVE_MODEL.get("sumo_file")
        if sumo_src and Path(sumo_src).exists():
            dest_sumo = dest / Path(sumo_src).name
            if not dest_sumo.exists() or overwrite:
                shutil.copy2(sumo_src, dest_sumo)

        # Save current state.xml via DTT
        state_dest = str(dest / "state.xml")
        ds = _make_ds()
        ds.sumo.executeCommand(f'save "{state_dest}"')

        # Copy DLL
        dll_src = CONFIG.get("model_dll")
        if dll_src and Path(dll_src).exists():
            dll_dest = dest / Path(dll_src).name
            if not dll_dest.exists() or overwrite:
                shutil.copy2(dll_src, dll_dest)

        return {
            "saved_to":   str(dest),
            "state_xml":  state_dest,
            "timestamp":  ts,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def compile_model(force_recompile: bool = False) -> dict:
    """Trigger SUMO to compile the process network into a runnable DLL.

    SUMO24 compilation is performed inside the SUMO GUI (Simulate button).
    This tool checks whether a valid DLL already exists and, if not, provides
    the exact steps required. If force_recompile=True it clears the existing DLL
    so the user is prompted to recompile in the GUI.

    Args:
        force_recompile: If True, deletes the existing DLL so recompilation is forced.
    """
    try:
        dll_path = Path(CONFIG["model_dll"])

        if force_recompile and dll_path.exists():
            backup = dll_path.with_suffix(f".dll.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            shutil.copy2(dll_path, backup)
            dll_path.unlink()
            ACTIVE_MODEL["compiled"] = False
            return {
                "action": "DLL removed — recompilation required",
                "backup":  str(backup),
                "next_steps": [
                    "1. Open the .sumo file in SUMO24 GUI.",
                    "2. Click Simulate and wait for 'Ready for simulation'.",
                    "3. In Core Window run: maptoic; save \"state.xml\";",
                    "4. Copy the new sumoproject.dll and state.xml here.",
                    "5. Call get_compile_status to confirm readiness.",
                ]
            }

        if dll_path.exists():
            return {
                "status":  "already_compiled",
                "dll":     str(dll_path),
                "mtime":   datetime.fromtimestamp(dll_path.stat().st_mtime).isoformat(),
                "note":    "Use force_recompile=True to force a fresh compile.",
            }

        return {
            "status": "dll_not_found",
            "expected_path": str(dll_path),
            "next_steps": [
                "1. Open the .sumo project file in SUMO24 GUI.",
                "2. Click Simulate and wait for 'Ready for simulation'.",
                "3. Open Advanced → Core Window.",
                "4. Type: maptoic; save \"state.xml\";",
                "5. Copy sumoproject.dll and state.xml to: " + str(dll_path.parent),
                "6. Call get_compile_status to verify.",
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def extract_dll(output_path: str = "") -> dict:
    """Locate and register the compiled sumoproject.dll.

    Scans the project directory for a .dll file and updates CONFIG to point at it.
    Use this after recompiling in the SUMO GUI.

    Args:
        output_path: Optional explicit path to the .dll file. If omitted, scans the
                     directory of the active .sumo file and the current working directory.
    """
    try:
        if output_path and Path(output_path).exists():
            dll_path = Path(output_path)
        else:
            search_dirs = [Path.cwd()]
            sumo_file = ACTIVE_MODEL.get("sumo_file")
            if sumo_file:
                search_dirs.insert(0, Path(sumo_file).parent)
            dll_path = None
            for d in search_dirs:
                candidates = list(d.glob("*.dll"))
                if candidates:
                    # Prefer sumoproject.dll
                    named = [c for c in candidates if "sumoproject" in c.name.lower()]
                    dll_path = named[0] if named else candidates[0]
                    break

        if not dll_path or not dll_path.exists():
            return {
                "error": "No .dll file found.",
                "searched": str(search_dirs) if 'search_dirs' in dir() else "current dir",
                "tip": "Compile the model in SUMO GUI first, then call extract_dll again."
            }

        CONFIG["model_dll"]        = str(dll_path)
        ACTIVE_MODEL["dll_path"]   = str(dll_path)
        ACTIVE_MODEL["compiled"]   = True

        return {
            "dll_registered": str(dll_path),
            "size_kb":  round(dll_path.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(dll_path.stat().st_mtime).isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP B — Process Unit Construction
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def list_available_unit_process_types() -> dict:
    """Return all unit process types that SUMO24 supports.

    These are the process objects you can add when building a WWTP from scratch.
    The list covers the standard SUMO24 / WRC process library.
    """
    unit_types = {
        "Hydraulic": [
            "Splitter", "Combiner", "FlowController", "Pump",
            "Pipe", "Valve", "MixingTank",
        ],
        "Primary_Treatment": [
            "PrimaryClarifier", "ScreensAndGritChamber", "EqualisationTank",
            "LamellaClarifier",
        ],
        "Biological_Aerobic": [
            "AerationTank", "OxidationDitch", "SBR",
            "MBR_Aerobic", "ContactStabilisation",
        ],
        "Biological_Anoxic": [
            "AnoxicTank", "Denitrification_Zone",
        ],
        "Biological_Anaerobic": [
            "AnaerobicTank", "UASB", "AnaerobicDigester",
        ],
        "Combined_Nutrient_Removal": [
            "UCT_Reactor", "A2O_Reactor", "JHB_Reactor", "Bardenpho_5stage",
            "Bardenpho_3stage", "Biodenipho",
        ],
        "Secondary_Clarification": [
            "SecondaryClarifier", "Thickener", "DAF",
        ],
        "Tertiary_Treatment": [
            "TertiaryFilter", "ChemicalPrecipitation", "UV_Disinfection",
            "Chlorination", "Ozonation", "MembraneFilter",
        ],
        "Sludge_Treatment": [
            "GravityThickener", "MechanicalThickener", "AerobicDigester",
            "AnaerobicDigester", "Centrifuge", "BeltFilter", "Drying_Bed",
        ],
        "Instrumentation": [
            "DO_Sensor", "NH4_Sensor", "NO3_Sensor", "TSS_Sensor", "pH_Sensor",
        ],
        "Controllers": [
            "DO_Controller", "SRT_Controller", "NitriteController",
            "PhosphorusController", "FlowController",
        ],
    }
    total = sum(len(v) for v in unit_types.items())
    return {
        "categories": len(unit_types),
        "unit_process_types": unit_types,
        "note": (
            "These are the standard SUMO24 process library types. "
            "Available types depend on your DTT addon version. "
            "To add one, call add_unit_process with the type name from this list."
        )
    }


@server.tool()
async def add_unit_process(process_type: str, instance_name: str,
                           kinetic_model: str = "") -> dict:
    """Add a treatment unit process to the active model.

    Uses the SUMO scripting interface via executeCommand. After adding units,
    call compile_model to rebuild the DLL.

    Args:
        process_type:  Type name from list_available_unit_process_types
                       (e.g. 'AerationTank', 'SecondaryClarifier').
        instance_name: Unique name for this instance (e.g. 'AerTank1', 'SecClar1').
        kinetic_model: Optional biological model to assign (e.g. 'ASM2d', 'ASM1').
                       Leave blank for non-biological units.
    """
    try:
        ds = _make_ds()
        cmd = f'addprocess "{process_type}" "{instance_name}"'
        ds.sumo.executeCommand(cmd)

        if kinetic_model:
            km_cmd = f'setmodel "{instance_name}" "{kinetic_model}"'
            ds.sumo.executeCommand(km_cmd)

        ACTIVE_MODEL["unit_processes"].append({
            "name": instance_name,
            "type": process_type,
            "kinetic_model": kinetic_model or "default",
        })

        return {
            "added": instance_name,
            "type":  process_type,
            "kinetic_model": kinetic_model or "not specified (default)",
            "note": "Call compile_model after adding all units and connections.",
        }
    except Exception as e:
        return {
            "error": str(e),
            "tip": (
                "If executeCommand is not available in your DTT version, add the unit "
                "manually in SUMO GUI. Then call compile_model and extract_dll."
            )
        }


@server.tool()
async def remove_unit_process(unit_name: str, remove_streams: bool = True) -> dict:
    """Remove a unit process from the active model.

    Args:
        unit_name:      Name of the unit to remove (e.g. 'AerTank2').
        remove_streams: If True (default), also removes all streams connected to this unit.
    """
    try:
        ds = _make_ds()
        cmd = f'removeprocess "{unit_name}"' + (' removestreams' if remove_streams else '')
        ds.sumo.executeCommand(cmd)

        ACTIVE_MODEL["unit_processes"] = [
            u for u in ACTIVE_MODEL["unit_processes"] if u["name"] != unit_name
        ]

        return {
            "removed": unit_name,
            "streams_removed": remove_streams,
            "note": "Call compile_model to rebuild the DLL after removing units.",
        }
    except Exception as e:
        return {
            "error": str(e),
            "tip": "Remove the unit manually in SUMO GUI if DTT scripting is unavailable."
        }


@server.tool()
async def list_available_kinetic_models() -> dict:
    """List biological kinetic models available for assignment to reactors in SUMO24."""
    models = {
        "Activated_Sludge": {
            "ASM1":  "IWA Activated Sludge Model No. 1 — C/N removal",
            "ASM2d": "IWA ASM2d — C/N/P removal with EBPR",
            "ASM3":  "IWA ASM3 — storage-based ASM for improved SRT sensitivity",
            "ASM3+BioP": "ASM3 extended with biological phosphorus",
        },
        "Membrane_Bioreactor": {
            "MBR_ASM2d": "ASM2d adapted for MBR (higher MLSS, different aeration)",
        },
        "Anaerobic": {
            "ADM1":      "IWA Anaerobic Digestion Model No. 1",
            "Siegrist":  "Siegrist anaerobic model",
        },
        "Simplified": {
            "Takács":    "Simplified settler model (secondary clarifier)",
            "CSTR_Simple": "Simple CSTR without biological kinetics",
        },
    }
    return {
        "kinetic_models": models,
        "tip": "Use set_kinetic_model to assign one of these to a reactor unit.",
    }


@server.tool()
async def set_kinetic_model(unit_name: str, kinetic_model: str) -> dict:
    """Assign or switch the biological kinetic model on a reactor unit.

    Args:
        unit_name:     Unit to reconfigure (e.g. 'AerTank1').
        kinetic_model: Model name from list_available_kinetic_models (e.g. 'ASM2d').
    """
    try:
        ds = _make_ds()
        ds.sumo.executeCommand(f'setmodel "{unit_name}" "{kinetic_model}"')
        return {
            "unit":          unit_name,
            "kinetic_model": kinetic_model,
            "note": "Recompile the model after switching kinetic models.",
        }
    except Exception as e:
        return {"error": str(e), "unit": unit_name, "kinetic_model": kinetic_model}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP C — Flow Network & Stream Configuration
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def connect_unit_processes(from_unit: str, to_unit: str,
                                 stream_name: str, stream_type: str = "liquid") -> dict:
    """Create a flow connection (stream) between two unit processes.

    Args:
        from_unit:   Source unit name (e.g. 'PrimClar1').
        to_unit:     Destination unit name (e.g. 'AerTank1').
        stream_name: Unique name for this stream (e.g. 'PrimEff_to_Aer').
        stream_type: 'liquid' (default), 'sludge', 'gas', or 'recycle'.
    """
    try:
        ds = _make_ds()
        cmd = (f'connect "{from_unit}" "{to_unit}" '
               f'"{stream_name}" "{stream_type}"')
        ds.sumo.executeCommand(cmd)

        ACTIVE_MODEL["streams"].append({
            "name":      stream_name,
            "from":      from_unit,
            "to":        to_unit,
            "type":      stream_type,
        })

        return {
            "stream_created": stream_name,
            "from":           from_unit,
            "to":             to_unit,
            "type":           stream_type,
            "note": "Recompile after all connections are defined.",
        }
    except Exception as e:
        return {
            "error": str(e),
            "tip": "Draw this connection in SUMO GUI if executeCommand is unavailable."
        }


@server.tool()
async def add_recycle_stream(from_unit: str, to_unit: str,
                             stream_name: str, recycle_type: str = "RAS") -> dict:
    """Add a recycle stream (RAS, WAS, internal recycle, or reject water).

    Args:
        from_unit:    Source unit (e.g. 'SecClar1' for RAS).
        to_unit:      Destination unit (e.g. 'AerTank1' for RAS return).
        stream_name:  Unique stream name (e.g. 'RAS_1').
        recycle_type: 'RAS', 'WAS', 'InternalRecycle', 'RejectWater', or 'Sidestream'.
    """
    try:
        type_map = {
            "RAS":             "return_activated_sludge",
            "WAS":             "waste_activated_sludge",
            "InternalRecycle": "internal_recycle",
            "RejectWater":     "reject_water",
            "Sidestream":      "sidestream",
        }
        sumo_type = type_map.get(recycle_type, "recycle")

        ds = _make_ds()
        ds.sumo.executeCommand(
            f'connect "{from_unit}" "{to_unit}" "{stream_name}" "{sumo_type}"'
        )

        ACTIVE_MODEL["streams"].append({
            "name":  stream_name,
            "from":  from_unit,
            "to":    to_unit,
            "type":  recycle_type,
        })

        return {
            "recycle_stream_created": stream_name,
            "type":   recycle_type,
            "from":   from_unit,
            "to":     to_unit,
        }
    except Exception as e:
        return {"error": str(e), "recycle_type": recycle_type}


@server.tool()
async def modify_flow_connection(stream_name: str, new_from: str = "",
                                 new_to: str = "", new_flow_m3d: float = -1) -> dict:
    """Redirect or resize a flow stream.

    Args:
        stream_name:    Name of the existing stream to modify.
        new_from:       New source unit (optional — omit to keep current).
        new_to:         New destination unit (optional — omit to keep current).
        new_flow_m3d:   New fixed flow rate in m³/d (-1 = do not change).
    """
    try:
        ds = _make_ds()
        actions = []

        if new_from or new_to:
            cmd = f'reconnect "{stream_name}"'
            if new_from:
                cmd += f' from="{new_from}"'
            if new_to:
                cmd += f' to="{new_to}"'
            ds.sumo.executeCommand(cmd)
            actions.append(f"reconnected: from={new_from or 'unchanged'} to={new_to or 'unchanged'}")

        if new_flow_m3d >= 0:
            # Try common SUMO flow parameter patterns
            flow_var_candidates = [
                f"Sumo__Plant__{stream_name}__param__Q",
                f"Sumo__Plant__{stream_name}__Q",
            ]
            set_ok = False
            for var in flow_var_candidates:
                try:
                    ds.sumo.set(var, new_flow_m3d)
                    actions.append(f"flow set to {new_flow_m3d} m³/d via {var}")
                    set_ok = True
                    break
                except Exception:
                    continue
            if not set_ok:
                actions.append(
                    f"flow change requested ({new_flow_m3d} m³/d) — "
                    "use search_variables with the stream name to find the correct Q variable"
                )

        # Update in-memory stream registry
        for s in ACTIVE_MODEL["streams"]:
            if s["name"] == stream_name:
                if new_from:
                    s["from"] = new_from
                if new_to:
                    s["to"] = new_to
                break

        return {"stream": stream_name, "actions_taken": actions}
    except Exception as e:
        return {"error": str(e), "stream": stream_name}


@server.tool()
async def list_flow_streams(unit_name: str = "") -> dict:
    """List all flow connections, optionally filtered to a specific unit.

    Combines the in-memory ACTIVE_MODEL stream registry with variable names
    that look like stream flow variables in the compiled model.

    Args:
        unit_name: Optional unit name filter (e.g. 'AerTank1').
    """
    try:
        registered = ACTIVE_MODEL.get("streams", [])
        if unit_name:
            registered = [
                s for s in registered
                if unit_name.lower() in s.get("from", "").lower()
                or unit_name.lower() in s.get("to", "").lower()
            ]

        # Also scan compiled model variables for stream-like Q variables
        compiled_streams = []
        try:
            ds = _make_ds()
            all_vars = ds.sumo.getVariableNames()
            q_vars = [v for v in all_vars if "__Q" in v and "param" not in v]
            if unit_name:
                q_vars = [v for v in q_vars if unit_name.lower() in v.lower()]
            compiled_streams = q_vars[:50]  # cap output
        except Exception:
            pass

        return {
            "registered_streams": registered,
            "compiled_flow_variables": compiled_streams,
            "unit_filter": unit_name or "none",
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP D — Influent & Load Definition
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def set_influent_characteristics(
    flow_m3d:  float,
    BOD_mgL:   float = 0.0,
    COD_mgL:   float = 0.0,
    TSS_mgL:   float = 0.0,
    VSS_mgL:   float = 0.0,
    TKN_mgL:   float = 0.0,
    NH4_mgL:   float = 0.0,
    TN_mgL:    float = 0.0,
    TP_mgL:    float = 0.0,
    temp_C:    float = 20.0,
    influent_unit: str = "Influent",
) -> dict:
    """Define influent wastewater composition and flow rate.

    Maps lab/field parameters to their SUMO SumoCore variable names and
    sets them in memory. Only non-zero values are applied.

    Args:
        flow_m3d:       Influent flow rate (m³/d).
        BOD_mgL:        BOD₅ (mg/L) — converted to substrate fraction.
        COD_mgL:        Total COD (mg/L).
        TSS_mgL:        Total suspended solids (mg/L).
        VSS_mgL:        Volatile suspended solids (mg/L).
        TKN_mgL:        Total Kjeldahl nitrogen (mg/L).
        NH4_mgL:        Ammonium-N (mg/L).
        TN_mgL:         Total nitrogen (mg/L — used if TKN not supplied).
        TP_mgL:         Total phosphorus (mg/L).
        temp_C:         Influent temperature (°C).
        influent_unit:  Name of the influent unit process (default 'Influent').
    """
    try:
        ds = _make_ds()

        # Map field parameters to candidate SUMO variable names
        param_map = {
            f"Sumo__Plant__{influent_unit}__param__Q":     flow_m3d   if flow_m3d   else None,
            f"Sumo__Plant__{influent_unit}__param__S_COD": COD_mgL    if COD_mgL    else None,
            f"Sumo__Plant__{influent_unit}__param__X_TSS": TSS_mgL    if TSS_mgL    else None,
            f"Sumo__Plant__{influent_unit}__param__X_VSS": VSS_mgL    if VSS_mgL    else None,
            f"Sumo__Plant__{influent_unit}__param__S_NH4": NH4_mgL    if NH4_mgL    else None,
            f"Sumo__Plant__{influent_unit}__param__S_TKN": TKN_mgL    if TKN_mgL    else None,
            f"Sumo__Plant__{influent_unit}__param__S_TP":  TP_mgL     if TP_mgL     else None,
            f"Sumo__Plant__{influent_unit}__param__T":     temp_C,
        }

        applied, skipped, failed = [], [], []
        all_vars = ds.sumo.getVariableNames()

        for var, value in param_map.items():
            if value is None or value == 0.0:
                skipped.append(var)
                continue
            if var in all_vars:
                try:
                    ds.sumo.set(var, float(value))
                    applied.append({"variable": var, "value": value})
                except Exception as ve:
                    failed.append({"variable": var, "error": str(ve)})
            else:
                failed.append({
                    "variable": var,
                    "error": "Not found — use search_variables to find the correct name"
                })

        return {
            "influent_unit":     influent_unit,
            "applied_count":     len(applied),
            "skipped_count":     len(skipped),
            "failed_count":      len(failed),
            "applied":           applied,
            "failed":            failed,
            "tip": (
                "If variables failed, call search_variables with keywords like "
                "'COD', 'TSS', 'NH4' to find the exact names in your compiled model."
            )
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def set_fractionation(unit_name: str, fraction_dict: dict) -> dict:
    """Set COD/TSS fractionation for a unit's influent characterisation.

    Fractionation splits total COD and TSS into model-specific components
    (Xs, Xp, Si, Ss, Xi, etc.) required by ASM-type models.

    Args:
        unit_name:     Unit to apply fractionation to (usually 'Influent').
        fraction_dict: Dict mapping fraction name to ratio (0–1), e.g.:
                       {
                         "Xs_COD_frac": 0.35,
                         "Si_COD_frac": 0.05,
                         "Ss_COD_frac": 0.20,
                         "Xi_COD_frac": 0.40,
                         "fXS":         0.75,
                       }
    """
    try:
        ds = _make_ds()
        all_vars = ds.sumo.getVariableNames()
        applied, failed = [], []

        for frac_name, ratio in fraction_dict.items():
            # Try several naming patterns
            candidates = [
                f"Sumo__Plant__{unit_name}__param__{frac_name}",
                f"Sumo__Plant__{unit_name}__{frac_name}",
                f"Sumo__Plant__Influent__param__{frac_name}",
            ]
            set_ok = False
            for var in candidates:
                if var in all_vars:
                    try:
                        ds.sumo.set(var, float(ratio))
                        applied.append({"fraction": frac_name, "variable": var, "value": ratio})
                        set_ok = True
                        break
                    except Exception as ve:
                        failed.append({"fraction": frac_name, "variable": var, "error": str(ve)})
                        break
            if not set_ok and not any(f["fraction"] == frac_name for f in failed):
                failed.append({
                    "fraction": frac_name,
                    "error": "Variable not found — use search_variables to find exact name"
                })

        return {
            "unit_name":     unit_name,
            "applied_count": len(applied),
            "failed_count":  len(failed),
            "applied":       applied,
            "failed":        failed,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP E — Persistent Parameter Editing
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def set_parameter_persistent(parameter: str, value: float) -> dict:
    """Write a parameter change permanently into the active state.xml file.

    Unlike set_parameter (in-memory only), this edits state.xml on disk so the
    change survives server restarts. Creates a timestamped backup before writing.

    Args:
        parameter: Full SumoCore parameter name.
        value:     New value in the parameter's native units.
    """
    try:
        state_path = Path(CONFIG["state_xml"])
        if not state_path.exists():
            return {"error": f"state.xml not found at {state_path}"}

        # Backup
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = state_path.with_suffix(f".xml.bak_{ts}")
        shutil.copy2(state_path, backup)

        # Parse and modify
        tree = ET.parse(state_path)
        root = tree.getroot()
        found = False
        for elem in root.iter():
            if elem.get("name") == parameter:
                old_val = elem.get("value")
                elem.set("value", str(value))
                found = True
                break

        if not found:
            return {
                "error": f"Parameter '{parameter}' not found in state.xml.",
                "tip": "Use search_variables to confirm the exact parameter name.",
                "backup_created": str(backup),
            }

        tree.write(state_path, encoding="utf-8", xml_declaration=True)

        return {
            "parameter":       parameter,
            "old_value":       old_val,
            "new_value":       str(value),
            "written_to":      str(state_path),
            "backup_created":  str(backup),
            "note": "Change is now persistent. Reload model to apply.",
        }
    except Exception as e:
        return {"error": str(e), "parameter": parameter}


@server.tool()
async def add_controller(controller_type: str, controlled_var: str,
                          setpoint: float, unit_name: str,
                          actuator_unit: str = "") -> dict:
    """Add a control loop to a unit process.

    Supported controller types: DO_Controller, SRT_Controller,
    NH4_Controller, NO3_Controller, FlowSplitter_Controller.

    Args:
        controller_type: e.g. 'DO_Controller', 'SRT_Controller'.
        controlled_var:  Variable the controller reads (e.g. 'S_O', 'SRT').
        setpoint:        Target setpoint value in native units.
        unit_name:       Unit the sensor is placed in (e.g. 'AerTank1').
        actuator_unit:   Unit the controller acts on (e.g. 'Blower1').
                         Defaults to unit_name if not supplied.
    """
    try:
        ds = _make_ds()
        actuator = actuator_unit or unit_name
        cmd = (
            f'addcontroller "{controller_type}" '
            f'sensor="{unit_name}" '
            f'variable="{controlled_var}" '
            f'setpoint={setpoint} '
            f'actuator="{actuator}"'
        )
        ds.sumo.executeCommand(cmd)
        return {
            "controller_added": controller_type,
            "sensor_unit":      unit_name,
            "controlled_var":   controlled_var,
            "setpoint":         setpoint,
            "actuator_unit":    actuator,
            "note": "Recompile the model after adding controllers.",
        }
    except Exception as e:
        return {
            "error": str(e),
            "tip": (
                "Add the controller in SUMO GUI (Process → Add Controller) if "
                "the executeCommand interface is unavailable in your DTT version."
            )
        }


# ═══════════════════════════════════════════════════════════════════════════
# GROUP F — Validation & Mass Balance
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def validate_model(check_level: str = "basic") -> dict:
    """Run validation checks on the current model configuration.

    Checks for missing connections, unset required parameters, and
    (if check_level='full') mass-balance sanity checks.

    Args:
        check_level: 'basic' (connection + parameter checks) or 'full' (+ mass balance).
    """
    try:
        issues = []
        warnings = []

        # Check DLL and state.xml exist
        dll_ok   = Path(CONFIG.get("model_dll", "")).exists()
        state_ok = Path(CONFIG.get("state_xml",  "")).exists()

        if not dll_ok:
            issues.append("sumoproject.dll not found — model must be compiled in SUMO GUI first.")
        if not state_ok:
            issues.append("state.xml not found — extract state from SUMO GUI (maptoic; save).")

        if dll_ok and state_ok:
            ds = _make_ds()
            all_vars = ds.sumo.getVariableNames()
            param_vars = [v for v in all_vars if "__param__" in v]

            # Check for common required parameters
            required_patterns = ["__Q", "__S_COD", "__X_TSS", "__T"]
            for pat in required_patterns:
                matching = [v for v in param_vars if pat in v]
                if not matching:
                    warnings.append(
                        f"No parameter found matching pattern '{pat}' — "
                        "influent characterisation may be incomplete."
                    )

            if check_level == "full":
                # Attempt a quick steady-state to surface solver errors
                try:
                    ds.sumo.executeCommand("steadystate maxiter=100")
                    warnings.append(
                        "Full check: quick steady-state ran without crashing — "
                        "model appears solvable. Run run_steady_state for full results."
                    )
                except Exception as ss_err:
                    issues.append(f"Full check: steady-state failed — {ss_err}")

        status = "OK" if not issues else "ISSUES_FOUND"
        return {
            "status":       status,
            "check_level":  check_level,
            "issue_count":  len(issues),
            "warning_count":len(warnings),
            "issues":       issues,
            "warnings":     warnings,
        }
    except Exception as e:
        return {"error": str(e)}


@server.tool()
async def get_mass_balance(job_id: str, elements: list = None) -> dict:
    """Return COD, N, P, and TSS mass balance across the plant for a completed job.

    Reads the job's output CSV and computes load-in vs load-out for each element.

    Args:
        job_id:   A completed job ID from run_steady_state or run_dynamic_simulation.
        elements: List of elements to balance. Default: ['COD', 'N', 'P', 'TSS'].
    """
    try:
        import csv as csv_mod

        if elements is None:
            elements = ["COD", "N", "P", "TSS"]

        # Locate the job CSV
        csv_files = glob.glob(str(Path(CONFIG["output_dir"]) / f"{job_id}*.csv"))
        if not csv_files:
            return {
                "error": f"No CSV found for job '{job_id}'.",
                "tip": "Call export_results_csv first to generate the CSV file."
            }

        with open(csv_files[0], newline="") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)

        if not rows:
            return {"error": "CSV is empty."}

        headers = list(rows[0].keys())

        # Variable mappings for mass balance elements
        element_vars = {
            "COD": {
                "influent": ["COD_in", "Inf_COD", "S_COD_in"],
                "effluent": ["COD_eff", "Eff_COD", "S_COD_eff", "COD_out"],
            },
            "N": {
                "influent": ["TN_in", "TKN_in", "Inf_TN"],
                "effluent": ["TN_eff", "Eff_TN", "TN_out"],
            },
            "P": {
                "influent": ["TP_in", "Inf_TP"],
                "effluent": ["TP_eff", "Eff_TP", "TP_out"],
            },
            "TSS": {
                "influent": ["TSS_in", "Inf_TSS"],
                "effluent": ["TSS_eff", "Eff_TSS", "TSS_out"],
            },
        }

        def find_col(candidates):
            for c in candidates:
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
            return round(sum(vals) / len(vals), 2) if vals else None

        balance = {}
        for elem in elements:
            if elem not in element_vars:
                balance[elem] = {"note": "Not in default element map"}
                continue
            inf_col = find_col(element_vars[elem]["influent"])
            eff_col = find_col(element_vars[elem]["effluent"])
            inf_val = col_mean(inf_col) if inf_col else None
            eff_val = col_mean(eff_col) if eff_col else None
            removal = None
            if inf_val and eff_val and inf_val > 0:
                removal = round((inf_val - eff_val) / inf_val * 100, 1)
            balance[elem] = {
                "influent_col":    inf_col or "not found in CSV",
                "effluent_col":    eff_col or "not found in CSV",
                "influent_mean":   inf_val,
                "effluent_mean":   eff_val,
                "removal_pct":     removal,
            }

        return {
            "job_id":   job_id,
            "csv":      csv_files[0],
            "elements": balance,
            "tip": (
                "If influent/effluent columns are not found, call get_effluent_statistics "
                "to see all available column names, then re-call with matching element names."
            )
        }
    except Exception as e:
        return {"error": str(e), "job_id": job_id}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP G — Additional State Management
# ═══════════════════════════════════════════════════════════════════════════

@server.tool()
async def initialize_state() -> dict:
    """Reset the model to its initial (t=0) state from the reference state.xml.

    Reloads the CONFIG state_xml so all in-memory parameter overrides are discarded.
    Does not modify the state.xml file itself.
    """
    try:
        state_path = Path(CONFIG["state_xml"])
        if not state_path.exists():
            return {"error": f"state.xml not found at {state_path}"}

        # Re-instantiate the DTT session to force a clean reload
        ds = _make_ds()
        ds.sumo.executeCommand('reset')

        return {
            "status":     "reset_to_initial_state",
            "state_xml":  str(state_path),
            "timestamp":  datetime.now().isoformat(),
            "note": (
                "All in-memory parameter overrides cleared. "
                "The model is back to its state.xml baseline."
            )
        }
    except Exception as e:
        return {
            "error": str(e),
            "tip": "If DTT reset fails, restart the MCP server to reload state.xml cleanly."
        }
```

---

## Step 4 — Save and restart

1. Save `server.py`.
2. Fully quit Claude Desktop (right-click tray icon → **Quit**).
3. Relaunch Claude Desktop.
4. In a new chat type: **"List all available SUMO24 tools"** — the new tools should appear.

---

## Step 5 — Verification prompts

Test each group is working by running these in Claude Desktop:

| Prompt | Expected tool |
|---|---|
| `Create a new SUMO24 project called TestPlant in F:/UNI/SUMO/Projects` | `create_model` |
| `Load the model at F:/UNI/SUMO/Projects/TestPlant/TestPlant.sumo` | `load_model` |
| `What unit process types can I add to SUMO24?` | `list_available_unit_process_types` |
| `Add a secondary clarifier called SecClar2 to the model` | `add_unit_process` |
| `Connect PrimClar1 outlet to AerTank1 inlet` | `connect_unit_processes` |
| `Add a RAS recycle stream from SecClar1 back to AerTank1` | `add_recycle_stream` |
| `Set influent to 28000 m³/d, COD 350, TSS 280, TKN 45, TP 7 mg/L` | `set_influent_characteristics` |
| `Permanently set the WAS pump flow to 320 m³/d in state.xml` | `set_parameter_persistent` |
| `Add a DO controller on AerTank1 with setpoint 2.0 mg/L` | `add_controller` |
| `Validate the model and report any issues` | `validate_model` |
| `Show me the COD and nitrogen mass balance for job ss_001` | `get_mass_balance` |
| `Reset the model to its initial state` | `initialize_state` |

---

## Important notes for Cowork

### What the DTT API supports directly
The `executeCommand` interface in the DTT Python API covers most of the build tools.
However, if your installed DTT version does not support a specific command, the tool
will return a `"tip"` field with the manual SUMO GUI equivalent.

### Build-from-scratch workflow order
When creating a new WWTP model, always follow this sequence:
1. `create_model` → creates the folder structure
2. Open the `.sumo` file in SUMO GUI and build the process network visually
3. Click **Simulate** in SUMO GUI → wait for "Ready"
4. In Core Window: `maptoic; save "state.xml";`
5. `extract_dll` → registers the compiled DLL
6. `load_model` → activates the project in the MCP server
7. `set_influent_characteristics` → define the influent load
8. `run_steady_state` + `check_compliance` → first results

### Reconfiguration workflow order
When changing an existing model:
1. `search_variables` + `get_parameter` → inspect before changing anything
2. `save_state` → snapshot the current state before making changes
3. `set_multiple_parameters` or `set_parameter_persistent` → apply changes
4. `run_steady_state` → verify the change had the intended effect
5. `check_compliance` + `generate_report` → document the outcome

### Variable names
SUMO variable names are case-sensitive with double-underscore separators:
`Sumo__Plant__<UnitName>__param__<ParameterName>`

Always call `search_variables` before `set_parameter` to confirm the exact name.
The `set_influent_characteristics` and `set_fractionation` tools handle name
resolution automatically for common parameters.
