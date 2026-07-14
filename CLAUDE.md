# SUMO24 MCP Server

Python MCP server exposing the SUMO24 Digital Twin Toolkit (DTT) API as tools
for Claude: run WWTP simulations, compare scenarios, check compliance, analyse
mass balances. Windows-oriented (SUMO24 + DTT addon + license required for real
runs); offline/extract paths work without a license.

## Layout
- `server.py` — MCP server entry point (stdio); all tool definitions live here
- `lib/` — engine code: `sumo_native.py`, `sumo_offline.py`, `sumo_compiler.py`,
  `schematic_parser.py`, `html_schematic_io.py`, `academic_bundle.py`, `lib/pipeline/`
- `docs/` — per-tool-group reference docs (keep in sync when adding/changing tools)
- `examples/mcp_use_client/` — standalone client (mcp-use) to smoke-test the
  server without Claude Desktop or an LLM
- `tests/smoke_test_offline_extract.py` — offline smoke test (no SUMO license needed)
- `install.ps1` / `diagnose.ps1` — Windows setup and diagnostics

## Commands
- `pip install -r requirements.txt`
- `python tests/smoke_test_offline_extract.py` — offline smoke test
- `python examples/mcp_use_client/demo_client.py` — end-to-end stdio check
  (discovers tools, calls read-only `list_scenarios`)

## Rules
- The DTT Python API is copied from the user's SUMO install and is NOT in the
  repo; never assume it is importable in CI/sandboxes — guard with the offline
  code paths in `lib/sumo_offline.py`.
- New tools: keep them read-only-safe by default, document them in the matching
  `docs/SUMO24_MCP_*.md` file, and add them to the README project structure.
- Prefer the smoke test + demo client for verification; full simulations only
  run on a licensed Windows machine.
