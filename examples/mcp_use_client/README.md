# Example: Driving sumo24-mcp with mcp-use

This example uses [mcp-use](https://github.com/mcp-use/mcp-use) — a Python/TypeScript
framework for building MCP clients — to connect directly to `server.py` and call
its tools, without going through Claude Desktop.

It's useful for:
- Smoke-testing the server after changes, without an LLM in the loop
- A starting point for building your own agent (mcp-use also supports wiring
  an LLM via `MCPAgent` — see the [mcp-use docs](https://github.com/mcp-use/mcp-use))

## Setup

```bash
pip install -r examples/mcp_use_client/requirements.txt
pip install -r requirements.txt   # the sumo24-mcp server's own dependency (mcp)
```

## Run

```bash
python examples/mcp_use_client/demo_client.py
```

This spawns `server.py` over stdio, lists all available tools, and calls
`list_scenarios` as a demo — a read-only tool that works even without a
compiled model or DTT license, so it runs out of the box. Tools that touch
the SUMO model (`run_steady_state`, `run_dynamic_simulation`, etc.) require
SUMO24 + DTT and a model in place — see the main [README](../../README.md).
