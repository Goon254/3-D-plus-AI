# SPDX-License-Identifier: GPL-3.0-or-later
"""Executes Animatica batches inside Blender (bpy).

Receives plain-JSON batches (already validated by the core, re-checked lightly here), applies all
ops as one transaction, rolls back on any error, and returns a compact result dict.

Rollback strategy: headless Blender has no reliable undo stack, so before each mutating batch we
write a snapshot .blend (``undo_token``) and restore it on failure. In the live add-on, the same
snapshot mechanism is used so behaviour is identical.
"""

from __future__ import annotations

import builtins
import math
import os
import signal
import sys
import tempfile
import time
import traceback
from typing import Any

import bpy
import mathutils

from .common import ID_PROP, TAGS_PROP, OpError, fast_cycles, rad, workbench_setup  # noqa: F401  (re-exported for scripts)
from .ops_anim import AnimOps
from .ops_material import MaterialOps
from .ops_render import RenderOps
from .ops_scene import SceneOps

READ_ONLY_OPS = {"query", "inspect", "render_preview", "render_final", "save"}


class Executor(SceneOps, MaterialOps, AnimOps, RenderOps):
    def __init__(self, workdir: str | None = None):
        self.workdir = workdir or tempfile.mkdtemp(prefix="animatica_")
        self._undo_counter = 0
        self.ensure_scene()

    # ------------------------------------------------------------------ scene helpers
    def ensure_scene(self) -> None:
        scene = bpy.context.scene
        if "animatica_project" not in scene:
            scene["animatica_project"] = True

    @property
    def scene(self):
        return bpy.context.scene

    def obj(self, oid: str):
        o = bpy.data.objects.get(oid)
        if o is not None:
            return o
        for cand in bpy.data.objects:  # artist may have renamed it; identity lives in the custom prop
            if cand.get(ID_PROP) == oid:
                return cand
        raise OpError(f"unknown id {oid!r}")

    def ids(self) -> set[str]:
        return {o.get(ID_PROP, o.name) for o in bpy.data.objects}

    def _link(self, o, collection: str | None):
        coll = self.scene.collection
        if collection:
            coll = bpy.data.collections.get(collection)
            if coll is None:
                coll = bpy.data.collections.new(collection)
                self.scene.collection.children.link(coll)
        coll.objects.link(o)

    def _new_object(self, op: dict, data) -> Any:
        oid = op["id"]
        if bpy.data.objects.get(oid) is not None:
            raise OpError(f"duplicate id {oid!r}")
        o = bpy.data.objects.new(oid, data)
        o[ID_PROP] = oid
        if op.get("tags"):
            o[TAGS_PROP] = ",".join(op["tags"])
        self._link(o, op.get("collection"))
        if op.get("parent"):
            o.parent = self.obj(op["parent"])
        o.location = op.get("location", (0, 0, 0))
        o.rotation_euler = rad(op.get("rotation", (0, 0, 0)))
        o.scale = op.get("scale", (1, 1, 1))
        return o

    # ------------------------------------------------------------------ batch entry
    def run_batch(self, batch: dict) -> dict:
        t0 = time.time()
        res: dict[str, Any] = {
            "batch_id": batch.get("batch_id", "?"),
            "ok": True,
            "created": [],
            "modified": [],
            "deleted": [],
            "warnings": [],
            "errors": [],
            "preview": None,
            "undo_token": None,
            "data": {},
        }
        ops = batch.get("ops", [])
        mutating = batch.get("mode") == "script" or any(o.get("op") not in READ_ONLY_OPS for o in ops)
        snapshot = None
        if mutating:
            snapshot = self._snapshot()
            res["undo_token"] = snapshot
        try:
            if batch.get("mode") == "script":
                self._run_script(batch.get("script") or "", float(batch.get("script_timeout_s", 30)), res)
            for i, op in enumerate(ops):
                try:
                    handler = getattr(self, "op_" + op["op"])
                except AttributeError:
                    raise OpError(f"unsupported op {op['op']!r}") from None
                try:
                    handler(op, res)
                except OpError as e:
                    raise OpError(f"ops[{i}]({op['op']}): {e}") from None
                except Exception as e:  # noqa: BLE001
                    raise OpError(f"ops[{i}]({op['op']}): {type(e).__name__}: {e}") from None
            verify = batch.get("verify") or {}
            if verify.get("preview"):
                path = os.path.join(self.workdir, "previews", f"{res['batch_id']}.png")
                self.op_render_preview(
                    {
                        "path": path,
                        "camera": verify.get("camera", "auto"),
                        "resolution": verify.get("resolution", (480, 270)),
                        "frame": verify.get("frame"),
                    },
                    res,
                )
        except Exception as e:  # noqa: BLE001
            res["ok"] = False
            res["errors"].append(str(e))
            if os.environ.get("ANIMATICA_DEBUG"):
                res["errors"].append(traceback.format_exc()[-1500:])
            if snapshot:
                self._restore(snapshot)
            res["created"], res["modified"], res["deleted"] = [], [], []
        res["elapsed_ms"] = int((time.time() - t0) * 1000)
        for k in ("created", "modified", "deleted"):
            res[k] = list(dict.fromkeys(res[k]))
        return res

    def _snapshot(self) -> str:
        self._undo_counter += 1
        path = os.path.join(self.workdir, "undo", f"u-{self._undo_counter}.blend")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=False)
        return path

    def _restore(self, path: str) -> None:
        bpy.ops.wm.open_mainfile(filepath=path)

    def undo(self, token: str) -> bool:
        if token and os.path.exists(token):
            self._restore(token)
            return True
        return False

    # ------------------------------------------------------------------ script mode
    SAFE_MODULES = {"math", "random", "mathutils", "bmesh", "bpy", "itertools", "functools", "colorsys"}

    def _run_script(self, code: str, timeout: float, res: dict) -> None:
        before = self.ids()

        def safe_import(name, *args, **kwargs):
            if name.split(".")[0] not in self.SAFE_MODULES:
                raise ImportError(f"import of {name!r} not allowed in script mode")
            return builtins.__import__(name, *args, **kwargs)

        banned = {"open", "exec", "eval", "compile", "input", "breakpoint", "__import__", "exit", "quit"}
        safe_builtins = {
            k: getattr(builtins, k) for k in dir(builtins) if k not in banned and not k.startswith("_")
        }
        safe_builtins["__import__"] = safe_import
        safe_builtins["__build_class__"] = builtins.__build_class__
        ns = {
            "__builtins__": safe_builtins,
            "bpy": bpy,
            "mathutils": mathutils,
            "math": math,
            "ax": ScriptHelpers(self),
            "__name__": "animatica_script",
        }

        def on_timeout(signum, frame):
            raise TimeoutError(f"script exceeded {timeout}s")

        old = None
        if hasattr(signal, "SIGALRM"):
            try:
                old = signal.signal(signal.SIGALRM, on_timeout)
                signal.setitimer(signal.ITIMER_REAL, timeout)
            except ValueError:  # not main thread (live add-on)
                old = None
        traced = old is None  # Windows (no SIGALRM) or a worker thread: enforce the deadline by tracing
        if traced:
            deadline = time.monotonic() + timeout

            def tracer(frame, event, arg):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"script exceeded {timeout}s")
                # line events only inside the script itself (cheap for helper/library frames)
                return tracer if frame.f_code.co_filename == "<animatica-script>" else None

            sys.settrace(tracer)
        try:
            exec(compile(code, "<animatica-script>", "exec"), ns)  # noqa: S102 - sandboxed namespace
        finally:
            if traced:
                sys.settrace(None)
            if old is not None:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old)
        for o in bpy.data.objects:
            if ID_PROP not in o:
                o[ID_PROP] = o.name
        after = self.ids()
        res["created"].extend(sorted(after - before))
        res["deleted"].extend(sorted(before - after))


class ScriptHelpers:
    """Small helper API available as ``ax`` inside script-mode batches."""

    def __init__(self, ex: Executor):
        self._ex = ex

    def obj(self, oid: str):
        return self._ex.obj(oid)

    def run_ops(self, ops: list[dict]) -> dict:
        res = {"created": [], "modified": [], "deleted": [], "warnings": [], "errors": [], "data": {}}
        for op in ops:
            getattr(self._ex, "op_" + op["op"])(op, res)
        return res
