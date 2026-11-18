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
* **Off stage means out of sight.** While off stage an actor must be away from the set
  (``OFFSTAGE_M`` from every action circle), and, once the cameras exist, outside every frame
  (:func:`in_frame`, used by ``scripts/savannah_scene.py`` on the real camera positions).

Pure Python: ``scripts/continuity_check.py`` runs it over the whole film before anything renders.
"""

from __future__ import annotations

import math
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
