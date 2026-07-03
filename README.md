# SUMO24 MCP Server

An MCP (Model Context Protocol) server that exposes the SUMO24 Digital Twin Toolkit (DTT) Python API as tools for Claude. Ask Claude to run simulations, compare scenarios, check compliance, analyse mass balances, and more — all from a chat window.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| SUMO24 installed | With the DTT addon (`SumoDTT24.dya`) applied |
| DTT license | `standalone+DTT`, `network+DTT`, or `container+DTT` |
| Python 3.10+ | Must match the Python SUMO's DTT addon expects |
| Claude Desktop | Any recent version |

---

## Quick Start

### 1. Clone the repo

```powershell
git clone https://github.com/<your-username>/sumo24-mcp.git
cd sumo24-mcp
```

### 2. Copy the DTT Python API from your SUMO installation

```powershell
# Default SUMO install path on Windows:
Copy-Item -Recurse "C:\Program Files\Dynamita\SUMO24\PythonAPI\dynamita" .\dynamita
```

The `dynamita/` folder is **not included in this repo** — it is proprietary Dynamita software that ships with SUMO24.

### 3. Add your model files

Place your compiled model at the repo root:

```
sumo24-mcp/
├── sumoproject.dll   ← extracted from your .sumo file (see below)
└── state.xml         ← saved steady-state from the SUMO GUI
```

**How to extract these from SUMO:**
1. Open your `.sumo` file in the SUMO GUI and click **Simulate**
2. Open **Advanced → Core Window**
3. Run: `maptoic; save "state.xml";`
4. Copy `state.xml` and `sumoproject.dll` from the SUMO project folder to the repo root

Or use the helper script:

```powershell
python lib\prepare_project.py --project "C:\Projects\MyPlant.sumo" --scenario "Baseline"
```

> **Example model available:** See [`examples/qaha-wwtp/`](examples/qaha-wwtp/) for the Qaha WWTP model used during development. Copy those files to the repo root to try the server with a working model before connecting your own.

### 4. Run the installer

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

This finds a working Python, installs `mcp`, smoke-tests the server, and writes the Claude Desktop config.

### 5. Restart Claude Desktop

Fully quit (right-click tray icon → **Quit**) and reopen. You should see **sumo24** in the tools panel.

---

## Repo Structure

```
sumo24-mcp/
├── server.py                  ← MCP server entry point
├── install.ps1                ← Windows installer / Claude Desktop config writer
├── diagnose.ps1               ← Diagnostic script
├── requirements.txt
├── .gitignore
├── lib/                       ← Supporting Python modules
│   ├── schematic_parser.py
│   ├── sumo_compiler.py
│   ├── sumo_pack.py
│   ├── sumo_native.py
│   ├── dtt_editor.py
│   ├── html_schematic_io.py
│   ├── unit_type_registry.py
│   ├── dynamita_compat.py
│   ├── prepare_project.py
│   └── pipeline/
├── examples/
│   ├── qaha-wwtp/             ← Example: Qaha WWTP digital twin
│   │   ├── README.md
│   │   ├── sumoproject.dll
│   │   └── state.xml
│   └── mcp_use_client/        ← Example: drive the server with mcp-use (no Claude Desktop)
│       ├── README.md
│       ├── demo_client.py
│       └── requirements.txt
├── docs/                      ← Tool reference docs
└── outputs/                   ← Simulation results (git-ignored)
```

Files you add locally and that are **not tracked by git**:

| File / folder | What it is |
|---|---|
| `dynamita/` | Proprietary DTT Python API — copy from your SUMO install |
| `sumoproject.dll` | Your compiled model |
| `state.xml` | Saved steady-state snapshot |
| `outputs/` | Simulation result files |

---

## Using a Different Model

Point the server at your own files with environment variables (the installer sets these automatically):

| Variable | Default | Description |
|---|---|---|
| `SUMO_DLL` | `sumoproject.dll` | Path to your compiled model DLL |
| `SUMO_STATE` | `state.xml` | Path to your saved state XML |
| `SUMO_OUTPUT` | `./outputs` | Directory for simulation results |

Or edit the `CONFIG` dict at the top of `server.py` directly.

---

## Available MCP Tools

| Tool | Description |
|---|---|
| `run_steady_state` | Steady-state run with optional influent overrides |
| `run_dynamic_simulation` | Dynamic run for N days, returns a job ID |
| `run_scenario_comparison` | Parallel run of multiple scenarios → compliance table |
| `set_parameter` | Queue a SumoCore parameter override for the next run |
| `get_parameter` | Read a parameter value from the loaded model |
| `get_job_status` | Poll a running or finished job |
| `check_compliance` | Evaluate results against effluent limits |
| `export_results_csv` | Save time-series data from a job to CSV |
| `list_scenarios` | Show all defined scenarios and their parameter changes |
| `get_mass_balance` | Compute plant-wide mass balance |
| `get_effluent_statistics` | Summary statistics for effluent quality |

Full tool reference: [`docs/`](docs/)

---

## Troubleshooting

**`dynamita` import fails** — Check that `dynamita/` is in the repo root and the DTT addon was installed in SUMO24. Run `.\diagnose.ps1` for a full check.

**License error** — Confirm your `dynaMIC` license includes the DTT sub-type.

**`sumo24` not visible in Claude** — Fully quit Claude Desktop (not just close the window) before restarting. Check logs at `%APPDATA%\Claude\logs\mcp-server-sumo24*.log`.

**Variable not found** — Variable names are case-sensitive and use double-underscore separators (e.g. `Sumo__Plant__Aeration__param__V`). Use the SUMO Core Window to verify exact names.

---

## License

This MCP server wrapper is open source. The `dynamita/` Python API is proprietary software from [Dynamita](https://www.dynamita.com/) and is distributed under the SUMO24 license agreement.
