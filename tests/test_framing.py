"""Crowding: a neighbour's headless body filling part of a face shot (``animatica.production.framing``;
DECISIONS #103)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _kiki_and_neema(gx: float, gy: float):
    """Kiki at the origin facing the camera, Neema side-on at (gx, gy)."""
    from animatica.production.scene import scene_from_dict
    from animatica.production.staging import poses_from_paths

    spec = scene_from_dict(
        {
            "id": "scx",
            "tod": "midday",
            "seconds": 4,
            "layout": {},
            "lines": [],
            "shots": [],
            "cast": {
                "kiki": {"species": "meerkat", "at": [0.0, 0.0], "yaw": 0},
                "neema": {"species": "giraffe", "at": [gx, gy], "yaw": 90},
            },
        }
    )
    return spec, poses_from_paths(spec, 2.0, 24)


def _shot(typ: str = "mcu", dist: float = 2.0, z: float = 0.3, lens: float = 50.0, **kw) -> dict:
    loc = [0.0, -dist, z]
    return {"shot": 0, "type": typ, "subjects": ["kiki"], "start": 0.0, "end": 2.0, "location": loc,
            "end_location": loc, "aim": [0.0, 0.0, z], "lens": lens, **kw}  # fmt: skip


def test_painters_pass_lets_the_nearer_box_cover_the_farther():
    from animatica.production.framing import paint

    far, near = (0.0, 0.0, 0.5, 1.0), (0.25, 0.0, 0.75, 1.0)
    got = paint([(near, 2.0, "near"), (far, 9.0, "far")])  # order given does not matter, depth does
    assert got["near"] == pytest.approx(0.5) and got["far"] == pytest.approx(0.25)
    assert paint([((-1.0, -1.0, 2.0, 2.0), 1.0, "all")]) == {
        "all": pytest.approx(1.0)
    }  # clipped to the frame


def test_a_giraffes_legs_beside_kikis_close_up_are_crowding_and_a_whole_giraffe_is_not():
    """The 2:30 / 3:12 film note: a neighbour's legs, its head far out of the top of the frame."""
    from animatica.production.framing import CROWD_AREA, crowding, frame_shares

    spec, poses = _kiki_and_neema(0.7, 0.8)
    shares = frame_shares(spec, _shot(), {c: poses[c][0] for c in poses})
    assert shares["neema"][0] > 4 * CROWD_AREA and shares["neema"][1] == 0.0  # legs fill it, head out of shot
    assert shares["kiki"][1] == 1.0
    bad = crowding(spec, [_shot()], poses, 24)
    assert [(v.kind, v.who) for v in bad] == [("crowding", "neema")] and "100 %" in bad[0].detail
    assert crowding(spec, [_shot(crowd_ok=True)], poses, 24) == []  # a foreground body that is the point
    from animatica.production.scene import scene_from_dict

    written = scene_from_dict(
        {
            "id": "scy",
            "tod": "midday",
            "seconds": 4,
            "layout": {},
            "cast": {"kiki": {"species": "meerkat", "at": [0.0, 0.0]}},
            "shots": [{"type": "mcu", "subjects": ["kiki"], "t": 0.0, "crowd_ok": True}],
        }
    )
    assert written.shots[0].crowd_ok  # the scene file can say so
    assert crowding(spec, [_shot("ws")], poses, 24) == []  # wides are not face shots
    # in front of Kiki, hiding her: still a headless body filling the close-up
    spec, poses = _kiki_and_neema(-0.7, -0.6)
    assert [v.who for v in crowding(spec, [_shot()], poses, 24)] == ["neema"]
    # far back, the whole giraffe small in the frame; or off to the side, out of it: fine
    for gx, gy in ((3.0, 30.0), (6.0, 0.8)):
        spec, poses = _kiki_and_neema(gx, gy)
        assert crowding(spec, [_shot()], poses, 24) == []


def test_a_neighbour_whose_face_is_in_the_shot_is_staging_not_crowding():
    from animatica.production.framing import crowding, frame_shares

    spec, poses = _kiki_and_neema(1.2, 0.8)
    two = _shot("ms", dist=9.0, z=1.6, lens=35.0)
    shares = frame_shares(spec, two, {c: poses[c][0] for c in poses})
    assert shares["neema"][1] > 0.5  # her head is in the frame
    assert crowding(spec, [two], poses, 24) == []


def test_the_film_finds_the_leg_columns_the_reviews_named_and_not_the_slivers():
    """Calibrated by eye on the final film (cloud review 11-20 18:36): SC 6 shots 11-12 (Neema's legs beside
    Zuri, ~3:15), SC 7 shot 5 (Tembo's leg column by Bibi Kobe's MCU, 3:34), SC 8 shot 2 (Zuri's legs over
    the night tortoise MCU); SC 7 shot 2's hoof sliver at the edge of Tembo's close-up is not."""
    from animatica.production.continuity import actor_speeds
    from animatica.production.framing import crowding
    from animatica.production.scene import cut_list, load_scenes, schedule, split_long
    from animatica.production.staging import approx_cameras, poses_from_paths

    scenes = load_scenes(ROOT / "films" / "savannah" / "07_scenes.json")
    found = set()
    for sid in ("sc06", "sc07", "sc08"):
        spec = scenes[sid]
        secs = schedule(spec, [0.6 + 0.36 * len(ln.text.split()) for ln in spec.lines], actor_speeds(spec))
        shots = split_long(cut_list(spec, secs), secs)
        poses = poses_from_paths(spec, secs, 24)
        for v in crowding(spec, approx_cameras(spec, shots, poses, 24), poses, 24):
            found.add((sid, int(v.detail.split()[1]), v.who))
    assert {("sc06", 11, "neema"), ("sc06", 12, "neema"), ("sc07", 5, "tembo"), ("sc08", 2, "zuri")} <= found
    assert not any(sid == "sc07" and shot == 2 for sid, shot, _ in found)
