"""MCP server: lets Claude (or any MCP client) drive Animatica directly with batched tools.

Run:  ``animatica-mcp``  or  ``python -m animatica.mcp.server`` (stdio transport).
Claude Desktop / Claude Code config::

    {"mcpServers": {"animatica": {"command": "python", "args": ["-m", "animatica.mcp.server"]}}}

Tools are deliberately coarse (one call = one batch): run_batch, query_scene, render_preview,
open_project, save_scene, protocol_schema, start_film, continue_project, revise_project, project_log.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from ..core.engine import BlenderSession
from ..core.protocol import OP_NAMES, BatchValidationError, batch_json_schema

INSTRUCTIONS = """Animatica drives a headless Blender through a *batched* operation protocol.
Send many ops per run_batch call (3–300+), with stable ids you choose. Units: metres, degrees, #RRGGBB.
Characters face -Y at rest; Z is up. Use render_preview to look at your work (one low-res still).
For whole films use start_film; for artist hand-offs use continue_project / revise_project."""

server = MCPServer(name="animatica", instructions=INSTRUCTIONS, version="0.1.0")
_state: dict[str, Any] = {"session": None, "workdir": Path(os.environ.get("ANIMATICA_MCP_WORKDIR", "output/mcp"))}


def _session() -> BlenderSession:
    if _state["session"] is None:
        _state["workdir"].mkdir(parents=True, exist_ok=True)
        _state["session"] = BlenderSession(workdir=_state["workdir"])
    return _state["session"]


def _batch(ops: list[dict[str, Any]], intent: str = "", batch_id: str | None = None, **kw: Any) -> dict[str, Any]:
    s = _session()
    _state["n"] = _state.get("n", 0) + 1
    try:
        res = s.run_batch({"batch_id": batch_id or f"mcp-{_state['n']:04d}", "agent": "mcp", "intent": intent, "ops": ops, **kw})
    except BatchValidationError as e:
        return {"ok": False, "errors": e.errors}
    return res.model_dump(exclude_defaults=True)


@server.tool(description="Execute one batch of protocol ops (validated as a whole, one undo step). "
                         "ops: list of {op: ..., ...}; see protocol_schema. Returns a compact result.")
def run_batch(ops: list[dict[str, Any]], intent: str = "", preview: bool = False, mode: str = "ops",
              script: str | None = None) -> dict[str, Any]:
    kw: dict[str, Any] = {"mode": mode}
    if script:
        kw["script"] = script
    if preview:
        kw["verify"] = {"preview": True, "camera": "auto"}
    return _batch(ops, intent, **kw)


@server.tool(description="Compact, filtered scene query. fields: type, transform, bbox, material, parent, shape_keys, animation, tags")
def query_scene(ids: list[str] | None = None, types: list[str] | None = None,
                fields: list[str] | None = None, limit: int = 200) -> dict[str, Any]:
    op: dict[str, Any] = {"op": "query", "fields": fields or ["type", "transform"], "limit": limit}
    if ids:
        op["ids"] = ids
    if types:
        op["types"] = types
    return _batch([op], "query")


@server.tool(description="Render one low-res still (Workbench by default). Returns the PNG path and exposure stats.")
def render_preview(camera: str = "auto", frame: int | None = None, engine: str = "workbench",
                   width: int = 480, height: int = 270) -> dict[str, Any]:
    op: dict[str, Any] = {"op": "render_preview", "camera": camera, "engine": engine, "resolution": [width, height]}
    if frame is not None:
        op["frame"] = frame
    return _batch([op], "preview")


@server.tool(description="Open an existing .blend (e.g. output/<project>/scene.blend) in the MCP session, or a new empty scene if path is empty.")
def open_project(path: str = "") -> dict[str, Any]:
    s = _session()
    if path:
        s.open(path)
    else:
        s.new_scene()
    return {"ok": True, "objects": len(s.known_ids)}


@server.tool(description="Save the MCP session's scene to a .blend path.")
def save_scene(path: str) -> dict[str, Any]:
    return _batch([{"op": "save", "path": path}], "save")


@server.tool(description="The batch JSON Schema and the list of op names.")
def protocol_schema(full: bool = False) -> dict[str, Any]:
    return {"ops": OP_NAMES, "schema": batch_json_schema() if full else "pass full=true for the JSON Schema"}


@server.tool(description="Make a whole short film from a prompt (Director→…→Editor). quality: ci|preview|draft|final. "
                         "Long-running for draft/final.")
def start_film(prompt: str, name: str | None = None, quality: str = "preview", out: str = "output") -> dict[str, Any]:
    from ..core.orchestrator import Studio

    st = Studio("auto", {"quality": quality}, echo=False).film(prompt, out, name)
    return {"project": str(st.root), "blend": str(st.blend), "video": st.artifacts.get("final"),
            "log": str(st.root / "log" / "index.html")}


@server.tool(description="Continue a project after hand edits in Blender; edited aspects are locked and preserved.")
def continue_project(project: str, quality: str = "preview") -> dict[str, Any]:
    from ..core.continuation import continue_project as cont

    st = cont(project, options={"quality": quality})
    return {"locked": st.locked, "video": st.artifacts.get("final")}


@server.tool(description="Targeted revision, e.g. 'make the robot blue and slow down shot 2'.")
def revise_project(project: str, instruction: str, quality: str = "preview") -> dict[str, Any]:
    from ..core.continuation import revise_project as rev

    st = rev(project, instruction, options={"quality": quality})
    return {"plan_shots": [s.model_dump() for s in st.plan.shots] if st.plan else [], "video": st.artifacts.get("final")}


@server.tool(description="Last N production-log events of a project (compact).")
def project_log(project: str, last: int = 30) -> list[dict[str, Any]]:
    from ..core.log import read_log

    return [{k: e.get(k) for k in ("t", "agent", "kind", "message")} for e in read_log(Path(project))[-last:]]


def main() -> None:
    try:
        server.run("stdio")
    finally:
        if _state["session"] is not None:
            _state["session"].close()


if __name__ == "__main__":
    main()
