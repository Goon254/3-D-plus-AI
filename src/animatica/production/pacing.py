"""Dead air: a stretch of the film, across cuts, where nothing on screen moves but the camera.

The owner's first animatic note (11-16) was "the first scene has no animal movement": SC 1 was 22 s of empty set
under the narration, two set-only shots, an EWS and a WS of the puddle. The per-shot check in
``scripts/savannah_animatic.py`` (``static_shots``) cannot see it: every shot now pushes in and orbits
(``scene.shot_move``), so each shot "moves" by more than 2 % of the frame, and a cut to a second still picture
resets it. What the owner saw was that nothing *happens*. So this check ignores the camera and the cuts and asks,
every quarter second, whether anything on screen is alive:

* an animal (cast or extra) in the frame and big enough to read (``MIN_SIZE`` of the frame height) that travels
  ``MOVE_FRAC`` of the frame height on the film within ``WINDOW_S`` (measured through the same camera, so the
  camera's own drift doesn't count) or turns by ``TURN_DEG``;
* an animal in the frame that speaks on screen, gestures (``gestures``), or changes expression (``reactions``,
  for ``REACT_S``);
* a bird flock in flight (``layout.birds``) or a prop moving on its keys (``layout.props[].moves``) in the frame;
* the spring bursting (``layout.spring``, for ``SPRING_S``) with the water in the frame.

Grass sway, water shimmer and the light are ambience, not action. A run of samples with none of these longer than
``MAX_DEAD_S`` (4.5 s, the same limit ``split_long`` and ``static_shots`` use) is a ``dead_air`` finding. A shot
marked ``hold`` (a deliberate still beat, a story reason: DESIGN_STAGE §7) is not counted against a run.

It runs on approximate cameras (``staging.approx_cameras``) in ``scripts/continuity_check.py --cameras``, before
anything renders, so it can stop a static opening at the script stage, not at the owner's review. It runs again on
the real cameras: ``scripts/savannah_scene.py`` checks each scene's shot cameras against its gait plans (printed
as ``CONTINUITY … dead_air``), and ``scripts/savannah_animatic.py`` lists it per scene from the scene reports
(``dead_air_in_report``: the report's cameras and line timings, the paths as scheduled), soft, next to the
horizon stripes, so the animatic's own report shows it.
"""

from __future__ import annotations

import math
from typing import Any

from animatica.production.continuity import Violation, actor_speeds, in_frame, on_stage, project
from animatica.production.scene import SceneSpec, schedule, vfov
from animatica.production.staging import _meta, _subject, poses_from_paths

MAX_DEAD_S = 4.5  # longest stretch with nothing moving on screen (DESIGN_STAGE §7: "~4 s")
STEP_S = 0.25
WINDOW_S = 1.0  # motion measured between t - WINDOW_S / 2 and t + WINDOW_S / 2
MOVE_FRAC = 0.02  # frame heights of travel on the film inside the window that read as moving
TURN_DEG = 15.0  # ... or this much turn of the body inside the window
MIN_SIZE = 0.02  # an animal shorter than this share of the frame height is a speck: its motion doesn't read
REACT_S = 0.8  # an expression change reads for this long
SPRING_S = 2.5  # the spring's burst (it grows to full for 2.5 s in savannah_scene.py)
Pose = tuple[float, float, float]


def _cam_at(sh: dict[str, Any], t: float) -> dict[str, Any]:
    u = (t - sh["start"]) / max(1e-6, sh["end"] - sh["start"])
    u = min(1.0, max(0.0, u))
    loc = [a + (b - a) * u for a, b in zip(sh["location"], sh.get("end_location", sh["location"]))]
    return {**sh, "location": loc}


def _pose(poses: dict[str, list[Pose]], c: str, t: float, fps: int) -> Pose:
    p = poses[c]
    return p[min(len(p) - 1, max(0, int(round(t * fps))))]


def _beat_t(k: Any, spec: SceneSpec) -> float:
    if isinstance(k, dict):
        if "line" in k:
            ln = spec.lines[int(k["line"])]
            return (ln.start if k.get("from") == "start" else ln.end) + float(k.get("dt", 0.0))
        return float(k.get("t", 0.0))
    return float(k[0])


