"""Acacia crowns measured as built (DECISIONS #98): the owner caught a solid cushion (11-16) and broccoli florets
(11-17) by eye; the layered flat tables of 11-18 are what he asked for. Both old canopies are rebuilt here from
their code at the time (``cc74f57``, ``fd4ee90``) so the check keeps failing them."""

import math
import random

import numpy as np

from animatica.production.continuity import set_assets
from animatica.production.scene import scene_from_dict
from animatica.sets import measure
from animatica.sets.measure import acacia_shape, canopy_problems, canopy_shape, metaball_grid
from animatica.sets.savannah import acacia_ops


def _tips(seed: int, s: float = 1.0):
    """The trunk's fork and branch tips, drawn from the rng exactly as ``acacia_ops`` does (unchanged since 11-16)."""
    rng = random.Random(seed)
    fork = (rng.uniform(-0.3, 0.3) * s, rng.uniform(-0.3, 0.3) * s, 2.2 * s)
    tips = []
    nb = rng.randint(3, 5)
    for b in range(nb):
        a = 2 * math.pi * (b + rng.uniform(-0.2, 0.2)) / nb
        reach = rng.uniform(1.6, 2.6) * s
        tips.append(
            (
                fork[0] + math.cos(a) * reach,
                fork[1] + math.sin(a) * reach,
                fork[2] + rng.uniform(1.3, 1.7) * s,
            )
        )
    return rng, fork, tips


def _el(x, y, z, r, flat):
    return {"type": "ellipsoid", "co": [x, y, z], "radius": r / 0.575, "size": [1.0, 1.0, flat]}


def cushion_1116(seed: int, s: float = 1.0):
    """The 11-16 canopy (``cc74f57``): one cushion of overlapping flattened balls."""
    _, fork, tips = _tips(seed, s)
    top = max(t[2] for t in tips)
    els = [_el(t[0], t[1], top + 0.15 * s, 1.5 * s, 0.32) for t in tips]
    return els + [_el(fork[0], fork[1], top + 0.3 * s, 2.2 * s, 0.25)]


def broccoli_1117(seed: int, s: float = 1.0):
    """The 11-17 canopy (``81568a2`` .. ``fd4ee90``): a centre clump and two rings of round clumps."""
    rng, fork, tips = _tips(seed, s)
    top = max(t[2] for t in tips)
    crown = max(math.dist(t[:2], fork[:2]) for t in tips) + 0.7 * s
    cx = sum(t[0] for t in tips) / len(tips) * 0.5 + fork[0] * 0.5
    cy = sum(t[1] for t in tips) / len(tips) * 0.5 + fork[1] * 0.5
    els = [_el(cx, cy, top + 0.35 * s, 0.75 * s, 0.4)]
    for ring, n, rr in ((0.45, 6, 0.62), (0.85, 11, 0.55)):
        a0 = rng.uniform(0, 2 * math.pi)
        for k in range(n):
            if rng.random() < 0.22:
                continue
            a = a0 + 2 * math.pi * (k + rng.uniform(-0.2, 0.2)) / n
            d = crown * ring * rng.uniform(0.9, 1.1)
            z = top + rng.uniform(0.05, 0.3) * s - ring * 0.25 * s
            els.append(
                _el(
                    cx + math.cos(a) * d,
                    cy + math.sin(a) * d,
                    z,
                    rr * s * rng.uniform(0.8, 1.15),
                    rng.uniform(0.32, 0.45),
                )
            )
    for t in tips:
        a = math.atan2(t[1] - fork[1], t[0] - fork[0]) + rng.uniform(-0.4, 0.4)
        els.append(
            _el(t[0] + math.cos(a) * 0.4 * s, t[1] + math.sin(a) * 0.4 * s, top - 0.45 * s, 0.5 * s, 0.42)
        )
    return els


def test_the_metaball_field_is_blenders_a_lone_ball_reaches_0_575_of_its_radius():
    step = 0.01
    grid, lo = metaball_grid([{"type": "ball", "co": [0.0, 0.0, 0.0], "radius": 1.0}], step)
    xs = lo[0] + step * np.nonzero(grid.any(axis=(1, 2)))[0]
    assert abs(xs.max() - 0.575) < 0.015 and abs(xs.min() + 0.575) < 0.015
    flat, lo = metaball_grid([_el(0.0, 0.0, 0.0, 1.0, 0.25)], step)  # ``size`` squashes it in z
    zs = lo[2] + step * np.nonzero(flat.any(axis=(0, 1)))[0]
    assert abs(zs.max() - 0.25) < 0.015


def test_the_old_cushion_and_the_broccoli_fail_and_the_layered_tables_pass():
    seed = 7  # the savannah layout's first acacia
    cushion = canopy_shape(cushion_1116(seed), 0.04)
    assert cushion["sky"] < measure.SKY_MIN and cushion["clumps"] == 1
    assert any("cushion" in p for p in canopy_problems(cushion))
    broccoli = canopy_shape(broccoli_1117(seed), 0.04)
    assert broccoli["round"] > measure.ROUND_MAX and broccoli["roundest"] < measure.FLORET_MIN
    assert [p for p in canopy_problems(broccoli) if "broccoli" in p]
    for seed, scale in ((7, 1.0), (18, 0.85), (43, 1.0)):
        tables = acacia_shape(scale, seed)
        assert canopy_problems(tables) == [], (seed, tables)
        assert tables["table"] >= 6.0 and tables["sky"] >= 0.1 and tables["round"] == 0.0


def test_a_round_ball_crown_is_not_a_table():
    ball = canopy_shape([_el(0.0, 0.0, 4.0, 1.5, 0.9)], 0.05)
    problems = canopy_problems(ball)
    assert ball["table"] < measure.TABLE_MIN and any("wide to deep" in p for p in problems)


def test_set_assets_names_each_failing_acacia_in_the_scene(monkeypatch):
    spec = scene_from_dict(
        {
            "id": "sc99",
            "title": "t",
            "tod": "midday",
            "cue": "x",
            "seconds": 4,
            "layout": {"acacias": [[-7.0, 9.0, 1.0], [11.0, 16.0, 0.85]]},
            "cast": {"tembo": {"species": "elephant", "at": [0, 0]}},
            "lines": [],
            "shots": [{"type": "ws", "subjects": ["tembo"], "t": 0}],
        }
    )
    assert set_assets(spec) == []  # the set as built
    seen = []

    def fake(scale, seed):
        seen.append((scale, seed))
        return canopy_shape(broccoli_1117(seed, scale), 0.04 * scale)

    monkeypatch.setattr(measure, "acacia_shape", fake)
    bad = set_assets(spec, seed=7)
    assert seen == [(1.0, 7), (0.85, 18)]  # the scene's seeds: layout seed + 11 i
    assert (
        bad and {v.kind for v in bad} == {"set_canopy"} and {v.who for v in bad} <= {"acacia_0", "acacia_1"}
    )


def test_acacia_ops_canopy_is_still_one_metaball_mesh_of_unrotated_ellipsoids():
    canopy = [o for o in acacia_ops("a", (0.0, 0.0), 1.0, 7) if o["op"] == "create_metaball_mesh"]
    assert len(canopy) == 1
    assert all(e["type"] == "ellipsoid" and not e.get("rotation") for e in canopy[0]["elements"])
