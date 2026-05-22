# Example: Qaha WWTP Model

This folder contains the compiled model files for the **Qaha Wastewater Treatment Plant** — a real Egyptian WWTP used as the development and reference model for this MCP server.

It is provided so you can run the server with a working model immediately, without needing to extract your own `.sumo` file first.

## Files

| File | Description |
|---|---|
| `sumoproject.dll` | Compiled SUMO model (extracted from `Verified BOD.sumo`) |
| `state.xml` | Saved steady-state snapshot (maptoic initialised) |

## How to use this example

Copy both files to the **repo root**:

```powershell
# From the repo root
Copy-Item examples\qaha-wwtp\sumoproject.dll .\sumoproject.dll
Copy-Item examples\qaha-wwtp\state.xml       .\state.xml
```

Then run `install.ps1` and restart Claude Desktop. The server will load the Qaha model automatically.

## Replacing with your own model

Once you've confirmed the server works with the Qaha example, replace the root `sumoproject.dll` and `state.xml` with your own model's files. See the main [README](../../README.md#using-a-different-model) for instructions.

## About the Qaha plant

The Qaha WWTP is located in Qalyubia Governorate, Egypt, and discharges to an agricultural drain subject to Egyptian Law 48/1982 effluent limits. The model was built in SUMO24 using ASM2d kinetics and calibrated against plant monitoring data.
