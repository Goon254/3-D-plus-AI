"""Dead air across cuts (``animatica.production.pacing``) and the per-shot static check it backs up."""

from __future__ import annotations

import dataclasses
import importlib
import math
import sys
from pathlib import Path

from animatica.production.continuity import actor_speeds
from animatica.production.pacing import MAX_DEAD_S, dead_air, life_at
from animatica.production.scene import cut_list, load_scenes, schedule, split_long
from animatica.production.staging import approx_cameras, poses_from_paths

ROOT = Path(__file__).resolve().parents[1]
FPS = 24


def _scene(path: Path, sid: str = "sc01", edit=None):
    spec = load_scenes(path)[sid]
    if edit:
        edit(spec)
    secs = schedule(spec, [0.6 + 0.36 * len(ln.text.split()) for ln in spec.lines], actor_speeds(spec))
    shots = split_long(cut_list(spec, secs), secs)
    poses = poses_from_paths(spec, secs, FPS)
    return spec, secs, poses, approx_cameras(spec, shots, poses, FPS)


def _animatic():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module("savannah_animatic")
    finally:
        sys.path.pop(0)


def test_the_old_empty_opening_is_dead_air_and_the_opening_with_herds_and_birds_is_not():
    """The owner's 11-16 note: "the first scene has no animal movement" (22 s of empty set). The opening with
    giraffes and zebras crossing and two flocks (DECISIONS #75) passes."""
    spec, secs, poses, cams = _scene(ROOT / "tests" / "data" / "sc01_2026-11-16.json")
    bad = dead_air(spec, cams, poses, FPS, secs)
    assert len(bad) == 1 and bad[0].kind == "dead_air"
    assert (
        bad[0].t == 0.0 and "for 22.0 s" in bad[0].detail and "through shot" in bad[0].detail
    )  # across the cuts

    spec, secs, poses, cams = _scene(ROOT / "films" / "savannah" / "07_scenes.json")
    assert dead_air(spec, cams, poses, FPS, secs) == []
    found = {w for t in range(0, int(secs)) for w in life_at(spec, _cam(cams, t), t, poses, FPS)}
    assert any(w.startswith("giraffe") for w in found) and any(w.startswith("zebra") for w in found)
    assert any(w.startswith("birds") for w in found)


def _cam(cams, t):
    from animatica.production.pacing import _cam_at

    return _cam_at(next(c for c in cams if c["start"] <= t < c["end"]), t)


def test_the_per_shot_static_check_cannot_see_the_old_opening():
    """Why the scene-level measure exists: every shot pushes in and orbits, so ``static_shots`` passes each of
    the old opening's set shots although nothing in them moves; a locked-off shot of the same length fails."""
    anim = _animatic()
    spec, secs, poses, cams = _scene(ROOT / "tests" / "data" / "sc01_2026-11-16.json")
    rep = {
        "shots": [
            {**c, "camera_move_frac": math.dist(c["location"], c["end_location"]) / c["frame_h_m"]}
            for c in cams
        ]
    }
    assert anim.static_shots(rep, MAX_DEAD_S) == []
    locked = {"shots": [{"shot": 0, "type": "ews", "start": 0.0, "end": 6.0, "camera_move_frac": 0.0}]}
    assert anim.static_shots(locked, MAX_DEAD_S) == [{"shot": 0, "type": "ews", "seconds": 6.0}]
    short = {"shots": [{"shot": 0, "type": "ews", "start": 0.0, "end": 4.0, "camera_move_frac": 0.0}]}
    moving = {"shots": [{"shot": 0, "type": "ews", "start": 0.0, "end": 6.0, "subject_move_frac": 0.05}]}
    assert anim.static_shots(short, MAX_DEAD_S) == [] and anim.static_shots(moving, MAX_DEAD_S) == []


def test_a_held_shot_or_a_flock_fills_the_dead_air():
    old = ROOT / "tests" / "data" / "sc01_2026-11-16.json"

    def hold(spec):
        spec.shots = [dataclasses.replace(s, hold=True) for s in spec.shots]

    spec, secs, poses, cams = _scene(old, edit=hold)
    assert dead_air(spec, cams, poses, FPS, secs) == []

    def birds(spec):  # one flock crossing the EWS : the rest of the scene is still dead
        spec.layout = {
            **spec.layout,
            "birds": [{"from": [-20.0, 15.0, 6.0], "to": [22.0, 11.0, 7.5], "t0": 0.3, "t1": 9.5, "n": 6}],
        }

    spec, secs, poses, cams = _scene(old, edit=birds)
    bad = dead_air(spec, cams, poses, FPS, secs)
    assert len(bad) == 1 and 5.0 <= bad[0].t <= 9.5  # dead again once the flock has crossed the frame


