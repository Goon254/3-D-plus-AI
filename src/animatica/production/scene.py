"""Long-form production, step 1: a machine-readable scene spec -> timed lines, a cut list and cameras.

Pure Python (no Blender), so the timing and coverage rules are unit-tested. ``scripts/savannah_scene.py``
turns a spec into a rendered, mixed scene with these functions.

A scene spec (``films/savannah/07_scenes.json``) gives, per scene: time of day, the location layout, the
cast with their marks or walking paths (gait + waypoints), the lines (speaker, text, expression beats, an
optional absolute start), reactions, SFX, and a shot list that cuts on lines (``"line": i``) or on times.

Rules:

* **Lines** start at their ``at`` time, or ``gap`` seconds after the previous line ends (never overlapping:
  an ``at`` that would overlap is pushed later and reported).
* **Scene length** = max(the spec's nominal length, last line end + tail).
* **Cuts** land on lines (a little before the first word, so the listener sees the speaker before the
  voice), are sorted, the first is at 0, and no shot is shorter than ``MIN_SHOT`` seconds.
* **Cameras** are framed from where the subjects really are (head positions measured on the posed rig):
  shot size sets the frame height, the lens sets the distance, and singles are cheated toward the
  speaker's face (3/4 view) while staying on the scene's camera side (the 180-degree rule).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from animatica.creatures.gesture import KINDS

MIN_SHOT = 1.2  # seconds: anything shorter reads as a glitch, not a cut
LINE_LEAD = 0.35  # cut to the speaker this long before the first word
SENSOR_W = 36.0  # mm (Blender's default, sensor fit AUTO = width for 16:9)
ASPECT = 16 / 9

# shot size -> (frame height as a multiple of the subject size, lens mm, camera height as a fraction of
# the aim height). "size" is the head size for close shots and the standing height for wider ones.
SHOT_SIZES: dict[str, tuple[float, float, float]] = {
    "cu": (2.0, 60.0, 0.97),  # head and a little shoulder
    "mcu": (2.9, 50.0, 0.95),  # head and chest
    "ms": (1.45, 40.0, 0.85),  # the whole animal, with headroom for the near side's perspective
    "ws": (1.0, 30.0, 0.7),  # fit every subject with room around them
    "ews": (1.0, 24.0, 0.5),  # the place: subjects small
}


@dataclass
class Line:
    who: str
    text: str
    expr: list[tuple[float, str]] = field(default_factory=list)  # (seconds into the line, expression)
    at: float | None = None
    gap: float = 0.45
    to: str = ""  # the addressee: the speaker turns partly toward them (eyeline)
    offscreen: bool = False  # heard, not seen (the speaker is off stage, e.g. lost in the grass)
    key: bool = False  # a story beat (the vow, the climax): the automatic trailer always has it
    start: float = 0.0  # filled by schedule()
    end: float = 0.0


@dataclass
class Actor:
    cid: str
    species: str
    at: tuple[float, float]
    yaw: float = 0.0  # degrees; rest faces -Y (toward the default camera side)
    gait: str = "walk"
    path: list[tuple[float, ...]] = field(default_factory=list)  # (t, x, y[, glide]) waypoints
    # the path as written, when some waypoints are timed off the lines or aimed at places (resolved by
    # schedule()): [t, x, y], {"line": i, "dt": s, "from": "end"|"start", "at": [x, y]}, {"then": s, "at": ...};
    # instead of "at", "to" names a destination ("water", "mound:0", "acacia:1", "prop:log", "actor:tembo",
    # "exit:right|left|back|front"), with "near": metres to stop short of it; without "then", the move takes
    # as long as the actor's gait needs (distance / speed); "glide": true passes through without stopping
    path_spec: list[Any] = field(default_factory=list)
    # on stage from ``enter`` (a beat: {"t": s} or {"line": i, "dt": s, "from": "start"|"end"}) until ``exit``;
    # off stage the actor must be out of every shot (production.continuity checks it)
    enter: dict[str, Any] | None = None
    exit: dict[str, Any] | None = None
    story_exit: bool = False  # leaves the group at the end of this scene: must re-enter in a later scene
    extra: bool = False  # a background animal (not a character): no lines, no story continuity
    ride: str | None = None  # rides on this cast member's back all scene (Kiki on Neema, SC 10)
    t_in: float = 0.0  # filled by schedule()
    t_out: float = 1e9
    open_from: float = 1e9  # an exit walk starts here: it may still be under way when the scene ends


@dataclass
class Shot:
    type: str
    subjects: list[str]
    t: float | None = None
    line: int | None = None
    side: float = 0.0  # degrees to swing the camera around the subject (+ = toward the subject's left)
    after: float | None = None  # with ``line``: cut this long after the line ENDS (a reaction shot)
    look: tuple[float, float, float] | None = None  # set-only shots: where to look
    frame_h: float | None = None  # set-only shots: frame height in metres at ``look``
    start: float = 0.0  # filled by cut_list()
    end: float = 0.0
    note: str = ""
    from_behind: bool = False  # a deliberate back view (a story reason): ``staging.facing_away`` skips it
    hold: bool = False  # a deliberate still beat (a story reason): ``pacing.dead_air`` doesn't count it
    crowd_ok: bool = False  # a foreground body is the point (a story reason): ``framing.crowding`` skips it
    trailer: bool = False  # a picture moment (the spring bursting): the auto trailer cuts to it


@dataclass
class Beat:
    """A timed event: at ``t`` seconds, or ``dt`` seconds after line ``line`` ends."""

    value: str  # expression (reactions) or SFX kind
    who: str = ""
    t: float | None = None
    line: int | None = None
    dt: float = 0.0

    def time(self, lines: list[Line]) -> float:
        return round(self.t if self.t is not None else lines[self.line].end + self.dt, 3)  # type: ignore[index]


@dataclass
class GestureBeat(Beat):
    """An acting gesture (``animatica.creatures.gesture.KINDS``) by ``who``: ``value`` is the kind."""

    dur: float = 1.5
    target: str = ""
    amount: float = 1.0


def _beat(d: Any, kind: str) -> Beat:
    if isinstance(d, dict):
        return Beat(
            value=d["expr" if kind == "reaction" else "kind"],
            who=d.get("who", ""),
            t=d.get("t"),
            line=d.get("line"),
            dt=float(d.get("dt", 0.0)),
        )
    if kind == "reaction":
        return Beat(t=float(d[0]), who=d[1], value=d[2])
    return Beat(t=float(d[0]), value=d[1])


@dataclass
class SceneSpec:
    id: str
    title: str
    tod: str
    cue: str
    seconds: float
    layout: dict[str, Any]
    cast: dict[str, Actor]
    lines: list[Line]
    shots: list[Shot]
    reactions: list[Beat] = field(default_factory=list)  # who changes expression when
    sfx: list[Beat] = field(default_factory=list)
    gestures: list[GestureBeat] = field(default_factory=list)
    eyelines: bool = True  # listeners turn their heads toward whoever is speaking
    ambience: dict[str, Any] = field(default_factory=dict)
    tail: float = 1.6
    lead: float = 1.0
    warnings: list[str] = field(default_factory=list)


def _actor(cid: str, d: dict[str, Any]) -> Actor:
    return Actor(
        cid=cid,
        species=d["species"],
        at=(float(d["at"][0]), float(d["at"][1])),
        yaw=float(d.get("yaw", 0.0)),
        gait=d.get("gait", "walk"),
        path=[(float(p[0]), float(p[1]), float(p[2])) for p in d.get("path", []) if not isinstance(p, dict)],
        path_spec=list(d.get("path", [])) if any(isinstance(p, dict) for p in d.get("path", [])) else [],
        enter=d.get("enter"),
        exit=d.get("exit"),
        story_exit=bool(d.get("story_exit", False)),
        extra=bool(d.get("extra", False)),
        ride=d.get("ride"),
    )


EXIT_DIST = 16.0  # metres an exit walks on past its last mark: well outside the widest shot
EXIT_DIRS = {"right": (1.0, 0.0), "left": (-1.0, 0.0), "back": (0.0, 1.0), "front": (0.0, -1.0)}


def _beat_time(b: dict[str, Any], lines: list[Line]) -> float:
    if "line" in b:
        ln = lines[int(b["line"])]
        return (ln.start if b.get("from") == "start" else ln.end) + float(b.get("dt", 0.0))
    return float(b.get("t", 0.0))


def landmark(
    name: str,
    layout: dict[str, Any],
    here: tuple[float, float],
    others: dict[str, tuple[float, float]] | None = None,
) -> tuple[float, float]:
    """World XY of a named destination on the set (see ``Actor.path_spec``)."""
    kind, _, arg = name.partition(":")
    if kind == "exit":
        dx, dy = EXIT_DIRS[arg or "right"]
        return here[0] + dx * EXIT_DIST, here[1] + dy * EXIT_DIST
    if kind == "water":
        w = layout.get("water")
        if not w:
            raise ValueError("no water on this set")
        return float(w[0]), float(w[1])
    if kind in ("mound", "acacia"):
        items = layout.get(kind + "s", [])
        x = items[int(arg or 0)]
        return float(x[0]), float(x[1])
    if kind == "prop":
        for pr in layout.get("props", []):
            if pr.get("name") == arg:
                return float(pr["at"][0]), float(pr["at"][1])
        raise ValueError(f"no prop named {arg!r}")
    if kind == "actor":
        if not others or arg not in others:
            raise ValueError(f"no actor {arg!r} to walk to")
        return others[arg]
    raise ValueError(f"unknown destination {name!r}")


def resolve_path(
    a: Actor,
    lines: list[Line],
    layout: dict[str, Any] | None = None,
    speed: float | None = None,
    others: dict[str, tuple[float, float]] | None = None,
) -> None:
    """Turn ``a.path_spec`` into absolute ``(t, x, y[, glide])`` waypoints once the lines are placed in time:
    walks that start on a line stay on it whatever length the voice take turned out to be, destinations
    resolve to places on the set, and an untimed move takes distance / ``speed`` (the gait's own pace)."""
    if not a.path_spec:
        return
    out: list[tuple[float, ...]] = []
    for p in a.path_spec:
        if not isinstance(p, dict):
            out.append((float(p[0]), float(p[1]), float(p[2])))
            continue
        here = (out[-1][1], out[-1][2]) if out else a.at
        if "to" in p:
            x, y = landmark(p["to"], layout or {}, here, others)
            if p["to"].startswith("exit") and out:
                a.open_from = min(a.open_from, out[-1][0] + float(p.get("wait", 0.0)))
            near = float(p.get("near", 0.0))
            d = math.hypot(x - here[0], y - here[1])
            if near and d > near:  # stop short, on the line from here
                x, y = here[0] + (x - here[0]) * (1 - near / d), here[1] + (y - here[1]) * (1 - near / d)
        else:
            x, y = float(p["at"][0]), float(p["at"][1])
        if "line" in p or "t" in p:
            t = _beat_time(p, lines)
        elif "then" in p:
            t = (out[-1][0] if out else 0.0) + float(p["then"])
        else:
            if not out:
                raise ValueError(f"{a.cid}: the first waypoint needs a time")
            v = float(p.get("speed", speed or 1.0))
            # the whole run since the last stop (through any glide points) at the gait's pace
            k = len(out) - 1
            while k > 0 and len(out[k]) > 3:
                k -= 1
            chain = [(w[1], w[2]) for w in out[k:]] + [(x, y)]
            seg = [math.dist(a_, b_) for a_, b_ in zip(chain, chain[1:])]
            t = out[k][0] + float(p.get("wait", 0.0)) + sum(seg) / max(v, 0.05)
            run, acc = sum(seg) or 1.0, 0.0
            for j in range(k + 1, len(out)):  # glide points pass at their share of the run (kept in order)
                acc += seg[j - k - 1]
                out[j] = (round(out[k][0] + (t - out[k][0]) * acc / run, 3), *out[j][1:])
        wp: tuple[float, ...] = (round(t, 3), round(x, 3), round(y, 3))
        if p.get("glide"):
            wp += (1.0,)
        out.append(wp)
    if [w[0] for w in out] != sorted(w[0] for w in out):
        raise ValueError(f"{a.cid}'s path times must increase once resolved: {[w[0] for w in out]}")
    a.path = out


def scene_from_dict(d: dict[str, Any]) -> SceneSpec:
    cast = {cid: _actor(cid, a) for cid, a in d.get("cast", {}).items()}
    lines = [
        Line(
            who=ln["who"],
            text=ln["text"],
            expr=[(float(t), e) for t, e in ln.get("expr", [])],
            at=ln.get("at"),
            gap=float(ln.get("gap", 0.45)),
            to=ln.get("to", ""),
            offscreen=bool(ln.get("offscreen", False)),
            key=bool(ln.get("key", False)),
        )
        for ln in d.get("lines", [])
    ]
    shots = [
        Shot(
            type=s["type"],
            subjects=list(s.get("subjects", [])),
            t=s.get("t"),
            line=s.get("line"),
            side=float(s.get("side", 0.0)),
            after=s.get("after"),
            look=tuple(s["look"]) if s.get("look") else None,
            frame_h=s.get("frame_h"),
            note=s.get("note", ""),
            from_behind=bool(s.get("from_behind", False)),
            hold=bool(s.get("hold", False)),
            crowd_ok=bool(s.get("crowd_ok", False)),
            trailer=bool(s.get("trailer", False)),
        )
        for s in d.get("shots", [])
    ]
    spec = SceneSpec(
        id=d["id"],
        title=d.get("title", d["id"]),
        tod=d["tod"],
        cue=d.get("cue", d["id"]),
        seconds=float(d["seconds"]),
        layout=d.get("layout", {}),
        cast=cast,
        lines=lines,
        shots=shots,
        reactions=[_beat(r, "reaction") for r in d.get("reactions", [])],
        sfx=[_beat(x, "sfx") for x in d.get("sfx", [])],
        gestures=[
            GestureBeat(
                value=g["kind"],
                who=g["who"],
                t=g.get("t"),
                line=g.get("line"),
                dt=float(g.get("dt", 0.0)),
                dur=float(g.get("dur", 1.5)),
                target=g.get("target", ""),
                amount=float(g.get("amount", 1.0)),
            )
            for g in d.get("gestures", [])
        ],
        eyelines=bool(d.get("eyelines", True)),
        ambience=d.get("ambience", {}),
        tail=float(d.get("tail", 1.6)),
        lead=float(d.get("lead", 1.0)),
    )
    validate(spec)
    return spec


def load_scenes(path: str | Path) -> dict[str, SceneSpec]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {s["id"]: scene_from_dict(s) for s in data["scenes"]}


SPEAKERS_OFFSCREEN = {"narrator"}


def validate(spec: SceneSpec) -> None:
    """Raise ValueError on a spec that cannot be produced (unknown speaker, shot subject, bad path)."""
    for i, ln in enumerate(spec.lines):
        if ln.who not in spec.cast and ln.who not in SPEAKERS_OFFSCREEN:
            raise ValueError(f"{spec.id} line {i}: speaker {ln.who!r} is not in the cast")
    for i, s in enumerate(spec.shots):
        if s.type not in SHOT_SIZES:
            raise ValueError(f"{spec.id} shot {i}: unknown shot size {s.type!r}")
        for who in s.subjects:
            if who not in spec.cast:
                raise ValueError(f"{spec.id} shot {i}: subject {who!r} is not in the cast")
        if (s.t is None) == (s.line is None):
            raise ValueError(f"{spec.id} shot {i}: give exactly one of 't' or 'line'")
        if s.line is not None and not 0 <= s.line < len(spec.lines):
            raise ValueError(f"{spec.id} shot {i}: line {s.line} does not exist")
        if not s.subjects and s.type not in ("ews", "ws"):
            raise ValueError(f"{spec.id} shot {i}: a {s.type} needs a subject")
        if not s.subjects and (s.look is None or not s.frame_h):
            raise ValueError(f"{spec.id} shot {i}: a shot without subjects needs 'look' and 'frame_h'")
    for b in spec.reactions + spec.sfx:
        if (b.t is None) == (b.line is None):
            raise ValueError(f"{spec.id}: beat {b.value!r} needs exactly one of 't' or 'line'")
        if b.line is not None and not 0 <= b.line < len(spec.lines):
            raise ValueError(f"{spec.id}: beat {b.value!r} refers to a missing line {b.line}")
    for b in spec.reactions:
        if b.who not in spec.cast:
            raise ValueError(f"{spec.id}: reaction by {b.who!r}, who is not in the cast")
    for g in spec.gestures:
        if (g.t is None) == (g.line is None):
            raise ValueError(f"{spec.id}: gesture {g.value!r} needs exactly one of 't' or 'line'")
        if g.line is not None and not 0 <= g.line < len(spec.lines):
            raise ValueError(f"{spec.id}: gesture {g.value!r} refers to a missing line {g.line}")
        if g.who not in spec.cast:
            raise ValueError(f"{spec.id}: gesture by {g.who!r}, who is not in the cast")
        if g.value not in KINDS:
            raise ValueError(f"{spec.id}: unknown gesture {g.value!r} (known: {', '.join(KINDS)})")
        if g.value in ("look_at", "trunk_spray") and g.target not in spec.cast:
            raise ValueError(f"{spec.id}: {g.value} by {g.who} needs a target in the cast")
        if g.value.startswith("trunk") and spec.cast[g.who].species != "elephant":
            raise ValueError(f"{spec.id}: {g.who} has no trunk for {g.value}")
    for i, ln in enumerate(spec.lines):
        if ln.to and ln.to not in spec.cast:
            raise ValueError(f"{spec.id} line {i}: addressee {ln.to!r} is not in the cast")
    for a in spec.cast.values():
        ts = [p[0] for p in a.path]
        if ts != sorted(ts):
            raise ValueError(f"{spec.id}: {a.cid}'s path times must increase")


OFFSTAGE_M = 9.0  # metres outside the nearest action circle: far enough to be out of every shot


def offstage_distance(layout: dict[str, Any], xy: tuple[float, float]) -> float:
    """Distance (m) from ``xy`` to the edge of the nearest action circle (negative inside one)."""
    circles = layout.get("action") or [(0.0, 0.0, 4.0)]
    return min(math.hypot(xy[0] - c[0], xy[1] - c[1]) - c[2] for c in circles)


def _stage_time(a: Actor, spec: SceneSpec, beat: Any, entering: bool) -> float:
    """An entrance or exit time: a beat, or ``"auto"``: the moment the actor's path crosses ``OFFSTAGE_M``
    from the set (the last time it is still that far out, entering; the first time it gets there, exiting)."""
    if beat != "auto":
        return round(_beat_time(beat, spec.lines), 3)
    if not a.path:
        raise ValueError(f"{spec.id}: {a.cid} has an automatic entrance/exit but no path")
    from animatica.creatures.gait import Waypoint, path_xy

    pts = [Waypoint(w[0], w[1], w[2], glide=len(w) > 3 and bool(w[3])) for w in a.path]
    t0, t1 = pts[0].t, pts[-1].t
    ts = [t0 + (t1 - t0) * k / 400 for k in range(401)]
    far = [offstage_distance(spec.layout, path_xy(pts, t)) >= OFFSTAGE_M for t in ts]
    if entering:
        last = max((k for k, f in enumerate(far) if f), default=None)
        if last is None or not far[0]:
            raise ValueError(f"{spec.id}: {a.cid}'s entrance does not start off stage")
        return round(ts[last], 3)
    first = next((k for k, f in enumerate(far) if f), None)
    if first is None:
        raise ValueError(f"{spec.id}: {a.cid}'s exit never leaves the stage (walk further: 'to': 'exit:...')")
    return round(ts[first], 3)


def schedule(spec: SceneSpec, durations: list[float], speeds: dict[str, float] | None = None) -> float:
    """Place every line in time (fills ``Line.start/end``), resolve the paths (``speeds``: each actor's gait
    pace in m/s, for untimed moves) and the stage entrances/exits; return the scene length in seconds."""
    if len(durations) != len(spec.lines):
        raise ValueError("one duration per line")
    t = spec.lead
    prev_end = None
    for i, (ln, d) in enumerate(zip(spec.lines, durations)):
        want = float(ln.at) if ln.at is not None else (t if prev_end is None else prev_end + ln.gap)
        if prev_end is not None and want < prev_end + 0.15:
            spec.warnings.append(
                f"line {i} ({ln.who}) at {want:.2f}s overlaps the previous line; moved to {prev_end + 0.15:.2f}s"
            )
            want = prev_end + 0.15
        ln.start, ln.end = round(want, 3), round(want + d, 3)
        prev_end = ln.end
    marks = {cid: a.at for cid, a in spec.cast.items()}
    for cid, a in spec.cast.items():
        resolve_path(a, spec.lines, spec.layout, (speeds or {}).get(cid), marks)
        a.t_in = _stage_time(a, spec, a.enter, entering=True) if a.enter else 0.0
        a.t_out = _stage_time(a, spec, a.exit, entering=False) if a.exit else 1e9
    last = prev_end if prev_end is not None else 0.0
    # an exit's walk on past the frame doesn't stretch the scene: it is over once the actor is off stage
    latest_action = max(
        [min(p[0], a.t_out, a.open_from) for a in spec.cast.values() if not a.extra for p in a.path] + [0.0]
    )
    latest_beat = max(
        [b.time(spec.lines) for b in spec.reactions + spec.sfx]
        + [g.time(spec.lines) + min(g.dur, 2.5) - 0.5 for g in spec.gestures]  # long holds don't stretch it
        + [0.0]
    )
    return round(max(spec.seconds, last + spec.tail, latest_action + 0.5, latest_beat + 1.0), 3)


def cut_list(spec: SceneSpec, seconds: float) -> list[Shot]:
    """Resolve shot start times (cuts on lines), sort, and drop shots shorter than MIN_SHOT."""
    shots = []
    for s in spec.shots:
        if s.t is not None:
            start = s.t
        elif s.after is not None:
            start = spec.lines[s.line].end + float(s.after)  # type: ignore[index]
        else:
            start = spec.lines[s.line].start - LINE_LEAD  # type: ignore[index]
        s.start = round(max(0.0, float(start)), 3)
        shots.append(s)
    shots.sort(key=lambda s: s.start)
    if not shots:
        shots = [Shot(type="ws", subjects=list(spec.cast), t=0.0)]
    shots[0].start = 0.0
    kept: list[Shot] = []
    for i, s in enumerate(shots):
        nxt = shots[i + 1].start if i + 1 < len(shots) else seconds
        if kept and s.start < kept[-1].start + MIN_SHOT:
            # too soon after the previous cut: hold the previous shot a little longer if this one still
            # gets MIN_SHOT before the next cut, else drop this one
            late = round(kept[-1].start + MIN_SHOT, 3)
            if nxt - late >= MIN_SHOT:
                spec.warnings.append(f"shot {s.type} {s.subjects} delayed {s.start:.2f}s -> {late:.2f}s")
                s.start = late
            else:
                spec.warnings.append(
                    f"shot {s.type} {s.subjects} at {s.start:.2f}s is under {MIN_SHOT}s; dropped"
                )
                continue
        if kept and nxt - s.start < MIN_SHOT and i + 1 < len(shots):
            spec.warnings.append(
                f"shot {s.type} {s.subjects} at {s.start:.2f}s is under {MIN_SHOT}s; dropped"
            )
            continue
        kept.append(s)
    if len(kept) > 1 and seconds - kept[-1].start < MIN_SHOT:
        spec.warnings.append(f"last shot {kept[-1].type} is under {MIN_SHOT}s; merged into the previous one")
        kept.pop()
    for i, s in enumerate(kept):
        s.end = kept[i + 1].start if i + 1 < len(kept) else seconds
    return kept


def split_long(shots: list[Shot], seconds: float, max_len: float = 4.5) -> list[Shot]:
    """Cut any shot longer than ``max_len`` into equal parts, each from a new angle (the camera swings
    alternately 22 degrees either side of the written one), so no single set-up holds the screen too long
    (DESIGN_STAGE §7: no static shot longer than about 4 s)."""
    out: list[Shot] = []
    for i, s in enumerate(shots):
        end = shots[i + 1].start if i + 1 < len(shots) else seconds
        dur = end - s.start
        n = max(1, math.ceil(dur / max_len - 1e-6))
        for k in range(n):
            part = replace(s, start=round(s.start + dur * k / n, 3))
            if k:
                part.side = s.side + (22.0 if k % 2 else -22.0)
                part.note = (s.note + " " if s.note else "") + f"(part {k + 1}/{n})"
            out.append(part)
    for i, s in enumerate(out):
        s.end = out[i + 1].start if i + 1 < len(out) else seconds
    return out


def expression_tracks(spec: SceneSpec) -> dict[str, list[tuple[float, str]]]:
    """Per character: (seconds, expression) keys from the lines' beats and the reactions, time-sorted."""
    tracks: dict[str, list[tuple[float, str]]] = {cid: [(0.0, "neutral")] for cid in spec.cast}
    for ln in spec.lines:
        if ln.who in tracks:
            tracks[ln.who] += [(round(ln.start + t, 3), e) for t, e in ln.expr]
    for b in spec.reactions:
        tracks[b.who].append((b.time(spec.lines), b.value))
    return {cid: sorted(tr) for cid, tr in tracks.items()}


# ------------------------------------------------------------------------------------------- cameras
V3 = tuple[float, float, float]


def vfov(lens: float) -> float:
    return 2 * math.atan((SENSOR_W / ASPECT) / 2 / lens)


def facing(yaw: float) -> tuple[float, float]:
    """World XY direction a creature looks at heading ``yaw`` (rest faces -Y)."""
    a = math.radians(yaw)
    return (math.sin(a), -math.cos(a))


def shot_move(loc: V3 | list[float], aim: V3 | list[float], kind: str, dur: float, i: int) -> list[float]:
    """Where shot ``i``'s camera ends: every shot moves, a slow push-in with a small orbit round the aim
    (longer shots orbit further), alternating sides shot to shot, so no shot is a locked-off still."""
    dur = max(0.1, dur)
    push = 0.05 if kind in ("ws", "ews") else 0.08
    orbit = math.radians(min(8.0, 1.2 + 1.1 * dur)) * (1 if i % 2 == 0 else -1)
    rx, ry, rz = (loc[0] - aim[0], loc[1] - aim[1], loc[2] - aim[2])
    ca, sa = math.cos(orbit), math.sin(orbit)
    return [
        aim[0] + (rx * ca - ry * sa) * (1 - push),
        aim[1] + (rx * sa + ry * ca) * (1 - push),
        aim[2] + rz * (1 - push),
    ]


@dataclass
class Subject:
    head: V3  # world head centre (measured on the posed rig)
    root: V3  # world body centre
    yaw: float
    head_size: float  # largest head dimension
    height: float  # head top above the ground (standing height)
    length: float  # nose-to-tail


def set_subject(look: tuple[float, float, float], frame_h: float) -> Subject:
    """A stand-in subject for a set-only shot: a box ``frame_h`` tall at ``look``."""
    h = frame_h / 1.35
    return Subject(head=look, root=(look[0], look[1], look[2]), yaw=0.0, head_size=0.3, height=h, length=0.0)


@dataclass
class Occluder:
    """Another animal on the set: a vertical cylinder (centre, radius, height) that can block a shot."""

    x: float
    y: float
    radius: float
    height: float


def blocked(cam: V3, aim: V3, occ: Occluder, frame_h: float = 0.0, margin: float = 0.1) -> bool:
    """True if ``occ`` stands between the camera and the subject inside the middle of the frame.

    The test widens with distance like the frustum does: at a fraction ``u`` of the way to the subject the
    frame is ``u * frame_h`` tall, and anything within the central 70 % of that width (plus the occluder's
    radius) that rises above the frame's bottom edge there would fill the foreground."""
    dx, dy = aim[0] - cam[0], aim[1] - cam[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return False
    u = ((occ.x - cam[0]) * dx + (occ.y - cam[1]) * dy) / L2
    if not 0.0 < u < 0.97:  # behind the camera, or behind the subject
        return False
    px, py = cam[0] + u * dx, cam[1] + u * dy
    z = cam[2] + u * (aim[2] - cam[2])
    half_w = 0.7 * u * frame_h * ASPECT / 2
    bottom = z - u * frame_h / 2
    return math.hypot(occ.x - px, occ.y - py) < occ.radius + margin + half_w and bottom < occ.height


SWINGS = (0.0, 15.0, -15.0, 30.0, -30.0, 45.0, -45.0, 60.0, -60.0)


def frame_shot(
    kind: str,
    subjects: list[Subject],
    side: float = 0.0,
    home: V3 = (0.0, -1.0, 0.0),
    aim_z: float | None = None,
    occluders: list[Occluder] | None = None,
) -> dict:
    """Camera location, aim point and lens for a shot of ``subjects``.

    ``home`` is the scene's camera side (unit XY vector from the action toward the cameras); every camera
    stays within 70 degrees of it so screen direction holds across cuts. If another animal
    (``occluders``) stands in the line of sight, the camera swings around the subject in 15-degree steps
    (nearest first, still within the camera side) until the view is clear; ``"swing"`` reports by how much.
    """
    best = None
    for sw in SWINGS if occluders else (0.0,):
        cam = _frame(kind, subjects, side + sw, home, aim_z, sw)
        if cam is None:
            continue
        hits = sum(
            blocked(tuple(cam["location"]), tuple(cam["aim"]), o, cam["frame_h"]) for o in occluders or []
        )
        if hits == 0:
            return {**cam, "swing": sw}
        if best is None or hits < best[0]:
            best = (hits, {**cam, "swing": sw, "blocked": hits})
    if best is None:
        return {**_frame(kind, subjects, side, home, aim_z, 0.0), "swing": 0.0}  # type: ignore[dict-item]
    return best[1]


def _frame(
    kind: str,
    subjects: list[Subject],
    side: float,
    home: V3,
    aim_z: float | None,
    swing: float,
) -> dict | None:
    frac, lens, hfrac = SHOT_SIZES[kind]
    half = vfov(lens) / 2
    hx, hy = home[0], home[1]
    if kind in ("cu", "mcu"):
        s = subjects[0]
        aim = s.head
        h = frac * s.head_size
        fx, fy = facing(s.yaw)
        # 3/4: halfway between the face and the camera side, clamped to the camera side
        dx, dy = 0.6 * fx + 0.4 * hx, 0.6 * fy + 0.4 * hy
    elif kind == "ms":
        s = subjects[0]
        top = s.height
        h = max(frac * top, 1.3 * s.length / ASPECT)
        # between the body and the head, so the face is never cut by the frame edge
        aim = ((s.root[0] + s.head[0]) / 2, (s.root[1] + s.head[1]) / 2, top * 0.5)
        fx, fy = facing(s.yaw)
        dx, dy = 0.35 * fx + 0.65 * hx, 0.35 * fy + 0.65 * hy
    else:
        xs = [c for s in subjects for c in (s.root[0] - s.length / 2, s.root[0] + s.length / 2)]
        ys = [s.root[1] for s in subjects]
        top = max([s.height for s in subjects] + [1.2])
        cx = (min(xs) + max(xs)) / 2 if xs else 0.0
        cy = sum(ys) / len(ys) if ys else 0.0
        spread = (max(xs) - min(xs)) if xs else 4.0
        pad = 1.2 if kind == "ws" else 4.0
        h = max(top * 1.35, spread * pad / ASPECT, 2.5 if kind == "ws" else 7.0)
        aim = (cx, cy, min(top * 0.5, h * 0.4) if aim_z is None else aim_z)
        dx, dy = hx, hy
    # keep on the camera side: rotate toward home if the angle is over 70 degrees
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    ang = math.degrees(math.atan2(hx * dy - hy * dx, hx * dx + hy * dy))  # home -> d, CCW +
    ang = max(-70.0, min(70.0, ang))
    if swing and abs(ang + swing) > 75.0:
        return None  # a swing may not take the camera off the camera side
    ang += side
    a = math.radians(ang)
    dx, dy = hx * math.cos(a) - hy * math.sin(a), hx * math.sin(a) + hy * math.cos(a)
    dist = (h / 2) / math.tan(half)
    cz = max(0.25, aim[2] * hfrac + (0.12 * dist if kind in ("ws", "ews") else 0.0))
    loc = (aim[0] + dx * dist, aim[1] + dy * dist, cz)
    return {
        "location": [round(v, 3) for v in loc],
        "aim": [round(v, 3) for v in aim],
        "lens": lens,
        "frame_h": round(h, 3),
        "distance": round(dist, 3),
    }
