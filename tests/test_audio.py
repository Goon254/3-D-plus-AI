from pathlib import Path

import numpy as np

from animatica.audio import lipsync, music, tts


def test_synth_tts_and_amplitude_lipsync(tmp_path):
    res = tts.synthesize(
        "Hello, little one.", tmp_path / "a.wav", tts.VoiceSpec(engine="synth", pitch=1.1, robot=0.2)
    )
    assert res["engine"] == "synth" and res["duration"] > 0.5
    cues = lipsync.amplitude_cues(res["path"])
    assert cues and all(c.value in lipsync.VISEME_WEIGHTS for c in cues)
    assert any(c.value not in ("X", "A") for c in cues)


def test_cues_to_keyframes_strictly_increasing():
    cues = [
        lipsync.Cue(0.0, 0.1, "X"),
        lipsync.Cue(0.1, 0.2, "D"),
        lipsync.Cue(0.2, 0.21, "B"),
        lipsync.Cue(0.21, 0.5, "F"),
    ]
    keys = lipsync.cues_to_keyframes(cues, 24, 100)
    for name in lipsync.SHAPE_KEYS:
        frames = [k[0] for k in keys[name]]
        assert frames == sorted(set(frames))
        assert frames[0] >= 100
    assert max(k[1] for k in keys["open"]) == 1.0  # the D viseme opens wide


def test_music_bed_and_mix(tmp_path):
    bed = music.generate_bed(4.0, "wonder", seed="t")
    assert bed.shape == (int(4.0 * music.SR), 2)
    assert 0.3 < np.abs(bed).max() <= 0.51
    v = tts.synthesize("Hi there.", tmp_path / "v.wav", tts.VoiceSpec(engine="synth"))
    out = music.mix(4.0, bed, [(1.0, v["path"])], tmp_path / "mix.wav")
    a, sr = tts.read_wav(out)
    assert sr == music.SR and len(a) == int(4.0 * music.SR)


def test_wav_roundtrip(tmp_path):
    x = np.sin(np.linspace(0, 100, 22050)).astype(np.float32) * 0.5
    p = tts.write_wav(tmp_path / "x.wav", x)
    y, sr = tts.read_wav(p)
    assert sr == tts.SAMPLE_RATE and np.allclose(x, y, atol=1e-3)


def test_music_bed_is_not_muddy():
    bed = music.generate_bed(8.0, "warm", seed="mud")
    assert music.band_energy_ratio(bed, 120.0) < 0.05  # high-passed: almost nothing below 120 Hz
    assert music.band_energy_ratio(bed, 250.0) < 0.35


def test_mlt_timeline_export(tmp_path):
    import xml.etree.ElementTree as ET

    from animatica.agents.director import normalize_plan, scripted_plan
    from animatica.audio.timeline import write_mlt
    from animatica.core.plan import FilmPlan

    prompt = "A robot finds a flower in a junkyard at sunset. It says: 'Hello there.'"
    plan = normalize_plan(FilmPlan.model_validate(scripted_plan(prompt)), prompt)
    arts = {
        "lines": {"line1": {"path": str(tmp_path / "audio/line1.wav"), "duration": 1.2, "start_s": 12.0}},
        "music": str(tmp_path / "audio/music_bed.wav"),
    }
    out = write_mlt(tmp_path, plan, arts, (960, 540))
    doc = ET.parse(out).getroot()
    v1 = doc.find("playlist[@id='V1']")
    assert len(v1.findall("entry")) == len(plan.shots)
    a1 = doc.find("playlist[@id='A1']")
    assert a1.find("blank").get("length") == str(12 * plan.fps)
    assert doc.find("producer[@id='line1']/property[@name='resource']").text == "audio/line1.wav"


