# SPDX-License-Identifier: GPL-3.0-or-later
"""Cycles compute-device selection: ``auto`` | ``cpu`` | ``cuda`` | ``optix``.

``auto`` prefers OptiX (NVIDIA RTX), then CUDA, then CPU. An explicit GPU request that the machine
cannot honour falls back to CPU with a warning instead of failing the render, so the same command
works on a laptop with an RTX card and on a GPU-less CI runner.

:func:`choose_backend` is pure (no ``bpy``) so it can be unit-tested anywhere; :func:`configure`
talks to Blender's Cycles preferences and caches the probe for the life of the process.
"""

from __future__ import annotations

import os

CHOICES = ("auto", "cpu", "cuda", "optix")
_PREFERENCE = {"auto": ("OPTIX", "CUDA"), "optix": ("OPTIX",), "cuda": ("CUDA",), "cpu": ()}
_probe_cache: dict[str, list[str]] | None = None


def requested_device(value: str | None) -> str:
    """The op's ``device``, else ``$ANIMATICA_RENDER_DEVICE``, else ``auto``."""
    v = (value or os.environ.get("ANIMATICA_RENDER_DEVICE") or "auto").strip().lower()
    if v not in CHOICES:
        raise ValueError(f"device must be one of {', '.join(CHOICES)}, got {v!r}")
    return v


def choose_backend(requested: str, available: dict[str, list[str]]) -> tuple[str, str | None]:
    """Pick a Cycles backend from ``available`` (backend -> GPU names).

    Returns ``(backend, warning)`` where backend is ``"OPTIX"``, ``"CUDA"`` or ``"CPU"``.
    """
    req = requested_device(requested)
    for backend in _PREFERENCE[req]:
        if available.get(backend):
            return backend, None
    if req in ("cuda", "optix"):
        return "CPU", f"{req} requested but no {req.upper()} GPU was found; rendering on CPU"
    return "CPU", None


def probe() -> dict[str, list[str]]:
    """GPUs Cycles can use, per backend (cached; the first call takes ~0.5 s)."""
    global _probe_cache
    if _probe_cache is not None:
        return _probe_cache
    import bpy

    found: dict[str, list[str]] = {}
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except (KeyError, AttributeError):
        _probe_cache = found
        return found
    for backend in ("OPTIX", "CUDA"):
        try:
            devs = prefs.get_devices_for_type(backend)
        except Exception:  # noqa: BLE001 - backend not compiled in / driver missing
            continue
        gpus = [d.name for d in devs if d.type == backend]
        if gpus:
            found[backend] = gpus
    _probe_cache = found
    return found


def configure(scene, requested: str | None) -> tuple[str, list[str]]:
    """Point ``scene`` (Cycles) at the chosen device. Returns ``(label, warnings)``,
    e.g. ``("OPTIX: NVIDIA GeForce RTX 5060 Laptop GPU", [])`` or ``("CPU", [])``."""
    available = probe()
    backend, warn = choose_backend(requested_device(requested), available)
    warnings = [warn] if warn else []
    if backend == "CPU":
        scene.cycles.device = "CPU"
        return "CPU", warnings
    import bpy

    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = backend
    for d in prefs.get_devices_for_type(backend):
        d.use = d.type == backend  # GPU only: hybrid CPU+GPU is slower with OptiX denoise/tiles
    scene.cycles.device = "GPU"
    try:
        scene.cycles.denoising_use_gpu = True
    except AttributeError:
        pass
    return f"{backend}: {', '.join(available[backend])}", warnings


def force_cpu(scene) -> None:
    scene.cycles.device = "CPU"
