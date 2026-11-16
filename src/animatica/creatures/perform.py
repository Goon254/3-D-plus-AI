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


def _k(frame: int, v: Any) -> list[Any]:
    return [frame, v, "LINEAR"]


def walk_keys(
    meta: CreatureMeta, gait: GaitSpec, points: list[Waypoint], fps: int = 24, frame0: int = 1, seed: int = 0
) -> tuple[list[dict[str, Any]], list[LocoFrame]]:
    plan = plan_locomotion(
        points, gait, meta.feet, meta.leg, meta.body_z, meta.foot_z, fps, joints=meta.joints
    )
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
                (p.head_nod + p.neck_counter) / n + 1.5 * math.sin(2 * math.pi * t / 3.1) / n,
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
                3 * math.sin(2 * math.pi * p.phase - 0.8 * k) + 2.0 * min(1.0, p.speed),
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
