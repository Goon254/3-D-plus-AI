"""Procedural music & ambience bed (numpy, no samples => no licensing questions).

A mood picks key, tempo and instrumentation. The bed is: warm detuned pad chords, a soft plucked
arpeggio, a low bass, and a filtered-noise ambience (wind). Dialogue ducking happens in ``mix``.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np

from .tts import read_wav, resample, write_wav

SR = 44100
MOODS = {
    # pads sit above the voice's fundamental (~100-250 Hz) so dialogue stays clear
    # name: (root midi, scale intervals, progression degrees, bpm, brightness)
    "warm": (64, [0, 2, 4, 5, 7, 9, 11], [0, 5, 3, 4], 72, 0.6),
    "wonder": (64, [0, 2, 4, 6, 7, 9, 11], [0, 4, 5, 3], 66, 0.75),  # lydian sparkle
    "melancholy": (62, [0, 2, 3, 5, 7, 8, 10], [0, 5, 2, 6], 60, 0.4),
    "playful": (65, [0, 2, 4, 5, 7, 9, 11], [0, 3, 4, 0], 96, 0.8),
    "mysterious": (62, [0, 1, 3, 5, 7, 8, 10], [0, 5, 6, 0], 58, 0.35),
    "tense": (59, [0, 2, 3, 5, 7, 8, 11], [0, 1, 0, 4], 84, 0.45),
}


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def highpass(x: np.ndarray, cutoff: float, sr: int = SR, slope_hz: float = 40.0) -> np.ndarray:
    """Zero-phase FFT high-pass with a smooth (raised-cosine) transition band."""
    spec = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(x.shape[0], 1 / sr)
    lo = cutoff - slope_hz
    gain = np.clip((f - lo) / slope_hz, 0, 1)
    gain = 0.5 - 0.5 * np.cos(np.pi * gain)
    spec *= gain[:, None] if x.ndim == 2 else gain
    return np.fft.irfft(spec, n=x.shape[0], axis=0).astype(np.float32)


def band_energy_ratio(x: np.ndarray, below: float = 120.0, sr: int = SR) -> float:
    """Fraction of spectral energy below ``below`` Hz (used to keep the bed from getting muddy)."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    p = np.abs(np.fft.rfft(mono)) ** 2
    f = np.fft.rfftfreq(len(mono), 1 / sr)
    return float(p[f < below].sum() / max(p.sum(), 1e-12))