def _heights(spec: SceneSpec) -> dict[str, tuple[float, float]]:
    """Per actor: (head height, head size) of its species at rest."""
    from animatica.creatures.species import SPECIES

    out = {}
    for c, a in spec.cast.items():
        out[c] = (_meta(a.species).head_height, max(SPECIES[a.species].head_size))
    return out


def _points(spec: SceneSpec, c: str, p: Pose, top: float) -> list[tuple[float, float, float]]:
    """The body's middle and the head (a close-up's subject) of actor ``c`` at pose ``p``."""
    return [(p[0], p[1], 0.5 * top), _subject(spec, c, p).head]


def life_at(
    spec: SceneSpec,
    cam: dict[str, Any],
    t: float,
    poses: dict[str, list[Pose]],
    fps: int,
    heights: dict[str, tuple[float, float]] | None = None,
) -> list[str]:
    """What moves on screen at ``t`` through ``cam`` (empty: nothing but the camera)."""
    heights = heights if heights is not None else _heights(spec)
    alive: list[str] = []
    seen: dict[str, bool] = {}
    for c in spec.cast:
        if c not in poses or not on_stage(spec, c, t):
            continue
        hh, hs = heights[c]
        top = hh + 0.5 * hs

        here = _pose(poses, c, t, fps)
        base, crown = project(cam, (here[0], here[1], 0.0)), project(cam, (here[0], here[1], top))
        head = project(cam, _subject(spec, c, here).head)
        size = max(
            abs(crown[1] - base[1]) if base and crown else 0.0,
            hs / (2 * math.tan(vfov(cam["lens"]) / 2) * head[2]) if head else 0.0,
        )
        seen[c] = size >= MIN_SIZE and any(in_frame(cam, q) for q in _points(spec, c, here, top))
        if not seen[c]:
            continue
        p0, p1 = _pose(poses, c, t - WINDOW_S / 2, fps), _pose(poses, c, t + WINDOW_S / 2, fps)
        travel = 0.0
        for a0, a1 in zip(_points(spec, c, p0, top), _points(spec, c, p1, top)):
            q0, q1 = project(cam, a0), project(cam, a1)
            if q0 and q1:
                travel = max(travel, math.dist(q0[:2], q1[:2]))
        turn = abs((p1[2] - p0[2] + 180.0) % 360.0 - 180.0)
        if travel >= MOVE_FRAC or turn >= TURN_DEG:
            alive.append(f"{c} moves")
    for ln in spec.lines:
        if seen.get(ln.who) and not ln.offscreen and ln.start <= t <= ln.end:
            alive.append(f"{ln.who} speaks")
    for g in spec.gestures:
        g0 = g.time(spec.lines)
        if seen.get(g.who) and g0 <= t <= g0 + g.dur:
            alive.append(f"{g.who} {g.value}")
    for b in spec.reactions:
        b0 = b.time(spec.lines)
        if seen.get(b.who) and b0 <= t <= b0 + REACT_S:
            alive.append(f"{b.who} looks {b.value}")
    for k, fl in enumerate(spec.layout.get("birds", [])):
        t0, t1 = float(fl.get("t0", 0.0)), float(fl.get("t1", 0.0))
        if t0 <= t <= t1:
            u = (t - t0) / max(1e-6, t1 - t0)
            p = [a_ + (b_ - a_) * u for a_, b_ in zip(fl["from"], fl["to"])]
            if in_frame(cam, (p[0], p[1], p[2])):
                alive.append(f"birds {k}")
    for pr in spec.layout.get("props", []):
        keys = sorted(
            (_beat_t(k, spec), list(k["to"] if isinstance(k, dict) else k[1])) for k in pr.get("moves", [])
        )
        for (ta, pa), (tb, pb) in zip(keys, keys[1:]):
            if (
                ta <= t <= tb
                and math.dist(pa, pb) > 0.05
                and (in_frame(cam, tuple(pa)) or in_frame(cam, tuple(pb)))
            ):
                alive.append(f"{pr.get('name', 'prop')} moves")
                break
    sp, w = spec.layout.get("spring"), spec.layout.get("water")
    if sp and w:
        t_on = _beat_t(sp, spec)
        if t_on <= t <= t_on + SPRING_S and in_frame(cam, (w[0], w[1], 0.0)):
            alive.append("the spring bursts")
    return alive


