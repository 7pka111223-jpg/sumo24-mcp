"""Standalone demo: drive the sumo24 MCP server with the mcp-use client library.

This connects directly to server.py over stdio and calls tools without an LLM
in the loop, useful for smoke-testing the server or as a template for building
an mcp-use-based agent on top of it.

Usage:
    pip install -r examples/mcp_use_client/requirements.txt
    python examples/mcp_use_client/demo_client.py
"""

import asyncio
import sys
from pathlib import Path

from mcp_use import MCPClient

REPO_ROOT = Path(__file__).resolve().parents[2]


async def main() -> None:
    config = {
        "mcpServers": {
            "sumo24": {
                "command": sys.executable,
                "args": [str(REPO_ROOT / "server.py")],
            }
        }
    }

    client = MCPClient.from_dict(config)
    await client.create_all_sessions()

    try:
        session = client.get_session("sumo24")

        tools = await session.list_tools()
        print(f"Discovered {len(tools)} tool(s) on the sumo24 server:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")

        print("\nCalling list_scenarios (no model/DTT license required)...")
        result = await session.call_tool(name="list_scenarios", arguments={})
        print(result.content[0].text)
    finally:
        await client.close_all_sessions()


if __name__ == "__main__":
    asyncio.run(main())