def test_rhubarb_is_used_when_installed(tmp_path):
    import pytest

    if not lipsync.find_rhubarb():
        pytest.skip("rhubarb not installed (scripts/setup_assets.sh)")
    res = tts.synthesize("Are you lost too?", tmp_path / "a.wav", tts.VoiceSpec(engine="synth"))
    cues, engine = lipsync.lipsync(res["path"], "Are you lost too?")
    # the Windows build prints nothing on stdout with -q: this used to fall back to "amplitude" silently
    assert engine == "rhubarb"
    assert cues and abs(cues[-1].end - res["duration"]) < 0.2


def test_soundfont_player_plays_real_samples_in_tune():
    import pytest

    from animatica.audio.soundfont import Note, default_soundfont, load, render, render_note

    path = default_soundfont()
    if path is None:
        pytest.skip("no SoundFont installed (scripts/setup_assets.sh)")
    sf = load(str(path))
    sr = 44100
    for prog in (73, 12, 48):  # flute, marimba, strings: a held A4 is at 440 Hz
        a = render_note(sf, 0, prog, 69, 100, 1.2)[:, 0][int(0.15 * sr) : int(1.1 * sr)]
        spec = np.abs(np.fft.rfft(a * np.hanning(len(a)), 1 << 17))
        f = np.fft.rfftfreq(1 << 17, 1 / sr)[np.argmax(spec)]
        assert abs(f - 440.0) < 6.0, (prog, f)
    drums = render([Note(0.0, 0.1, 63, 110, 0, bank=128)], 0.5, sf)
    assert np.abs(drums).max() > 0.05  # GM percussion (bank 128) sounds


def test_pitch_shift_keeps_the_voice_pitch_without_hop_buzz():
    # plain overlap-add imprinted a 93.75 Hz buzz (sr / hop) that a pitch tracker heard as the voice: WSOLA must
    # land on the requested pitch and leave no energy at the hop rate
    from animatica.audio.tts import _time_stretch, resample

    sr = 24000
    t = np.arange(sr * 2) / sr
    tone = (np.sin(2 * np.pi * 150 * t) + 0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32) * 0.3
    for pitch in (1.32, 0.8):
        y = _time_stretch(resample(tone, int(sr * pitch), sr), len(tone))
        seg = y[2400:-2400] * np.hanning(len(y) - 4800)
        spec = np.abs(np.fft.rfft(seg))
        f = np.fft.rfftfreq(len(seg), 1 / sr)
        assert abs(f[np.argmax(spec)] - 150 * pitch) < 2.0
        assert spec[(f > 90) & (f < 98)].max() / spec.max() < 0.01


def test_ambience_beds_and_footsteps():
    from animatica.audio import ambience as am

    for tod in ("dawn", "midday", "night"):
        a = am.bed(tod, 6, water=tod == "dawn", seed=1)
        rms = 20 * np.log10(np.sqrt(np.mean(a.astype(np.float64) ** 2)))
        assert a.shape == (6 * am.SR, 2) and np.abs(a).max() <= 0.5 + 1e-6
        assert abs(rms - (-34 if tod == "night" else -30)) < 0.5
    night = am.bed("night", 6, seed=1).mean(axis=1)
    spec = np.abs(np.fft.rfft(night))
    f = np.fft.rfftfreq(len(night), 1 / am.SR)
    assert spec[(f > 4000) & (f < 5500)].sum() > spec[(f > 5500) & (f < 7000)].sum()  # cricket trills
    steps = am.footsteps_track("elephant", [(0.5, 0.0), (1.2, 0.3)], 2.0)
    assert (
        np.abs(steps[int(0.5 * am.SR) : int(0.8 * am.SR)]).max() > 0.1
        and np.abs(steps[: int(0.4 * am.SR)]).max() == 0
    )


