"""Acting layers: bone-frame maths, eyelines, gestures, and the trunk spray."""

from __future__ import annotations

import math

import pytest

from animatica.creatures.build import build_creature
from animatica.creatures.gait import GAITS, Waypoint
from animatica.creatures.gesture import (
    IDENT,
    KINDS,
    Gesture,
    Rig,
    acting_layers,
    apply,
    axis_angle,
    euler_to_mat,
    gaze_track,
    heading_to,
    local_rotation,
    mat_mul,
    mat_to_euler,
    rest_matrix,
    spray_droplets,
    transpose,
)
from animatica.creatures.perform import plan_for, walk_keys
from animatica.creatures.species import SPECIES
from animatica.production.scene import Line


def _close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for ra, rb in zip(a, b) for x, y in zip(ra, rb))


@pytest.mark.parametrize("d", [(0, 1, 0), (0, -1, 0.2), (0.3, -0.4, 0.9), (0, 0, -1), (0, -1, 0)])
def test_rest_matrix_is_a_rotation_that_points_y_along_the_bone(d):
    b = rest_matrix(d)
    n = math.sqrt(sum(c * c for c in d))
    assert apply(b, (0, 1, 0)) == pytest.approx(tuple(c / n for c in d), abs=1e-9)
    assert _close(mat_mul(transpose(b), b), IDENT)


def test_local_rotation_reproduces_the_body_space_rotation():
    d = (0.2, -0.5, 0.8)
    for axis in ((0, 0, 1), (1, 0, 0), (0.3, 0.2, 0.9)):
        p = local_rotation(d, axis, 37.0)
        b = rest_matrix(d)
        assert _close(mat_mul(b, mat_mul(p, transpose(b))), axis_angle(axis, 37.0))


def test_euler_round_trip_matches_blender_xyz_order():
    for e in ([10, -20, 30], [0, 0, 75], [-40, 5, -120]):
        assert mat_to_euler(euler_to_mat(e)) == pytest.approx(e, abs=1e-6)
    # XYZ order: X is applied first, so Z then turns the X-rotated frame
    assert _close(euler_to_mat([90, 0, 90]), mat_mul(axis_angle((0, 0, 1), 90), axis_angle((1, 0, 0), 90)))


def _plans(fps=24, seconds=6.0):
    out = {}
    for cid, sp, at, yaw in (("a", "zebra", (0.0, 0.0), 0.0), ("b", "giraffe", (3.0, 0.0), 0.0)):
        _ops, meta = build_creature(cid, SPECIES[sp], at=at, yaw=yaw)
        pts = [Waypoint(0.0, *at), Waypoint(seconds, *at)]
        out[cid] = (meta, plan_for(meta, GAITS[sp]["walk"], pts, fps, yaw0=yaw))
    return out


def test_listeners_turn_toward_the_speaker_smoothly_and_turn_back():
    fps = 24
    built = _plans(fps)
    plans = {c: p for c, (_m, p) in built.items()}
    ln = Line(who="b", text="hi", start=2.0, end=3.5)
    g = gaze_track("a", plans, [ln], [], fps)
    # b stands at +X; a faces -Y, so b is to a's left: a counter-clockwise (+) turn of 90 deg, clamped
    want = heading_to(plans["a"][0].root, plans["b"][0].root) - plans["a"][0].yaw
    assert want == pytest.approx(90.0, abs=1)
    assert abs(g[int(1.0 * fps)]) < 1.0  # nobody is talking yet
    assert g[int(3.0 * fps)] > 60.0  # looking at the speaker
    assert abs(g[int(5.9 * fps)]) < 8.0  # and back again
    assert max(abs(x - y) for x, y in zip(g, g[1:])) < 12.0  # glides, never snaps
    # the speaker turns only part of the way toward the addressee (the lens cheat)
    ln.to = "a"
    gb = gaze_track("b", plans, [ln], [], fps)
    assert -45.0 < gb[int(3.0 * fps)] < -20.0


@pytest.mark.parametrize("kind", [k for k in KINDS if not k.startswith("trunk") and k != "look_at"])
def test_gestures_move_only_inside_their_window(kind):
    fps = 24
    meta, plan = _plans(fps)["b"]
    rig = Rig("giraffe", meta.bone_dirs, meta.neck_bones, [], meta.ear_bones)
    lay = acting_layers(rig, plan, None, [Gesture("b", kind, 2.0, 1.5)], fps)
    moved = [k for k in range(len(plan)) if any(not _close(lay[b][k], IDENT, 1e-4) for b in lay)]
    assert moved, kind
    assert min(moved) >= int(2.0 * fps) and max(moved) <= int(3.5 * fps) + 1


def test_trunk_spray_raises_the_trunk_and_drops_land_on_the_target():
    fps = 24
    _ops, meta = build_creature("t", SPECIES["elephant"], at=(0.0, 0.0), yaw=0.0)
    pts = [Waypoint(0.0, 0.0, 0.0), Waypoint(4.0, 0.0, 0.0)]
    plan = plan_for(meta, GAITS["elephant"]["walk"], pts, fps, yaw0=0.0)
    rig = Rig("elephant", meta.bone_dirs, meta.neck_bones, meta.trunk_bones, meta.ear_bones)
    lay = acting_layers(rig, plan, None, [Gesture("t", "trunk_spray", 1.0, 1.0, target="")], fps)
    tip = meta.trunk_bones[-1]
    # mid-gesture the trunk tip bone points forward/up much more than at rest
    rest = meta.bone_dirs[tip]
    raised = apply(rest_matrix(rest), apply(lay[tip][int(1.5 * fps)], (0, 1, 0)))
    assert raised[2] > rest[2] / math.sqrt(sum(c * c for c in rest)) + 0.2
    keys, _ = walk_keys(meta, GAITS["elephant"]["walk"], pts, fps, 1, yaw0=0.0, plan=plan, overlay=lay)
    assert any(k["property"] == f"bone:{tip}.rotation" for k in keys)
    tips = {f: (0.0, -1.0 - 0.01 * (f - 30), 1.0) for f in range(30, 37)}
    head = (-3.0, -1.5, 0.35)
    ops = spray_droplets("t", tips, head, fps, 120, count=12, seed=1)
    drops = [o for o in ops if o["op"] == "create_primitive"]
    assert len(drops) == 12
    for o in ops:
        if o["op"] == "insert_keyframes" and o["property"] == "location":
            first, path = o["keys"][0], [k[1] for k in o["keys"]]
            assert first[0] in tips and first[1] == pytest.approx(list(tips[first[0]]), abs=1e-3)
            near = min(math.dist(p, head) for p in path)
            assert near < 0.45  # every drop reaches the target's head
            assert path[-1][2] >= 0.0  # and is gone before it sinks into the ground
        if o["op"] == "insert_keyframes" and o["property"] == "scale":
            assert o["keys"][0][1] == [0.0, 0.0, 0.0]  # hidden before launch
