# Install SUMO24 MCP with DynaSand

## Windows setup

Install Python 3.11 or later and a licensed SUMO24 installation first. DTT licensing is required for native simulations. The server package includes DynaSand's specification, process workbook, palette group and icon; it does not redistribute SUMO executables, model-base workbooks, compiled model DLLs, private plant projects, or licenses.

From this directory:

```powershell
.\install.ps1
```

Setup creates a local `.venv`, installs the server with GUI/report/Excel dependencies, validates the native scheduler version and an actual MCP initialization/list-tools exchange, and installs DynaSand. It writes the `sumo24` entry in Claude Desktop's `mcpServers` configuration and preserves other entries. Existing malformed configuration files are not overwritten.

To specify locations:

```powershell
.\install.ps1 -SumoDir 'D:\SUMO24' -ProjectDir 'C:\Models\ExtractedPlant' -ConfigPath 'C:\MyClient\mcp.json'
```

`-ProjectDir` is optional and must contain `sumoproject.dll` and `state.xml`. Without it, setup succeeds for authoring/offline use, but you must configure a model before simulating. SUMO's installation directory and your plant-project directory serve different purposes.

`-ConfigPath` supports clients using the `mcpServers` JSON format. Client-specific formats such as OpenCode JSONC need a corresponding client-side registration using the command/arguments/environment from the generated configuration; do not point this option at an incompatible format.

The default setup detects the SUMO installation from `SUMO_INSTALL_DIR`, the Windows registry, then common locations. You can provide the folder containing `Sumo24.exe` and `sumoscheduler.dll`, or a `Process code` / `Dir\My Process Code` directory inside that installation. An invalid explicit directory is not silently replaced by another installation.

If installation fails, the interactive setup reports the error, asks **“Enter your SUMO files directory …”**, and retries with your answer. Enter cancels. `-NonInteractive` returns an error instead of waiting for input. Python/pip bootstrap failures identify the missing prerequisite; a SUMO directory cannot repair an unavailable Python interpreter or a failed dependency download.

For an already provisioned Python environment, `-SkipDependencies -PythonExe 'C:\path\python.exe'` runs the same unit installation and verification steps without pip.

## Wheel installation

```powershell
python -m pip install 'sumo24_mcp-0.2.0-py3-none-any.whl[gui,reports,excel]'
sumo24-mcp-install
```

**Run both commands.** Pip installs the server and bundled assets; `sumo24-mcp-install` deploys the unit to the selected SUMO installation and registers the client. Installing a wheel alone cannot choose your SUMO installation or client configuration. `sumo24-mcp` starts the stdio server.

## DynaSand in SUMO

Restart SUMO after setup. In **Configure → Process unit list**, expand **SUMO24 MCP units**, then choose **DynaSand**. Setup installs into:

```text
<SUMO installation>\Dir\My Process Code\Process Units\SUMO24 MCP units\DynaSand\
    DynaSand Group Info.xlsx
    HH_DynaSand_v1.xlsx
    HH_DynaSand_v1.emf
```

The internal `HH_DynaSand_v1` class name is retained for existing-model compatibility. The GUI category/family are no longer HH. The icon artwork still contains the internal class label.

Known previously shipped DynaSand files in the HH category are migrated, with backups retained under the installation data directory. Edited or unrecognized conflicting units are refused, not deleted. Shared HH groups containing other units are preserved. Rerunning setup verifies asset hashes and preserves ownership records. Vendor `Process code` files are never overwritten.

For an isolated removal demonstration, connect inlet to `inp`, filtrate to a product outlet, and `wash` to a separate reject outlet. Recycling all wash directly to the unit inlet produces no net steady-state removal across that closed boundary. Select alum **or** ferric dosing; simultaneous positive doses are rejected by MCP scheduling preflight. GUI-only model execution remains governed by the workbook's conflict diagnostic, so follow the same single-coagulant rule in SUMO itself.

## Native process compatibility

SUMO24 starts native worker processes using Windows process breakaway. Some MCP clients put the server in a Job Object that forbids this; the Python MCP SDK 1.27.1 default stdio launcher is one measured example. Native simulation now returns an explanatory MCP error before launching, and offline tools remain usable. The server does not alter the client's process policy.

Use a client/launcher configured to permit SUMO worker processes. A client author using Windows Job Objects must explicitly support `JOB_OBJECT_LIMIT_BREAKAWAY_OK` (and manage native-job cleanup). The live integration harness exercises both a compatible client and the refusal path. Changing your SUMO directory does not fix this policy restriction. Installation checks loading and discovery, not every possible client's process policy.

## Recovery and development

Installation stages files, records ownership hashes, preserves replaced bytes, and rolls back failures, including manifest/config commit failures. Cross-drive installations are supported. A crash or incomplete rollback retains a recovery journal and blocks further mutation until inspected; do not delete recovery directories without checking their contents.

Portable regression tests:

```powershell
python -m unittest discover -s tests -v
```

The maintainer release workflow is `PY/tools/build_dynasand_release.py prepare`, `build`, then `validate`. It recompiles and runs native positive/zero-flow checks before writing the source-release digest manifest. This is a development/release operation, not a step end users must perform.
