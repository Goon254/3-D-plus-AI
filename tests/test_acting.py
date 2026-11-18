"""Acting driven by the dialogue (owner's note, animatic 11-18: "lips and acting don't match the voices")."""

import numpy as np

from animatica.production.acting import dialogue_beats, pauses, speech_accents
from animatica.production.scene import Line

SR = 16000


def _speech(syllables: list[tuple[float, float]], seconds: float) -> np.ndarray:
    """A fake take: a 180 Hz buzz in bursts (start, loudness) of 0.14 s."""
    t = np.arange(int(seconds * SR)) / SR
    x = np.zeros_like(t)
    for s0, amp in syllables:
        m = (t >= s0) & (t < s0 + 0.14)
        x[m] += amp * np.sin(2 * np.pi * 180 * t[m]) * np.sin(np.pi * (t[m] - s0) / 0.14)
    return x.astype(np.float32)


def test_accents_land_on_the_syllables_and_the_loud_ones_are_stressed():
    syl = [(0.2, 0.5), (0.45, 1.0), (0.7, 0.5), (1.4, 0.5), (1.65, 0.9)]
    acc = speech_accents(_speech(syl, 2.2), SR)
    assert len(acc) == len(syl)
    for (t, _), (s0, _) in zip(acc, syl):
        assert abs(t - (s0 + 0.07)) < 0.05  # the middle of each syllable
    stressed = [t for t, w in acc if w == 1.0]
    assert any(abs(t - 0.52) < 0.05 for t in stressed) and any(abs(t - 1.72) < 0.05 for t in stressed)
    # the gap between 0.84 s and 1.4 s is a phrase break; the lead-in and the tail are not
    br = pauses(_speech(syl, 2.2), SR)
    assert len(br) == 1 and 0.9 < br[0] < 1.35


def test_speakers_beat_and_blink_listeners_blink_and_the_addressee_nods():
    x = _speech([(0.2, 0.8), (0.5, 1.0), (1.2, 0.7)], 1.8)
    lines = [Line("tembo", "Then I'll find it.", to="neema", start=2.0, end=3.8)]
    spans = {c: [(0.0, 10.0)] for c in ("tembo", "neema", "zuri")}
    b = dialogue_beats(lines, [(x, SR)], spans, written=[])
    talk = [g for g in b.gestures if g.kind == "talk"]
    assert len(talk) == 1 and talk[0].who == "tembo" and len(talk[0].accents) == 3
    assert all(2.0 < t < 3.8 for t, _ in talk[0].accents)  # scene time, on the line
    assert any(g.kind == "nod" and g.who == "neema" for g in b.gestures)  # the addressee acknowledges
    assert not any(g.kind == "nod" and g.who == "zuri" for g in b.gestures)
    assert b.blinks["tembo"][0] < 2.0 and any(2.6 < t < 3.4 for t in b.blinks["tembo"])  # line start + break
    assert b.blinks["zuri"] and b.blinks["neema"]
    # an off-screen line has no talking head, and the written gestures win
    lines[0].offscreen = True
    assert not [g for g in dialogue_beats(lines, [(x, SR)], spans, []).gestures if g.kind == "talk"]


def test_talk_layer_moves_the_head_on_the_accents():
    from animatica.creatures.gait import LocoFrame
    from animatica.creatures.gesture import Gesture, Rig, acting_layers

    plan = [LocoFrame((0.0, 0.0, 1.0), 0.0, 0.0, 0.0, 0.0, 0.0) for _ in range(48)]
    rig = Rig("zebra", {"neck_1": (0.0, -0.5, 0.8), "head": (0.0, -1.0, 0.0)}, ["neck_1"])
    g = Gesture("zuri", "talk", 0.0, 2.0)
    g.accents = [(1.0, 1.0)]
    head = acting_layers(rig, plan, None, [g], 24)["head"]
    quiet, beat = head[6], head[25]  # 0.25 s vs just after the accent at 1.0 s
    dev = lambda m: sum(abs(m[i][j] - (1.0 if i == j else 0.0)) for i in range(3) for j in range(3))  # noqa: E731
    assert dev(beat) > dev(quiet) + 0.02


def test_a_speaker_facing_away_cheats_toward_the_cameras():
    from animatica.creatures.gait import LocoFrame
    from animatica.creatures.gesture import gaze_track

    away = [
        LocoFrame((0.0, 0.0, 1.0), 180.0, 0.0, 0.0, 0.0, 0.0) for _ in range(72)
    ]  # facing +Y, cameras at -Y
    line = Line("tembo", "I can walk.", start=0.5, end=2.5)
    still = gaze_track("tembo", {"tembo": away}, [line], [], 24)
    cheat = gaze_track("tembo", {"tembo": away}, [line], [], 24, lens=(0.0, -1.0))
    assert max(abs(a) for a in still) < 1e-6
    assert max(abs(a) for a in cheat[24:60]) > 30  # the head comes round toward the lens while talking
