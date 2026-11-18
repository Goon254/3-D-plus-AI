"""Gait library and foot-locked locomotion planner (pure Python: testable without Blender).

The numbers come from ``knowledge/species/*.md`` (duty factors, footfall phases, stride frequencies).
A path becomes per-frame root motion plus a *world-space* target for every foot:

* A gait phase ``s`` (in strides) advances at the stride frequency for the current speed. Foot ``i`` is in
  stance while ``frac(s - phase_i) < duty``.
* **Foot-lock.** At touchdown a foot is planted where its hip/shoulder will be at mid-stance (looked up on
  the real path, so turns and speed changes are handled). During stance it does not move by a millimetre.
  The body travels over it and the leg IK does the rest.
* Swing arcs from the lift-off point to the next touchdown point: eased horizontally, with a lifted
  arc. When the animal stops, the phase freezes. A foot caught mid-swing finishes its step onto its
  neutral spot, so the animal stands squarely on four planted feet.
* Stride length scales with leg length (``stride = rel_stride * leg``, shortened at low speed), so a
  stylised short-legged calf never over-reaches. The leg-reach limit is enforced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

LEGS = ("LH", "LF", "RH", "RF")


@dataclass(frozen=True)
class GaitSpec:
    name: str
    duty: float  # fraction of the stride a foot is on the ground
    phases: dict[str, float]  # touchdown time of each foot as a fraction of the stride (LH = 0)
    rel_stride: float  # stride length / leg length at the gait's nominal speed
    freq: float  # stride frequency (Hz) at the nominal speed
    swing_height: float = 0.12  # foot lift as a fraction of leg length
    bob: float = 0.015  # body rise and fall (fraction of leg length), twice per stride
    roll: float = 2.0  # degrees of side-to-side roll toward the stance side
    pitch: float = 1.0  # degrees of fore-aft rocking
    head_nod: float = 4.0  # degrees, twice per stride (equids nod on each fore landing)
    neck_counter: float = 0.0  # degrees; giraffe neck swings out of phase with the trunk

    def nominal_speed(self, leg: float) -> float:
        return self.rel_stride * leg * self.freq


def _ph(lh: float, lf: float, rh: float, rf: float) -> dict[str, float]:
    return {"LH": lh, "LF": lf, "RH": rh, "RF": rf}


# --------------------------------------------------------------------------------------------- library
# Phase tables from the species notes (LH, LF, RH, RF touchdown as a fraction of the stride).
GAITS: dict[str, dict[str, GaitSpec]] = {
    # Hutchinson et al. 2006: lateral sequence at every speed, never airborne, fore duty > hind duty.
    "elephant": {
        "walk": GaitSpec("walk", 0.70, _ph(0.0, 0.24, 0.5, 0.74), 1.05, 0.75, 0.10, 0.012, 3.0, 1.2, 3.0),
        "fast_walk": GaitSpec(
            "fast_walk", 0.58, _ph(0.0, 0.25, 0.5, 0.75), 1.3, 1.0, 0.12, 0.016, 3.0, 1.5, 3.5
        ),
    },
    # Basu et al. 2019: lateral couplets (the same-side fore lands soon after the hind), neck counter-swing.
    "giraffe": {
        "walk": GaitSpec(
            "walk", 0.66, _ph(0.0, 0.12, 0.5, 0.62), 1.15, 0.55, 0.11, 0.010, 4.0, 1.0, 2.0, 6.0
        ),
    },
    # Equid gaits: walk = LS singlefoot; trot = diagonal pairs; canter = three-beat with suspension.
    "zebra": {
        "walk": GaitSpec("walk", 0.62, _ph(0.0, 0.25, 0.5, 0.75), 1.1, 0.85, 0.13, 0.014, 2.0, 1.0, 5.0),
        "trot": GaitSpec("trot", 0.42, _ph(0.0, 0.5, 0.5, 0.0), 1.6, 1.35, 0.18, 0.03, 1.5, 1.0, 1.5),
        "canter": GaitSpec("canter", 0.34, _ph(0.0, 0.3, 0.3, 0.55), 2.1, 1.6, 0.2, 0.04, 2.0, 5.0, 6.0),
    },
    # No measured meerkat gait: LS walk ("hind foot set just behind the fore before it lifts"); half-bound.
    "meerkat": {
        "walk": GaitSpec("walk", 0.65, _ph(0.0, 0.3, 0.5, 0.8), 0.9, 2.0, 0.15, 0.02, 3.0, 2.0, 6.0),
        "scurry": GaitSpec("scurry", 0.38, _ph(0.0, 0.55, 0.08, 0.62), 1.7, 4.0, 0.22, 0.05, 1.0, 6.0, 3.0),
    },
    # Hermann's tortoise: LS, diagonally coupled, duty ~0.8, phase 0.4-0.5, low stride frequency.
    "tortoise": {
        "walk": GaitSpec("walk", 0.82, _ph(0.0, 0.42, 0.5, 0.92), 0.7, 0.35, 0.18, 0.02, 2.0, 1.5, 4.0),
    },
}


@dataclass(frozen=True)
class FootSpot:
    """A foot's neutral spot in the root frame: +X is the animal's left, +Y is behind (it faces -Y)."""

    x: float
    y: float


@dataclass
class Waypoint:
    t: float
    x: float
    y: float
    glide: bool = False  # pass through without stopping (its time is ignored; the run eases as a whole)


@dataclass
class LocoFrame:
    root: tuple[float, float, float]  # world position of the body centre
    yaw: float  # degrees (rest faces -Y; 90 = walking toward +X)
    pitch: float
    roll: float
    phase: float  # gait phase in strides
    speed: float
    feet: dict[str, tuple[float, float, float]] = field(default_factory=dict)  # world foot targets
    stance: dict[str, bool] = field(default_factory=dict)
    head_nod: float = 0.0
    neck_counter: float = 0.0
    sentinel: float = 0.0  # 0 = on all fours, 1 = upright sentinel (meerkat)


def _smooth(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def _curve(run: list[Waypoint], steps: int = 12) -> list[Waypoint]:
    """A run through glide points as a Catmull-Rom curve (densified), so turns are arcs, not corners."""
    if len(run) < 3:
        return run
    pts = [(p.x, p.y) for p in run]
    ext = [
        (2 * pts[0][0] - pts[1][0], 2 * pts[0][1] - pts[1][1]),
        *pts,
        (2 * pts[-1][0] - pts[-2][0], 2 * pts[-1][1] - pts[-2][1]),
    ]
    out = [run[0]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for j in range(1, steps + 1):
            u = j / steps
            u2, u3 = u * u, u * u * u
            x, y = (
                0.5
                * (
                    2 * p1[k]
                    + (p2[k] - p0[k]) * u
                    + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * u2
                    + (3 * p1[k] - p0[k] - 3 * p2[k] + p3[k]) * u3
                )
                for k in (0, 1)
            )
            out.append(Waypoint(run[0].t, x, y, glide=True))
    out[-1] = run[-1]
    return out


def path_xy(points: list[Waypoint], t: float) -> tuple[float, float]:
    """Position on the path at time t: eased between consecutive waypoints (starts and stops gently).

    ``glide`` waypoints are passed through without stopping: a run of them between two stops is one eased
    move along the polyline, by arc length (so a turn drawn as an arc of glide points is walked, not stopped
    at every point)."""
    if t <= points[0].t:
        return points[0].x, points[0].y
    stops = [p for i, p in enumerate(points) if not p.glide or i in (0, len(points) - 1)]
    for a, b in zip(stops, stops[1:]):
        if t <= b.t:
            ia, ib = points.index(a), points.index(b)
            run = _curve(points[ia : ib + 1])
            u = _smooth((t - a.t) / max(b.t - a.t, 1e-6))
            segs = [math.hypot(q.x - p.x, q.y - p.y) for p, q in zip(run, run[1:])]
            goal = u * sum(segs)
            for (p, q), d in zip(zip(run, run[1:]), segs):
                if goal <= d or q is b:
                    w = min(1.0, goal / d) if d > 1e-9 else 1.0
                    return p.x + (q.x - p.x) * w, p.y + (q.y - p.y) * w
                goal -= d
    return points[-1].x, points[-1].y


def _rot(yaw: float, x: float, y: float) -> tuple[float, float]:
    a = math.radians(yaw)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def best_start_phase(gait: GaitSpec) -> float:
    """Gait phase to start walking from a square stand: the one where the planted foot with the most
    stance left has the least (so no foot is dragged far behind the hip on the first step)."""

    def worst(s0: float) -> float:
        rem = 0.0
        for ph in gait.phases.values():
            p = (s0 - ph) % 1.0
            if p < gait.duty:
                rem = max(rem, gait.duty - p)
        return rem

    return min((i / 200 for i in range(200)), key=worst)


def plan_locomotion(
    points: list[Waypoint],
    gait: GaitSpec,
    feet: dict[str, FootSpot],
    leg: float,
    body_z: float,
    foot_z: float,
    fps: int = 24,
    t_end: float | None = None,
    yaw0: float | None = None,
    reach_slack: float | None = None,
    joints: dict[str, tuple[float, float, float, float]] | None = None,
    max_drop: float = 0.07,
) -> list[LocoFrame]:
    """Per-frame root motion and foot-locked world foot targets for a walk along ``points``."""
    t_end = points[-1].t if t_end is None else t_end
    n = int(round(t_end * fps)) + 1
    ts = [k / fps for k in range(n)]
    xy = [path_xy(points, t) for t in ts]
    # speed and heading
    speed = [0.0] * n
    yaw = [0.0] * n
    last_yaw = yaw0 if yaw0 is not None else 90.0
    for k in range(n):
        a, b = xy[max(0, k - 1)], xy[min(n - 1, k + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        dt = (min(n - 1, k + 1) - max(0, k - 1)) / fps
        speed[k] = math.hypot(dx, dy) / max(dt, 1e-6)
        if speed[k] > 0.02:
            # rest pose faces -Y: heading (dx, dy) = (sin yaw, -cos yaw)
            last_yaw = math.degrees(math.atan2(dx, -dy))
        yaw[k] = last_yaw
    # unwrap and smooth the heading (no snapping when the path turns)
    for k in range(1, n):
        while yaw[k] - yaw[k - 1] > 180:
            yaw[k] -= 360
        while yaw[k] - yaw[k - 1] < -180:
            yaw[k] += 360
    sm = list(yaw)
    for _ in range(3):
        sm = [sm[0]] + [(sm[k - 1] + 2 * sm[k] + sm[k + 1]) / 4 for k in range(1, n - 1)] + [sm[-1]]
    yaw = sm

    nominal = gait.nominal_speed(leg)
    # leg-reach limit: in stance the foot travels from stride*duty/2 ahead of the hip to the same distance
    # behind it. ``reach_slack`` is how far a leg can reach horizontally from its rest height (from the rig);
    # without it, assume the hip rests at 0.93 of leg length.
    slack = reach_slack if reach_slack is not None else 0.9 * math.sqrt(1 - 0.93**2) * leg
    if joints:
        # vaulting legs: the body may sink up to ``max_drop`` of the leg at the ends of a stance, so near-
        # straight (pillar) legs can still take a real stride
        # (splayed legs, e.g. a tortoise's, also spend reach sideways: the foot sits outboard of the joint)
        slack = min(
            math.sqrt(
                max(
                    (0.95 * c) ** 2
                    - ((jz - (foot_z - body_z)) - max_drop * c) ** 2
                    - (feet[leg].x - jx) ** 2
                    - (feet[leg].y - jy) ** 2,
                    1e-6,
                )
            )
            for leg, (jx, jy, jz, c) in joints.items()
        )
    max_stride = 2 * slack / gait.duty

    def stride_len(v: float) -> float:
        rel = max(0.35, min(1.0, v / max(nominal, 1e-6))) ** 0.5
        return min(gait.rel_stride * leg * rel, max_stride)

    # gait phase: advances only while moving
    freq = [v / stride_len(v) if v > 0.02 else 0.0 for v in speed]
    s = [0.0] * n
    for k in range(1, n):
        s[k] = s[k - 1] + 0.5 * (freq[k] + freq[k - 1]) / fps
    # starting from a stand: every foot is planted at its neutral spot, so the gait must begin at the phase
    # where no planted foot still has a long stance ahead (it would trail far behind the hip). Pick the
    # phase that minimises the longest remaining stance: the animal leads off with the right foot.
    start_phase = best_start_phase(gait)
    for k in range(n):
        if freq[k] > 0 and (k == 0 or freq[k - 1] == 0):
            shift = (start_phase - s[k]) % 1.0
            for j in range(k, n):
                s[j] += shift

    def neutral(k: int, foot: str) -> tuple[float, float]:
        k = max(0, min(n - 1, k))
        ox, oy = _rot(yaw[k], feet[foot].x, feet[foot].y)
        return xy[k][0] + ox, xy[k][1] + oy

    # distance travelled along the path, for distance-based look-ahead
    cum = [0.0] * n
    for k in range(1, n):
        cum[k] = cum[k - 1] + math.hypot(xy[k][0] - xy[k - 1][0], xy[k][1] - xy[k - 1][1])

    def plant_at(k: int, foot: str) -> tuple[float, float]:
        """Touchdown spot: where the hip/shoulder will be after half the stance travel (stride*duty/2),
        looked up along the real path. Distance-based, so slowing down never plants a foot out of reach."""
        if freq[k] <= 0:
            return neutral(k, foot)
        goal = cum[k] + stride_len(speed[k]) * gait.duty / 2
        j = k
        while j < n - 1 and cum[j] < goal:
            j += 1
        return neutral(j, foot)

    settle = max(2, int(round(0.28 * fps)))
    out: list[LocoFrame] = []
    stance_raw = {f: [((s[k] - gait.phases[f]) % 1.0) < gait.duty for k in range(n)] for f in LEGS}
    stance: dict[str, list[bool]] = {}
    for f in LEGS:
        st = list(stance_raw[f])
        # standing still: a foot caught in swing lands after a short settle; then everyone stays planted
        k = 0
        while k < n:
            if freq[k] == 0.0:
                k0 = k
                while k < n and freq[k] == 0.0:
                    k += 1
                swinging = not st[k0 - 1] if k0 > 0 else False
                for j in range(k0, k):
                    st[j] = (not swinging) or (j - k0 >= settle)
            else:
                k += 1
        stance[f] = st
    pos: dict[str, list[tuple[float, float, float]]] = {}
    for f in LEGS:
        st = stance[f]
        p: list[tuple[float, float, float] | None] = [None] * n
        # stance spans: locked at the touchdown spot
        k = 0
        while k < n:
            if st[k]:
                k0 = k
                if k0 == 0:
                    # already standing at the start: place it where the phase says it is within its stance
                    off = (gait.duty / 2 - ((s[0] - gait.phases[f]) % 1.0)) * stride_len(speed[0])
                    nx, ny = neutral(0, f)
                    fx, fy = _rot(yaw[0], 0.0, -1.0)
                    spot = (nx + fx * off * (freq[0] > 0), ny + fy * off * (freq[0] > 0))
                elif freq[k0] == 0.0 or freq[k0 - 1] == 0.0:
                    spot = neutral(k0, f)
                else:
                    spot = plant_at(k0, f)
                while k < n and st[k]:
                    p[k] = (spot[0], spot[1], foot_z)
                    k += 1
            else:
                k += 1
        # swing spans: arc from the lift-off spot to the next touchdown spot. Interpolated *relative to the
        # moving hip* (offset at lift-off -> offset at touchdown), so a foot that eases off the ground never
        # trails the body out of reach
        k = 0
        while k < n:
            if not st[k]:
                k0 = k
                while k < n and not st[k]:
                    k += 1
                ka, kb = max(0, k0 - 1), min(n - 1, k)
                a = p[k0 - 1] if k0 > 0 else (*neutral(k0, f), foot_z)
                b = p[k] if k < n else (*plant_at(n - 1, f), foot_z)
                na, nb = neutral(ka, f), neutral(kb, f)
                ra, rb = (a[0] - na[0], a[1] - na[1]), (b[0] - nb[0], b[1] - nb[1])
                span = k - (k0 - 1)
                for j in range(k0, k):
                    u = (j - (k0 - 1)) / span
                    w = _smooth(u)
                    lift = gait.swing_height * leg * math.sin(math.pi * u)
                    nj = neutral(j, f)
                    p[j] = (
                        nj[0] + ra[0] + (rb[0] - ra[0]) * w,
                        nj[1] + ra[1] + (rb[1] - ra[1]) * w,
                        foot_z + lift,
                    )
            else:
                k += 1
        pos[f] = [q if q is not None else (*neutral(i, f), foot_z) for i, q in enumerate(p)]

    # vaulting: per frame, the highest the body can be while every leg keeps 4 % of its length bent;
    # the body follows that (it drops at touchdown/lift-off, rises over the planted foot) instead of a sine
    vault = [0.0] * n
    if joints:
        for k in range(n):
            limit = body_z
            for f, (jx, jy, jz, c) in joints.items():
                # swinging legs count too: a foot just lifted off is still far behind the hip
                ox, oy = _rot(yaw[k], jx, jy)
                dx = pos[f][k][0] - (xy[k][0] + ox)
                dy = pos[f][k][1] - (xy[k][1] + oy)
                avail = math.sqrt(max((0.96 * c) ** 2 - dx * dx - dy * dy, 0.0))
                limit = min(limit, pos[f][k][2] + avail - jz)
            vault[k] = max(0.0, body_z - limit)
        # soften: a short min-preserving blur (never less drop than needed, no frame-to-frame jitter)
        for _ in range(2):
            vault = [
                max(vault[k], (vault[max(0, k - 1)] + 2 * vault[k] + vault[min(n - 1, k + 1)]) / 4)
                for k in range(n)
            ]
    for k in range(n):
        moving = min(1.0, speed[k] / max(nominal * 0.3, 1e-6))
        ph = s[k]
        bob = vault[k] + (
            0.0 if joints else gait.bob * leg * moving * (0.5 - 0.5 * math.cos(4 * math.pi * ph))
        )
        out.append(
            LocoFrame(
                root=(xy[k][0], xy[k][1], body_z - bob),
                yaw=yaw[k],
                pitch=gait.pitch * moving * math.sin(2 * math.pi * ph),
                roll=gait.roll * moving * math.sin(2 * math.pi * ph),
                phase=ph,
                speed=speed[k],
                feet={f: pos[f][k] for f in LEGS},
                stance={f: stance[f][k] for f in LEGS},
                head_nod=gait.head_nod * moving * math.sin(4 * math.pi * ph + 0.6),
                neck_counter=gait.neck_counter * moving * math.sin(4 * math.pi * ph + math.pi),
            )
        )
    return out


def foot_slide(frames: list[LocoFrame]) -> float:
    """Largest horizontal movement of any foot between consecutive frames while it stays in stance (m)."""
    worst = 0.0
    for a, b in zip(frames, frames[1:]):
        for f in LEGS:
            if a.stance[f] and b.stance[f]:
                d = math.hypot(b.feet[f][0] - a.feet[f][0], b.feet[f][1] - a.feet[f][1])
                worst = max(worst, d)
    return worst


def planted_drift(
    stance: list[dict[str, bool]], feet: list[dict[str, tuple[float, ...]]]
) -> dict[str, float | int | str]:
    """Measured planted-foot drift: the largest horizontal move of a foot between consecutive frames in which it
    is in stance in both, plus how many such stance pairs were measured.

    ``stance[k][leg]`` comes from the plan and ``feet[k][leg]`` from the deformed rig. ``pairs`` is what tells
    "no drift" from "never measured": a take in which no foot ever stays planted for two frames has ``pairs == 0``
    and must not pass as perfect. Ties keep the first pair, so a leg is always named when anything was measured.
    """
    worst: dict[str, float | int | str] = {"drift": 0.0, "leg": "", "frame": 0, "pairs": 0}
    for k in range(1, min(len(stance), len(feet))):
        for leg in LEGS:
            if not (stance[k - 1].get(leg) and stance[k].get(leg)):
                continue
            a, b = feet[k - 1][leg], feet[k][leg]
            d = math.hypot(b[0] - a[0], b[1] - a[1])
            worst["pairs"] = int(worst["pairs"]) + 1
            if not worst["leg"] or d > float(worst["drift"]):
                worst.update(drift=d, leg=leg, frame=k + 1)
    return worst


def planted_travel(
    stance: list[dict[str, bool]], feet: list[dict[str, tuple[float, ...]]]
) -> dict[str, float | int | str]:
    """How far a planted foot strays over one whole stance phase (furthest from where it landed, horizontally),
    worst over the take, plus how many phases were measured. A per-frame limit (:func:`planted_drift`) misses a
    sole that creeps a few millimetres every frame, or a rigid hoof that rocks about its fetlock as the leg
    sweeps back: the contact patch then skates by the hoof's height times the sweep angle."""
    worst: dict[str, float | int | str] = {"travel": 0.0, "leg": "", "start": 0, "end": 0, "phases": 0}
    n = min(len(stance), len(feet))
    for leg in LEGS:
        k = 0
        while k < n:
            if not stance[k].get(leg):
                k += 1
                continue
            j = k
            while j + 1 < n and stance[j + 1].get(leg):
                j += 1
            if j > k:
                a = feet[k][leg]
                d = max(math.hypot(feet[m][leg][0] - a[0], feet[m][leg][1] - a[1]) for m in range(k, j + 1))
                worst["phases"] = int(worst["phases"]) + 1
                if not worst["leg"] or d > float(worst["travel"]):
                    worst.update(travel=d, leg=leg, start=k + 1, end=j + 1)
            k = j + 1
    return worst