def generate_bed(duration: float, mood: str = "warm", seed: str = "", ambience: str = "wind") -> np.ndarray:
    root, scale, prog, bpm, bright = MOODS.get(mood, MOODS["warm"])
    rng = np.random.default_rng(zlib.crc32((seed + mood).encode()))
    n = int(duration * SR)
    t = np.arange(n) / SR
    out = np.zeros((n, 2), np.float32)
    beat = 60.0 / bpm
    bar = beat * 4
    chord_len = bar * 2

    def deg(d: int, octave: int = 0) -> float:
        return root + scale[d % 7] + 12 * (d // 7 + octave)

    # pads
    n_chords = int(np.ceil(duration / chord_len)) + 1
    for ci in range(n_chords):
        d = prog[ci % len(prog)]
        start = ci * chord_len
        s0, s1 = int(start * SR), min(n, int((start + chord_len + 1.0) * SR))
        if s0 >= n:
            break
        tt = t[s0:s1] - start
        env = np.minimum(1, tt / 1.2) * np.clip((chord_len + 1.0 - tt) / 1.5, 0, 1)
        for k, note in enumerate([deg(d), deg(d + 2), deg(d + 4), deg(d, 1)]):
            f = midi_hz(note)
            for det, pan in ((-0.12, 0.3), (0.12, 0.7)):
                ff = f * 2 ** (det / 12 / 4)
                ph = rng.uniform(0, 6.28)
                wave = np.sin(2 * np.pi * ff * tt + ph) + 0.25 * bright * np.sin(4 * np.pi * ff * tt + ph)
                amp = 0.05 / (1 + 0.3 * k)
                out[s0:s1, 0] += (wave * env * amp * (1 - pan)).astype(np.float32)
                out[s0:s1, 1] += (wave * env * amp * pan).astype(np.float32)
        # bass
        fb = midi_hz(deg(d, -1))
        benv = np.exp(-tt / 2.5) * np.minimum(1, tt / 0.05)
        b = 0.035 * (np.sin(2 * np.pi * fb * tt) + 0.5 * np.sin(4 * np.pi * fb * tt)) * benv  # light bass; 2nd harmonic carries on small speakers
        out[s0:s1, :] += b[:, None].astype(np.float32)

    # plucked arpeggio (starts after an intro bar, eighth notes)
    step = beat / 2
    i = 0
    tt0 = bar
    while tt0 < duration - 1.0:
        ci = int(tt0 // chord_len)
        d = prog[ci % len(prog)]
        pattern = [0, 2, 4, 7, 4, 2]
        note = deg(d + pattern[i % len(pattern)], 1)
        if rng.random() < 0.85:
            s0 = int(tt0 * SR)
            ln = min(n - s0, int(1.2 * SR))
            tt = np.arange(ln) / SR
            f = midi_hz(note)
            pl = (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(6 * np.pi * f * tt)) * np.exp(-tt * (3.5 + 2 * (1 - bright)))
            pan = 0.5 + 0.35 * np.sin(i * 0.7)
            out[s0 : s0 + ln, 0] += (0.045 * pl * (1 - pan)).astype(np.float32)
            out[s0 : s0 + ln, 1] += (0.045 * pl * pan).astype(np.float32)
        i += 1
        tt0 += step

    # ambience
    if ambience:
        noise = rng.standard_normal((n, 2)).astype(np.float32)
        k = 64
        kernel = np.ones(k, np.float32) / k
        for c in range(2):
            noise[:, c] = np.convolve(noise[:, c], kernel, mode="same")
        noise = highpass(noise, 350.0, slope_hz=150.0)  # airy wind, not rumble
        gust = 0.5 + 0.5 * np.sin(2 * np.pi * t / 7.0 + 1.0) * np.sin(2 * np.pi * t / 3.1)
        out += (noise * (0.05 + 0.08 * gust[:, None])).astype(np.float32)

    out = highpass(out, 120.0)  # keep the low end clear for dialogue and small speakers

    # fades + simple stereo reverb-ish smear
    fade = np.minimum(1, t / 2.0) * np.minimum(1, (duration - t) / 2.5)
    out *= fade[:, None].astype(np.float32)
    d = int(0.09 * SR)
    out[d:, 0] += 0.25 * out[:-d, 1]
    out[d:, 1] += 0.25 * out[:-d, 0]
    out /= max(1e-6, np.abs(out).max()) / 0.5
    return out


def mix(duration: float, bed: np.ndarray | None, dialogue: list[tuple[float, str]], out_path: str | Path,
        duck_db: float = -12.0, sfx: list[tuple[float, str, float]] | None = None) -> Path:
    """Mix dialogue clips (start_seconds, wav) over the bed, ducking the bed under speech."""
    n = int(duration * SR)
    master = np.zeros((n, 2), np.float32)
    if bed is not None:
        b = bed[:n]
        if len(b) < n:
            b = np.pad(b, ((0, n - len(b)), (0, 0)))
        master += b
    speech_env = np.zeros(n, np.float32)
    voice = np.zeros(n, np.float32)
    for start, wav in dialogue:
        a, sr = read_wav(wav)
        a = resample(a, sr, SR)
        s0 = int(start * SR)
        ln = max(0, min(len(a), n - s0))
        voice[s0 : s0 + ln] += a[:ln]
        speech_env[max(0, s0 - int(0.25 * SR)) : s0 + ln + int(0.4 * SR)] = 1.0
    for start, wav, gain in sfx or []:
        a, sr = read_wav(wav)
        a = resample(a, sr, SR) * gain
        s0 = int(start * SR)
        ln = max(0, min(len(a), n - s0))
        master[s0 : s0 + ln] += a[:ln, None]
    # smooth the duck envelope (attack/release ~150ms)
    k = int(0.15 * SR)
    smooth = np.convolve(speech_env, np.ones(k, np.float32) / k, mode="same")
    gain = 10 ** (duck_db * smooth / 20)
    master *= gain[:, None]
    master += np.stack([voice, voice], axis=1) * 0.9
    peak = np.abs(master).max()
    if peak > 0.98:
        master *= 0.98 / peak
    return write_wav(out_path, master, SR)
