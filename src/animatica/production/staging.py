"""Staging tangents: one animal's feet drawn right on the top outline of a nearer one.

The cloud film review (11-19 00:36) saw Zuri's forelegs "standing on" Bibi Kobe's shell at 5:06 (SC 10). The
bodies are 0.4 m apart (``continuity.actor_overlap`` passes): the low camera lines the zebra's hooves up with
the top of the shell in front of her, so the picture reads as contact. Only the camera can see that, so this
check works on the shot cameras:

* for every shot, every few frames, every pair of on-stage animals in the frame, the **farther** one's feet
  (its footprint's four corners on the ground) are projected onto the film, and so is the **nearer** one's top
  outline (the top of its back or shell over the middle of its body, across its projected width);
* a foot that lands within ``TANGENT_TOL`` of a frame height of that outline (and within ``REL_TOL`` of the
  nearer animal's height on the film, so a wide shot isn't judged on a hair), inside its width, is a tangent
  (well below it the foot is simply hidden behind the nearer body; well above, it is clear of it).

:func:`approx_cameras` rebuilds the shots' cameras in pure Python (``frame_shot`` on the rest-pose heads), so
``scripts/continuity_check.py --cameras`` can run the check on a whole film without Blender; the scene
script runs the same check on the real cameras it built (heads measured on the posed rigs).
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

from animatica.production.continuity import (
    Violation,
    footprint,
    headings,
    on_stage,
    position,
    project,
)
from animatica.production.scene import (
    ASPECT,
    Occluder,
    SceneSpec,
    Shot,
    Subject,
    frame_shot,
    set_subject,
    shot_move,
    vfov,
)

TANGENT_TOL = 0.03  # frame heights between a far foot and a near top outline that read as touching
REL_TOL = 0.15  # ... and at most this share of the nearer animal's height on the film (small in a wide)
MIN_HEIGHT = 0.04  # a nearer animal under this share of the frame height is too small for a tangent to read
DEPTH_GAP_M = 0.5  # the farther animal must be at least this much farther (else they stand side by side)
BACK_DEG = 120.0  # the camera this far round from where the body faces: we see the back and rump, not a face
BACK_SHARE = 0.5  # ... for at least this share of a shot's samples
FACE_SHOTS = ("cu", "mcu", "ms")  # shots that exist to show a face (wides may follow a journey from behind)
Pose = tuple[float, float, float]  # world x, y, yaw (degrees, rest faces -Y)


def _rot(x: float, y: float, yaw: float) -> tuple[float, float]:
    a = math.radians(yaw)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def feet_points(species: str, pose: Pose) -> list[tuple[float, float, float]]:
    """The footprint's four corners on the ground: where the legs stand."""
    fp = footprint(species)
    out = []
    for lx, ly in (
        (-fp.half_w, fp.front),
        (fp.half_w, fp.front),
        (fp.half_w, fp.back),
        (-fp.half_w, fp.back),
    ):
        dx, dy = _rot(lx, ly, pose[2])
        out.append((pose[0] + dx, pose[1] + dy, 0.0))
    return out


def top_outline(
    species: str, pose: Pose, cam: dict[str, Any], inset: float = 0.8
) -> tuple[float, float, float, float, float] | None:
    """The nearer animal's top outline on the film: (x_min, x_max, y_top, depth, height). ``y_top`` is the
    top of the back over the body's middle, ``height`` its height above the ground on the film; the width is
    the footprint's at that height, ``inset`` for the rounding."""
    fp = footprint(species)
    mid = (fp.front + fp.back) / 2
    cx, cy = _rot(0.0, mid, pose[2])
    c = project(cam, (pose[0] + cx, pose[1] + cy, fp.top))
    g = project(cam, (pose[0] + cx, pose[1] + cy, 0.0))
    if c is None or g is None:
        return None
    xs = []
    hl, hw = inset * (fp.back - fp.front) / 2, inset * fp.half_w
    for lx, ly in ((-hw, mid - hl), (hw, mid - hl), (hw, mid + hl), (-hw, mid + hl)):
        dx, dy = _rot(lx, ly, pose[2])
        p = project(cam, (pose[0] + dx, pose[1] + dy, fp.top))
        if p is not None:
            xs.append(p[0])
    if not xs:
        return None
    return min(xs), max(xs), c[1], c[2], c[1] - g[1]


def _visible(p: tuple[float, float, float] | None) -> bool:
    return p is not None and abs(p[0]) <= ASPECT / 2 and abs(p[1]) <= 0.5


