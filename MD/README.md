# SUMO24 MCP Server

An MCP (Model Context Protocol) server that exposes SUMO24's Digital Twin Toolkit
(DTT) Python API as tools for Claude. Designed for the Qaha WWTP digital twin project.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| SUMO24 installed | With DTT addon (`SumoDTT24.dya`) applied |
| DTT license | standalone+DTT, network+DTT, or container+DTT |
| Python 3.10+ | Matches SUMO's bundled Python version |
| `mcp` package | `pip install mcp` |

---

## Project Structure

```
sumo24-mcp/
├── server.py              ← MCP server (main entry point)
├── prepare_project.py     ← One-time project extraction script
├── requirements.txt
├── claude_desktop_config.json
├── dynamita/              ← Copy from SUMO install folder (DTT addon)
│   ├── scheduler.py
│   ├── sumon.py
│   └── tool.py
├── sumoproject.dll        ← Extracted from your .sumo file
├── state.xml              ← Saved steady-state from SUMO GUI
├── scenarios/             ← .scs script files for each scenario
│   └── Sc1_increased_RAS.scs
└── outputs/               ← Simulation results (CSV/TSV)
```

---

## Setup — Step by Step

### 1. Install dependencies

```bash
pip install mcp
```

### 2. Copy the DTT Python API

After installing the DTT addon in SUMO, copy the `dynamita` folder:

```
# Windows default install path:
C:\Program Files\Dynamita\SUMO24\PythonAPI\dynamita\

# Copy to your project:
cp -r "C:\Program Files\Dynamita\SUMO24\PythonAPI\dynamita" ./dynamita
```

### 3. Prepare your project files

Open your `.sumo` file in the SUMO GUI:
1. Click **Simulate** → wait for "Ready for simulation"
2. Open **Advanced → Core Window**
3. In the command box, type: `maptoic; save "state.xml";`
4. Copy `state.xml` and `sumoproject.dll` from the project directory to this folder

Or use the helper script:

```bash
python prepare_project.py --project "C:/Projects/Qaha_WWTP.sumo" --scenario "Baseline"
```

### 4. Update CONFIG in server.py

Edit the `CONFIG` dict at the top of `server.py`:

```python
CONFIG = {
    "model_dll":  "sumoproject.dll",   # path to extracted DLL
    "state_xml":  "state.xml",         # path to saved system state
    "output_dir": "./outputs",
}
```

### 5. Register with Claude Desktop

Copy the contents of `claude_desktop_config.json` into:

```
# Windows
%APPDATA%\Claude\claude_desktop_config.json

# macOS
~/Library/Application Support/Claude/claude_desktop_config.json
```

Update the paths to match your actual project location.

### 6. Start Claude Desktop

Claude will automatically start the MCP server. You'll see `sumo24` listed in
the tools panel. You can now ask Claude things like:

> "Run a steady-state simulation with influent flow 30,000 m³/day and check Law 48 compliance"

> "Compare all 6 Qaha scenarios and tell me which ones are compliant"

> "Run a 30-day dynamic simulation with the extended SRT scenario"

---

## Available MCP Tools

| Tool | Description |
|---|---|
| `run_steady_state` | Steady-state run with optional influent overrides |
| `run_dynamic_simulation` | Dynamic run for N days, returns job ID |
| `run_scenario_comparison` | Parallel run of multiple scenarios → compliance table |
| `set_parameter` | Queue a SumoCore parameter override for the next run |
| `get_job_status` | Poll a running/finished job |
| `check_compliance` | Evaluate results against Egyptian Law 48/1982 |
| `export_results_csv` | Save time-series data from a job to CSV |
| `list_scenarios` | Show all defined scenarios and their parameter changes |

---

## Adding Your Own Scenarios

Edit the `SCENARIOS` dict in `server.py`:

```python
SCENARIOS = {
    "my_scenario": [
        "set Sumo__Plant__OxidationDitch__param__V 15000",
        "set Sumo__Plant__WAS_Pump__param__Q 400",
    ],
}
```

Variable names can be found in:
- SUMO GUI → Advanced → Core Window (list of all variables)
- The exported `state.xml` file (search for `param`)

---

## Law 48/1982 Limits (configured in CONFIG)

| Parameter | Limit |
|---|---|
| TSS | 50 mg/L |
| BOD₅ | 60 mg/L |
| COD | 80 mg/L |

Modify `law48_limits` in `CONFIG` to adjust these values.

---

## Troubleshooting

**`dynamita` import fails:** Ensure the `dynamita` folder is next to `server.py` or
in your Python path. Check the DTT addon was installed correctly.

**License error:** Keep `ds.sumo.setLogDetails(6)` in the code to see full DTT feedback.
Make sure your `dynaMIC` license includes the DTT sub-type.

**Empty results:** Confirm the project was compiled in the SUMO GUI before extracting the DLL.
The DLL must match the current version of your model.

**Variable not found:** Use the SUMO Core Window to verify exact variable name spelling.
Names are case-sensitive and use double-underscore separators.
