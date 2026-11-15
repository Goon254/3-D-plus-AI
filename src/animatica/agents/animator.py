"""Animator: shot list + rig -> keyframes, applying the 12 principles where they matter most at this scale:

* timing & easing (ease-in/out on every move, holds between beats)
* anticipation (lean back / dip before moving forward, head ducks before the "notice")
* overshoot & settle (head turns use BACK easing; root stops with a small overshoot)
* follow-through & overlapping action (antenna/tail is a damped spring driven by root acceleration;
  arms lag the body)
* secondary motion (tread bob while moving, idle breathing, flower sway, blinks)
* squash & stretch (hops, the settle at the end)
* lip sync (Rhubarb visemes -> mouth shape keys)

Big moves are authored as sparse pose curves; secondary layers are added on top and the composite is
sampled every ``step`` frames into one batched ``insert_keyframes`` op per channel.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..core.llm import scripted
from ..knowledge import lookup
from .base import Agent

if TYPE_CHECKING:
    from ..core.orchestrator import Context

SYSTEM = """You are the lead Animator. For each shot, choose performance parameters (not keyframes).
Return JSON {"shots": {"<shot id>": {"energy": 0..1, "speed": 0.6..1.5, "head_tilt": -20..20,
"reach": bool, "bounce": bool, "look_around": bool}}}. Favour clear silhouettes, anticipation before
big moves, and holds so the audience can read emotions."""


# ------------------------------------------------------------------------------------------ easing
def ease(kind: str, u: float) -> float:
    u = min(1.0, max(0.0, u))
    if kind == "linear":
        return u
    if kind == "in":
        return u * u * u
    if kind == "out":
        return 1 - (1 - u) ** 3
    if kind == "back":  # overshoot then settle
        c1, c3 = 1.70158, 2.70158
        return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2
    if kind == "hold":
        return 0.0 if u < 1 else 1.0
    return 3 * u * u - 2 * u * u * u if kind == "smooth" else (4 * u**3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2)


@dataclass
class Curve:
    """Piecewise pose curve: keys (time_s, value, ease_into_this_key)."""

    default: float = 0.0
    keys: list[tuple[float, float, str]] = field(default_factory=list)

    def key(self, t: float, v: float, e: str = "inout") -> Curve:
        self.keys.append((t, v, e))
        self.keys.sort(key=lambda k: k[0])
        return self

    def __call__(self, t: float) -> float:
        if not self.keys:
            return self.default
        if t <= self.keys[0][0]:
            return self.keys[0][1]
        for (t0, v0, _), (t1, v1, e) in zip(self.keys, self.keys[1:]):
            if t <= t1:
                return v0 + (v1 - v0) * ease(e, (t - t0) / max(t1 - t0, 1e-6))
        return self.keys[-1][1]


@dataclass
class Rig:
    root_x: Curve = field(default_factory=lambda: Curve(-5.5))
    root_yaw: Curve = field(default_factory=lambda: Curve(90.0))
    root_hop: Curve = field(default_factory=Curve)
    lean: Curve = field(default_factory=Curve)
    dip: Curve = field(default_factory=Curve)
    squash: Curve = field(default_factory=lambda: Curve(1.0))
    head_turn: Curve = field(default_factory=Curve)
    head_nod: Curve = field(default_factory=Curve)
    head_tilt: Curve = field(default_factory=Curve)
    eye_open: Curve = field(default_factory=lambda: Curve(1.0))
    eye_size: Curve = field(default_factory=lambda: Curve(1.0))
    arm_L: Curve = field(default_factory=Curve)
    arm_R: Curve = field(default_factory=Curve)
    elbow_L: Curve = field(default_factory=lambda: Curve(-12.0))  # negative = forearm bends forward
    elbow_R: Curve = field(default_factory=lambda: Curve(-12.0))
    blinks: list[float] = field(default_factory=list)


def spring(drive: list[float], dt: float, k: float = 90.0, c: float = 7.0, gain: float = 1.0) -> list[float]:
    """Damped spring driven by an external acceleration signal -> follow-through angle."""
    x, v, out = 0.0, 0.0, []
    for a in drive:
        acc = -k * x - c * v - gain * a
        v += acc * dt
        x += v * dt
        out.append(x)
    return out


# ------------------------------------------------------------------------------------------ performance
def wheel_spin_degrees(xs: list[float], radius: float, max_step: float = 35.0) -> list[float]:
    """Cumulative wheel rotation (degrees, about the axle) for a root path sampled per frame.

    The hero always drives forward (it yaws to face its direction of travel), so the wheel turns by the
    absolute distance covered: angle = arc length / radius. Without motion blur a wheel turning more than
    ~45 deg per frame strobes (wagon-wheel effect: it reads as still or backwards), so the per-frame step
    is capped at ``max_step`` -- the usual cartoon cheat; a spinning wheel still reads as driving.
    """
    out, acc = [], 0.0
    for i, x in enumerate(xs):
        if i:
            acc += min(max_step, math.degrees(abs(x - xs[i - 1]) / radius))
        out.append(acc)
    return out


def default_performance(plan: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for s in plan["shots"]:
        b = s["beat"]
        out[s["id"]] = {
            "energy": {"enter": 0.6, "discover": 0.8, "speak": 0.5, "react": 0.9, "celebrate": 1.0, "settle": 0.3}.get(b, 0.5),
            "speed": 1.0, "head_tilt": 12 if b in ("speak", "settle") else 0,
            "reach": b == "speak", "bounce": b in ("react", "celebrate") or (b == "speak"),
            "look_around": b == "enter",
        }
    return {"shots": out}


@scripted("animator.performance")
def _scripted_perf(payload: dict[str, Any]) -> dict[str, Any]:
    return default_performance(payload["plan"])


class Animator(Agent):
    role = "animator"
    task = "animator.performance"
    system_prompt = SYSTEM

    def build_rig(self, ctx: Context, perf: dict[str, Any]) -> tuple[Rig, dict[str, Any]]:
        plan = ctx.plan
        fps = plan.fps
        frames = plan.shot_frames()
        rig = Rig()
        prop_x = plan.prop.location[0] if plan.prop else 1.3
        reach_gap = 0.95 if plan.hero.kind == "robot" else 0.75
        stand_x = prop_x - reach_gap * plan.hero.scale
        start_x = -5.5 if plan.shots[0].beat == "enter" else stand_x - 1.5
        x = start_x
        notes: dict[str, Any] = {"stand_x": stand_x}
        rig.root_x.key(0, start_x)
        rig.head_turn.key(0, 0)
        for shot in plan.shots:
            f0, f1 = frames[shot.id]
            t0, t1 = (f0 - 1) / fps, f1 / fps
            dur = t1 - t0
            p = perf.get(shot.id, {})
            energy = float(p.get("energy", 0.5))
            speed = max(0.6, min(1.5, float(p.get("speed", 1.0))))
            tilt = float(p.get("head_tilt", 0))
            if shot.beat == "enter":
                end_x = stand_x - 1.5
                move_end = t0 + min(dur - 0.5, dur * 0.85 / speed)
                rig.root_x.key(t0 + 0.2, x, "linear").key(move_end, end_x + 0.08, "inout").key(move_end + 0.35, end_x, "out")
                rig.lean.key(t0 + 0.2, 0).key(t0 + 0.9, 7 * energy + 3).key(move_end - 0.4, 5).key(move_end + 0.1, -5 * energy, "out").key(move_end + 0.6, 0)
                if p.get("look_around", True):
                    rig.head_turn.key(t0 + 1.4, 0).key(t0 + 2.0, -28, "back").key(t0 + 3.0, -28, "hold").key(t0 + 3.5, 18, "back").key(move_end, 18)
                    rig.head_turn.key(t1, -30, "inout")  # ends looking away towards camera: sets up the "notice"
                rig.blinks += [t0 + 1.2, t0 + 3.8]
                x = end_x
            elif shot.beat in ("discover", "approach"):
                # anticipation: head snaps to the prop (overshoot), eyes widen, lean back, then approach
                notice = t0 + 0.5
                rig.head_turn.key(notice, -30, "hold").key(notice + 0.35, 0, "back")
                rig.head_nod.key(notice, 0).key(notice + 0.3, 8, "back")
                rig.eye_size.key(notice, 1.0).key(notice + 0.25, 1.35, "back").key(notice + 1.6, 1.15)
                rig.dip.key(notice + 0.4, 0).key(notice + 0.8, -0.05 * energy - 0.02, "out").key(notice + 1.3, 0.0)
                rig.lean.key(notice + 0.5, 0).key(notice + 1.0, -9 * energy, "out")  # anticipation lean back
                move_start = notice + 1.15
                move_end = min(t1 - 0.9, move_start + 2.2 / speed)
                rig.root_x.key(move_start, x, "hold").key(move_end, stand_x, "inout")
                rig.lean.key(move_start + 0.25, 6, "out").key(move_end - 0.2, 3).key(move_end + 0.4, 13 * energy + 4, "back")
                rig.head_nod.key(move_end, 6).key(move_end + 0.5, 16, "inout")
                rig.blinks += [notice + 1.9]
                x = stand_x
            elif shot.beat == "speak":
                lines = [d for d in plan.dialogue if d.shot == shot.id]
                rig.lean.key(t0 + 0.4, 10, "inout")
                rig.head_nod.key(t0 + 0.3, 12).key(t0 + 1.0, 8)
                if tilt:
                    rig.head_tilt.key(t0 + 0.3, 0).key(t0 + 1.1, tilt, "inout")
                for d in lines:
                    ts = t0 + d.at
                    dur_line = ctx.state.artifacts.get("lines", {}).get(d.id, {}).get("duration", 1.5)
                    rig.head_nod.key(ts - 0.15, 4).key(ts + 0.25, 14, "out").key(ts + dur_line, 9)
                    rig.eye_size.key(ts, 1.12).key(ts + 0.3, 1.25, "back").key(ts + dur_line + 0.4, 1.1)
                    if p.get("reach"):
                        reach_t = ts + dur_line + 0.3
                        # the camera-side arm (R: the hero faces +X, cameras sit on -Y) does the acting
                        rig.arm_R.key(ts + 0.2, 0).key(reach_t, -38, "inout").key(min(t1 - 0.6, reach_t + 1.5), -50).key(t1, -20)
                        # gentle reach: elbow folds first (anticipation), then the forearm extends toward the prop
                        rig.elbow_R.key(ts + 0.2, -12).key(reach_t - 0.3, -55, "inout").key(reach_t + 0.5, -20, "out").key(t1, -15)
                    if p.get("bounce"):
                        hop_t = ts + dur_line + 0.15
                        if hop_t + 0.6 < t1:
                            rig.dip.key(hop_t, 0).key(hop_t + 0.12, -0.04, "out").key(hop_t + 0.3, 0.03, "out").key(hop_t + 0.55, 0, "inout")
                            rig.squash.key(hop_t, 1.0).key(hop_t + 0.12, 0.93).key(hop_t + 0.3, 1.05).key(hop_t + 0.55, 1.0)
                rig.blinks += [t0 + 0.4, t0 + dur - 1.3]
                if tilt:
                    rig.head_tilt.key(t1, tilt * 0.6)
            elif shot.beat in ("react", "celebrate"):
                for k in range(2 if shot.beat == "react" else 3):
                    ht = t0 + 0.8 + 0.8 * k
                    if ht + 0.7 > t1:
                        break
                    rig.squash.key(ht, 1.0).key(ht + 0.12, 0.88, "out").key(ht + 0.3, 1.1).key(ht + 0.6, 1.0)
                    rig.root_hop.key(ht + 0.12, 0).key(ht + 0.35, 0.25 * energy, "out").key(ht + 0.6, 0, "in")
                rig.eye_size.key(t0 + 0.5, 1.4, "back")
                rig.arm_L.key(t0 + 0.6, -120 * energy, "back").key(t1 - 0.5, -20)
                rig.arm_R.key(t0 + 0.7, -120 * energy, "back").key(t1 - 0.4, -20)
                for k in range(4):  # waving forearms
                    rig.elbow_L.key(t0 + 0.9 + 0.35 * k, -60 if k % 2 == 0 else -15, "inout")
                    rig.elbow_R.key(t0 + 1.0 + 0.35 * k, -15 if k % 2 == 0 else -60, "inout")
                rig.blinks += [t0 + 0.3]
            elif shot.beat == "settle":
                rig.lean.key(t0 + 0.6, 4, "inout")
                rig.dip.key(t0 + 0.8, 0).key(t0 + 2.0, -0.09, "inout")
                rig.squash.key(t0 + 0.8, 1.0).key(t0 + 2.0, 0.94, "inout")
                rig.head_tilt.key(t0 + 1.0, tilt or 10, "inout")
                rig.head_nod.key(t0 + 1.0, 10)
                rig.eye_open.key(t0 + 1.5, 1.0).key(t0 + 2.6, 0.55, "inout")
                rig.arm_R.key(t0 + 0.5, -20).key(t0 + 1.8, -8)
                rig.blinks += [t0 + 0.5]
            elif shot.beat == "idle":
                # alone: slow look around, a sigh (dip + head drop + droopy eyes), blinks; no travel
                rig.root_x.key(t0, x, "hold")
                rig.head_turn.key(t0 + 0.6, 0).key(t0 + 1.6, -35, "inout").key(t0 + 2.4, -35, "hold").key(t0 + 3.3, 25, "inout")
                sigh = t0 + dur * 0.62
                rig.dip.key(sigh - 0.3, 0).key(sigh + 0.4, -0.05, "inout").key(sigh + 1.4, -0.02, "inout")
                rig.head_nod.key(sigh - 0.2, 0).key(sigh + 0.5, 18, "inout")
                rig.eye_open.key(sigh, 1.0).key(sigh + 0.5, 0.65, "inout")
                rig.head_turn.key(t1, -30, "inout")  # looking away: sets up the "notice"
                rig.eye_open.key(t1 - 0.1, 0.7)
                rig.blinks += [t0 + 1.0, t0 + 3.0]
            elif shot.beat == "exit":
                # anticipation, turn back the way it came, a last look over the shoulder, roll away
                rig.lean.key(t0 + 0.3, 0).key(t0 + 0.6, -6, "out").key(t0 + 1.0, 0)
                rig.root_yaw.key(t0 + 0.5, 90).key(t0 + 1.5, 270, "back")
                rig.head_turn.key(t0 + 1.6, 0).key(t0 + 2.3, -150, "inout").key(t0 + 3.0, -150, "hold").key(t0 + 3.5, 0, "inout")
                rig.root_x.key(t0 + 3.4, x, "hold").key(t1, x - 3.5, "in")
                rig.lean.key(t0 + 3.6, 8, "out")
                x = x - 3.5
        end_t = frames[plan.shots[-1].id][1] / fps
        notes["end_t"] = end_t
        return rig, notes

    def run(self, ctx: Context) -> dict[str, Any]:
        plan = ctx.plan
        perf = self.ask(ctx, {"plan": plan.model_dump(mode="json"), "knowledge": lookup("anticipation overshoot follow-through secondary motion dialogue acting")})
        perf_shots = perf.get("shots", {})
        for sid, override in ctx.state.tuning.get("performance", {}).items():  # artist revisions win
            perf_shots.setdefault(sid, {}).update(override)
        rig, notes = self.build_rig(ctx, perf_shots)
        tune = ctx.state.tuning.get("animator", {})
        fps, end_f = plan.fps, plan.frame_end
        step = int(tune.get("step", 2))
        frames = list(range(1, end_f + 1, step))
        if frames[-1] != end_f:
            frames.append(end_f)
        dt = 1 / fps
        ts_all = [(f - 1) / fps for f in range(1, end_f + 1)]
        xs = [rig.root_x(t) for t in ts_all]
        vel = [0.0] + [(b - a) / dt for a, b in zip(xs, xs[1:])]
        acc = [0.0] + [(b - a) / dt for a, b in zip(vel, vel[1:])]
        antenna = spring(acc, dt, k=80, c=6, gain=4.0)
        arm_lag = spring(acc, dt, k=60, c=9, gain=2.0)
        speed = [abs(v) for v in vel]
        floor_offset = float(tune.get("floor_offset", 0.0))

        def at(f: int, series: list[float]) -> float:
            return series[min(len(series) - 1, f - 1)]

        def sample(fn: Callable[[int, float], Any]) -> list[list[Any]]:
            return [[f, fn(f, (f - 1) / fps), "BEZIER"] for f in frames]

        def r(v: float, n: int = 4) -> float:
            return round(v, n)

        breathe = lambda t: 0.006 * math.sin(2 * math.pi * t / 2.6)  # noqa: E731
        def bob(f: int, t: float) -> float:
            amp = 0.012 * min(1.0, at(f, speed) / 1.2)
            wave = math.sin(2 * math.pi * 5.0 * t)
            return amp * (wave if robot else abs(wave) * 2.5)  # treads rattle; paws hop
        body_base_z = 0.55 if plan.hero.kind == "robot" else 0.33
        body_half = 0.25 if plan.hero.kind == "robot" else 0.306  # squash is anchored at the contact point
        robot = plan.hero.kind == "robot"
        dip_scale = 1.0 if robot else 0.0  # a critter has no treads to sink into: its dips become squash

        def sq(t: float) -> float:
            # critter dips are expressed as squash (volume-preserving, anchored at the feet)
            return rig.squash(t) + (0.0 if robot else 1.6 * rig.dip(t))

        ops: list[dict[str, Any]] = [
            {"op": "set_frame_range", "start": 1, "end": end_f, "fps": fps},
            {"op": "insert_keyframes", "target": "hero_root", "property": "location",
             "keys": sample(lambda f, t: [r(rig.root_x(t)), 0.0, r(rig.root_hop(t) + floor_offset)])},
            {"op": "insert_keyframes", "target": "hero_root", "property": "rotation",
             "keys": sample(lambda f, t: [0.0, 0.0, r(rig.root_yaw(t), 2)])},
            {"op": "insert_keyframes", "target": "hero_body", "property": "location",
             "keys": sample(lambda f, t: [0.0, 0.0, r(body_base_z + dip_scale * rig.dip(t) - body_half * (1 - sq(t))
                                                    + breathe(t) + bob(f, t))])},
            {"op": "insert_keyframes", "target": "hero_body", "property": "rotation",
             "keys": sample(lambda f, t: [r(rig.lean(t) + 2.5 * math.sin(2 * math.pi * 2.5 * t) * min(1.0, at(f, speed) / 1.2), 2),
                                          r(1.2 * math.sin(2 * math.pi * t / 3.1), 2), 0.0])},
            {"op": "insert_keyframes", "target": "hero_body", "property": "scale",
             "keys": sample(lambda f, t: [r(1 + (1 - sq(t)) * 0.5), r(1 + (1 - sq(t)) * 0.5), r(sq(t) + breathe(t))])},
            {"op": "insert_keyframes", "target": "hero_head_pivot", "property": "rotation",
             "keys": sample(lambda f, t: [r(rig.head_nod(t) + 1.5 * math.sin(2 * math.pi * t / 2.6 + 0.6), 2),
                                          r(rig.head_tilt(t), 2), r(rig.head_turn(t), 2)])},
            {"op": "insert_keyframes", "target": "hero_antenna_pivot", "property": "rotation",
             "keys": sample(lambda f, t: [r(math.degrees(at(f, antenna)) * 0.9 + 3 * math.sin(2 * math.pi * t / 1.7), 2),
                                          r(2 * math.sin(2 * math.pi * t / 2.3), 2), 0.0])},
        ]
        for side, curve in (("L", rig.arm_L), ("R", rig.arm_R)):
            sgn = 1 if side == "L" else -1
            ops.append({"op": "insert_keyframes", "target": f"hero_arm_pivot_{side}", "property": "rotation",
                        "keys": sample(lambda f, t, c=curve, s=sgn: [r(c(t) + math.degrees(at(f, arm_lag)) * 0.5
                                                                         + 2 * math.sin(2 * math.pi * t / 2.6 + s), 2),
                                                                       r(4 * s, 2), 0.0])})
        if "hero_elbow_L" in ctx.engine.known_ids:  # jointed arms: elbow bend + overlapping lag behind the shoulder
            for side, curve in (("L", rig.elbow_L), ("R", rig.elbow_R)):
                ops.append({"op": "insert_keyframes", "target": f"hero_elbow_{side}", "property": "rotation",
                            "keys": sample(lambda f, t, c=curve: [r(c(t) + math.degrees(at(f, arm_lag)) * 0.8, 2), 0.0, 0.0])})
        if robot and "hero_wheel_L0" in ctx.engine.known_ids:  # wheels roll by distance travelled (no skating)
            spin = wheel_spin_degrees(xs, 0.075 * plan.hero.scale)
            for side in ("L", "R"):
                for j in range(3):
                    ops.append({"op": "insert_keyframes", "target": f"hero_wheel_{side}{j}", "property": "rotation",
                                "keys": sample(lambda f, t: [r(at(f, spin), 1), 0.0, 0.0])})
        # eyes: blink = fast scale-Z dip (2 frames down, 3 up), multiplied with eye size and openness
        def eye_z(t: float) -> float:
            b = 1.0
            for bt in rig.blinks:
                if bt - 0.08 <= t <= bt + 0.14:
                    u = (t - (bt - 0.08)) / 0.22
                    b = min(b, abs(2 * u - 1) ** 1.5 * 0.95 + 0.05)
            return rig.eye_size(t) * rig.eye_open(t) * b

        eye_frames = sorted(set(frames) | {f for bt in rig.blinks for f in
                                            range(int((bt - 0.12) * fps) + 1, int((bt + 0.2) * fps) + 2) if 1 <= f <= end_f})
        base = (1.0, 0.35, 1.25) if plan.hero.kind == "robot" else (1.0, 0.5, 1.3)
        for side in ("L", "R"):
            ops.append({"op": "insert_keyframes", "target": f"hero_eye_{side}", "property": "scale",
                        "keys": [[f, [r(base[0] * rig.eye_size((f - 1) / fps)), base[1], r(base[2] * eye_z((f - 1) / fps))], "BEZIER"]
                                 for f in eye_frames]})
        # flower / prop sway (secondary motion of the world)
        if plan.prop:
            ops.append({"op": "insert_keyframes", "target": "prop_pivot", "property": "rotation",
                        "keys": [[f, [r(3.5 * math.sin(2 * math.pi * (f / fps) / 3.3), 2), r(5 * math.sin(2 * math.pi * (f / fps) / 4.1 + 1), 2), 0.0],
                                  "BEZIER"] for f in range(1, end_f + 1, 6)]})
        # "until a flower blooms": in the idle arc the prop grows in at the start of the discover beat
        grow = plan.prop and plan.shots[0].beat == "idle" and any(
            w in plan.prompt.lower() for w in ("bloom", "grow", "sprout", "appear", "lands", "falls"))
        if grow and len(plan.shots) > 1:
            g0 = plan.shot_frames()[plan.shots[1].id][0]
            ops.append({"op": "insert_keyframes", "target": "prop", "property": "scale",
                        "keys": [[1, [0.01, 0.01, 0.01], "CONSTANT"], [g0, [0.01, 0.01, 0.01], "BACK"],
                                 [g0 + int(0.8 * fps), [1.0, 1.0, 1.0], "BEZIER"]]})
        # lip sync
        mouth_keys = ctx.state.artifacts.get("mouth_keys") or {}
        for key, keys in mouth_keys.items():
            if keys:
                ops.append({"op": "insert_keyframes", "target": "hero_mouth", "property": f"shape_key:{key}", "keys": keys})
        n_keys = sum(len(o.get("keys", [])) for o in ops)
        res = self.submit(ctx, self.batch(f"Animate {plan.hero.name}: {len(plan.shots)} shots, {n_keys} keys "
                                          f"(anticipation, overshoot, follow-through, lip sync)", ops))
        ctx.log.event("decision", self.role, f"performance per shot: {perf_shots}", performance=perf_shots)
        return {"keys": n_keys, "batch": res.batch_id, "root_x": rig.root_x, **notes}
