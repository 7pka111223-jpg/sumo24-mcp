"""Actual stdio discovery contract used by setup; no model simulation."""
import asyncio
import json
import os
from pathlib import Path
import sys


async def check():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("server.py"))], env=dict(os.environ))
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            init = await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            required = {"run_dynamic_simulation", "run_steady_state", "hh_install_process_unit"}
            if not required <= names:
                raise RuntimeError(f"Required tools missing: {required - names}")
            print(json.dumps({"server": init.serverInfo.name, "tools": len(names)}))


if __name__ == "__main__":
    asyncio.run(check())
