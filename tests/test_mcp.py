"""Milestone 6: the MCP server starts and its tools work (in-process client and real stdio)."""

import asyncio
import json
import sys

import pytest

mcp = pytest.importorskip("mcp")
pytestmark = pytest.mark.blender


def _text(result):
    return json.loads(result.content[0].text)


def test_mcp_tools_in_process(tmp_path, monkeypatch):
    from animatica.mcp import server as srv

    monkeypatch.setitem(srv._state, "workdir", tmp_path)

    async def go():
        async with mcp.Client(srv.server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"run_batch", "query_scene", "render_preview", "start_film", "continue_project", "revise_project"} <= names
            r = _text(await c.call_tool("run_batch", {"ops": [
                {"op": "create_primitive", "id": "box", "shape": "cube", "location": [0, 0, 0.5]},
                {"op": "add_camera", "id": "cam", "location": [3, -3, 2], "look_at": "box"}], "intent": "test"}))
            assert r["ok"] and set(r["created"]) == {"box", "cam"}
            bad = _text(await c.call_tool("run_batch", {"ops": [{"op": "transform", "target": "ghost", "location": [0, 0, 0]}]}))
            assert bad["ok"] is False and "unknown id" in bad["errors"][0]
            q = _text(await c.call_tool("query_scene", {"ids": ["box"], "fields": ["bbox"]}))
            assert q["data"]["objects"]["box"]["bbox"][0][2] == 0.0
            pv = _text(await c.call_tool("render_preview", {"camera": "cam"}))
            assert pv["preview"].endswith(".png")
    try:
        asyncio.run(go())
    finally:
        if srv._state["session"] is not None:
            srv._state["session"].close()
            srv._state["session"] = None


def test_mcp_stdio_server_starts(tmp_path):
    from mcp import StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=["-m", "animatica.mcp.server"],
                                   env={"ANIMATICA_MCP_WORKDIR": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin"})

    async def go():
        async with mcp.Client(params) as c:
            tools = (await c.list_tools()).tools
            assert any(t.name == "protocol_schema" for t in tools)
            r = _text(await c.call_tool("protocol_schema", {}))
            assert "insert_keyframes" in r["ops"]
    asyncio.run(go())
