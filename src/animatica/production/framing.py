"""Crowding: a neighbour's headless body (legs, a flank, a leg column) filling part of a face shot.

The film reviews (11-19 00:36 onward) kept a "known, still open" note: in close and medium shots the herd
stands so close that a giraffe's or a zebra's legs, or the side of Tembo, fill the frame next to the face the
shot is about (2:30 the giraffe's legs behind Kiki; 3:12 the giraffe's legs and Tembo's flank either side of
Zuri; the tortoise MCUs in SC 3, 7 and 8 with a zebra or elephant leg column at the frame edge). A neighbour
in a two-shot whose face we see is staging; a neighbour we see only as legs or a flank, its head out of the
frame, is clutter the eye cannot place. This check works on the shot cameras (no frames needed):

* for every close or medium shot (``staging.FACE_SHOTS``), every quarter second, every on-stage actor (riders
  and extras left out) is drawn on a coarse grid of the frame, farthest first, as two boxes: its body (the
  footprint from the ground to the top of the back, projected) and its head (the rest-pose head's size);
* a non-subject whose head box is mostly outside the frame (``HEAD_INSIDE``) and whose body still owns at least
  ``CROWD_AREA`` of the frame after nearer actors are drawn over it is **headless** at that moment;
* headless for at least ``CROWD_SHARE`` of the samples it is on stage for is a ``crowding`` finding (one per
  shot and neighbour, with the median share of the frame).

Boxes overstate legs (the gaps between them count), so ``CROWD_AREA`` was set on the film by eye
(DECISIONS #103): the leg columns and flanks the reviews named measure 0.08-0.6 of the frame on the
approximate cameras; slivers that only touch the edge (a tail tip, a hoof in a corner) measure under 0.06.

It runs with the other camera checks: ``scripts/continuity_check.py --cameras`` (approximate cameras, the
whole film in seconds) and ``scripts/savannah_scene.py`` on the real cameras it built. A shot can opt out
with ``crowd_ok`` when a body in the foreground is the point (a story reason).
"""

from __future__ import annotations

from typing import Any

from animatica.production.continuity import Violation, footprint, on_stage, project
from animatica.production.exposure import head_box, inside
from animatica.production.pacing import _cam_at
from animatica.production.scene import ASPECT, SceneSpec
from animatica.production.staging import FACE_SHOTS, Pose, _rot, _subject

CROWD_AREA = 0.06  # a headless neighbour owning this share of the frame is clutter (calibrated on the film)
CROWD_SHARE = 0.5  # ... for at least this share of the shot (while it is on stage)
HEAD_INSIDE = 0.5  # a head box less than this much inside the frame is out of the shot
GRID = (64, 36)  # cells across and down the frame for the painter's pass
Box = tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the frame width / height, y down


def body_box(species: str, pose: Pose, cam: dict[str, Any]) -> tuple[Box, float] | None:
    """The body's box on the frame (the footprint's corners from the ground to the top of the back; unclipped)
    and the depth of its centre; ``None`` when it is all behind the camera. Corners behind the camera are
    left out (a flank right at the lens is drawn from the corners in front of it)."""
    fp = footprint(species)
    pts = []
    for lx, ly in (
        (-fp.half_w, fp.front),
        (fp.half_w, fp.front),
        (fp.half_w, fp.back),
        (-fp.half_w, fp.back),
    ):
        dx, dy = _rot(lx, ly, pose[2])
        for z in (0.0, fp.top):
            p = project(cam, (pose[0] + dx, pose[1] + dy, z))
            if p is not None:
                pts.append(p)
    if not pts:
        return None
    xs = [p[0] / ASPECT + 0.5 for p in pts]
    ys = [0.5 - p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys)), sum(p[2] for p in pts) / len(pts)


