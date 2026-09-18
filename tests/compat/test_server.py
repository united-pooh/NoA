from __future__ import annotations

import sys
from importlib.metadata import entry_points
from typing import cast

import anyio
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def test_compatibility_ping_returns_structured_result() -> None:
    from noa.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("compatibility_ping", {"value": "ready"})

    assert result.structured_content == {"status": "pass", "value": "ready"}
    assert result.is_error is False


async def test_compatibility_tools_have_descriptions() -> None:
    from noa.server import mcp

    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    expected_tools = {"compatibility_ping", "compatibility_runtime"}
    assert expected_tools.issubset(tools)
    assert all(tools[name].description for name in expected_tools)


async def test_compatibility_runtime_matches_direct_runtime_checks() -> None:
    from noa.compat.runtime import build_runtime_checks
    from noa.server import mcp

    expected = [check.model_dump(mode="json") for check in build_runtime_checks()]

    async with Client(mcp) as client:
        result = await client.call_tool("compatibility_runtime")

    runtime_checks = cast(list[dict[str, object]], result.data)
    assert runtime_checks == expected
    assert {"python", "fastmcp-stability"} <= {str(check["name"]) for check in runtime_checks}


async def test_python_module_serves_tools_over_stdio() -> None:
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "noa"],
        keep_alive=False,
    )

    with anyio.fail_after(10):
        async with Client(transport, init_timeout=5, timeout=5) as client:
            result = await client.call_tool("compatibility_ping")

    assert result.structured_content == {"status": "pass", "value": "pong"}
    assert result.is_error is False


def test_console_script_points_to_server_run() -> None:
    noa_entries = [
        entry_point.value
        for entry_point in entry_points(group="console_scripts")
        if entry_point.name == "noa"
    ]

    assert noa_entries == ["noa.server:run"]
