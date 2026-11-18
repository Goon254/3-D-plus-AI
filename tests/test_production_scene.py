"""Animatic additions to the scene model: walks timed off lines, long holds split into new angles."""


def test_paths_timed_off_lines_follow_the_voice_takes():
    """Animatic specs start walks on lines: the waypoints move with however long the takes turned out."""
    from animatica.production.scene import scene_from_dict, schedule

    d = {
        "id": "x",
        "title": "x",
        "tod": "dawn",
        "cue": "x",
        "seconds": 4,
        "layout": {},
        "cast": {
            "tembo": {
                "species": "elephant",
                "at": [0, 0],
                "path": [{"line": 0, "dt": 0.5, "at": [0, 0]}, {"then": 3.0, "at": [2, 0]}],
            }
        },
        "lines": [{"who": "tembo", "text": "Hello there.", "at": 1.0}],
        "shots": [],
    }
    short, long_ = scene_from_dict(d), scene_from_dict(d)
    schedule(short, [1.0])
    secs = schedule(long_, [2.5])
    assert short.cast["tembo"].path == [(2.5, 0.0, 0.0), (5.5, 2.0, 0.0)]
    assert long_.cast["tembo"].path == [(4.0, 0.0, 0.0), (7.0, 2.0, 0.0)]
    assert secs >= 7.5  # the scene runs long enough to finish the walk


def test_split_long_cuts_every_hold_to_new_angles():
    from animatica.production.scene import Shot, split_long

    shots = [Shot("ws", ["a"], t=0.0, start=0.0), Shot("cu", ["a"], t=10.0, start=10.0, side=5.0)]
    out = split_long(shots, 12.0, max_len=4.5)
    assert [s.start for s in out] == [0.0, 3.333, 6.667, 10.0]
    assert max(s.end - s.start for s in out) <= 4.5
    assert [s.side for s in out[:3]] == [0.0, 22.0, -22.0] and out[3].side == 5.0
