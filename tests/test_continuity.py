"""Continuity (owner's catch, animatic 11-18): Zuri ran off into the grass in SC 5 and still stood in the open at
the start of SC 6. Presence is now explicit (enter / exit / story exits) and checked; paths aim at places."""

import math

from animatica.production.continuity import check_scene, check_story, in_frame
from animatica.production.scene import cut_list, scene_from_dict, schedule


def _scene(sid: str, zuri: dict, lines=None, shots=None) -> dict:
    return {
        "id": sid,
        "title": sid,
        "tod": "afternoon",
        "cue": sid,
        "seconds": 12,
        "layout": {"action": [[0.0, 0.0, 3.0]], "water": [1.0, 4.0, 1.0]},
        "cast": {"tembo": {"species": "elephant", "at": [0, 0]}, "zuri": {"species": "zebra", **zuri}},
        "lines": lines or [{"who": "tembo", "text": "Zuri, wait!", "at": 1.0}],
        "shots": shots or [{"type": "ws", "subjects": ["tembo"], "t": 0}],
    }


RUN_OFF = {
    "at": [1.0, 0.0],
    "gait": "canter",
    "path": [{"t": 2.0, "at": [1.0, 0.0]}, {"to": "exit:back"}],
    "exit": "auto",
    "story_exit": True,
}


def _check(d: dict, speeds=None):
    spec = scene_from_dict(d)
    secs = schedule(spec, [1.0 for _ in spec.lines], speeds)
    shots = cut_list(spec, secs)
    return spec, check_scene(spec, shots, secs)[0]


def test_a_character_who_ran_off_cannot_stand_in_the_next_scene():
    a = scene_from_dict(_scene("a", RUN_OFF))
    still_there = scene_from_dict(_scene("b", {"at": [2.0, 1.0]}))
    bad = check_story([a, still_there])
    assert [v.kind for v in bad] == ["story_absent"] and bad[0].who == "zuri"
    found = scene_from_dict(
        _scene(
            "b",
            {"at": [2.0, 20.0], "path": [{"t": 3.0, "at": [2.0, 20.0]}, {"at": [2.0, 3.0]}], "enter": "auto"},
        )
    )
    assert check_story([a, found]) == []


def test_exits_and_entrances_resolve_from_the_path_and_keep_off_stage_actors_away():
    spec, bad = _check(_scene("a", RUN_OFF), speeds={"zuri": 3.0})
    z = spec.cast["zuri"]
    assert z.path[-1][1:3] == (1.0, 16.0)  # exit:back walks 16 m on, away from the cameras
    assert math.isclose(
        z.path[-1][0], 2.0 + 16.0 / 3.0, abs_tol=0.01
    )  # an untimed move takes distance / speed
    assert 2.0 < z.t_out < z.path[-1][0]  # off stage once 9 m outside the action circle
    assert bad == []
    # an exit that stops at the edge of the set is caught
    near = dict(
        RUN_OFF, path=[{"t": 2.0, "at": [1.0, 0.0]}, {"then": 2.0, "at": [1.0, 5.0]}], exit={"t": 5.0}
    )
    _, bad = _check(_scene("a", near))
    assert [v.kind for v in bad] == ["offstage_near"]


def test_shots_lines_and_gestures_of_an_absent_actor_are_violations():
    lost = {
        "at": [2.0, 20.0],
        "path": [{"t": 6.0, "at": [2.0, 20.0]}, {"then": 4.0, "at": [2.0, 3.0]}],
        "enter": "auto",
    }
    lines = [{"who": "zuri", "text": "Hellooo?", "at": 1.0}]
    _, bad = _check(_scene("b", lost, lines=lines, shots=[{"type": "ms", "subjects": ["zuri"], "t": 0}]))
    assert {v.kind for v in bad} == {"line_offstage", "shot_subject"}
    lines[0]["offscreen"] = True  # heard, not seen: fine, as long as no shot shows her then
    _, bad = _check(_scene("b", lost, lines=lines))
    assert bad == []


def test_landmarks_and_glides():
    from animatica.creatures.gait import Waypoint, path_xy

    d = _scene(
        "a",
        {
            "at": [-3.0, 0.0],
            "path": [{"t": 0.0, "at": [-3.0, 0.0]}, {"then": 4.0, "to": "water", "near": 1.5}],
        },
    )
    spec, _ = _check(d)
    x, y = spec.cast["zuri"].path[-1][1:3]
    assert math.isclose(math.hypot(x - 1.0, y - 4.0), 1.5, abs_tol=0.01)  # stops at the water's edge
    # a run through a glide point is a curve with no stop at the corner
    pts = [Waypoint(0, 0, 0), Waypoint(0, 2, 0, glide=True), Waypoint(2, 2, 2)]
    near_corner = [path_xy(pts, t) for t in (0.9, 1.0, 1.1)]
    speeds = [math.dist(a, b) for a, b in zip(near_corner, near_corner[1:])]
    assert min(speeds) > 0.1  # still moving through the turn
    (ax, ay), (bx, by) = near_corner[0], near_corner[-1]
    assert (
        abs(bx - ax) > 0.05 and abs(by - ay) > 0.05
    )  # heading diagonally through the turn: an arc, no corner


def test_in_frame_projects_through_the_camera():
    cam = {"location": [0.0, -10.0, 1.0], "aim": [0.0, 0.0, 1.0], "lens": 35.0}
    assert in_frame(cam, (0.0, 0.0, 1.0))
    assert not in_frame(cam, (12.0, 0.0, 1.0))  # far off to the side
    assert not in_frame(cam, (0.0, -12.0, 1.0))  # behind the camera


def test_an_animal_walking_into_a_termite_mound_is_caught():
    """Animatic v2: Kiki's path ended inside the SC 4 mound and her close-up was a brown frame."""
    from animatica.production.continuity import inside_set
    from animatica.production.scene import scene_from_dict

    d = {
        "id": "scx",
        "tod": "midday",
        "seconds": 6,
        "layout": {"mounds": [[0.0, 3.0, 1.0]]},
        "cast": {"kiki": {"species": "meerkat", "at": [0.0, 0.0], "path": [[0.5, 0.0, 0.0], [3.0, 0.0, 2.9]]}},
        "lines": [],
        "shots": [],
    }
    spec = scene_from_dict(d)
    assert [v.kind for v in inside_set(spec, 6.0)] == ["inside_set"]
    d["cast"]["kiki"]["path"][-1] = [3.0, 0.0, 2.0]  # stops in front of it
    assert not inside_set(scene_from_dict(d), 6.0)
