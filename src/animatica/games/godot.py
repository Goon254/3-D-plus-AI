"""Godot engine client: validates game batches and runs them through the GDScript runner (MIT adapter)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
ADDON = REPO_ROOT / "adapters" / "godot" / "addons" / "animatica"
CACHE = Path(os.environ.get("ANIMATICA_CACHE", Path.home() / ".cache" / "animatica"))
GODOT_OPS = {
    "load_scene",
    "create_node",
    "add_shape",
    "add_polygon",
    "attach_script",
    "set_property",
    "add_input_action",
    "save_scene",
}
ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class GodotError(RuntimeError):
    pass


def godot_bin() -> str | None:
    env = os.environ.get("ANIMATICA_GODOT_BIN")
    if env and Path(env).exists():
        return env
    for name in ("godot", "godot4"):
        if shutil.which(name):
            return shutil.which(name)
    found = sorted((CACHE / "godot").glob("Godot_v4*_linux.x86_64"))
    return str(found[-1]) if found else None


def validate_godot_batch(batch: dict[str, Any], existing: set[str] | None = None) -> list[str]:
    """Same semantics as the film protocol: whole-batch validation, precise errors, before execution."""
    errors: list[str] = []
    known = set(existing or set())
    has_root = bool(existing)
    for i, op in enumerate(batch.get("ops", [])):
        p = f"ops[{i}]({op.get('op')})"
        kind = op.get("op")
        if kind not in GODOT_OPS:
            errors.append(f"{p}: unsupported op")
            continue
        new_id = op.get("id") if kind in ("create_node", "add_polygon", "add_shape") else None
        if kind == "add_shape" and not new_id:
            new_id = f"{op.get('target')}_shape"
        if new_id:
            if not ID_RE.match(str(new_id)):
                errors.append(f"{p}: invalid id {new_id!r}")
            if new_id in known:
                errors.append(f"{p}: duplicate id {new_id!r}")
        parent = op.get("parent") if kind == "create_node" else op.get("target")
        if kind == "create_node" and parent is None:
            if has_root:
                errors.append(f"{p}: scene already has a root")
            has_root = True
        elif (
            kind in ("create_node", "add_shape", "add_polygon", "attach_script", "set_property")
            and parent not in known
        ):
            errors.append(f"{p}: unknown id {parent!r}")
        if kind == "load_scene":
            has_root = True
        if kind == "add_polygon" and len(op.get("points", [])) < 3:
            errors.append(f"{p}: polygon needs at least 3 points")
        if new_id:
            known.add(new_id)
    return errors


def run_batch(project: Path, batch: dict[str, Any], timeout: float = 120) -> dict[str, Any]:
    exe = godot_bin()
    if not exe:
        raise GodotError("Godot 4 not found: set ANIMATICA_GODOT_BIN or run scripts/setup_assets.sh --godot")
    errors = validate_godot_batch(batch)
    if errors:
        return {"batch_id": batch.get("batch_id"), "ok": False, "errors": errors, "stage": "validate"}
    install_addon(project)
    with tempfile.TemporaryDirectory() as td:
        bpath, rpath = Path(td) / "batch.json", Path(td) / "result.json"
        bpath.write_text(json.dumps(batch))
        proc = subprocess.run(
            [
                exe,
                "--headless",
                "--path",
                str(project),
                "-s",
                "res://addons/animatica/runner.gd",
                "--",
                str(bpath),
                str(rpath),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if not rpath.exists():
            raise GodotError(f"runner produced no result: {proc.stderr[-800:]}")
        res = json.loads(rpath.read_text())
    res["engine_errors"] = script_errors(proc.stderr + proc.stdout)
    return res


def install_addon(project: Path) -> None:
    dst = project / "addons" / "animatica"
    dst.mkdir(parents=True, exist_ok=True)
    for f in ADDON.iterdir():
        shutil.copy2(f, dst / f.name)


def script_errors(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if re.search(r"SCRIPT ERROR|Parse Error|ERROR:|Failed to load script", line):
            out.append(line.strip()[:300])
    return out[:20]


def run_game(
    project: Path, frames: int = 3600, args: list[str] | None = None, timeout: float = 300
) -> tuple[int, str, str]:
    exe = godot_bin()
    if not exe:
        raise GodotError("Godot 4 not found")
    cmd = [
        exe,
        "--headless",
        "--path",
        str(project),
        "--fixed-fps",
        "60",
        "--quit-after",
        str(frames),
        "--",
        *(args or []),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def check_scripts(project: Path, scripts: list[str]) -> list[str]:
    exe = godot_bin()
    errs: list[str] = []
    for s in scripts:
        p = subprocess.run(
            [exe, "--headless", "--path", str(project), "--check-only", "-s", s],
            capture_output=True,
            text=True,
            timeout=120,
        )
        errs += script_errors(p.stderr + p.stdout)
    return errs
