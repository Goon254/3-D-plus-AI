"""Dark faces: a close or medium shot whose subject's head is near black on the rendered frame.

The film review (11-19 00:36) noted the SC 8 tortoise close-up at 3:48: night, a low key light, and Bibi Kobe's
head is a dark shape against a dark ground: the shot exists to show her face and it shows nothing. The
shot plan cannot see light, so this check works on rendered frames, through the shot's own camera:

* for every close or medium shot (``staging.FACE_SHOTS``), at its middle, each subject on stage whose head
  projects into the frame at a readable size (radius ≥ ``MIN_RADIUS`` of the frame height, ≥ ``MIN_INSIDE`` of
  its box inside the frame) gets a box round the head (the head's rest size, projected);
* the box's median luminance (Rec. 709 on the encoded frame, 0-1) under ``DARK_MEDIAN`` is a dark face.

Calibration (DECISIONS #102, frames in ``tests/data/frames``): on the final film every face shot's head box was
drawn and checked by eye. The SC 8 tortoise MCUs (3:50, 3:54) measure 0.016; every other face in the film,
including the dusk and night ones, measures ≥ 0.09 (the darkest: Kiki's night close-up in SC 8, 0.092; Bibi
Kobe at dusk in SC 7, 0.10). ``DARK_MEDIAN`` sits between them.

It runs where the frames and the cameras meet: ``scripts/savannah_animatic.py`` on each scene's render and
``report.json`` cameras (soft, ``dark_faces`` in ``animatic.json``), and ``scripts/frame_check.py --faces`` on a
film or animatic (the scene reports' cameras when they have them; approximate cameras on the cloud).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from animatica.production.continuity import actor_speeds, on_stage, project
from animatica.production.pacing import _cam_at, _pose, line_durations
from animatica.production.scene import ASPECT, SceneSpec, cut_list, schedule, split_long, vfov
from animatica.production.staging import FACE_SHOTS, _subject, approx_cameras, poses_from_paths
from animatica.sets.frames import grab, luminance

DARK_MEDIAN = (
    0.05  # head-box median luminance under this reads as black (film: dark tortoise 0.016, rest ≥ 0.09)
)
MIN_RADIUS = 0.03  # head radius on the film in frame heights; smaller and the shot is not about this face
MIN_INSIDE = 0.4  # share of the head's box inside the frame
Box = tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the frame width / height, y down


def head_box(
    cam: dict[str, Any], head: tuple[float, float, float], head_size: float
) -> tuple[Box, float] | None:
    """The head's box on the frame (``Box``, unclipped) and its radius in frame heights; ``None`` behind the
    camera."""
    p = project(cam, head)
    if p is None:
        return None
    x, y, z = p
    r = 0.5 * head_size / (2 * math.tan(vfov(cam["lens"]) / 2) * z)
    return ((x - r) / ASPECT + 0.5, 0.5 - y - r, (x + r) / ASPECT + 0.5, 0.5 - y + r), r


def inside(box: Box) -> float:
    """Share of ``box`` inside the frame."""
    x0, y0, x1, y1 = box
    area = max(1e-9, (x1 - x0) * (y1 - y0))
    w = max(0.0, min(1.0, x1) - max(0.0, x0))
    h = max(0.0, min(1.0, y1) - max(0.0, y0))
    return w * h / area


def face_exposure(image: Any, box: Box) -> dict[str, Any]:
    """Luminance of the head's box on a frame (path, PIL image or RGB array): ``median``, ``p90`` and
    ``dark`` (median under ``DARK_MEDIAN``)."""
    lum = luminance(image)
    h, w = lum.shape
    x0, y0, x1, y1 = box
    c0, c1 = max(0, int(x0 * w)), min(w, int(math.ceil(x1 * w)))
    r0, r1 = max(0, int(y0 * h)), min(h, int(math.ceil(y1 * h)))
    if c1 - c0 < 2 or r1 - r0 < 2:
        return {"median": None, "p90": None, "dark": False}
    reg = lum[r0:r1, c0:c1]
    med = float(np.median(reg))
    return {
        "median": round(med, 3),
        "p90": round(float(np.percentile(reg, 90)), 3),
        "dark": med < DARK_MEDIAN,
    }


def face_targets(
    spec: SceneSpec, shots: list[dict[str, Any]], poses: dict[str, list[tuple[float, float, float]]], fps: int
) -> list[dict[str, Any]]:
    """Per face shot, at its middle: each subject on stage whose head is big enough and inside the frame,
    with its box (``shot``, ``type``, ``t`` in scene seconds, ``who``, ``box``, ``radius``)."""
    out = []
    for sh in shots:
        if sh.get("type") not in FACE_SHOTS or not {"location", "aim", "lens"} <= set(sh):
            continue
        t = (sh["start"] + sh["end"]) / 2
        cam = _cam_at(sh, t)
        for c in sh.get("subjects", []):
            if c not in spec.cast or c not in poses or not on_stage(spec, c, t):
                continue
            sub = _subject(spec, c, _pose(poses, c, t, fps))
            hb = head_box(cam, sub.head, sub.head_size)
            if hb is None or hb[1] < MIN_RADIUS or inside(hb[0]) < MIN_INSIDE:
                continue
            out.append(
                {
                    "shot": sh.get("shot", "?"),
                    "type": sh["type"],
                    "t": round(t, 2),
                    "who": c,
                    "box": [round(v, 4) for v in hb[0]],
                    "radius": round(hb[1], 4),
                }
            )
    return out


def scene_cameras(
    spec: SceneSpec, rep: dict[str, Any] | None, fps: int = 24
) -> tuple[list[dict[str, Any]], dict[str, list[tuple[float, float, float]]], float, bool]:
    """A scene's shot cameras, the actors' poses, its length and whether the cameras are approximate: the
    report's own cameras (``savannah_scene.py``'s ``report.json``, timed by its voice takes) when it has
    them, else ``staging.approx_cameras`` on the scheduled paths (no Blender; timings from a word count)."""
    secs = schedule(spec, line_durations(spec, rep), actor_speeds(spec))
    shots = [s for s in (rep or {}).get("shots", []) if {"location", "aim", "lens"} <= set(s)]
    seconds = float((rep or {}).get("seconds", secs))
    poses = poses_from_paths(spec, max(secs, seconds), fps)
    if shots:
        return shots, poses, seconds, False
    cuts = split_long(cut_list(spec, secs), secs)
    return approx_cameras(spec, cuts, poses, fps), poses, secs, True


def dark_faces(
    spec: SceneSpec,
    shots: list[dict[str, Any]],
    poses: dict[str, list[tuple[float, float, float]]],
    video: str | Path,
    fps: int = 24,
    offset: float = 0.0,
    scale: float = 1.0,
) -> list[dict[str, Any]]:
    """The face shots of one scene whose subject's head is near black on ``video``. The scene's second ``t``
    is the video's ``offset + t * scale`` (a whole film: the scene's start; approximate cameras: the
    rendered length over the scheduled one). One row per dark face: ``scene``, ``shot``, ``type``, ``who``,
    ``t`` (scene seconds), ``video_t``, ``median``, ``p90``, ``box``."""
    out = []
    for tg in face_targets(spec, shots, poses, fps):
        vt = offset + tg["t"] * scale
        rgb = grab(video, vt)
        if rgb is None:
            continue
        ex = face_exposure(rgb, tuple(tg["box"]))  # type: ignore[arg-type]
        if ex["dark"]:
            out.append(
                {
                    "scene": spec.id,
                    "shot": tg["shot"],
                    "type": tg["type"],
                    "who": tg["who"],
                    "t": tg["t"],
                    "video_t": round(vt, 2),
                    "median": ex["median"],
                    "p90": ex["p90"],
                    "box": tg["box"],
                }
            )
    return out


def dark_faces_in_report(
    spec: SceneSpec, rep: dict[str, Any], video: str | Path, fps: int = 24
) -> list[dict[str, Any]]:
    """``dark_faces`` on a rendered scene (``video``) through its own ``report.json`` cameras; a report
    without cameras gives nothing (the animatic does not guess)."""
    shots, poses, _, approximate = scene_cameras(spec, rep, fps)
    if approximate:
        return []
    return dark_faces(spec, shots, poses, video, fps)