def test_delivery_plan_pauses_breaths_and_emphasis():
    from animatica.audio import delivery as dl

    ph = dl.plan(
        "When I was young... there was a spring past the two baobabs that bow to each other. Its water sings.",
        "wise",
    )
    assert [p.end for p in ph] == ["...", ".", "."]
    assert ph[0].pause > ph[1].pause > 0 and ph[-1].pause == 0  # ellipsis > full stop; none after the line
    assert ph[1].breath and not ph[0].breath  # breathe after a long sentence only
    assert ph[0].text.endswith(",")  # an ellipsis is spoken suspended, not with a falling full stop
    # markup is never spoken, whatever punctuation follows it; CAPS words are emphasised and lower-cased
    spoken, emph = dl.spoken("Your trunk's a hose with *hiccups*! She's gone. EVERYBODY PANIC!")
    assert "*" not in spoken and "PANIC" not in spoken
    words = spoken.split()
    assert [words[i] for i in emph] == ["hiccups!", "everybody", "panic!"]
    assert dl.mood_of("dripping, dignified") == dl.MOODS["dignified"]
    r = [dl.line_rate(t, 1.0) for t in ("Water!", "Thank you, Tembo.", "A singing spring?")]
    assert len(set(r)) == 3 and all(0.96 <= x <= 1.04 for x in r)  # small per-line variation
    assert dl.stress_word("soʊ") == "ˈsoʊː" and dl.stress_word("sˈɪŋɪŋ") == "sˈɪːŋɪŋ"
    assert dl.emphasise_phonemes("ɐ sˈɪŋɪŋ spɹˈɪŋ?", [1], 3) == "ɐ sˈɪːŋɪŋ spɹˈɪŋ?"
    assert dl.emphasise_phonemes("ɐ sˈɪŋɪŋ", [1], 3) is None  # tokens don't line up -> speak from text


def test_widen_pauses_stretches_boundary_gaps_and_breathes():
    from animatica.audio import delivery as dl

    sr = 24000

    def tone(s):
        return (0.5 * np.sin(2 * np.pi * 180 * np.arange(int(s * sr)) / sr)).astype(np.float32)

    # two phrases (long, then short, like the text) with the model's own 0.1 s gap between them
    a = np.concatenate([tone(2.6), np.zeros(int(0.1 * sr), np.float32), tone(0.7)])
    ph = dl.plan("Then the five friends set off together across the grass. And it was far.")
    out = tts._widen_pauses(a, sr, ph)
    gaps = tts._silences(out, sr)
    assert len(out) > len(a) and ph[0].breath
    # the breath sits inside the widened pause, so the pause reads as two quiet runs around it
    assert sum(g1 - g0 for g0, g1 in gaps) / sr >= ph[0].pause - 0.3


def test_voice_fx_resampler_pitch_and_placement():
    from animatica.audio import voice_fx as fx

    sr = 24000
    x = np.sin(2 * np.pi * 1000 * np.arange(sr) / sr).astype(np.float32)
    y = fx.resample(x, sr, 48000)
    ref = np.sin(2 * np.pi * 1000 * np.arange(len(y)) / 48000)
    assert np.abs(y[300:-300] - ref[300:-300]).max() < 1e-3
    spec = np.abs(np.fft.rfft(y))
    f = np.fft.rfftfreq(len(y), 1 / 48000)
    assert 20 * np.log10(spec[f > 12000].max() / spec.max()) < -80  # no images above the old Nyquist
    p = fx.pitch_shift(x, sr, 2 ** (2 / 12))
    sp = np.abs(np.fft.rfft(p))
    assert len(p) == len(x) and abs(np.fft.rfftfreq(len(p), 1 / sr)[sp.argmax()] - 1122.5) < 3
    # compression narrows the gap between a loud and a quiet syllable
    burst = np.concatenate([x[:6000] * 0.9, x[:6000] * 0.1])
    c = fx.compress(burst, sr)
    assert c[:6000].std() / c[6000:].std() < burst[:6000].std() / burst[6000:].std()
    placed = fx.place_outdoor(x[:12000] * 0.8, sr, seed=1)
    assert len(placed) > 12000 + int(fx.PRE * sr)
    assert np.abs(placed[: int(fx.PRE * sr)]).max() < 0.01  # only faint room tone before the first word
    assert np.abs(placed).max() <= 0.81


