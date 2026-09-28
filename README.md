# SUMO24 MCP

MCP tools for SUMO24 models, simulation, analysis, and custom treatment units. The supported installation workflow includes **DynaSand**, available in SUMO's Configuration tab under **SUMO24 MCP units → DynaSand**.

On Windows with Python 3.11+ and SUMO24 installed:

```powershell
.\install.ps1
```

The installer finds SUMO, installs dependencies into `.venv`, validates native loading and MCP startup, installs DynaSand, and registers the server. If SUMO cannot be found or setup fails, it asks for your SUMO files directory and retries. Restart SUMO and your MCP client after setup.

See [installation and recovery](INSTALLATION.md), [runtime behavior](docs/runtime.md), and [implementation/test results](docs/reviews/2026-09-08-implementation-results.md).