def sentinel_paws(
    frames: list[dict[str, tuple[float, ...]]], ground_z: float, chain: float
) -> dict[str, float | int]:
    """How the fore paws sit in the meerkat's sentinel (paws tucked at the chest), worst over the given frames.

    Each frame maps ``hips``/``chest`` (the torso's spine: body centre and front), ``head`` and the fore paws
    ``LF``/``RF`` (lower-leg bone tips) to world points; lengths are shares of the fore-leg ``chain``:

    * ``lift``: the lowest paw's height above the ground (a paw left on the ground is not tucked);
    * ``reach``: the furthest paw's distance from the torso's axis (a paw held out, or dangling forward);
    * ``chin`` / ``drop``: the smallest and the biggest drop from the head down to a paw (paws at or over the face
      read as begging; paws far below it hang, they aren't tucked at the chest);
    * ``spread``: the biggest height difference between the two paws (a tuck is a pair);
    * ``frames``: how many frames were measured (zero is "never measured", never a pass).
    """
    out: dict[str, float | int] = {
        "lift": 9.0,
        "reach": 0.0,
        "chin": 9.0,
        "drop": 0.0,
        "spread": 0.0,
        "frames": 0,
    }
    c = max(chain, 1e-6)
    for f in frames:
        h, ch = f["hips"], f["chest"]
        ax = [ch[i] - h[i] for i in range(3)]
        al = math.sqrt(sum(a * a for a in ax)) or 1e-6
        u = [a / al for a in ax]
        zs = []
        for leg in ("LF", "RF"):
            p = f[leg]
            d = [p[i] - h[i] for i in range(3)]
            t = sum(d[i] * u[i] for i in range(3))
            perp = math.sqrt(max(0.0, sum(x * x for x in d) - t * t))
            out["reach"] = max(float(out["reach"]), perp / c)
            out["lift"] = min(float(out["lift"]), (p[2] - ground_z) / c)
            out["chin"] = min(float(out["chin"]), (f["head"][2] - p[2]) / c)
            out["drop"] = max(float(out["drop"]), (f["head"][2] - p[2]) / c)
            zs.append(p[2])
        out["spread"] = max(float(out["spread"]), abs(zs[0] - zs[1]) / c)
        out["frames"] = int(out["frames"]) + 1
    return out
