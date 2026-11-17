"""Scene production: spec loading, line timing, cuts, expression tracks, camera framing, the scene mix."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from animatica.audio import ambience
from animatica.production import sound
from animatica.production.scene import (
    MIN_SHOT,
    Occluder,
    Subject,
    blocked,
    cut_list,
    expression_tracks,
    frame_shot,
    load_scenes,
    scene_from_dict,
    schedule,
    set_subject,
    vfov,
)

SCENES = Path(__file__).resolve().parents[1] / "films" / "savannah" / "07_scenes.json"


def _spec(**kw):
    d = {
        "id": "t",
        "tod": "dawn",
        "seconds": 6,
        "cast": {"a": {"species": "zebra", "at": [0, 0]}, "b": {"species": "meerkat", "at": [2, 0]}},
        "lines": [{"who": "a", "text": "one"}, {"who": "b", "text": "two", "at": 1.5}],
        "shots": [
            {"type": "ws", "subjects": ["a", "b"], "t": 0},
            {"type": "ms", "subjects": ["b"], "line": 1},
        ],
    }
    d.update(kw)
    return scene_from_dict(d)


def test_film_scene_specs_load_and_validate():
    scenes = load_scenes(SCENES)
    assert {"sc01", "sc02"} <= set(scenes)
    sc02 = scenes["sc02"]
    assert {a.species for a in sc02.cast.values()} == {"zebra", "meerkat", "elephant", "giraffe"}
    assert all(s.subjects or s.look for s in sc02.shots)


@pytest.mark.parametrize(
    "bad",
    [
        {"lines": [{"who": "nobody", "text": "hi"}]},
        {"shots": [{"type": "ms", "subjects": ["a"], "t": 0, "line": 0}]},
        {"shots": [{"type": "xcu", "subjects": ["a"], "t": 0}]},
        {"shots": [{"type": "ms", "subjects": ["zz"], "t": 0}]},
        {"shots": [{"type": "ws", "subjects": [], "t": 0}]},  # a set shot needs look + frame_h
        {"reactions": [{"who": "zz", "t": 1, "expr": "happy"}]},
        {"gestures": [{"who": "a", "kind": "moonwalk", "t": 1}]},  # unknown gesture
        {"gestures": [{"who": "a", "kind": "trunk_drink", "t": 1}]},  # a zebra has no trunk
        {"gestures": [{"who": "a", "kind": "look_at", "t": 1}]},  # look at whom?
        {"gestures": [{"who": "a", "kind": "nod", "line": 7}]},
        {"lines": [{"who": "a", "text": "hi", "to": "zz"}]},
    ],
)
def test_bad_specs_are_rejected(bad):
    with pytest.raises(ValueError):
        _spec(**bad)


def test_lines_never_overlap_and_the_scene_fits_them():
    sp = _spec()
    seconds = schedule(sp, [2.0, 1.0])  # line 1 wants 1.5 s but line 0 runs to 3.0 s
    a, b = sp.lines
    assert a.start == sp.lead and a.end == pytest.approx(3.0)
    assert b.start >= a.end + 0.15 and sp.warnings  # pushed later, and reported
    assert seconds >= b.end + sp.tail - 1e-6


def test_cuts_land_before_the_line_and_short_shots_are_dropped():
    sp = _spec(
        shots=[
            {"type": "ws", "subjects": ["a", "b"], "t": 0},
            {"type": "ms", "subjects": ["a"], "line": 0},
            {"type": "cu", "subjects": ["b"], "line": 0, "after": 0.1},
            {"type": "ms", "subjects": ["b"], "line": 1},  # 0.4 s after the cu: too short
        ]
    )
    seconds = schedule(sp, [2.0, 1.0])
    shots = cut_list(sp, seconds)
    assert shots[0].start == 0.0
    assert all(s.end - s.start >= MIN_SHOT - 1e-6 for s in shots)
    # the line starts at 1.0 s: cutting 0.35 s early would leave the opening wide 0.65 s long, so it holds
    assert shots[1].start == pytest.approx(MIN_SHOT) and any("delayed" in w for w in sp.warnings)
    assert [s.start for s in shots] == sorted(s.start for s in shots)
    assert shots[-1].end == seconds


def test_cut_lands_just_before_the_first_word():
    sp = _spec(lead=3.0)
    schedule(sp, [1.0, 1.0])
    shots = cut_list(sp, 8.0)
    assert shots[1].start == pytest.approx(sp.lines[1].start - 0.35)


def test_expression_tracks_follow_lines_and_reactions():
    sp = _spec(
        lines=[{"who": "a", "text": "x", "expr": [[0, "happy"], [0.5, "sad"]]}],
        shots=[{"type": "ws", "subjects": ["a"], "t": 0}],
        reactions=[{"who": "b", "line": 0, "dt": 0.3, "expr": "surprised"}],
    )
    schedule(sp, [1.0])
    tr = expression_tracks(sp)
    assert tr["a"] == [(0.0, "neutral"), (1.0, "happy"), (1.5, "sad")]
    assert tr["b"] == [(0.0, "neutral"), (2.3, "surprised")]


def _subj(x=0.0, y=0.0, yaw=0.0, head=0.3, height=1.4, length=1.8):
    return Subject(
        head=(x, y - 0.6, height - head / 2),
        root=(x, y, 0.8),
        yaw=yaw,
        head_size=head,
        height=height,
        length=length,
    )


@pytest.mark.parametrize("kind", ["cu", "mcu", "ms", "ws"])
def test_cameras_stay_on_the_camera_side_and_frame_the_subject(kind):
    for yaw in (0.0, 90.0, -90.0, 180.0):  # even a subject facing away keeps the camera on the -Y side
        s = _subj(yaw=yaw)
        cam = frame_shot(kind, [s])
        loc, aim = cam["location"], cam["aim"]
        d = (loc[0] - aim[0], loc[1] - aim[1])
        ang = math.degrees(math.atan2(d[0], -d[1]))  # 0 = straight down -Y
        assert abs(ang) <= 70.1, (kind, yaw, ang)
        # the frame height at the aim point is what the shot size asked for
        dist = math.dist(loc, aim)
        assert 2 * dist * math.tan(vfov(cam["lens"]) / 2) == pytest.approx(cam["frame_h"], rel=0.05)


def test_close_ups_are_tighter_than_mediums_and_wides_fit_everyone():
    s = _subj()
    cu, mcu, ms = (frame_shot(k, [s])["frame_h"] for k in ("cu", "mcu", "ms"))
    assert cu < mcu < ms
    far = _subj(x=8.0)
    ws = frame_shot("ws", [s, far])
    assert ws["frame_h"] * 16 / 9 >= 8.0 + 1.8  # both bodies across the frame width
    assert min(0.0, 8.0) <= ws["aim"][0] <= 8.0
    spot = frame_shot("ews", [set_subject((1.0, 9.0, 3.0), 9.0)], aim_z=3.0)
    assert spot["aim"] == [1.0, 9.0, 3.0] and spot["frame_h"] == pytest.approx(9.0)


def test_scene_mix_ducks_music_under_lines_and_keeps_dialogue_clear():
    sr = sound.SR
    t = np.arange(int(1.5 * sr)) / sr
    voice = np.stack([np.sin(2 * np.pi * 180 * t) * 0.3] * 2, axis=1).astype(np.float32)
    music = np.stack([np.sin(2 * np.pi * 440 * np.arange(6 * sr) / sr) * 0.3] * 2, axis=1).astype(np.float32)
    amb = ambience.bed("dawn", 6.0, water=True, seed=1)
    mix, rep = sound.mix_scene(6.0, [(2.0, voice)], music, amb, None, [(4.5, ambience.sfx("splash"))])
    assert mix.shape == (6 * sr, 2)
    assert rep["dialogue_clarity_db"] >= 10.0
    # music is ~18 dB down inside the line compared with before it
    m_only, _ = sound.mix_scene(6.0, [(2.0, voice * 0)], music, None)
    duck = sound.duck_envelope(6 * sr, [(2 * sr, int(3.5 * sr))])
    assert duck[int(2.7 * sr)] == pytest.approx(1.0) and duck[int(0.5 * sr)] == 0.0
    inside = sound.db(m_only[int(2.5 * sr) : int(3.2 * sr)])
    before = sound.db(m_only[int(0.5 * sr) : int(1.2 * sr)])
    assert before - inside >= 15.0


@pytest.mark.parametrize("kind", ["drip", "slurp", "splash", "log_roll"])
def test_sfx_are_stereo_short_and_audible(kind):
    x = ambience.sfx(kind, seed=3)
    assert x.ndim == 2 and x.shape[1] == 2 and 0.1 * sound.SR < len(x) < 2.5 * sound.SR
    assert 0.02 < float(np.abs(x).max()) < 1.0


def test_gestures_and_addressees_load_and_long_holds_do_not_stretch_the_scene():
    sp = _spec(
        lines=[{"who": "a", "text": "one", "to": "b"}],
        shots=[{"type": "ws", "subjects": ["a", "b"], "t": 0}],
        gestures=[
            {"who": "b", "kind": "head_duck", "t": 0.5, "dur": 60},
            {"who": "b", "kind": "nod", "line": 0, "dt": 0.2, "dur": 1.0},
        ],
    )
    assert sp.lines[0].to == "b" and sp.eyelines
    assert [g.value for g in sp.gestures] == ["head_duck", "nod"]
    seconds = schedule(sp, [1.0])
    assert seconds < 10  # the 60 s hold is a pose, not a beat that needs screen time
    assert sp.gestures[1].time(sp.lines) == pytest.approx(sp.lines[0].end + 0.2)


def test_sc02_stages_the_puddle_gag():
    sc02 = load_scenes(SCENES)["sc02"]
    kinds = {(g.who, g.value) for g in sc02.gestures}
    assert {("tembo", "trunk_drink"), ("tembo", "trunk_spray"), ("tembo", "ears_droop")} <= kinds
    assert ("neema", "head_duck") in kinds
    spray = next(g for g in sc02.gestures if g.value == "trunk_spray")
    assert spray.target == "kiki"


@pytest.mark.parametrize("kind", ["cu", "mcu", "ms"])
def test_cameras_swing_around_an_animal_standing_in_the_way(kind):
    s = _subj(yaw=-40.0)
    free = frame_shot(kind, [s])
    loc, aim = free["location"], free["aim"]
    # put a zebra-sized body halfway along the sight line
    r = 0.15 * free["distance"]  # a head or a body, in proportion to how close the camera is
    zebra = Occluder((loc[0] + aim[0]) / 2, (loc[1] + aim[1]) / 2, r, 1.5)
    assert blocked(tuple(loc), tuple(aim), zebra, free["frame_h"])
    cam = frame_shot(kind, [s], occluders=[zebra])
    assert cam["swing"] != 0.0 and "blocked" not in cam
    assert not blocked(tuple(cam["location"]), tuple(cam["aim"]), zebra, cam["frame_h"])
    d = (cam["location"][0] - cam["aim"][0], cam["location"][1] - cam["aim"][1])
    assert abs(math.degrees(math.atan2(d[0], -d[1]))) <= 75.1  # still on the camera side
    # something behind the subject, or off to the side, doesn't count
    behind = Occluder(aim[0] - (loc[0] - aim[0]), aim[1] - (loc[1] - aim[1]), r, 1.5)
    assert not blocked(tuple(loc), tuple(aim), behind, free["frame_h"])
    assert frame_shot(kind, [s], occluders=[behind])["swing"] == 0.0
