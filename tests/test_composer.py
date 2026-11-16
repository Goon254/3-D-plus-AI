"""Composer: per-scene cues, leitmotifs, MIDI round trip, rendering (numpy always, FluidSynth when present)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from animatica.audio import composer as C
from animatica.audio.midi import DRUM_CHANNEL, Note, Track, read_notes, write_midi

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "films" / "savannah" / "05_cue_sheet.json"


@pytest.fixture(scope="module")
def cues():
    return C.load_cue_sheet(SHEET)


@pytest.fixture(scope="module")
def arrs(cues):
    return {c.id: C.arrange(c) for c in cues}


def test_midi_round_trip(tmp_path):
    a = Track("lead", 0, 108, [Note(0, 1, 62, 90), Note(1.5, 0.5, 66, 70), Note(1.5, 2, 69, 60)])
    d = Track("drums", DRUM_CHANNEL, 0, [Note(0, 0.2, 64, 100), Note(0.25, 0.2, 70, 40)])
    path = write_midi(tmp_path / "x.mid", [a, d], bpm=93.0)
    back = read_notes(path)
    assert abs(back["bpm"] - 93.0) < 0.01
    lead, drums = back["tracks"][1], back["tracks"][2]
    assert lead["name"] == "lead" and lead["program"] == 108 and lead["channel"] == 0
    assert [(n.start, n.dur, n.pitch, n.vel) for n in lead["notes"]] == [
        (0, 1, 62, 90),
        (1.5, 0.5, 66, 70),
        (1.5, 2, 69, 60),
    ]
    assert drums["channel"] == DRUM_CHANNEL and drums["program"] is None and len(drums["notes"]) == 2


def test_cue_sheet_covers_the_film_and_lands_on_scene_lengths(cues, arrs):
    assert len(cues) == 10  # title folded into sc01, end card into sc10
    total = sum(c.seconds for c in cues)
    assert 300 <= total <= 330
    for c in cues:
        a = arrs[c.id]
        assert abs(a.bars * 4 * 60 / a.bpm - c.seconds) < 1e-6, c.id  # exactly on the cut
        assert abs(a.bpm - c.bpm) / c.bpm < 0.12, c.id  # the nudge stays musical
        assert a.motif_entries(), f"{c.id} has no leitmotif"
        chans = {t.channel for t in a.tracks}
        assert len(chans) <= 16
        # one program per channel: GM program changes are channel-wide
        by_ch = {}
        for t in a.tracks:
            if t.channel != DRUM_CHANNEL:
                assert by_ch.setdefault(t.channel, t.program) == t.program, c.id


def test_no_two_scenes_share_a_cue_and_the_moods_vary(cues, arrs):
    prints = [arrs[c.id].fingerprint() for c in cues]
    assert len(set(prints)) == len(prints)
    bpms = [arrs[c.id].bpm for c in cues]
    assert max(bpms) - min(bpms) >= 40
    assert len({c.key for c in cues}) >= 6
    modes = {m for a in arrs.values() for m in a.bar_modes}
    assert {"major", "minor", "dorian", "mixolydian", "lydian"} <= modes
    # instrumentation differs scene to scene: no two cues have the same instrument set
    sets = [tuple(arrs[c.id].programs) for c in cues]
    assert len(set(sets)) == len(sets)
    # the only deliberate reprise is the home theme, and it is re-orchestrated
    rep = [c for c in cues if c.reprise_of]
    assert [c.id for c in rep] == ["sc10"]
    assert arrs["sc10"].programs != arrs["sc01"].programs


def test_every_character_has_a_leitmotif_with_its_own_timbre(arrs):
    seen: dict[str, int] = {}
    for a in arrs.values():
        for name, _ in a.motif_entries():
            seen[name] = seen.get(name, 0) + 1
    for name in ("main", "tembo", "zuri", "kiki", "neema", "bibi"):
        assert seen.get(name, 0) >= 2, name
    programs = [C.MOTIFS[n].program for n in ("main", "tembo", "zuri", "kiki", "neema", "bibi")]
    assert len(set(programs)) == len(programs)


def _motif_pcs(arr, name, section_mood):
    """Pitch classes (relative to the cue's tonic) of a motif's notes inside bars of the given mood."""
    tr = next(t for t in arr.tracks if t.name == f"motif:{name}")
    key = C.KEYS[arr.cue.key]
    return {
        (n.pitch - key) % 12
        for n in tr.notes
        if arr.bar_moods[min(arr.bars - 1, int(n.start // 4))] == section_mood
    }


def test_tembos_theme_turns_minor_at_the_low_point_and_major_on_his_choice(arrs):
    a = arrs["sc07"]
    sad, solo = _motif_pcs(a, "tembo", "sad"), _motif_pcs(a, "tembo", "solo")
    assert 3 in sad and 4 not in sad  # minor third while he is lost
    assert 4 in solo and 3 not in solo  # major third when he decides
    # and it is the same tune: the bouncy comedy version in sc02 has the same rhythm
    t2 = next(t for t in arrs["sc02"].tracks if t.name == "motif:tembo")
    first = [n for n in t2.notes if n.start < t2.entries[0] + C.MOTIFS["tembo"].beats]
    assert len(first) == sum(1 for d, _ in C.MOTIFS["tembo"].notes if d is not None)


def test_drums_follow_the_mood(arrs):
    def drum_bars(a):
        tr = next((t for t in a.tracks if t.channel == DRUM_CHANNEL), None)
        return {int(n.start // 4) for n in tr.notes} if tr else set()

    a7 = arrs["sc07"]
    assert not drum_bars(a7)  # the low point is a kalimba and strings, no drums
    a4 = arrs["sc04"]
    db = drum_bars(a4)
    adv = {b for b in range(a4.bars) if a4.bar_moods[b] == "adventure"}
    tender = {b for b in range(a4.bars) if a4.bar_moods[b] == "tender"}
    assert adv <= db and not (tender & db)  # the journey grooves; the quiet breath is quiet
    # the climax builds: percussion gets louder through the build section
    a9 = arrs["sc09"]
    dr = next(t for t in a9.tracks if t.channel == DRUM_CHANNEL)
    build = [b for b in range(a9.bars) if a9.bar_moods[b] == "build"]
    v0 = np.mean([n.vel for n in dr.notes if int(n.start // 4) == build[0]])
    v1 = np.mean([n.vel for n in dr.notes if int(n.start // 4) == build[-1]])
    assert v1 > v0 + 8


def test_cadence_lands_on_the_tonic(arrs):
    for a in arrs.values():
        assert a.bar_chords[-1] == 0
        last = [
            n for t in a.tracks if t.channel != DRUM_CHANNEL for n in t.notes if n.start >= (a.bars - 1) * 4
        ]
        assert last and any((n.pitch - C.KEYS[a.cue.key]) % 12 == 0 for n in last)


def test_numpy_render_of_a_cue(tmp_path, cues):
    cue = next(c for c in cues if c.id == "sc07")
    rep = C.render_cue(C.arrange(cue), tmp_path, engine="numpy")
    a = C._read(tmp_path / rep["wav"])
    assert abs(len(a) / C.SR - (cue.seconds + 1.5)) < 0.01
    assert np.abs(a).max() <= 0.9 and rep["rms_db"] > -35
    assert (tmp_path / rep["midi"]).stat().st_size > 200
    assert np.abs(a[-100:]).max() < 1e-3  # faded tail for the crossfade


@pytest.mark.skipif(C.renderer() != "fluidsynth", reason="needs fluidsynth + a GM SoundFont")
def test_fluidsynth_cues_sound_different_by_mood(tmp_path, cues):
    by = {c.id: c for c in cues}
    reps = {k: C.render_cue(C.arrange(by[k]), tmp_path) for k in ("sc04", "sc07")}
    assert all(r["engine"] == "fluidsynth" for r in reps.values())
    # the journey is louder than the low point
    assert reps["sc04"]["rms_db"] > reps["sc07"]["rms_db"] + 2
    a = C._read(tmp_path / "sc04.wav")
    from animatica.audio.music import band_energy_ratio

    assert band_energy_ratio(a, 60.0, C.SR) < 0.02  # no rumble under the dialogue


def test_soundfont_engine_renders_a_cue_with_real_samples(tmp_path):
    import pytest

    from animatica.audio import composer

    if composer.find_soundfont() is None:
        pytest.skip("no SoundFont cached")
    cues = composer.load_cue_sheet(
        composer.Path(__file__).resolve().parents[1] / "films/savannah/05_cue_sheet.json"
    )
    rep = composer.render_cue(composer.arrange(cues[1]), tmp_path, engine="soundfont")
    assert rep["engine"] == "soundfont" and rep["rms_db"] > -40 and (tmp_path / rep["wav"]).exists()
