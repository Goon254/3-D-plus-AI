"""Savannah creatures: gait planner (foot-lock, footfall order, duty factor, reach) and body-plan builder."""

import math

import pytest

from animatica.core.protocol import validate_batch
from animatica.creatures.build import build_creature
from animatica.creatures.gait import GAITS, LEGS, Waypoint, foot_slide, plan_locomotion
from animatica.creatures.perform import walk_keys
from animatica.creatures.species import SPECIES


def walk(species: str, gait: str = "walk", seconds: float = 8.0):
    ops, meta = build_creature(species, SPECIES[species])
    g = GAITS[species][gait]
    v = g.nominal_speed(meta.leg)
    pts = [
        Waypoint(0, 0, 0),
        Waypoint(1, 0, 0),
        Waypoint(1 + seconds, v * seconds * 0.8, 0),
        Waypoint(seconds + 2.5, v * seconds * 0.8, 0),
    ]
    plan = plan_locomotion(pts, g, meta.feet, meta.leg, meta.body_z, meta.foot_z, joints=meta.joints)
    return ops, meta, g, plan


def touchdowns(plan, leg):
    return [i for i in range(1, len(plan)) if plan[i].stance[leg] and not plan[i - 1].stance[leg]]


@pytest.mark.parametrize("species", sorted(SPECIES))
def test_feet_never_slide_and_the_animal_ends_standing(species):
    _, meta, g, plan = walk(species)
    assert foot_slide(plan) == 0.0  # a planted foot does not move at all
    assert all(plan[-1].stance.values())  # it stops on four planted feet
    travelled = plan[-1].root[0] - plan[0].root[0]
    assert travelled > meta.leg  # and it really went somewhere


@pytest.mark.parametrize("species", sorted(SPECIES))
def test_stance_feet_stay_within_leg_reach(species):
    _, meta, g, plan = walk(species)
    for p in plan:
        a = math.radians(p.yaw)
        for leg in LEGS:
            jx, jy, jz, chain = meta.joints[leg]
            wx = p.root[0] + jx * math.cos(a) - jy * math.sin(a)
            wy = p.root[1] + jx * math.sin(a) + jy * math.cos(a)
            d = math.dist((wx, wy, p.root[2] + jz), p.feet[leg])
            assert d <= chain * 1.001, (species, leg, d, chain)


def test_lateral_sequence_walk_footfall_order():
    # zebra (equid) walk: LH -> LF -> RH -> RF, evenly spaced; duty factor ~0.62 (Muybridge, equine gait reviews)
    _, _, g, plan = walk("zebra")
    mid = [i for i in range(len(plan)) if plan[i].speed > 0.9 * max(p.speed for p in plan)]
    a, b = mid[0], mid[-1]
    events = sorted((i, leg) for leg in LEGS for i in touchdowns(plan, leg) if a <= i <= b)
    order = [leg for _, leg in events]
    start = order.index("LH")
    assert order[start : start + 4] == ["LH", "LF", "RH", "RF"]
    # measured duty factor in the steady part of the walk
    st = [plan[i].stance["LF"] for i in range(a, b)]
    assert sum(st) / len(st) == pytest.approx(g.duty, abs=0.06)


def test_elephant_never_leaves_the_ground_and_giraffe_uses_lateral_couplets():
    # Hutchinson 2006: elephants keep >= 2 feet down, never an aerial phase
    _, _, _, plan = walk("elephant")
    assert min(sum(p.stance.values()) for p in plan) >= 2
    # Basu 2019: the same-side fore lands soon after the hind (lateral couplets, limb phase ~0.12)
    _, _, g, plan = walk("giraffe")
    lh, lf = touchdowns(plan, "LH"), touchdowns(plan, "LF")
    gaps = [min((f - h for f in lf if f > h), default=99) for h in lh[1:-1]]
    period = (lh[-1] - lh[1]) / max(1, len(lh) - 2)
    assert gaps and all(gap / period < 0.2 for gap in gaps)


def test_zebra_trot_moves_diagonal_pairs_together():
    _, _, _, plan = walk("zebra", "trot")
    lh, rf = touchdowns(plan, "LH"), touchdowns(plan, "RF")
    assert lh and all(any(abs(a - b) <= 1 for b in rf) for a in lh[1:-1])


def test_a_foot_caught_mid_swing_lands_when_the_animal_stops():
    _, meta, g, plan = walk("zebra")
    stop = max(i for i, p in enumerate(plan) if p.speed > 0.02)
    # within 0.3 s of stopping every foot is down, and nothing is left hanging in the air
    later = plan[stop + int(0.3 * 24) + 1 :]
    assert later and all(all(p.stance.values()) for p in later)
    assert all(abs(p.feet[leg][2] - meta.foot_z) < 1e-9 for p in later for leg in LEGS)


@pytest.mark.parametrize("species", sorted(SPECIES))
def test_build_and_walk_ops_validate(species):
    ops, meta = build_creature(species, SPECIES[species], at=(1.0, 2.0), yaw=90)
    keys, plan = walk_keys(meta, GAITS[species]["walk"], [Waypoint(0, 1, 2), Waypoint(3, 1 + meta.leg, 2)])
    validate_batch({"batch_id": "c", "ops": ops})
    names = {b["name"] for o in ops if o["op"] == "create_armature" for b in o["bones"]}
    assert (
        {"hips", "chest", "head", "leg_LF_up", "leg_RH_lo"} <= names and meta.neck_bones and meta.tail_bones
    )
    assert sum(o["op"] == "add_bone_constraint" for o in ops) == 4  # IK on every leg
    if species == "elephant":
        assert len(meta.trunk_bones) == 5
    assert all(k[2] == "LINEAR" for o in keys if o["target"].endswith(("_ik_LF", "_root")) for k in o["keys"])