def staging_tangent(
    spec: SceneSpec,
    shots: list[dict[str, Any]],
    poses: dict[str, list[Pose]],
    fps: int,
    tol: float = TANGENT_TOL,
) -> list[Violation]:
    """On the shot cameras (``shots``: the scene's shot report with ``location``, ``end_location``, ``aim``,
    ``lens``, ``start``, ``end``): a farther animal's foot drawn on a nearer one's top outline. ``poses``: per
    actor, per frame (from frame 1), its root ``(x, y, yaw)``. Riders and extras are left out. One violation
    per shot and pair, at the closest moment."""
    ids = [c for c, a in spec.cast.items() if not a.ride and not a.extra and c in poses]
    out: list[Violation] = []
    for sh in shots:
        f0, f1 = 1 + int(sh["start"] * fps), max(1 + int(sh["start"] * fps), int(sh["end"] * fps))
        found: dict[tuple[str, str], tuple[float, float]] = {}  # (far, near) -> (|dy|, t)
        for f in range(f0, f1 + 1, max(1, fps // 4)):
            t = (f - 1) / fps
            u = (f - f0) / max(1, f1 - f0)
            loc = [a + (b - a) * u for a, b in zip(sh["location"], sh.get("end_location", sh["location"]))]
            cam = {**sh, "location": loc}
            here = [c for c in ids if on_stage(spec, c, t)]
            pose = {c: poses[c][min(len(poses[c]) - 1, f - 1)] for c in here}
            for near in here:
                outline = top_outline(spec.cast[near].species, pose[near], cam)
                if outline is None:
                    continue
                x0, x1, y_top, z_near, h = outline
                if h < MIN_HEIGHT or not _visible(((x0 + x1) / 2, y_top, z_near)):
                    continue
                lim = min(tol, REL_TOL * h)
                for far in here:
                    if far == near:
                        continue
                    for p in (project(cam, q) for q in feet_points(spec.cast[far].species, pose[far])):
                        if not _visible(p) or p[2] < z_near + DEPTH_GAP_M:  # type: ignore[index]
                            continue
                        dy = abs(p[1] - y_top)  # type: ignore[index]
                        if x0 <= p[0] <= x1 and dy <= lim:  # type: ignore[index]
                            k = (far, near)
                            if k not in found or dy < found[k][0]:
                                found[k] = (dy, t)
        for (far, near), (dy, t) in found.items():
            out.append(
                Violation(
                    spec.id,
                    "staging_tangent",
                    f"{far}/{near}",
                    round(t, 2),
                    f"shot {sh.get('shot', '?')} ({sh.get('type', '?')}): {far}'s feet sit on {near}'s top "
                    f"outline ({dy * 100:.1f} % of the frame height away)",
                )
            )
    return out


def view_angle(pose: Pose, cam_xy: tuple[float, float] | list[float]) -> float:
    """Degrees between where the body faces (yaw, rest faces -Y) and the direction to the camera on the
    ground: 0 = facing the lens, 90 = profile, 180 = seen straight from behind."""
    a = math.radians(pose[2])
    fx, fy = math.sin(a), -math.cos(a)
    dx, dy = cam_xy[0] - pose[0], cam_xy[1] - pose[1]
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (fx * dx + fy * dy) / d))))


