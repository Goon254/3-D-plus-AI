"""Voice DSP in plain numpy: a clean resampler, small pitch shifts, breaths, and outdoor placement.

Why it exists: dry TTS sounds "in a box". Three things make a line sit in a scene:

* **clean resampling** — linear interpolation aliases and images (a metallic fizz on sibilants); a windowed-
  sinc resampler with a proper low-pass doesn't;
* **placement** — a gentle EQ (high-pass, tame the low-mid mud, a touch of presence, soften the fizzy top),
  light 2:1 compression so quiet syllables carry, then an *outdoor* acoustic: no room reverb, only a ground
  reflection, a couple of distant soft reflections (trees, rocks) and a short diffuse air tail;
* **room tone** — a faint, steady bed of air under and around the line so speech never sits on digital
  silence.

Everything is deterministic (seeded) and offline.
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------- resampling and pitch


def resample(a: np.ndarray, sr_from: int, sr_to: int, taps: int = 24) -> np.ndarray:
    """Windowed-sinc (Kaiser) resampling with an anti-alias low-pass at the lower Nyquist. Mono 1-D."""
    a = np.asarray(a, np.float32)
    if sr_from == sr_to or len(a) == 0:
        return a.copy()
    n_out = int(round(len(a) * sr_to / sr_from))
    step = sr_from / sr_to  # input samples per output sample
    cut = min(1.0, sr_to / sr_from)  # cutoff relative to input Nyquist
    half = int(np.ceil(taps / cut))
    pad = np.pad(a, (half + 1, half + 2))
    out = np.empty(n_out, np.float32)
    k = np.arange(-half, half + 1)
    win_beta = 8.0
    chunk = max(1, 400_000 // (2 * half + 1))
    for s in range(0, n_out, chunk):
        pos = (np.arange(s, min(n_out, s + chunk)) * step)[:, None]
        base = np.floor(pos).astype(np.int64)
        idx = base + k[None, :]
        d = pos - idx  # distance from each tap
        x = np.clip(d / (half + 1), -1, 1)
        win = np.i0(win_beta * np.sqrt(1 - x**2)) / np.i0(win_beta)
        h = cut * np.sinc(cut * d) * win
        out[s : s + len(pos)] = (pad[idx + half + 1] * h).sum(axis=1)
    return out


def semitones(ratio: float) -> float:
    return float(12 * np.log2(ratio))


def pitch_shift(a: np.ndarray, sr: int, ratio: float) -> np.ndarray:
    """Shift pitch by ``ratio`` keeping the duration: sinc-resample, then WSOLA back to length.

    Meant for small shifts (within +-2 semitones); large shifts move the formants with the pitch and sound
    like a sped-up tape, which is why the cast uses voice blends instead.
    """
    if abs(ratio - 1.0) < 1e-4:
        return np.asarray(a, np.float32)
    from .tts import _time_stretch

    shifted = resample(a, int(round(sr * ratio)), sr)
    return _time_stretch(shifted, len(a))


# ---------------------------------------------------------------- spectral helpers


def _shape(a: np.ndarray, sr: int, gain_db) -> np.ndarray:
    """Zero-phase EQ: multiply the spectrum by ``gain_db(freqs)`` (whole-signal FFT; lines are short)."""
    n = len(a)
    if n == 0:
        return a
    m = 1 << int(np.ceil(np.log2(n + 1024)))
    spec = np.fft.rfft(a, m)
    f = np.fft.rfftfreq(m, 1 / sr)
    spec *= 10 ** (gain_db(f) / 20)
    return np.fft.irfft(spec, m)[:n].astype(np.float32)


def _highpass_db(f, fc, order=2):
    return 10 * np.log10(1 / (1 + (fc / np.maximum(f, 1e-3)) ** (2 * order)))


def _lowpass_db(f, fc, order=2):
    return 10 * np.log10(1 / (1 + (f / fc) ** (2 * order)))


def _bell_db(f, fc, gain, q):
    x = np.log2(np.maximum(f, 1e-3) / fc)
    return gain * np.exp(-0.5 * (x * q * 2.4) ** 2)


def _shelf_db(f, fc, gain, high=True):
    x = np.log2(np.maximum(f, 1e-3) / fc)
    s = 1 / (1 + np.exp(-x * 4))
    return gain * (s if high else 1 - s)


def voice_eq(a: np.ndarray, sr: int) -> np.ndarray:
    """Gentle dialogue EQ: HPF 85 Hz, -1.5 dB below 220 Hz, +1.5 dB presence at 3 kHz, -2.5 dB above 8 kHz."""
    nyq = sr / 2

    def g(f):
        out = _highpass_db(f, 85) + _shelf_db(f, 220, -1.5, high=False) + _bell_db(f, 3000, 1.5, 1.0)
        out = out + _shelf_db(f, min(8000, nyq * 0.7), -2.5)
        return out

    return _shape(a, sr, g)


# ---------------------------------------------------------------- dynamics


def compress(
    a: np.ndarray,
    sr: int,
    threshold_db: float = -20.0,
    ratio: float = 2.0,
    attack: float = 0.01,
    release: float = 0.15,
    block: float = 0.004,
) -> np.ndarray:
    """Light feed-forward RMS compression (2:1 above -20 dBFS) with make-up gain to the original peak level.

    The detector runs on 4 ms blocks with attack/release smoothing, and the gain curve is interpolated back
    to samples, so there are no clicks and no per-sample Python loop."""
    a = np.asarray(a, np.float32)
    if len(a) == 0:
        return a
    peak0 = float(np.abs(a).max()) + 1e-9
    b = max(1, int(block * sr))
    nb = int(np.ceil(len(a) / b))
    pad = np.pad(a, (0, nb * b - len(a)))
    rms = np.sqrt(np.mean(pad.reshape(nb, b) ** 2, axis=1) + 1e-12)
    lvl = 20 * np.log10(rms)
    ka, kr = np.exp(-block / attack), np.exp(-block / release)
    env = np.empty(nb)
    e = lvl[0]
    for i, x in enumerate(lvl):
        k = ka if x > e else kr
        e = k * e + (1 - k) * x
        env[i] = e
    over = np.maximum(env - threshold_db, 0.0)
    gain_db = -over * (1 - 1 / ratio)
    t_blocks = (np.arange(nb) + 0.5) * b
    g = 10 ** (np.interp(np.arange(len(a)), t_blocks, gain_db) / 20)
    y = a * g.astype(np.float32)
    return y * (peak0 / (float(np.abs(y).max()) + 1e-9))


# ---------------------------------------------------------------- breaths and room tone


def _noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.standard_normal(n).astype(np.float32)


def breath(sr: int, seconds: float = 0.26, seed: int = 0, level: float = 0.05) -> np.ndarray:
    """A soft inhale: noise through two broad vocal-tract-ish resonances (~1.2 and ~2.6 kHz, open-mouth
    'haah' shape), an asymmetric rise-fall envelope, peak ``level`` (default ~-26 dB under a 0.85 line)."""
    rng = np.random.default_rng(seed)
    n = max(8, int(seconds * sr))
    x = _noise(n, rng)
    f1 = 1100 + 250 * rng.random()
    f2 = 2500 + 400 * rng.random()

    def g(f):
        return np.maximum(_bell_db(f, f1, 14, 0.7), _bell_db(f, f2, 10, 0.8)) + _highpass_db(f, 450, 2) - 14

    x = _shape(x, sr, g)
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * np.clip(t, 0, 1) ** 0.7) ** 1.6  # quicker onset, longer fade
    x = x * env
    return (x / (np.abs(x).max() + 1e-9) * level).astype(np.float32)


def room_tone(n: int, sr: int, seed: int = 0, level_db: float = -56.0) -> np.ndarray:
    """Outdoor air: steady pink-ish noise, band-limited 120 Hz - 6 kHz, at ``level_db`` RMS (dBFS)."""
    rng = np.random.default_rng(seed + 9001)
    x = _noise(n, rng)

    def g(f):
        return -10 * np.log10(np.maximum(f, 20) / 20) + _highpass_db(f, 120) + _lowpass_db(f, 6000)

    x = _shape(x, sr, g)
    rms = float(np.sqrt(np.mean(x**2))) + 1e-12
    return (x * (10 ** (level_db / 20) / rms)).astype(np.float32)


# ---------------------------------------------------------------- outdoor acoustic


def outdoor_ir(sr: int, seed: int = 0, distance: float = 2.5) -> np.ndarray:
    """Impulse response of an open savannah: the direct sound, a ground bounce a few ms later (soft, a little
    darker), two or three distant reflections off trees/rocks at 25-70 ms (-20 to -26 dB, dark), and a
    120 ms diffuse air tail at about -34 dB. No enclosed-room reverb."""
    rng = np.random.default_rng(seed + 77)
    n = int(0.2 * sr)
    ir = np.zeros(n, np.float32)
    ir[0] = 1.0
    ground = int(sr * (0.0025 + 0.0015 * min(distance, 6) / 6))
    ir[ground] += 0.22
    for d_ms, g_db in (
        (26 + 8 * rng.random(), -20),
        (41 + 12 * rng.random(), -23),
        (63 + 9 * rng.random(), -26),
    ):
        ir[int(sr * d_ms / 1000)] += 10 ** (g_db / 20) * (1 if rng.random() > 0.5 else -1)
    tail_n = int(0.12 * sr)
    t = np.arange(tail_n) / sr
    tail = _noise(tail_n, rng) * np.exp(-t / 0.035) * 10 ** (-34 / 20) * 6
    tail[: int(0.008 * sr)] *= np.linspace(0, 1, int(0.008 * sr))
    ir[int(0.01 * sr) : int(0.01 * sr) + tail_n] += tail
    # reflections are darker than the direct sound: low-pass everything after the first 2 ms
    late = ir.copy()
    late[: int(0.002 * sr)] = 0
    early = ir - late
    late = _shape(late, sr, lambda f: _lowpass_db(f, 3500, 1))
    return (early + late).astype(np.float32)


def convolve(a: np.ndarray, ir: np.ndarray) -> np.ndarray:
    n = len(a) + len(ir) - 1
    m = 1 << int(np.ceil(np.log2(n)))
    return np.fft.irfft(np.fft.rfft(a, m) * np.fft.rfft(ir, m), m)[:n].astype(np.float32)


def place_outdoor(
    a: np.ndarray,
    sr: int,
    seed: int = 0,
    distance: float = 2.5,
    tone_db: float = -56.0,
    pre: float = 0.08,
) -> np.ndarray:
    """EQ -> light compression -> outdoor reflections -> room tone under and around the line.

    The result is ``pre`` seconds of room tone, the placed line, and its short tail; callers that schedule
    lines by their first word should start this signal ``pre`` seconds early (``PRE`` below)."""
    a = np.asarray(a, np.float32)
    peak = float(np.abs(a).max()) + 1e-9
    y = compress(voice_eq(a, sr), sr)
    y = convolve(y, outdoor_ir(sr, seed, distance))
    y *= peak / (float(np.abs(y).max()) + 1e-9)
    p = int(pre * sr)
    y = np.concatenate([np.zeros(p, np.float32), y])
    tone = room_tone(len(y), sr, seed, tone_db)
    f = min(len(y) // 2, int(0.06 * sr))  # fade the tone in/out so lines butt together cleanly
    ramp = np.ones(len(y), np.float32)
    ramp[:f] = np.linspace(0, 1, f)
    ramp[len(y) - f :] = np.linspace(1, 0, f)
    return (y + tone * ramp).astype(np.float32)


PRE = 0.08
