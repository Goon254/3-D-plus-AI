"""Continuity: who is on stage in every shot, checked against the story's exits and entrances.

The owner's catch (animatic 11-18): Zuri runs off into the tall grass at the end of SC 5, yet stood in plain
view at the start of SC 6 while the others were still calling for her. Nothing knew she had left. This
module makes presence explicit and checks it:

* **Stage time.** An actor is on stage from ``enter`` until ``exit`` (``Actor.t_in`` / ``t_out``, resolved by
  ``schedule()``); everyone else is on stage for the whole scene.
* **Story exits.** An actor whose scene marks ``story_exit`` has left the group: every later scene that casts
  them must bring them back with an ``enter`` (and until then they are off stage).
* **Shots.** A shot's subjects must be on stage when it starts.
* **Lines.** A speaker must be on stage while speaking, unless the line is ``offscreen`` (heard, not seen); an
  off-screen line must not cut to its speaker.
* **Acting.** Gestures and reactions by an actor who is off stage are mistakes.
* **Nobody walks into anybody.** Two on-stage animals' body footprints (an oriented box per species, measured
  on the base mesh, turned to the heading the gait would give) must not overlap (:func:`actor_overlap`; the
  final film had Zuri's forelegs standing on Bibi Kobe's shell in SC 10).
* **Off stage means out of sight.** While off stage an actor must be away from the set
  (``OFFSTAGE_M`` from every action circle), and, once the cameras exist, outside every frame
  (:func:`in_frame`, used by ``scripts/savannah_scene.py`` on the real camera positions).

Pure Python: ``scripts/continuity_check.py`` runs it over the whole film before anything renders.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from animatica.creatures.gait import Waypoint, path_xy
from animatica.production.scene import ASPECT, OFFSTAGE_M, SceneSpec, Shot, offstage_distance, vfov

SAMPLE_S = 0.25


@dataclass
class Violation:
    scene: str
    kind: str
    who: str
    t: float
    detail: str

    def __str__(self) -> str:
        return f"{self.scene} {self.t:6.2f}s {self.kind:14s} {self.who:10s} {self.detail}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "kind": self.kind,
            "who": self.who,
            "t": round(self.t, 2),
            "detail": self.detail,
            "key": violation_key(self),
        }


_SHOT = re.compile(r"\bshot (\d+)\b")
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


def violation_key(v: Violation | dict[str, Any]) -> str:
    """A key that names the same problem from one run to the next, even when the timing moves.

    Scene, kind and who, then the shot number when the finding is about a shot (a re-timed line moves the
    shot's start and its measured percentages, not its index), else the detail with every number blanked
    out (a mark moved by 5 cm changes the depth, not the problem).
    """
    if isinstance(v, Violation):
        scene, kind, who, detail = v.scene, v.kind, v.who, v.detail
    else:
        scene, kind, who, detail = v["scene"], v["kind"], v["who"], v["detail"]
    m = _SHOT.search(detail)
    where = f"shot {m.group(1)}" if m else _NUMBER.sub("#", detail)
    return f"{scene}|{kind}|{who}|{where}"


def continuity_report(violations: list[Violation], **meta: Any) -> dict[str, Any]:
    """The machine-readable report (``continuity_check.py --json``): counts per kind and every finding."""
    counts: dict[str, int] = {}
    for v in violations:
        counts[v.kind] = counts.get(v.kind, 0) + 1
    return {
        **meta,
        "total": len(violations),
        "counts": dict(sorted(counts.items())),
        "violations": [v.as_dict() for v in violations],
    }


CAMERA_KINDS = frozenset(
    {"staging_tangent", "facing_away", "dead_air", "crowding"}
)  # only measured with ``cameras`` on


def diff_reports(old: dict[str, Any], new: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """What changed between two reports: ``fixed`` (only in old), ``new`` (only in new), ``kept``.

    Findings are matched by :func:`violation_key` (recomputed, so reports written before the key existed
    still compare); a key found twice on one side is matched as many times as it appears on both. When
    only one report measured the cameras, the camera findings are left out of the comparison: a run that
    didn't look can't have fixed them. A finding about a shot is keyed by the shot's index, so inserting
    or removing a shot earlier in a scene shows that scene's later shot findings as fixed + new.
    """
    skip = CAMERA_KINDS if bool(old.get("cameras")) != bool(new.get("cameras")) else frozenset()

    def by_key(rep: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for d in rep.get("violations", []):
            if d["kind"] not in skip:
                out.setdefault(violation_key(d), []).append(d)
        return out

    a, b = by_key(old), by_key(new)
    fixed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for k in sorted(set(a) | set(b)):
        olds, news = a.get(k, []), b.get(k, [])
        n = min(len(olds), len(news))
        kept += news[:n]
        fixed += olds[n:]
        added += news[n:]
    return {"fixed": fixed, "new": added, "kept": kept}


@dataclass
class Presence:
    """Per scene: who is on stage in each shot (the table the report prints)."""

    scene: str
    shots: list[tuple[float, float, str, list[str], list[str]]] = field(default_factory=list)
    # (start, end, type, subjects, everyone on stage during the shot)


def on_stage(spec: SceneSpec, cid: str, t: float) -> bool:
    a = spec.cast[cid]
    return a.t_in - 1e-6 <= t <= a.t_out + 1e-6


def position(spec: SceneSpec, cid: str, t: float) -> tuple[float, float]:
    a = spec.cast[cid]
    if not a.path:
        return a.at
    pts = [Waypoint(w[0], w[1], w[2], glide=len(w) > 3 and bool(w[3])) for w in a.path]
    return path_xy(pts, t)


def _off_set(spec: SceneSpec, xy: tuple[float, float]) -> float:
    return offstage_distance(spec.layout, xy)


def check_scene(spec: SceneSpec, shots: list[Shot], seconds: float) -> tuple[list[Violation], Presence]:
    """Check one scheduled scene (``schedule()`` and ``cut_list()`` already ran)."""
    out: list[Violation] = []
    pres = Presence(spec.id)
    for s in shots:
        here = [c for c in spec.cast if on_stage(spec, c, s.start + 0.05) or on_stage(spec, c, s.end - 0.05)]
        pres.shots.append((s.start, s.end, s.type, list(s.subjects), here))
        for c in s.subjects:
            if not on_stage(spec, c, s.start + 0.05):
                out.append(
                    Violation(spec.id, "shot_subject", c, s.start, f"{s.type} on {c}, who is off stage")
                )
    for i, ln in enumerate(spec.lines):
        if ln.who not in spec.cast:
            continue
        mid = (ln.start + ln.end) / 2
        if ln.offscreen:
            for s in shots:
                if ln.who in s.subjects and s.start < ln.end and s.end > ln.start:
                    out.append(
                        Violation(
                            spec.id,
                            "offscreen_cut",
                            ln.who,
                            s.start,
                            f"line {i} is off screen but a shot shows them",
                        )
                    )
        elif not on_stage(spec, ln.who, mid):
            out.append(
                Violation(
                    spec.id,
                    "line_offstage",
                    ln.who,
                    ln.start,
                    f"line {i} spoken off stage (mark it offscreen)",
                )
            )
    for g in spec.gestures:
        t = g.time(spec.lines)
        if g.who in spec.cast and not on_stage(spec, g.who, t):
            out.append(Violation(spec.id, "gesture_offstage", g.who, t, f"{g.value} while off stage"))
    for b in spec.reactions:
        t = b.time(spec.lines)
        if b.who in spec.cast and not on_stage(spec, b.who, t):
            out.append(Violation(spec.id, "react_offstage", b.who, t, f"{b.value} while off stage"))
    # off stage = away from the set
    for cid, a in spec.cast.items():
        if a.t_in <= 0 and a.t_out >= seconds:
            continue
        k, worst = 0, None
        while k * SAMPLE_S <= seconds:
            t = k * SAMPLE_S
            if not on_stage(spec, cid, t):
                d = _off_set(spec, position(spec, cid, t))
                if d < OFFSTAGE_M and (worst is None or d < worst[1]):
                    worst = (t, d)
            k += 1
        if worst:
            out.append(
                Violation(
                    spec.id,
                    "offstage_near",
                    cid,
                    worst[0],
                    f"off stage but only {worst[1]:.1f} m from the action (< {OFFSTAGE_M})",
                )
            )
    out += inside_set(spec, seconds)
    out += actor_overlap(spec, seconds)
    return out, pres


SOLID = {"mounds": 0.62, "acacias": 0.2}  # footprint radius (x the item's scale) an animal can't stand in


def inside_set(spec: SceneSpec, seconds: float, step: float = 0.25) -> list[Violation]:
    """An animal whose body centre walks into a termite mound or a tree trunk (animatic v2: Kiki "popped up"
    inside the SC 4 mound and the close-up was a brown frame)."""
    out = []
    for cid, a in spec.cast.items():
        if a.ride:
            continue
        t = 0.0
        while t <= seconds:
            if on_stage(spec, cid, t):
                x, y = position(spec, cid, t)
                hit = next(
                    (
                        (kind, i)
                        for kind, r in SOLID.items()
                        for i, (mx, my, sc) in enumerate(spec.layout.get(kind, []))
                        if math.hypot(x - mx, y - my) < r * sc
                    ),
                    None,
                )
                if hit:
                    out.append(
                        Violation(
                            spec.id,
                            "inside_set",
                            cid,
                            t,
                            f"stands inside {hit[0][:-1]} {hit[1]} at ({x:.2f}, {y:.2f})",
                        )
                    )
                    break
            t += step
    return out


def set_assets(spec: SceneSpec, seed: int | None = None) -> list[Violation]:
    """Set models measured as built (``animatica.sets.measure``): every acacia in the scene's layout must have a
    flat-table crown with sky through it, not a cushion or broccoli florets (the owner's set notes, 11-16/11-17).
    ``seed`` is the set layout's seed (``Layout.seed``); the scene builds acacia ``i`` with ``seed + 11 i``."""
    from animatica.sets.measure import acacia_shape, canopy_problems
    from animatica.sets.savannah import Layout

    base = Layout().seed if seed is None else seed
    out = []
    for i, (_, _, sc) in enumerate(spec.layout.get("acacias", [])):
        for problem in canopy_problems(acacia_shape(sc, base + 11 * i)):
            out.append(Violation(spec.id, "set_canopy", f"acacia_{i}", 0.0, problem))
    return out


TOUCH_M = 0.03  # footprints may graze (a hoof beside a flank); deeper than this is one animal inside another


@dataclass(frozen=True)
class Footprint:
    """A species' body footprint in its root frame (faces -Y, +X is its left): ``front`` (the nose, < 0) to
    ``back`` (the rump, > 0), ``half_w`` to each side. Tails, ears and eyes don't count; neither does anything
    above the back (a giraffe's head over a tortoise is a composition, not a collision)."""

    front: float
    back: float
    half_w: float
    top: float = 0.0  # height of the back (or shell) above the ground: the body's top outline


_FOOTPRINTS: dict[str, Footprint] = {}


def footprint(species: str) -> Footprint:
    """Measured on the built base mesh: the body's metaball elements (centre +- radius x size) and any
    other body mesh (the tortoise's shell), up to the top of the torso."""
    if species in _FOOTPRINTS:
        return _FOOTPRINTS[species]
    from animatica.creatures.build import build_creature
    from animatica.creatures.species import SPECIES

    sp = SPECIES[species]
    ops, meta = build_creature("fp", sp, at=(0.0, 0.0), yaw=0.0)
    top = sp.torso_at[2] + sp.torso[2] / 2  # root frame: the root sits at body_z
    boxes: list[tuple[float, float, float]] = []  # (x, y, z top) in the root frame
    shell_top = -math.inf
    for o in ops:
        if o["op"] == "create_metaball_mesh" and o["id"] == "fp_body":
            for e in o["elements"]:
                (x, y, z), r = e["co"], e["radius"]
                sx, sy, sz = e.get("size", (1.0, 1.0, 1.0))
                if z - r * sz <= top:
                    zt = min(z + r * sz, top)
                    boxes += [(abs(x) + r * sx, y - r * sy, zt), (abs(x) + r * sx, y + r * sy, zt)]
        elif o["op"] == "create_mesh" and o["id"] == "fp_shell":
            lx, ly, lz = o.get("location", (0.0, 0.0, 0.0))
            boxes += [(abs(v[0] + lx), v[1] + ly, v[2] + lz) for v in o["vertices"] if v[2] + lz <= top]
            shell_top = max(v[2] + lz for v in o["vertices"])  # the dome rises above the torso
    if not boxes:  # a body style without metaballs: the torso box
        boxes = [(sp.torso[0] / 2, sp.torso_at[1] - sp.torso[1] / 2, top)]
        boxes.append((sp.torso[0] / 2, sp.torso_at[1] + sp.torso[1] / 2, top))
    fp = Footprint(
        front=min(b[1] for b in boxes),
        back=max(b[1] for b in boxes),
        half_w=max(b[0] for b in boxes),
        top=sp.body_z + max([b[2] for b in boxes] + [shell_top]),
    )
    _FOOTPRINTS[species] = fp
    return fp


def _corners(fp: Footprint, xy: tuple[float, float], yaw: float) -> list[tuple[float, float]]:
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    out = []
    for lx, ly in (
        (-fp.half_w, fp.front),
        (fp.half_w, fp.front),
        (fp.half_w, fp.back),
        (-fp.half_w, fp.back),
    ):
        out.append((xy[0] + lx * c - ly * s, xy[1] + lx * s + ly * c))  # gait._rot: root frame -> world
    return out


def box_overlap(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """How deep two convex quads overlap (separating axis theorem): 0 if they don't touch, else the
    smallest push along any edge normal that would separate them (metres)."""
    depth = math.inf
    for poly in (a, b):
        for i in range(len(poly)):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
            nx, ny = y0 - y1, x1 - x0
            n = math.hypot(nx, ny) or 1.0
            nx, ny = nx / n, ny / n
            pa = [p[0] * nx + p[1] * ny for p in a]
            pb = [p[0] * nx + p[1] * ny for p in b]
            d = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if d <= 0:
                return 0.0
            depth = min(depth, d)
    return depth


def headings(spec: SceneSpec, cid: str, seconds: float, step: float = SAMPLE_S) -> list[float]:
    """The actor's yaw (degrees, rest faces -Y) every ``step`` s, the way the gait plan turns it: along the
    path while moving, held while standing; before the first move it already faces the first move."""
    a = spec.cast[cid]
    n = int(seconds / step) + 1
    if not a.path or len(a.path) < 2:
        return [a.yaw] * n
    (x0, y0), (x1, y1) = a.path[0][1:3], a.path[1][1:3]
    last = math.degrees(math.atan2(x1 - x0, -(y1 - y0))) if (x0, y0) != (x1, y1) else a.yaw
    out, dt = [], 0.05
    for k in range(n):
        t = k * step
        p, q = position(spec, cid, max(0.0, t - dt)), position(spec, cid, t + dt)
        dx, dy = q[0] - p[0], q[1] - p[1]
        if math.hypot(dx, dy) / (2 * dt) > 0.02:
            last = math.degrees(math.atan2(dx, -dy))
        out.append(last)
    return out


def actor_overlap(spec: SceneSpec, seconds: float, step: float = SAMPLE_S) -> list[Violation]:
    """Two on-stage animals whose body footprints overlap by more than ``TOUCH_M`` (one walks into, or
    stands on, the other). A rider (``ride``) and the animal it rides are exempt. One violation per pair:
    the first moment, with the deepest overlap seen."""
    ids = [c for c, a in spec.cast.items() if not a.ride]
    n = int(seconds / step) + 1
    yaw = {c: headings(spec, c, seconds, step) for c in ids}
    fps = {c: footprint(spec.cast[c].species) for c in ids}
    out = []
    for i, c1 in enumerate(ids):
        for c2 in ids[i + 1 :]:
            first, worst = None, 0.0
            for k in range(n):
                t = k * step
                if not (on_stage(spec, c1, t) and on_stage(spec, c2, t)):
                    continue
                p1, p2 = position(spec, c1, t), position(spec, c2, t)
                reach = max(-fps[c1].front, fps[c1].back) + max(-fps[c2].front, fps[c2].back) + 1.0
                if math.hypot(p1[0] - p2[0], p1[1] - p2[1]) > reach:
                    continue
                d = box_overlap(_corners(fps[c1], p1, yaw[c1][k]), _corners(fps[c2], p2, yaw[c2][k]))
                if d > TOUCH_M:
                    first = t if first is None else first
                    worst = max(worst, d)
            if first is not None:
                out.append(
                    Violation(
                        spec.id,
                        "actor_overlap",
                        f"{c1}+{c2}",
                        first,
                        f"bodies overlap (deepest {worst:.2f} m)",
                    )
                )
    return out


def check_story(specs: list[SceneSpec]) -> list[Violation]:
    """Across scenes in film order: an actor who left the group (``story_exit``) must re-``enter``."""
    out: list[Violation] = []
    away: set[str] = set()
    for spec in specs:
        for cid, a in spec.cast.items():
            if a.extra:
                continue
            if cid in away:
                if not a.enter:
                    out.append(
                        Violation(
                            spec.id,
                            "story_absent",
                            cid,
                            0.0,
                            "left the group earlier and is here with no entrance",
                        )
                    )
                away.discard(cid)
        for cid, a in spec.cast.items():
            if a.story_exit:
                if not a.exit:
                    out.append(Violation(spec.id, "story_exit", cid, 0.0, "leaves the group but has no exit"))
                away.add(cid)
    return out


def project(cam: dict[str, Any], point: tuple[float, float, float]) -> tuple[float, float, float] | None:
    """``point`` on the camera's film: (x, y) in frame heights from the centre (+x right, +y up; the frame
    spans y in [-0.5, 0.5] and x in [-ASPECT/2, ASPECT/2]) and its depth along the view (m); ``None`` behind
    the camera."""
    loc, aim = cam["location"], cam["aim"]
    f = [aim[i] - loc[i] for i in range(3)]
    fl = math.sqrt(sum(v * v for v in f)) or 1.0
    f = [v / fl for v in f]
    r = [f[1], -f[0], 0.0]  # right = forward x up(Z)
    rl = math.hypot(r[0], r[1]) or 1.0
    r = [r[0] / rl, r[1] / rl, 0.0]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    d = [point[i] - loc[i] for i in range(3)]
    z = sum(d[i] * f[i] for i in range(3))
    if z <= 0.1:
        return None
    k = 1.0 / (2 * math.tan(vfov(cam["lens"]) / 2) * z)
    return (sum(d[i] * r[i] for i in range(3)) * k, sum(d[i] * u[i] for i in range(3)) * k, z)


def in_frame(cam: dict[str, Any], point: tuple[float, float, float], margin: float = 0.05) -> bool:
    """True if ``point`` projects inside the camera's frame (``cam``: location, aim, lens), with a margin as a
    fraction of the frame (a bit outside still counts: an ear or a tail pokes in)."""
    loc, aim = cam["location"], cam["aim"]
    f = [aim[i] - loc[i] for i in range(3)]
    fl = math.sqrt(sum(v * v for v in f)) or 1.0
    f = [v / fl for v in f]
    r = [f[1], -f[0], 0.0]  # right = forward x up(Z)
    rl = math.hypot(r[0], r[1]) or 1.0
    r = [r[0] / rl, r[1] / rl, 0.0]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    d = [point[i] - loc[i] for i in range(3)]
    z = sum(d[i] * f[i] for i in range(3))
    if z <= 0.1:
        return False
    half_v = math.tan(vfov(cam["lens"]) / 2)
    half_h = half_v * ASPECT
    x = sum(d[i] * r[i] for i in range(3)) / z
    y = sum(d[i] * u[i] for i in range(3)) / z
    return abs(x) <= half_h * (1 + margin) and abs(y) <= half_v * (1 + margin)


def actor_speeds(spec: SceneSpec) -> dict[str, float]:
    """Each actor's gait pace (m/s) for untimed moves (``schedule(..., speeds=)``), from the rig's leg."""
    from animatica.creatures.build import build_creature
    from animatica.creatures.gait import GAITS
    from animatica.creatures.species import SPECIES

    out = {}
    for cid, a in spec.cast.items():
        _, meta = build_creature(cid, SPECIES[a.species], at=a.at)
        g = GAITS[a.species].get(a.gait) or GAITS[a.species]["walk"]
        out[cid] = g.nominal_speed(meta.leg)
    return out


def check_frames(
    spec: SceneSpec,
    shots: list[dict[str, Any]],
    where: dict[str, list[tuple[float, float, float]]],
    fps: int,
) -> list[Violation]:
    """On the real cameras: every actor off stage during a shot must be outside its frame.

    ``shots``: the scene's shot report (``start``, ``end``, ``location``, ``end_location``, ``aim``, ``lens``);
    ``where``: per actor, per frame (from frame 1), a world point to test (the head)."""
    out: list[Violation] = []
    for sh in shots:
        f0, f1 = 1 + int(sh["start"] * fps), 1 + int(sh["end"] * fps) - 1
        for cid, pts in where.items():
            if spec.cast[cid].extra:
                continue
            for f in range(f0, max(f0, f1) + 1, max(1, fps // 4)):
                t = (f - 1) / fps
                if on_stage(spec, cid, t):
                    continue
                u = (f - f0) / max(1, f1 - f0)
                loc = [
                    a + (b - a) * u for a, b in zip(sh["location"], sh.get("end_location", sh["location"]))
                ]
                if in_frame({**sh, "location": loc}, pts[min(len(pts) - 1, f - 1)]):
                    out.append(
                        Violation(
                            spec.id,
                            "offstage_seen",
                            cid,
                            round(t, 2),
                            f"off stage but in shot {sh['shot']} ({sh['type']})",
                        )
                    )
                    break
    return out
