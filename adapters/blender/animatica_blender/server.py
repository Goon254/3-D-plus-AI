# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON-RPC-ish server for the Blender adapter.

Transports:
  * ``--stdio``  : newline-delimited JSON on stdin/stdout (headless subprocess; default)
  * ``--tcp PORT``: same messages over a local TCP socket (blocking loop; the live add-on uses a timer)

Request:  {"id": 1, "method": "run_batch", "params": {"batch": {...}}}
Response: {"id": 1, "result": {...}}  or  {"id": 1, "error": "message"}

Methods: ping, new_scene, open, run_batch, undo, shutdown.
Run with:  python -m animatica_blender.server --stdio   (needs `import bpy`)
      or:  blender -b --python-expr "import animatica_blender.server as s; s.main()" -- --stdio
"""

from __future__ import annotations

import json
import os
import socket
import sys

import bpy

from .executor import Executor

VERSION = "0.1"


class Handler:
    def __init__(self, workdir: str | None = None):
        self.ex = Executor(workdir)
        self.running = True

    def handle(self, msg: dict) -> dict:
        mid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        try:
            if method == "ping":
                result = {"pong": True, "blender": bpy.app.version_string, "adapter": VERSION}
            elif method == "new_scene":
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.ex.ensure_scene()
                if params.get("workdir"):
                    self.ex.workdir = params["workdir"]
                result = {"ok": True}
            elif method == "open":
                bpy.ops.wm.open_mainfile(filepath=params["path"])
                if params.get("workdir"):
                    self.ex.workdir = params["workdir"]
                result = {"ok": True, "objects": len(bpy.data.objects)}
            elif method == "run_batch":
                result = self.ex.run_batch(params["batch"])
            elif method == "undo":
                result = {"ok": self.ex.undo(params.get("token", ""))}
            elif method == "ids":
                result = {"ids": sorted(self.ex.ids())}
            elif method == "shutdown":
                self.running = False
                result = {"ok": True}
            else:
                return {"id": mid, "error": f"unknown method {method!r}"}
            return {"id": mid, "result": result}
        except Exception as e:  # noqa: BLE001
            return {"id": mid, "error": f"{type(e).__name__}: {e}"}


def serve_stdio(handler: Handler) -> None:
    # Blender writes logs to stdout; keep the protocol channel clean by moving it to a private fd.
    proto = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    proto.write(json.dumps({"ready": True, "blender": bpy.app.version_string}) + "\n")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            proto.write(json.dumps({"id": None, "error": f"bad json: {e}"}) + "\n")
            continue
        proto.write(json.dumps(handler.handle(msg)) + "\n")
        if not handler.running:
            break


def serve_tcp(handler: Handler, port: int, host: str = "127.0.0.1") -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    print(json.dumps({"ready": True, "port": srv.getsockname()[1]}), flush=True)
    while handler.running:
        conn, _ = srv.accept()
        with conn, conn.makefile("rw", buffering=1) as f:
            for line in f:
                if not line.strip():
                    continue
                f.write(json.dumps(handler.handle(json.loads(line))) + "\n")
                f.flush()
                if not handler.running:
                    break
    srv.close()


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    workdir = None
    if "--workdir" in argv:
        workdir = argv[argv.index("--workdir") + 1]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    handler = Handler(workdir)
    if "--tcp" in argv:
        serve_tcp(handler, int(argv[argv.index("--tcp") + 1]))
    else:
        serve_stdio(handler)


if __name__ == "__main__":
    main()
