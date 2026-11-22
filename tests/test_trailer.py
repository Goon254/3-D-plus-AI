"""The automatic trailer cut list (``production.trailer``, DECISIONS #107)."""

from __future__ import annotations

from pathlib import Path

from animatica.feature.planner import plan_scene
from animatica.feature.story import scripted_premise, scripted_screenplay, validate_screenplay
from animatica.production.continuity import actor_speeds
from animatica.production.pacing import line_durations
from animatica.production.scene import cut_list, load_scenes, scene_from_dict, schedule
from animatica.production.trailer import MAX_CUT_S, MIN_CUT_S, PICTURE_S, punch, trailer_cuts

ROOT = Path(__file__).resolve().parents[1]


def _savannah_reports() -> list[dict]:
    """The savannah's scenes scheduled on the word-count estimates (what the cloud has without the voices)."""
    reps = []
    for spec in load_scenes(ROOT / "films" / "savannah" / "07_scenes.json").values():
        secs = schedule(spec, line_durations(spec, None), actor_speeds(spec))
        lines = [
            {
                "who": ln.who,
                "text": ln.text,
                "start": ln.start,
                "end": ln.end,
                **({"key": True} if ln.key else {}),
            }
            for ln in spec.lines
        ]
        shots = [
            {"shot": i, "start": sh.start, "end": sh.end, "note": sh.note, "trailer": sh.trailer}
            for i, sh in enumerate(cut_list(spec, secs))
        ]
        reps.append({"scene": spec.id, "seconds": secs, "lines": lines, "shots": shots})
    return reps


def _texts(reps: list[dict], cuts: list[list]) -> list[str]:
    by = {r["scene"]: r for r in reps}
    return [
        ln["text"] for sid, a, d in cuts for ln in by[sid]["lines"] if ln["start"] < a + d and ln["end"] > a
    ]


def test_punchy_lines_score_above_long_explanations():
    assert punch("EVERYBODY PANIC!") > punch("Its water sings... and it never runs dry.")
    assert punch("Hello? Anybody?") > punch(" ".join(["word"] * 18) + ".")


def test_the_savannah_gets_a_trailer_like_the_hand_made_one():
    reps = _savannah_reports()
    by = {r["scene"]: r for r in reps}
    cuts = trailer_cuts(reps)
    total = sum(c[2] for c in cuts)
    assert 55.0 <= total <= 75.0  # 60-90 s with the two 3 s cards
    assert {c[0] for c in cuts} == set(by)  # the whole arc
    order = [list(by).index(c[0]) for c in cuts]
    assert order == sorted(order)  # film order
    first = [ln for ln in by[cuts[0][0]]["lines"] if ln["start"] < cuts[0][1] + cuts[0][2]]
    last = [ln for ln in by[cuts[-1][0]]["lines"] if ln["end"] > cuts[-1][1]]
    assert first[0]["who"] == "narrator" and last[-1]["who"] == "narrator"  # the world, the moral
    assert "all* of us" in last[-1]["text"]
    texts = []
    for sid, a, d in cuts:
        assert MIN_CUT_S <= d <= MAX_CUT_S
        for ln in by[sid]["lines"]:
            if ln["start"] < a + d and ln["end"] > a:  # a line in the cut is in it whole
                assert a <= ln["start"] and ln["end"] <= a + d, (sid, ln["text"])
                texts.append(ln["text"])
    for hand in ("DANGER! ...Oh. It's a rock.", "EVERYBODY PANIC!", "There! Stripes!", "One... two... PUSH!"):
        assert hand in texts  # lines the hand-made list also cut on
    speakers = {
        ln_who
        for sid, a, d in cuts
        for ln_who in [ln["who"] for ln in by[sid]["lines"] if ln["start"] < a + d and ln["end"] > a]
    }
    assert {"tembo", "kiki", "zuri", "neema", "bibi_kobe"} <= speakers  # every friend speaks
    for i, (sid, a, d) in enumerate(cuts):  # no two cuts overlap
        for sid2, a2, d2 in cuts[i + 1 :]:
            assert sid != sid2 or a + d <= a2 or a2 + d2 <= a
    assert trailer_cuts(reps) == cuts  # deterministic


def test_no_lines_no_cuts_and_long_lines_are_never_cut_mid_voice():
    assert trailer_cuts([{"scene": "sc01", "seconds": 10.0, "lines": []}]) == []
    long = {"who": "narrator", "text": "word " * 30, "start": 0.5, "end": 11.0}
    assert trailer_cuts([{"scene": "sc01", "seconds": 12.0, "lines": [long]}]) == []


def test_story_beats_and_picture_moments_are_always_in():
    """The 11-21 review: the automatic list missed Tembo's vow, the climax exchange and the singing spring."""
    reps = _savannah_reports()
    plain_cuts = trailer_cuts(reps)
    assert "Then I'll find it. For everyone." not in _texts(reps, plain_cuts)  # what the review saw
    by = {r["scene"]: r for r in reps}
    for ln in by["sc03"]["lines"] + by["sc09"]["lines"]:
        if ln["text"] in ("Then I'll find it. For everyone.", "Then don't."):
            ln["key"] = True  # the vow; the climax's answer
    spring = next(sh for sh in by["sc09"]["shots"] if "water bubbles up" in sh["note"])
    spring["trailer"] = True
    cuts = trailer_cuts(reps)
    texts = _texts(reps, cuts)
    assert "Then I'll find it. For everyone." in texts
    assert "You can't even hold a drink!" not in texts  # the vow ends its cut: Zuri's tease would undercut it
    assert "I can't... do it... alone." in texts and "Then don't." in texts  # the exchange, as one cut
    pic = [c for c in cuts if c[0] == "sc09" and spring["start"] <= c[1] < spring["end"]]
    assert len(pic) == 1 and MIN_CUT_S <= pic[0][2] <= PICTURE_S
    voices = [(ln["start"], ln["end"]) for ln in by["sc09"]["lines"]]
    assert all(
        e <= pic[0][1] or s >= pic[0][1] + pic[0][2] for s, e in voices
    )  # picture only: no voice in it
    assert 55.0 <= sum(c[2] for c in cuts) <= 80.0
    order = [(list(by).index(c[0]), c[1]) for c in cuts]
    assert order == sorted(order)
    for i, (sid, a, d) in enumerate(cuts):
        for sid2, a2, d2 in cuts[i + 1 :]:
            assert sid != sid2 or a + d <= a2 or a2 + d2 <= a


def test_a_planned_feature_film_marks_its_story_beats_for_the_trailer():
    prem = scripted_premise({"idea": "a little meerkat and an old turtle look for the lost rain"})
    play = scripted_screenplay({"premise": prem})
    assert validate_screenplay(play, prem) == []
    keys = [ln["text"] for sc in play["scenes"] for ln in sc["lines"] if ln.get("key")]
    assert len(keys) == 2 and keys[1] == "I don't know the way."
    spec = scene_from_dict(plan_scene(play["scenes"][0], prem, 0))
    assert [ln.key for ln in spec.lines] == [False, True]  # the hero's want reaches the scene spec
    bad = {"scenes": [dict(sc, lines=[dict(ln, key=True) for ln in sc["lines"]]) for sc in play["scenes"]]}
    assert any("key lines" in e for e in validate_screenplay(bad, prem))