def paint(layers: list[tuple[Box, float, str]], grid: tuple[int, int] = GRID) -> dict[str, float]:
    """Painter's pass on a coarse grid: ``layers`` are ``(box, depth, owner)``; the farthest are drawn first
    and nearer boxes cover them. Returns each owner's share of the frame."""
    nx, ny = grid
    cells: list[list[str | None]] = [[None] * nx for _ in range(ny)]
    for (x0, y0, x1, y1), _, who in sorted(layers, key=lambda layer: -layer[1]):
        c0, c1 = max(0, int(x0 * nx + 0.5)), min(nx, int(x1 * nx + 0.5))
        r0, r1 = max(0, int(y0 * ny + 0.5)), min(ny, int(y1 * ny + 0.5))
        for r in range(r0, r1):
            row = cells[r]
            for c in range(c0, c1):
                row[c] = who
    out: dict[str, float] = {}
    for row in cells:
        for who in row:
            if who is not None:
                out[who] = out.get(who, 0.0) + 1.0
    return {k: v / (nx * ny) for k, v in out.items()}


def frame_shares(
    spec: SceneSpec, cam: dict[str, Any], pose: dict[str, Pose]
) -> dict[str, tuple[float, float]]:
    """Per actor in ``pose`` (id -> root pose): (share of the frame its body owns after nearer actors are drawn
    over it, share of its head box inside the frame)."""
    layers: list[tuple[Box, float, str]] = []
    head_in: dict[str, float] = {}
    for c, p in pose.items():
        bb = body_box(spec.cast[c].species, p, cam)
        sub = _subject(spec, c, p)
        hb = head_box(cam, sub.head, sub.head_size)
        head_in[c] = 0.0 if hb is None else inside(hb[0])
        if bb is not None:
            layers.append((bb[0], bb[1], c))
        if hb is not None:
            hp = project(cam, sub.head)
            layers.append((hb[0], hp[2] if hp else 1e9, c + "#head"))
    owned = paint(layers)
    return {c: (owned.get(c, 0.0), head_in[c]) for c in pose}


def crowding(
    spec: SceneSpec,
    shots: list[dict[str, Any]],
    poses: dict[str, list[Pose]],
    fps: int,
    area: float = CROWD_AREA,
    share: float = CROWD_SHARE,
) -> list[Violation]:
    """Close and medium shots (``FACE_SHOTS``) where a neighbour's headless body fills ``area`` of the frame for
    ``share`` of the shot. ``shots``: the scene's shot report (``location``, ``end_location``, ``aim``, ``lens``,
    ``start``, ``end``, ``subjects``); ``poses``: per actor, per frame (from frame 1), its root ``(x, y,
    yaw)``. One violation per shot and neighbour, at the shot's middle."""
    ids = [c for c, a in spec.cast.items() if not a.ride and not a.extra and c in poses]
    out: list[Violation] = []
    for sh in shots:
        if (
            sh.get("type") not in FACE_SHOTS
            or sh.get("crowd_ok")
            or not {"location", "aim", "lens"} <= set(sh)
        ):
            continue
        subs = set(sh.get("subjects", []))
        f0 = 1 + int(sh["start"] * fps)
        f1 = max(f0, int(sh["end"] * fps))
        seen: dict[str, list[float]] = {}  # neighbour -> per sample: its headless share (0 when not headless)
        for f in range(f0, f1 + 1, max(1, fps // 4)):
            t = (f - 1) / fps
            here = [c for c in ids if on_stage(spec, c, t)]
            pose = {c: poses[c][min(len(poses[c]) - 1, f - 1)] for c in here}
            shares = frame_shares(spec, _cam_at(sh, t), pose)
            for c in here:
                if c in subs:
                    continue
                owned, head_in = shares[c]
                seen.setdefault(c, []).append(owned if head_in < HEAD_INSIDE else 0.0)
        for c, vals in seen.items():
            hits = sorted(v for v in vals if v >= area)
            if not hits or len(hits) / len(vals) < share:
                continue
            med = hits[len(hits) // 2]
            out.append(
                Violation(
                    spec.id,
                    "crowding",
                    c,
                    round((sh["start"] + sh["end"]) / 2, 2),
                    f"shot {sh.get('shot', '?')} ({sh['type']} of {', '.join(sorted(subs)) or 'the set'}): "
                    f"{c}'s body fills {100 * med:.0f} % of the frame with its head out of shot for "
                    f"{100 * len(hits) / len(vals):.0f} % of the shot; move it out of frame or into the "
                    f"shot with its face, or mark the shot crowd_ok",
                )
            )
    return out