def test_savannah_cast_uses_blends_with_small_pitch_shifts():
    import json
    from pathlib import Path

    d = json.loads((Path(__file__).parents[1] / "films/savannah/06_voices.json").read_text(encoding="utf-8"))
    stock = {"af", "am", "bf", "bm"}
    for name, c in d["cast"].items():
        assert abs(12 * np.log2(c["pitch"])) <= 2.0 + 1e-6, name
        for part in c["voice"].split("+"):
            assert part.split(":")[0][:2] in stock, name


def test_line_cache_key_and_reuse(tmp_path, monkeypatch):
    from animatica.audio import tts

    monkeypatch.setenv("ANIMATICA_LINE_CACHE", str(tmp_path / "lines"))
    a = tts.VoiceSpec(engine="synth", voice="af_bella")
    assert tts.cache_key("Hi.", a, "synth") == tts.cache_key(
        "Hi.", tts.VoiceSpec(engine="synth", voice="af_bella"), "synth"
    )
    assert tts.cache_key("Hi.", a, "synth") != tts.cache_key("Hi!", a, "synth")
    assert tts.cache_key("Hi.", a, "synth") != tts.cache_key(
        "Hi.", tts.VoiceSpec(voice="af_bella", pitch=1.05), "synth"
    )
    info = {
        "path": str(tts.write_wav(tmp_path / "x.wav", np.zeros(2400, np.float32))),
        "engine": "kokoro",
        "duration": 0.1,
    }
    tts._to_cache("k1", info)
    hit = tts._from_cache("k1", tmp_path / "y.wav")
    assert hit["cached"] and hit["engine"] == "kokoro" and (tmp_path / "y.wav").exists()
    assert tts._from_cache("nope", tmp_path / "z.wav") is None


def test_chatterbox_falls_back_to_kokoro_on_bad_transcript(tmp_path, monkeypatch):
    from animatica.audio import tts

    monkeypatch.setenv("ANIMATICA_LINE_CACHE", str(tmp_path / "lines"))
    spoken = []

    def fake_single(text, out, voice, engines):
        spoken.append(engines)
        tts.write_wav(out, np.zeros(2400, np.float32))
        return {"path": str(out), "engine": "kokoro", "duration": 0.1}

    monkeypatch.setattr(tts, "_single", fake_single)
    monkeypatch.setattr(
        tts, "synthesize", lambda text, out, spec: fake_single(text, Path(out), spec, ["kokoro"])
    )
    monkeypatch.setattr(
        tts,
        "_run_chatterbox",
        lambda takes: [{"heard": "garbled", "wer": 0.8, "tries": 3, "words": []}] * len(takes),
    )
    r = tts.synthesize_batch([("Water, at last!", tmp_path / "a.wav", tts.VoiceSpec(engine="chatterbox"))])[0]
    assert r["engine"] == "kokoro" and "wer 0.8" in r["fallback"]
    assert spoken[-1] == ["chatterbox", "kokoro"]


def test_chatterbox_post_emphasis_and_alignment():
    from animatica.audio import tts

    t = tts._align_words(
        ["your", "trunk's", "a", "hose"],
        [["Your", 0.1, 0.3], ["trunks", 0.3, 0.6], ["a", 0.6, 0.7], ["hose,", 0.7, 1.0]],
    )
    assert t[0] == (0.1, 0.3) and t[3] == (0.7, 1.0) and 1 not in t
    sr = tts.SAMPLE_RATE
    a = np.concatenate([np.zeros(sr // 2), 0.5 * np.sin(np.arange(sr) * 0.05), np.zeros(sr // 2)]).astype(
        np.float32
    )
    b, cut = tts._trim(a, sr)
    assert abs(cut / sr - 0.45) < 0.02 and len(b) < len(a)
