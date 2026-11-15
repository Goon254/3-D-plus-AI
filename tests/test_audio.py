import numpy as np

from animatica.audio import lipsync, music, tts


def test_synth_tts_and_amplitude_lipsync(tmp_path):
    res = tts.synthesize("Hello, little one.", tmp_path / "a.wav", tts.VoiceSpec(engine="synth", pitch=1.1, robot=0.2))
    assert res["engine"] == "synth" and res["duration"] > 0.5
    cues = lipsync.amplitude_cues(res["path"])
    assert cues and all(c.value in lipsync.VISEME_WEIGHTS for c in cues)
    assert any(c.value not in ("X", "A") for c in cues)


def test_cues_to_keyframes_strictly_increasing():
    cues = [lipsync.Cue(0.0, 0.1, "X"), lipsync.Cue(0.1, 0.2, "D"), lipsync.Cue(0.2, 0.21, "B"), lipsync.Cue(0.21, 0.5, "F")]
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