def test_the_film_finds_the_climax_hold_on_kikis_back():
    """SC 9's last shots (4:36-4:48 in the film): Kiki stands still with her back to us by the spring for
    over ten seconds, cut into four parts from new angles; confirmed by eye on the animatic v2 (11-20 09:36)."""
    spec, secs, poses, cams = _scene(ROOT / "films" / "savannah" / "07_scenes.json", "sc09")
    bad = dead_air(spec, cams, poses, FPS, secs)
    assert len(bad) == 1 and "through shot" in bad[0].detail
    assert secs - bad[0].t > 10.0


def _report(spec, secs, cams, stretch: float = 1.0):
    """A scene report as ``savannah_scene.py`` writes it: the shot cameras and the voice takes' timings."""
    return {
        "seconds": secs,
        "shots": [{**c, "hold": c.get("hold", False)} for c in cams],
        "lines": [
            {
                "who": ln.who,
                "text": ln.text,
                "start": ln.start,
                "end": ln.start + (ln.end - ln.start) * stretch,
            }
            for ln in spec.lines
        ],
    }


def test_the_animatic_lists_dead_air_from_the_scene_reports_own_cameras():
    """The animatic's report shows dead air per scene from each scene's real cameras (here the same cameras,
    written as a scene report), not only ``continuity_check.py``'s approximate ones; soft rows, one per run."""
    anim = _animatic()
    film = ROOT / "films" / "savannah" / "07_scenes.json"
    spec, secs, poses, cams = _scene(film, "sc09")
    rep = _report(spec, secs, cams)
    rows = anim.dead_air_rows(
        load_scenes(film)["sc09"], rep
    )  # a fresh, unscheduled spec, as the animatic has
    assert len(rows) == 1 and rows[0]["scene"] == "sc09" and secs - rows[0]["t"] > 10.0
    assert "through shot" in rows[0]["detail"]

    spec, secs, poses, cams = _scene(film, "sc01")
    assert anim.dead_air_rows(load_scenes(film)["sc01"], _report(spec, secs, cams)) == []
    old = ROOT / "tests" / "data" / "sc01_2026-11-16.json"
    spec, secs, poses, cams = _scene(old)
    rows = anim.dead_air_rows(load_scenes(old)["sc01"], _report(spec, secs, cams))
    assert len(rows) == 1 and rows[0]["t"] == 0.0


def test_dead_air_in_a_report_uses_its_takes_and_needs_its_cameras():
    """The line timings come from the report's voice takes (the laptop's real voices), and a report without
    cameras (written before the shots carried them) gives nothing rather than guessing."""
    from animatica.production.pacing import dead_air_in_report, line_durations

    film = ROOT / "films" / "savannah" / "07_scenes.json"
    spec, secs, poses, cams = _scene(film, "sc09")
    rep = _report(spec, secs, cams, stretch=1.5)
    fresh = load_scenes(film)["sc09"]
    want = [(ln.end - ln.start) * 1.5 for ln in spec.lines]
    assert all(abs(a - b) < 1e-9 for a, b in zip(line_durations(fresh, rep), want, strict=True))
    estimate = [0.6 + 0.36 * len(ln.text.split()) for ln in fresh.lines]
    partial = {**rep, "lines": rep["lines"][1:]}  # one take missing: fall back to the estimate for all
    assert line_durations(fresh, partial) == estimate and line_durations(fresh, None) == estimate
    dead_air_in_report(fresh, rep)
    assert abs((fresh.lines[0].end - fresh.lines[0].start) - want[0]) < 1e-6  # scheduled with the takes
    bare = {
        **rep,
        "shots": [{k: v for k, v in s.items() if k not in ("location", "aim")} for s in rep["shots"]],
    }
    assert dead_air_in_report(load_scenes(film)["sc09"], bare) == []
