"""Real loopback HTTP plus subprocess stdio MCP. No Google, Telegram or AWS calls."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters, stdio_client

from fareflare.cli import main


def test_stdio_mcp_to_running_api(tmp_path, flight_url):
    config = tmp_path / "config.json"
    main(["--config", str(config), "init"])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    root = Path(__file__).parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(root / "src"),
        "FAREFLARE_API_URL": f"http://127.0.0.1:{port}",
    }
    env.pop("FAREFLARE_API_KEY", None)
    command = [sys.executable, "-m", "fareflare.cli", "--config", str(config)]
    process = subprocess.Popen(
        [*command, "serve", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert process.poll() is None, "Local API exited during startup"
            time.sleep(0.05)
        else:
            raise AssertionError("Local API did not become ready")

        async def exercise():
            parameters = StdioServerParameters(
                command=sys.executable, args=[*command[1:], "mcp"], env=env
            )
            async with (
                stdio_client(parameters) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                assert "create_monitor" in {tool.name for tool in tools.tools}
                result = await session.call_tool(
                    "create_monitor",
                    {"url": flight_url, "idempotency_key": "stdio-integration"},
                )
                data = result.model_dump(by_alias=True)
                assert not data.get("isError", False)
                assert "pending" in json.dumps(data)
                listing = await session.call_tool("list_monitors", {})
                assert "414" in json.dumps(listing.model_dump(by_alias=True))

        asyncio.run(exercise())
    finally:
        process.terminate()
        process.wait(timeout=5)
