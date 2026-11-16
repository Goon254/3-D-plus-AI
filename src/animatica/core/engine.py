"""Engine client: talks to an engine adapter process (Blender) over newline-delimited JSON.

The core never imports bpy. The Blender adapter (GPL) runs as a separate process, either:
  * a Python interpreter that can ``import bpy`` (the PyPI ``bpy`` wheel) — default, or
  * a Blender binary in background mode (``blender -b --python-expr ...``), or
  * a running Blender with the live add-on (TCP, see :class:`LiveBlenderSession`).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from .protocol import Batch, BatchResult, validate_batch

REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTER_DIR = Path(os.environ.get("ANIMATICA_BLENDER_ADAPTER", REPO_ROOT / "adapters" / "blender"))


class EngineError(RuntimeError):
    pass


def _bpy_python() -> str | None:
    cand = os.environ.get("ANIMATICA_BLENDER_PYTHON") or sys.executable
    try:
        out = subprocess.run([cand, "-c", "import bpy"], capture_output=True, timeout=120)
        return cand if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def blender_command() -> list[str]:
    py = _bpy_python()
    if py:
        return [py, "-m", "animatica_blender.server", "--stdio"]
    blender = os.environ.get("ANIMATICA_BLENDER_BIN") or shutil.which("blender")
    if blender:
        return [
            blender,
            "-b",
            "--factory-startup",
            "--python-expr",
            f"import sys; sys.path.insert(0, {str(ADAPTER_DIR)!r}); import animatica_blender.server as s; s.main()",
            "--",
            "--stdio",
        ]
    raise EngineError(
        "Blender not found. Install the bpy wheel (`pip install bpy`, matching Python version) or set "
        "ANIMATICA_BLENDER_BIN to a Blender binary. See docs/SETUP.md."
    )


def blender_available() -> bool:
    try:
        blender_command()
        return True
    except EngineError:
        return False


_PROBE = (
    "import json, sys; sys.path.insert(0, sys.argv[1]); from animatica_blender import devices; "
    "found = devices.probe(); print(json.dumps({'gpus': found, 'auto': devices.choose_backend('auto', found)[0]}))"
)


def render_devices() -> dict | None:
    """GPUs Cycles can use and what ``--device auto`` resolves to, probed in the (GPL) adapter's
    interpreter so this process never imports bpy. ``None`` if only a Blender binary is available."""
    py = _bpy_python()
    if not py:
        return None
    try:
        out = subprocess.run(
            [py, "-c", _PROBE, str(ADAPTER_DIR)], capture_output=True, text=True, timeout=180
        )
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, IndexError):
        return None


class _Session:
    known_ids: set[str]

    def call(self, method: str, **params: Any) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def run_batch(self, batch: Batch | dict[str, Any], validate: bool = True) -> BatchResult:
        if validate:
            batch = validate_batch(batch, self.known_ids)
        elif isinstance(batch, dict):
            batch = Batch.model_validate(batch)
        raw = self.call("run_batch", batch=batch.model_dump(mode="json", exclude_none=True))
        result = BatchResult.model_validate(raw)
        if result.ok:
            self.known_ids |= set(result.created)
            self.known_ids -= set(result.deleted)
        return result

    def refresh_ids(self) -> set[str]:
        self.known_ids = set(self.call("ids")["ids"])
        return self.known_ids


class BlenderSession(_Session):
    """A persistent headless Blender process. One batch per round-trip."""

    def __init__(self, workdir: str | Path | None = None, timeout: float = 3600):
        self.timeout = timeout
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ADAPTER_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = blender_command()
        if workdir:
            cmd += ["--workdir", str(workdir)]
        self._log = open(os.devnull, "w") if not os.environ.get("ANIMATICA_DEBUG") else None
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            text=True,
            env=env,
            bufsize=1,
        )
        ready = self._readline()
        if not ready.get("ready"):
            raise EngineError(f"adapter failed to start: {ready}")
        self.blender_version = ready.get("blender")
        self._next = 0
        self._lock = threading.Lock()
        self.known_ids: set[str] = set()

    def _readline(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            raise EngineError(f"Blender adapter exited (code {self.proc.poll()})")
        return json.loads(line)

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        with self._lock:
            self._next += 1
            msg = {"id": self._next, "method": method, "params": params}
            assert self.proc.stdin is not None
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            reply = self._readline()
        if "error" in reply:
            raise EngineError(reply["error"])
        return reply["result"]

    def new_scene(self, workdir: str | Path | None = None) -> None:
        self.call("new_scene", workdir=str(workdir) if workdir else None)
        self.known_ids = set()

    def open(self, path: str | Path, workdir: str | Path | None = None) -> None:
        self.call("open", path=str(path), workdir=str(workdir) if workdir else None)
        self.refresh_ids()

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.call("shutdown")
            except (EngineError, BrokenPipeError, OSError):
                pass
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def __enter__(self) -> BlenderSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class LiveBlenderSession(_Session):
    """Connects to the live add-on inside a running Blender (same protocol over TCP)."""

    def __init__(self, port: int = 9876, host: str = "127.0.0.1"):
        self.sock = socket.create_connection((host, port), timeout=600)
        self.f = self.sock.makefile("rw", buffering=1)
        self._next = 0
        self.known_ids = set()
        self.refresh_ids()

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        self._next += 1
        self.f.write(json.dumps({"id": self._next, "method": method, "params": params}) + "\n")
        self.f.flush()
        reply = json.loads(self.f.readline())
        if "error" in reply:
            raise EngineError(reply["error"])
        return reply["result"]

    def close(self) -> None:
        self.sock.close()