def dead_air(
    spec: SceneSpec,
    shots: list[dict[str, Any]],
    poses: dict[str, list[Pose]],
    fps: int,
    seconds: float | None = None,
    max_dead: float = MAX_DEAD_S,
) -> list[Violation]:
    """Stretches longer than ``max_dead`` seconds, across cuts, where nothing on screen moves but the camera.
    ``shots``: the cameras (``staging.approx_cameras`` or the scene's shot report: ``location``,
    ``end_location``, ``aim``, ``lens``, ``start``, ``end``). One violation per stretch, keyed by its first shot."""
    if not shots:
        return []
    end = seconds if seconds is not None else max(s["end"] for s in shots)
    heights = _heights(spec)
    n = int(end / STEP_S + 1e-6) + 1
    still: list[tuple[float, int] | None] = []  # (t, shot index) when nothing moves; None when alive or held
    for k in range(n):
        t = min(end, k * STEP_S)
        i = next((j for j, s in enumerate(shots) if s["start"] - 1e-6 <= t < s["end"]), len(shots) - 1)
        sh = shots[i]
        if sh.get("hold") or life_at(spec, _cam_at(sh, t), t, poses, fps, heights):
            still.append(None)
        else:
            still.append((t, i))
    out: list[Violation] = []
    run: list[tuple[float, int]] = []
    for s in still + [None]:
        if s is not None:
            run.append(s)
            continue
        if run and run[-1][0] - run[0][0] + STEP_S > max_dead + 1e-6:
            t0, t1 = run[0][0], min(end, run[-1][0] + STEP_S)
            a, b = shots[run[0][1]], shots[run[-1][1]]
            span = (
                f"shot {a.get('shot', run[0][1])} ({a.get('type', '?')})"
                if a is b
                else f"shot {a.get('shot', run[0][1])} ({a.get('type', '?')}) through shot "
                f"{b.get('shot', run[-1][1])} ({b.get('type', '?')})"
            )
            out.append(
                Violation(
                    spec.id,
                    "dead_air",
                    "scene",
                    round(t0, 2),
                    f"{span}: nothing on screen moves but the camera for {t1 - t0:.1f} s "
                    f"({t0:.1f}-{t1:.1f} s, max {max_dead:g}); give an animal, a flock or a prop something to "
                    f"do in frame, or mark a deliberate still beat hold",
                )
            )
        run = []
    return out


def line_durations(spec: SceneSpec, rep: dict[str, Any] | None) -> list[float]:
    """Each line's length: from a scene report's voice takes when it has every line (``lines[].start/end``),
    else a word-count estimate (0.6 s + 0.36 s a word, what the cloud uses without the voices)."""
    if rep:
        got = {
            (ln["who"], ln["text"]): ln["end"] - ln["start"] for ln in rep.get("lines", []) if "text" in ln
        }
        if all((ln.who, ln.text) in got for ln in spec.lines):
            return [got[(ln.who, ln.text)] for ln in spec.lines]
    return [0.6 + 0.36 * len(ln.text.split()) for ln in spec.lines]


def dead_air_in_report(spec: SceneSpec, rep: dict[str, Any], fps: int = 24) -> list[Violation]:
    """``dead_air`` on a rendered scene's own cameras: ``rep`` is ``savannah_scene.py``'s ``report.json``
    (``shots`` with ``location`` / ``end_location`` / ``aim`` / ``lens`` / ``hold``, ``lines`` with the takes'
    timings, ``seconds``). ``spec`` is scheduled here with the report's line timings, and the actors follow
    their scheduled paths (the gait plans follow them; a stride's sway is below ``MOVE_FRAC``). A report
    without cameras (an old one) gives nothing: re-run the scene's set-up to get them."""
    shots = [s for s in rep.get("shots", []) if {"location", "aim", "lens"} <= set(s)]
    if not shots:
        return []
    secs = schedule(spec, line_durations(spec, rep), actor_speeds(spec))
    seconds = float(rep.get("seconds", secs))
    poses = poses_from_paths(spec, max(secs, seconds), fps)
    return dead_air(spec, shots, poses, fps, seconds)
