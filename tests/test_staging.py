"""Staging tangents (cloud review 11-19 03:36): a farther animal's feet drawn on a nearer one's top outline."""

from __future__ import annotations

import math

import pytest


def _herd(cast: dict) -> dict:
    return {"id": "scx", "tod": "midday", "seconds": 4, "layout": {}, "cast": cast, "lines": [], "shots": []}


def _cam(height: float) -> dict:
    """A static low camera 4 m in front of the origin, looking along +Y at the ground's level."""
    return {
        "shot": 0,
        "type": "ws",
        "start": 0.0,
        "end": 2.0,
        "location": [0.0, -4.0, height],
        "end_location": [0.0, -4.0, height],
        "aim": [0.0, 4.0, height],
        "lens": 30.0,
    }


def _scene(zebra_y: float, zebra_x: float):
    from animatica.production.scene import scene_from_dict

    return scene_from_dict(
        _herd(
            {
                "bibi_kobe": {"species": "tortoise", "at": [0.0, 0.0], "yaw": 90},
                "zuri": {"species": "zebra", "at": [zebra_x, zebra_y], "yaw": 90},
            }
        )
    )


def _lined_up(height: float) -> tuple[float, float]:
    """Where to stand the zebra (side on) so her near feet sit exactly on the line from the camera over the
    top of the tortoise's shell: (x, y) of her root."""
    from animatica.production.continuity import footprint

    bibi, zuri = footprint("tortoise"), footprint("zebra")
    y_ground = -4.0 + 4.0 * height / (height - bibi.top)  # the sight line over the shell top meets the ground
    mid_t = (bibi.front + bibi.back) / 2
    # yaw 90: a root-frame (lx, ly) lands at (-ly, lx); her near feet (lx = -half_w) and front row (ly = front)
    return -mid_t + zuri.front, y_ground + zuri.half_w


def test_feet_on_a_nearer_shell_are_a_tangent_and_clear_of_it_are_not():
    from animatica.production.staging import poses_from_paths, staging_tangent

    h = 1.0
    x, y = _lined_up(h)
    spec = _scene(y, x)
    poses = poses_from_paths(spec, 2.0, 24)
    bad = staging_tangent(spec, [_cam(h)], poses, 24)
    assert [(v.kind, v.who) for v in bad] == [("staging_tangent", "zuri/bibi_kobe")]
    assert "0.0 %" in bad[0].detail
    # 3 m farther back her feet are drawn well above the shell: clear (from a camera 1 m up the ground 8 m
    # away is a thin strip, so one metre back is still only 2 % of the frame: still a tangent)
    spec = _scene(y + 1.0, x)
    assert len(staging_tangent(spec, [_cam(h)], poses_from_paths(spec, 2.0, 24), 24)) == 1
    spec = _scene(y + 3.0, x)
    assert staging_tangent(spec, [_cam(h)], poses_from_paths(spec, 2.0, 24), 24) == []
    # 3 m to the side her feet are beside the shell, not on it (1.5 m puts her hind feet on it instead)
    spec = _scene(y, x + 3.0)
    assert staging_tangent(spec, [_cam(h)], poses_from_paths(spec, 2.0, 24), 24) == []
    # from a camera high above, the same marks are no tangent: the shell's top is drawn far below her feet
    spec = _scene(y, x)
    assert staging_tangent(spec, [_cam(3.0)], poses_from_paths(spec, 2.0, 24), 24) == []


def test_project_puts_the_aim_at_the_centre_and_up_is_up():
    from animatica.production.continuity import in_frame, project

    cam = _cam(1.0)
    x, y, z = project(cam, (0.0, 4.0, 1.0))  # type: ignore[misc]
    assert (x, y, z) == pytest.approx((0.0, 0.0, 8.0))
    assert project(cam, (0.0, 0.0, 2.0))[1] > 0 > project(cam, (0.0, 0.0, 0.0))[1]  # type: ignore[index]
    assert project(cam, (1.0, 0.0, 1.0))[0] > 0  # +X is screen right from a camera looking along +Y
    assert project(cam, (0.0, -5.0, 1.0)) is None  # behind the camera
    # half the vertical field of view lands on the frame's top edge
    from animatica.production.scene import vfov

    top = (0.0, 0.0, 1.0 + 4.0 * math.tan(vfov(30.0) / 2))
    assert project(cam, top)[1] == pytest.approx(0.5)  # type: ignore[index]
    assert in_frame(cam, top) and not in_frame(cam, (0.0, 0.0, 1.0 + 4.6 * math.tan(vfov(30.0) / 2)))


def test_the_top_outline_is_the_back_or_the_shell():
    from animatica.production.continuity import footprint

    assert 0.4 < footprint("tortoise").top < 0.6  # the shell's dome, not the torso inside it
    assert 1.0 < footprint("zebra").top < 1.3  # the withers, not the head
    assert footprint("meerkat").top < 0.25


def test_the_film_finds_zuri_on_bibi_kobes_shell_in_sc10():
    """The 00:36 film review's 5:06 case, on the approximate cameras (rest heads, estimated line lengths)."""
    from pathlib import Path

    from animatica.production.continuity import actor_speeds
    from animatica.production.scene import cut_list, load_scenes, schedule, split_long
    from animatica.production.staging import approx_cameras, poses_from_paths, staging_tangent

    spec = load_scenes(Path(__file__).resolve().parents[1] / "films" / "savannah" / "07_scenes.json")["sc10"]
    secs = schedule(spec, [0.6 + 0.36 * len(ln.text.split()) for ln in spec.lines], actor_speeds(spec))
    shots = split_long(cut_list(spec, secs), secs)
    poses = poses_from_paths(spec, secs, 24)
    cams = approx_cameras(spec, shots, poses, 24)
    assert len(cams) == len(shots) and all("end_location" in c for c in cams)
    bad = staging_tangent(spec, cams, poses, 24)
    assert ["zuri/bibi_kobe"] == sorted({v.who for v in bad})


def test_shot_move_pushes_in_and_orbits_alternately():
    from animatica.production.scene import shot_move

    loc, aim = (0.0, -10.0, 2.0), (0.0, 0.0, 1.0)
    a, b = shot_move(loc, aim, "ws", 3.0, 0), shot_move(loc, aim, "ws", 3.0, 1)
    assert math.dist(a, aim) == pytest.approx(0.95 * math.dist(loc, aim))
    assert a[0] == pytest.approx(-b[0]) and a[0] != 0.0  # opposite orbits on alternate shots
    assert math.dist(shot_move(loc, aim, "cu", 3.0, 0), aim) == pytest.approx(0.92 * math.dist(loc, aim))
