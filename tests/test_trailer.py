"""The automatic trailer cut list (``production.trailer``, DECISIONS #107)."""

from __future__ import annotations

from pathlib import Path

from animatica.production.continuity import actor_speeds
from animatica.production.pacing import line_durations
from animatica.production.scene import load_scenes, schedule
from animatica.production.trailer import MAX_CUT_S, MIN_CUT_S, punch, trailer_cuts

ROOT = Path(__file__).resolve().parents[1]


def _savannah_reports() -> list[dict]:
    """The savannah's scenes scheduled on the word-count estimates (what the cloud has without the voices)."""
    reps = []
    for spec in load_scenes(ROOT / "films" / "savannah" / "07_scenes.json").values():
        secs = schedule(spec, line_durations(spec, None), actor_speeds(spec))
        lines = [{"who": ln.who, "text": ln.text, "start": ln.start, "end": ln.end} for ln in spec.lines]
        reps.append({"scene": spec.id, "seconds": secs, "lines": lines})
    return reps


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
