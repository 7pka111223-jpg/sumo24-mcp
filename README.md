# SUMO24 MCP

SUMO24 MCP is a Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that gives an MCP client tools for working with SUMO24 wastewater treatment models. It combines model inspection, simulation, scenario analysis, engineering checks, data import, reporting, GUI assistance, and custom process-unit authoring. Native simulations use the included `dynamita` scheduler adapter with a separately installed, licensed SUMO24 Digital Twin Toolkit (DTT).

The repository also includes a DynaSand custom process unit. Installation adds it to SUMO's **Configure → Process unit list → SUMO24 MCP units → DynaSand** palette.

## What the server can do

| Area | Examples |
| --- | --- |
| Model and state inspection | Load a project, inspect units and variables, check the compiled DLL and state file, and examine or queue parameter changes. |
| Simulation and analysis | Run steady-state or dynamic jobs, compare scenarios, check job status, export time series, and evaluate configured effluent limits. |
| Engineering workflow | Validate model structure and mass balance, work through a staged build pipeline, and inspect schematic or SUMO project artifacts. |
| Data and reporting | Read measurement workbooks, compare observations with simulations, and export charts, tables, and reports. |
| SUMO interaction | Use optional Windows GUI tools for palette, canvas, and dialog operations. |
| Custom units | Draft and review a `unit_spec`, check dimensions and continuity, compile SumoSlang, run tracer checks, and emit or install unit assets. |

Tools are advertised through MCP, so the available names and input schemas can be inspected in your client. Some tools need a compiled model, a running SUMO installation, optional Python dependencies, or a compatible GUI session. The custom-unit workflow includes review and validation gates before unit workbook emission; its drafting tools do not infer missing engineering values.

## Requirements and quick start

- Windows, Python 3.11 or later, and an existing licensed SUMO24 installation. Native simulation requires the DTT add-on and license.
- A compiled plant project (`sumoproject.dll` and `state.xml`) for model-specific simulation. You can install the server without one for authoring and other offline work.
- An MCP client that can launch a local stdio server. The installer configures Claude Desktop by default; another client can use a compatible `mcpServers` JSON configuration or equivalent command, arguments, and environment settings.

From the repository root, run:

```powershell
.\install.ps1
```

The installer creates `.venv`, installs the package and optional GUI/report/Excel dependencies, checks native loading and MCP startup, deploys DynaSand into SUMO, and registers a `sumo24` server entry. It detects common SUMO locations and can ask for the SUMO files directory if setup fails. Restart SUMO and your MCP client after installation.

To provide the locations explicitly:

```powershell
.\install.ps1 -SumoDir 'D:\SUMO24' -ProjectDir 'C:\Models\ExtractedPlant' -ConfigPath 'C:\MyClient\mcp.json'
```

`-SumoDir` identifies the SUMO installation; `-ProjectDir` identifies the extracted plant project containing `sumoproject.dll` and `state.xml`. They are different directories with different roles. `-ConfigPath` must point to a client configuration using the `mcpServers` JSON format. See [installation and recovery](INSTALLATION.md) for wheel installation, detection rules, troubleshooting, and the DynaSand deployment layout.

## Using the server

After restarting the client, look for the `sumo24` server and its tool list. A typical model workflow is:

1. Use `get_compile_status` or `get_model_info` to check which DLL and state file the server sees.
2. Explore with `list_unit_processes`, `list_parameters`, or `search_variables` before changing a model.
3. Run `run_steady_state` or `run_dynamic_simulation`, then inspect `get_job_status` and export results with `export_results_csv`.
4. Compare alternatives with `run_scenario_comparison` and evaluate outputs with `check_compliance`.

The installer sets `SUMO_INSTALL_DIR`, `SUMO_DLL`, `SUMO_STATE`, and `SUMO_OUTPUT` in the client entry. Without `-ProjectDir`, the model paths point to an installation data directory until you configure a plant project. The server uses stdio for MCP communication; run it through an MCP client or use the `sumo24-mcp` entry point in an installed environment.

Simulation results depend on the selected model, state, inputs, and license. The compliance tool evaluates configured limits and can return `COMPLIANT`, `NON-COMPLIANT`, or `INSUFFICIENT_DATA`; its result is not a certification of legal applicability or model calibration. See the [runtime and result contract](docs/runtime.md) for job behavior, result quality, cancellation, and model edit semantics.

## Repository layout

| Path | Purpose |
| --- | --- |
| `PY/server.py` | MCP tool definitions and server dispatch. |
| `PY/sumo_runtime.py`, `PY/runtime_results.py` | Native job lifecycle and result interpretation. |
| `PY/hh_tools.py`, `PY/bundled_units/` | Custom-unit authoring tools and bundled DynaSand assets. |
| `PY/install_server.py`, `install.ps1` | Installation, validation, client registration, and unit deployment. |
| `dynamita/` | SUMO scheduler Python adapter. |
| `tests/`, `docs/` | Portable tests, runtime notes, and integration evidence. |

This repository does not include SUMO executables, a DTT license, private plant projects, compiled model DLLs, or model state files. See [implementation and test results](docs/reviews/2026-09-08-implementation-results.md) for the recorded integration checks. Portable tests can be run from the repository root with `python -m unittest discover -s tests -v`.