def facing_away(
    spec: SceneSpec,
    shots: list[dict[str, Any]],
    poses: dict[str, list[Pose]],
    fps: int,
    back_deg: float = BACK_DEG,
    share: float = BACK_SHARE,
) -> list[Violation]:
    """A close or medium shot (``FACE_SHOTS``) whose subject we see from behind for most of the shot (the
    film review's SC 9 climax: Kiki's back while the spring sings). Judged per subject: the only subject, any
    subject in a close-up, or a subject who speaks on screen in the shot (a silent listener with its back to
    us in a two-shot is an over-the-shoulder, which is fine). The body's heading is used, not the head's: a
    head turned 30-40 degrees toward the lens does not turn a rump into a face. ``from_behind`` on a shot
    marks a deliberate back view and skips it. One violation per shot and subject, at the shot's middle."""
    out: list[Violation] = []
    for sh in shots:
        if sh.get("type") not in FACE_SHOTS or sh.get("from_behind"):
            continue
        subs = [c for c in sh.get("subjects", []) if c in poses and c in spec.cast]
        f0, f1 = 1 + int(sh["start"] * fps), max(1 + int(sh["start"] * fps), int(sh["end"] * fps))
        for c in subs:
            speaks = any(
                ln.who == c and not ln.offscreen and ln.start < sh["end"] - 0.3 and ln.end > sh["start"] + 0.3
                for ln in spec.lines
            )
            if not (len(subs) == 1 or sh["type"] in ("cu", "mcu") or speaks):
                continue
            angles = []
            for f in range(f0, f1 + 1, max(1, fps // 4)):
                if not on_stage(spec, c, (f - 1) / fps):
                    continue
                u = (f - f0) / max(1, f1 - f0)
                loc = [
                    a + (b - a) * u for a, b in zip(sh["location"], sh.get("end_location", sh["location"]))
                ]
                angles.append(view_angle(poses[c][min(len(poses[c]) - 1, f - 1)], loc[:2]))
            if not angles:
                continue
            back = [x for x in angles if x >= back_deg]
            if len(back) / len(angles) >= share:
                med = sorted(angles)[len(angles) // 2]
                why = "speaks" if speaks else ("close-up" if sh["type"] != "ms" else "the shot's subject")
                out.append(
                    Violation(
                        spec.id,
                        "facing_away",
                        c,
                        round((sh["start"] + sh["end"]) / 2, 2),
                        f"shot {sh.get('shot', '?')} ({sh['type']}, {why}): seen from behind for "
                        f"{100 * len(back) / len(angles):.0f} % of the shot (median {med:.0f} degrees from "
                        f"the lens); swing the camera round or turn the actor, or mark the shot from_behind",
                    )
                )
    return out


def poses_from_paths(spec: SceneSpec, seconds: float, fps: int) -> dict[str, list[Pose]]:
    """Per actor, per frame: root ``(x, y, yaw)`` from the scheduled paths (the gait follows them)."""
    n = int(seconds * fps) + 1
    out = {}
    for c in spec.cast:
        yaw = headings(spec, c, seconds, 1.0 / fps)
        out[c] = [(*position(spec, c, k / fps), yaw[min(len(yaw) - 1, k)]) for k in range(n)]
    return out


_META: dict[str, Any] = {}


def _meta(species: str) -> Any:
    if species not in _META:
        from animatica.creatures.build import build_creature
        from animatica.creatures.species import SPECIES

        _META[species] = build_creature("m", SPECIES[species], at=(0.0, 0.0))[1]
    return _META[species]


def _subject(spec: SceneSpec, c: str, pose: Pose) -> Subject:
    from animatica.creatures.species import SPECIES

    sp = SPECIES[spec.cast[c].species]
    m = _meta(spec.cast[c].species)
    hx, hy = _rot(sp.head_at[0], sp.head_at[1], pose[2])
    hs = max(sp.head_size)
    head = (pose[0] + hx, pose[1] + hy, m.head_height)
    return Subject(head=head, root=(pose[0], pose[1], sp.body_z), yaw=pose[2], head_size=hs,
                   height=head[2] + hs * 0.5, length=m.length)  # fmt: skip


def approx_cameras(
    spec: SceneSpec, shots: list[Shot], poses: dict[str, list[Pose]], fps: int
) -> list[dict[str, Any]]:
    """The shots' cameras as ``scripts/savannah_scene.py`` frames them, but on the rest-pose heads over the
    scheduled paths instead of the heads measured on the posed rigs (no Blender). Close enough to find a
    tangent; the scene script re-checks on its real cameras."""
    from animatica.creatures.species import SPECIES

    out = []
    for i, sh in enumerate(shots):
        f0, f1 = 1 + int(sh.start * fps), 1 + int(sh.end * fps)
        samples = sorted({f0, (f0 + f1) // 2, max(f0, f1 - 1)})
        if sh.subjects:
            use = samples if sh.type in ("ws", "ews") else [samples[len(samples) // 2]]
            talking = any(
                ln.who in sh.subjects
                and not ln.offscreen
                and ln.start < sh.end - 0.3
                and ln.end > sh.start + 0.3
                for ln in spec.lines
            )
            if sh.type == "ms" and len(sh.subjects) == 1 and talking:
                c0 = sh.subjects[0]
                sp0, m0 = SPECIES[spec.cast[c0].species], _meta(spec.cast[c0].species)
                top = m0.head_height + max(sp0.head_size) * 0.5
                if max(sp0.head_size) / max(1.45 * top, 1.3 * m0.length / 1.7778) < 0.24:
                    sh = dataclasses.replace(sh, type="mcu")
            subs = [
                _subject(spec, c, poses[c][min(len(poses[c]) - 1, f - 1)]) for f in use for c in sh.subjects
            ]
        else:
            subs = [set_subject(sh.look, sh.frame_h)]  # type: ignore[arg-type]
        mid = (f0 + f1) // 2
        occ = []
        for c in spec.cast:
            if c in sh.subjects:
                continue
            s = _subject(spec, c, poses[c][min(len(poses[c]) - 1, mid - 1)])
            top = s.height
            occ.append(Occluder(s.root[0], s.root[1], max(0.2, 0.25 * s.length), top))
            occ.append(Occluder(s.head[0], s.head[1], s.head_size * 0.6, top))
        cam = frame_shot(sh.type, subs, side=sh.side, aim_z=sh.look[2] if sh.look else None, occluders=occ)
        end_loc = shot_move(cam["location"], cam["aim"], sh.type, sh.end - sh.start, i)
        out.append(
            {
                "shot": i,
                "type": sh.type,
                "subjects": sh.subjects,
                "from_behind": sh.from_behind,
                "start": sh.start,
                "end": round(sh.end, 3),
                "end_location": [round(v, 4) for v in end_loc],
                "frame_h_m": round(2 * cam["distance"] * math.tan(vfov(cam["lens"]) / 2), 3),
                **cam,
            }
        )
    return out
