# SUMO24 MCP — Windows setup

The short version: open **PowerShell** in this folder (`F:\UNI\SUMO\MCP`) and run

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Then fully quit Claude Desktop (right-click the system-tray icon → **Quit**) and
re-open it. `sumo24` should now appear in the tools panel.

If it doesn't, run the diagnostic:

```powershell
powershell -ExecutionPolicy Bypass -File .\diagnose.ps1
```

---

## Why the install failed before

`claude_desktop_config.json` was using `"command": "python"`, which on Windows breaks in three common ways:

1. **Python isn't on PATH** for the user account Claude Desktop runs as — the process silently fails to spawn.
2. **The Microsoft Store `python` stub** is first on PATH, which opens the Store instead of running Python.
3. **`mcp` was installed for a different Python** than the one that actually runs.

`install.ps1` avoids all three by:
- finding a real Python (`py -3` first, then `python`, then known install paths, rejecting the Store stub),
- installing `mcp` into **that specific** Python via `-m pip install mcp`,
- writing the config with the **absolute path** to `python.exe` so Claude Desktop never has to resolve `python` itself.

It also sets `PYTHONPATH` to the project root so `import dynamita` resolves from `MCP\dynamita\`.

---

## Where things live

| File | Location | Purpose |
|---|---|---|
| Server code | `F:\UNI\SUMO\MCP\PY\server.py` | MCP server entry point |
| Project DLL | `F:\UNI\SUMO\MCP\sumoproject.dll` | Extracted from `Verified BOD.sumo` |
| Saved state | `F:\UNI\SUMO\MCP\state.xml` | Steady-state snapshot from SUMO GUI |
| DTT API | `F:\UNI\SUMO\MCP\dynamita\` | Copied from `C:\Program Files\Dynamita\SUMO24\PythonAPI\dynamita\` |
| Outputs | `F:\UNI\SUMO\MCP\outputs\` | CSV results written by the server |
| Claude config | `%APPDATA%\Claude\claude_desktop_config.json` | Where `install.ps1` writes the `sumo24` entry |
| Claude MCP logs | `%APPDATA%\Claude\logs\mcp-server-sumo24*.log` | First place to look when something breaks |

---

## Manual install (if you can't run the script)

1. **Install Python 3.10+** from <https://www.python.org/downloads/>.
   During install, tick **Add python.exe to PATH** and **Install launcher for all users**.

2. In PowerShell, install the MCP package:
   ```powershell
   py -3 -m pip install --upgrade mcp
   ```

3. Create the Claude config folder if it doesn't exist:
   ```powershell
   mkdir "$env:APPDATA\Claude" -Force
   ```

4. Write the config file. Open `%APPDATA%\Claude\claude_desktop_config.json`
   in Notepad and paste:
   ```json
   {
     "mcpServers": {
       "sumo24": {
         "command": "py",
         "args": ["-3", "F:/UNI/SUMO/MCP/PY/server.py"],
         "env": {
           "SUMO_DLL":    "F:/UNI/SUMO/MCP/sumoproject.dll",
           "SUMO_STATE":  "F:/UNI/SUMO/MCP/state.xml",
           "SUMO_OUTPUT": "F:/UNI/SUMO/MCP/outputs",
           "PYTHONPATH":  "F:/UNI/SUMO/MCP"
         }
       }
     }
   }
   ```
   Forward slashes are fine and avoid JSON-escaping issues on Windows.

5. Right-click the Claude tray icon → **Quit**, then relaunch Claude Desktop.

---

## Checklist when `sumo24` still doesn't show up

Run `diagnose.ps1` first — it checks each of the below automatically.

- Is there a `sumo24` entry under `mcpServers` in `%APPDATA%\Claude\claude_desktop_config.json`?
- Does the JSON parse? Paste it into <https://jsonlint.com> to confirm.
- Did you **quit** Claude Desktop through the tray icon, not just close the window? The tray process must restart for config changes to take effect.
- Run in a terminal: `py -3 F:\UNI\SUMO\MCP\PY\server.py` — the process should sit there silently reading stdin. If it prints an error and exits, that's your problem.
- Check `%APPDATA%\Claude\logs\` for files starting with `mcp-server-sumo24`. The last few lines usually say exactly what went wrong.

---

## After it works

Once `sumo24` is in the tools panel you can ask Claude things like:

> "Run a steady-state simulation and check Law 48 compliance."

The tools available are listed in `README.md` (`run_steady_state`,
`run_dynamic_simulation`, `run_scenario_comparison`, `list_scenarios`,
`set_parameter`, `get_job_status`, `check_compliance`, `export_results_csv`).

The scenario and variable names in `server.py` are **generic placeholders**
(Qaha WWTP template). Edit the `SCENARIOS` dict and the `EFFLUENT_VARS` list
in `PY\server.py` so they match the variable names your compiled model
actually exposes — you can find the real names in SUMO GUI → **Advanced →
Core Window**, or by grep-ing `state.xml` for `param`.
