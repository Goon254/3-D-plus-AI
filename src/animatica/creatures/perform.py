"""Locomotion plan -> keyframes: root (path, bob, pitch, roll, heading), IK foot targets, neck/head
motion, tail swish, ear flicks (elephant flaps), trunk swing, blinks. Idle layers keep going while the
animal stands, so it never freezes into a statue.

Dense keys use LINEAR interpolation: Bezier handles would overshoot between per-frame keys and nudge a
planted foot.
"""

from __future__ import annotations

import math
import random
from typing import Any

from .build import CreatureMeta
from .gait import GaitSpec, LocoFrame, Waypoint, plan_locomotion
from .species import SPECIES


def _k(frame: int, v: Any) -> list[Any]:
    return [frame, v, "LINEAR"]


SENTINEL_PITCH = 72.0  # degrees the meerkat's body rises from horizontal when it stands up
SENTINEL_NECK = 60.0  # the neck bends forward again so the head looks ahead, not at the sky
SENTINEL_TAIL = 48.0  # the tail swings back down to the ground: the third leg of the tripod


def _smooth(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def apply_sentinel(meta: CreatureMeta, plan: list[LocoFrame], fps: int) -> None:
    """Meerkat sentinel pose whenever it stands still (knowledge/species/meerkat.md): it rises on its hind
    legs, balancing on legs + tail, front paws tucked at the chest, head level and scanning. The body pitches
    up around the hips, so the planted hind feet keep their reach; it drops to all fours before walking."""
    n = len(plan)
    moving = [p.speed > 0.02 for p in plan]
    big = 10**6
    since = [big] * n
    until = [big] * n
    last = None
    for k in range(n):
        if moving[k]:
            last = k
        since[k] = 0 if moving[k] else (k - last if last is not None else big)
    nxt = None
    for k in range(n - 1, -1, -1):
        if moving[k]:
            nxt = k
        until[k] = 0 if moving[k] else (nxt - k if nxt is not None else big)
    hips = [j for leg, j in meta.joints.items() if leg[1] == "H"]
    fronts = {leg: j for leg, j in meta.joints.items() if leg[1] == "F"}
    hy = sum(j[1] for j in hips) / len(hips)
    hz = sum(j[2] for j in hips) / len(hips)
    for k, p in enumerate(plan):
        rise = 1.0 if since[k] >= big else _smooth((since[k] / fps - 0.2) / 0.55)
        drop = 1.0 if until[k] >= big else _smooth((until[k] / fps - 0.1) / 0.4)
        b = min(rise, drop)
        if b <= 0:
            continue
        th = math.radians(-SENTINEL_PITCH * b)  # negative pitch = front up
        # pivot around the hips: local offset H - Rx(th) H, then into the world by the heading
        oy = hy - (hy * math.cos(th) - hz * math.sin(th))
        oz = hz - (hy * math.sin(th) + hz * math.cos(th))
        ya = math.radians(p.yaw)
        wx, wy = -oy * math.sin(ya), oy * math.cos(ya)
        root = (p.root[0] + wx, p.root[1] + wy, p.root[2] + oz)
        pitch = p.pitch - SENTINEL_PITCH * b
        a = math.radians(pitch)
        for leg, (jx, jy, jz, chain) in fronts.items():
            # paws tucked in front of the chest, hanging half a leg below the shoulder (body space)
            lx, ly, lz = jx * 0.9, jy - 0.15 * chain, jz - 0.55 * chain
            y2, z2 = ly * math.cos(a) - lz * math.sin(a), ly * math.sin(a) + lz * math.cos(a)
            tx = root[0] + lx * math.cos(ya) - y2 * math.sin(ya)
            ty = root[1] + lx * math.sin(ya) + y2 * math.cos(ya)
            tz = root[2] + z2
            g = p.feet[leg]
            p.feet[leg] = (g[0] + (tx - g[0]) * b, g[1] + (ty - g[1]) * b, g[2] + (tz - g[2]) * b)
            if b > 0.05:
                p.stance[leg] = False
        p.root, p.pitch, p.sentinel = root, pitch, b


def walk_keys(
    meta: CreatureMeta,
    gait: GaitSpec,
    points: list[Waypoint],
    fps: int = 24,
    frame0: int = 1,
    seed: int = 0,
    yaw0: float | None = None,
) -> tuple[list[dict[str, Any]], list[LocoFrame]]:
    plan = plan_locomotion(
        points, gait, meta.feet, meta.leg, meta.body_z, meta.foot_z, fps, joints=meta.joints, yaw0=yaw0
    )
    if SPECIES[meta.species].default_pose == "sentinel":
        apply_sentinel(meta, plan, fps)
    rng = random.Random(seed)
    frames = [frame0 + i for i in range(len(plan))]
    ts = [i / fps for i in range(len(plan))]
    r = lambda v, n=4: round(v, n)  # noqa: E731
    ops: list[dict[str, Any]] = [
        {
            "op": "insert_keyframes",
            "target": meta.root,
            "property": "location",
            "keys": [
                _k(
                    f,
                    [
                        r(p.root[0]),
                        r(p.root[1]),
                        r(p.root[2] + 0.004 * meta.body_z * math.sin(2 * math.pi * t / 3.1)),
                    ],
                )
                for f, p, t in zip(frames, plan, ts)
            ],
        },
        {
            "op": "insert_keyframes",
            "target": meta.root,
            "property": "rotation",
            "keys": [_k(f, [r(p.pitch, 2), r(p.roll, 2), r(p.yaw, 2)]) for f, p in zip(frames, plan)],
        },
    ]
    for leg, tgt in meta.ik_targets.items():
        ops.append(
            {
                "op": "insert_keyframes",
                "target": tgt,
                "property": "location",
                "keys": [
                    _k(f, [r(p.feet[leg][0]), r(p.feet[leg][1]), r(p.feet[leg][2])])
                    for f, p in zip(frames, plan)
                ],
            }
        )

    def bone(name: str, fn) -> None:
        ops.append(
            {
                "op": "insert_keyframes",
                "target": meta.rig,
                "property": f"bone:{name}.rotation",
                "keys": [_k(f, [r(v, 2) for v in fn(p, t)]) for f, p, t in zip(frames, plan, ts)],
            }
        )

    # neck: gait nod + counter-swing + a slow idle look-around; the head partly cancels it (gaze steadies)
    n = max(1, len(meta.neck_bones))
    look_t = [rng.uniform(1.0, 2.5) for _ in range(3)]

    def look(t: float) -> float:
        return 6 * math.sin(2 * math.pi * t / 7.3 + look_t[0]) + 3 * math.sin(
            2 * math.pi * t / 3.1 + look_t[1]
        )

    for name in meta.neck_bones:
        bone(
            name,
            lambda p, t: [
                (p.head_nod + p.neck_counter + SENTINEL_NECK * p.sentinel) / n
                + 1.5 * math.sin(2 * math.pi * t / 3.1) / n,
                0.0,
                look(t) / n,
            ],
        )
    bone("head", lambda p, t: [-0.5 * p.head_nod - 0.7 * p.neck_counter, 0.0, 0.0])
    # tail: a travelling swish down the chain (follow-through) plus a little lift with speed
    for k, name in enumerate(meta.tail_bones):
        amp = 8 + 4 * k

        def tail(p: LocoFrame, t: float, k: int = k, amp: float = amp) -> list[float]:
            return [
                3 * math.sin(2 * math.pi * p.phase - 0.8 * k)
                + 2.0 * min(1.0, p.speed)
                + (SENTINEL_TAIL if k == 0 else -8.0) * p.sentinel,
                0.0,
                amp * math.sin(2 * math.pi * t / 2.3 - 0.7 * k),
            ]

        bone(name, tail)
    # trunk: a pendulum that lags the step, curling a little at the tip
    for k, name in enumerate(meta.trunk_bones):
        bone(
            name,
            lambda p, t, k=k: [
                4 * math.sin(2 * math.pi * p.phase - 0.5 * k)
                + 2.5 * math.sin(2 * math.pi * t / 2.7 - 0.4 * k)
                - 3 * (k > 2),
                0.0,
                5 * math.sin(2 * math.pi * t / 3.3 - 0.45 * k),
            ],
        )
    # ears: elephants fan slowly (cooling); everyone else flicks now and then
    flicks = sorted(rng.uniform(0.5, max(1.0, ts[-1])) for _ in range(max(1, int(ts[-1] / 2.5))))
    for side, name in zip((1, -1), meta.ear_bones):
        if meta.species == "elephant":
            bone(
                name,
                lambda p, t, s=side: [
                    0.0,
                    0.0,
                    s * (10 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.4 * t + 0.4 * s))),
                ],
            )
        else:

            def ear(p: LocoFrame, t: float, s: int = side) -> list[float]:
                flick = sum(
                    math.exp(-(((t - ft) / 0.08) ** 2)) for i, ft in enumerate(flicks) if i % 2 == (s > 0)
                )
                return [-25 * flick, 0.0, s * 6 * math.sin(2 * math.pi * t / 4.1 + s)]

            bone(name, ear)
    # blinks: quick squash of the eye ball, iris and glint every 2.5-5 s
    blinks: list[float] = []
    t = rng.uniform(0.6, 1.6)
    while t < ts[-1]:
        blinks.append(t)
        t += rng.uniform(2.5, 5.0)

    def lid(t: float) -> float:
        v = 1.0
        for b in blinks:
            if b - 0.06 <= t <= b + 0.12:
                u = (t - (b - 0.06)) / 0.18
                v = min(v, abs(2 * u - 1) ** 1.5 * 0.92 + 0.08)
        return v

    for eye in meta.eyes:
        side = eye.rsplit("_", 1)[1]
        for part in (eye, f"{meta.cid}_iris_{side}", f"{meta.cid}_glint_{side}"):
            ops.append(
                {
                    "op": "insert_keyframes",
                    "target": part,
                    "property": "scale",
                    "keys": [_k(f, [1.0, 1.0, r(lid(t), 3)]) for f, t in zip(frames, ts)],
                }
            )
    return ops, plan
