"""Ambience beds and SFX for the savannah, synthesized (procedural: no samples, no licence questions).

Beds per location and time of day: wind in the grass (brown noise with slow gusts), birds at dawn and by day
(varied chirp phrases), a sparse cicada buzz at midday, crickets at night (pulsed 4-5 kHz trills), water
lapping near the watering hole. SFX per action: footsteps per species (driven by the gait planner's touchdown
events), a splash, a creaking log roll.

All output is stereo float32 at 48 kHz (the Composer's rate). Seeds make every bed reproducible.
"""

from __future__ import annotations

import math

import numpy as np

SR = 48000


def _lp(x: np.ndarray, hz: float) -> np.ndarray:
    """One-pole low-pass (per channel if 2-D)."""
    a = math.exp(-2 * math.pi * hz / SR)
    y = np.empty_like(x)
    acc = np.zeros(x.shape[1:], dtype=np.float64) if x.ndim > 1 else 0.0
    for i in range(len(x)):
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def _lp_fast(x: np.ndarray, hz: float) -> np.ndarray:
    """FFT low-pass with a soft roll-off: fast enough for minutes of noise."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    resp = 1 / np.sqrt(1 + (f / max(hz, 1.0)) ** 4)
    if x.ndim == 1:
        return np.fft.irfft(np.fft.rfft(x) * resp, n).astype(np.float32)
    return np.stack([np.fft.irfft(np.fft.rfft(x[:, c]) * resp, n) for c in range(x.shape[1])], axis=1).astype(
        np.float32
    )


def _bp_fast(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    resp = (1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** 4)) * (1 / np.sqrt(1 + (f / hi) ** 4))
    return np.fft.irfft(np.fft.rfft(x) * resp, n).astype(np.float32)


def _place(out: np.ndarray, t: float, sig: np.ndarray, pan: float = 0.0, gain: float = 1.0) -> None:
    s = int(t * SR)
    if s >= len(out) or s < 0:
        return
    p = (pan + 1) / 2
    lr = (
        np.array([math.cos(p * math.pi / 2), math.sin(p * math.pi / 2)], dtype=np.float32)
        * math.sqrt(2)
        * gain
    )
    e = min(len(out), s + len(sig))
    out[s:e] += sig[: e - s, None] * lr


# ------------------------------------------------------------------------------------------ beds
def wind(seconds: float, strength: float, rng: np.random.Generator) -> np.ndarray:
    """Wind through dry grass: stereo filtered noise, a low body plus a hissing top, swelling in gusts."""
    n = int(seconds * SR)
    # brown-ish rumble: white noise shaped by a steep low-pass (no integration: integrated noise has a jump
    # where the circular FFT filter wraps, which spikes the ends)
    body = _lp_fast(rng.standard_normal((n, 2)), 160) * 3.0
    body -= _lp_fast(body, 25)  # no sub-audio drift
    hiss = _bp_fast(rng.standard_normal(n), 1800, 7000)
    hiss = np.stack([hiss, np.roll(hiss, 311)], axis=1)
    t = np.arange(n) / SR
    phase = rng.uniform(0, 6.28, 3)
    gust = 0.55 + 0.25 * np.sin(2 * np.pi * t / 9.0 + phase[0]) + 0.2 * np.sin(2 * np.pi * t / 3.7 + phase[1])
    gust = np.clip(gust + 0.1 * np.sin(2 * np.pi * t / 1.3 + phase[2]), 0.15, 1.2)[:, None]
    return ((body * 0.9 + hiss * 0.05) * gust * strength).astype(np.float32)


def bird(rng: np.random.Generator, kind: int) -> np.ndarray:
    """One bird phrase: a few chirps (frequency sweeps with a little vibrato)."""
    notes = int(rng.integers(2, 6))
    out: list[np.ndarray] = []
    base = rng.uniform(2200, 4200)
    for _ in range(notes):
        d = rng.uniform(0.05, 0.16)
        t = np.arange(int(d * SR)) / SR
        sweep = base * (1 + (rng.uniform(-0.35, 0.45) if kind % 2 else 0.3) * t / d)
        vib = 1 + 0.03 * np.sin(2 * np.pi * rng.uniform(20, 45) * t)
        ph = 2 * np.pi * np.cumsum(sweep * vib) / SR
        env = np.sin(np.pi * t / d) ** 2
        out.append((np.sin(ph) + 0.2 * np.sin(2 * ph)) * env)
        out.append(np.zeros(int(rng.uniform(0.03, 0.12) * SR)))
    return np.concatenate(out).astype(np.float32)


def crickets(seconds: float, rng: np.random.Generator, voices: int = 6) -> np.ndarray:
    """Night insects: several crickets, each a pulsed high tone (chirp trains) at its own rate and place."""
    n = int(seconds * SR)
    out = np.zeros((n, 2), np.float32)
    t = np.arange(n) / SR
    for _ in range(voices):
        f = rng.uniform(4200, 5200)
        rate = rng.uniform(2.0, 3.6)  # chirps per second
        pulse = rng.uniform(28, 40)  # wing strokes per second inside a chirp
        chirp = (np.sin(2 * np.pi * rate * t + rng.uniform(0, 6.3)) > 0.55).astype(np.float32)
        strokes = (0.5 + 0.5 * np.sin(2 * np.pi * pulse * t)) ** 4
        sig = np.sin(2 * np.pi * f * t) * chirp * strokes * rng.uniform(0.02, 0.05)
        pan = rng.uniform(-0.8, 0.8)
        p = (pan + 1) / 2
        out[:, 0] += sig * math.cos(p * math.pi / 2)
        out[:, 1] += sig * math.sin(p * math.pi / 2)
    return out


def cicadas(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """A distant midday cicada drone that swells and fades now and then."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    buzz = _bp_fast(rng.standard_normal(n), 3500, 7500) * (0.5 + 0.5 * np.sin(2 * np.pi * 180 * t))
    swell = np.clip(np.sin(2 * np.pi * t / rng.uniform(7, 11) + rng.uniform(0, 6)), 0, 1) ** 2
    sig = buzz * swell * 0.03
    return np.stack([sig, np.roll(sig, 97)], axis=1).astype(np.float32)


def water_lap(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Gentle water at the edge: soft low-passed noise bursts with small bubbly tones."""
    n = int(seconds * SR)
    out = np.zeros((n, 2), np.float32)
    t = 0.0
    while t < seconds:
        d = rng.uniform(0.25, 0.6)
        m = int(d * SR)
        x = _lp_fast(rng.standard_normal(m), 900) * np.sin(np.pi * np.arange(m) / m) ** 2 * 0.25
        for _ in range(int(rng.integers(0, 3))):  # a bubble or two
            bd = int(0.04 * SR)
            bt = np.arange(bd) / SR
            f0 = rng.uniform(400, 900)
            bub = np.sin(2 * np.pi * np.cumsum(f0 * (1 + 2 * bt / 0.04)) / SR) * np.exp(-bt * 70) * 0.08
            o = int(rng.uniform(0, max(1, m - bd)))
            x[o : o + bd] += bub[: len(x[o : o + bd])]
        _place(out, t, x.astype(np.float32), pan=rng.uniform(-0.3, 0.3))
        t += rng.uniform(0.3, 1.1)
    return out


BED = {  # per time of day: wind strength, birds per minute, insects
    "dawn": (0.35, 26, None),
    "midday": (0.55, 8, "cicadas"),
    "afternoon": (0.6, 10, "cicadas"),
    "sunset": (0.4, 16, None),
    "night": (0.25, 0, "crickets"),
}


def bed(tod: str, seconds: float, water: bool = False, seed: int = 0) -> np.ndarray:
    """The location ambience for a scene: wind + birds/insects for the time of day (+ water if near it)."""
    rng = np.random.default_rng(seed)
    strength, birds_pm, insects = BED[tod]
    out = wind(seconds, strength, rng)
    for _ in range(int(birds_pm * seconds / 60)):
        _place(
            out,
            rng.uniform(0, seconds),
            bird(rng, int(rng.integers(0, 4))),
            pan=rng.uniform(-0.9, 0.9),
            gain=rng.uniform(0.04, 0.11),
        )
    if insects == "crickets":
        out += crickets(seconds, rng)
    elif insects == "cicadas":
        out += cicadas(seconds, rng)
    if water:
        out += water_lap(seconds, rng)
    # a bed sits under everything: -30 dBFS RMS (night quieter), no peak above -6 dBFS
    target = 10 ** ((-34.0 if tod == "night" else -30.0) / 20)
    rms = float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) or 1.0
    out *= target / rms
    peak = float(np.abs(out).max())
    if peak > 0.5:
        out *= 0.5 / peak
    return out.astype(np.float32)


# ------------------------------------------------------------------------------------------ SFX
FOOT = {  # species -> footstep voice
    "elephant": "thump",
    "giraffe": "hoof",
    "zebra": "hoof",
    "meerkat": "patter",
    "tortoise": "scrape",
}


def footstep(kind: str, rng: np.random.Generator, weight: float = 1.0) -> np.ndarray:
    if kind == "thump":  # a padded, heavy foot: low sine drop + a puff of dust
        d = 0.28
        t = np.arange(int(d * SR)) / SR
        body = np.sin(2 * np.pi * np.cumsum(70 * (1 - 0.4 * t / d)) / SR) * np.exp(-t * 18)
        dust = _lp_fast(rng.standard_normal(len(t)), 1200) * np.exp(-t * 30) * 0.25
        return ((body * 0.9 + dust) * 0.55 * weight).astype(np.float32)
    if kind == "hoof":  # a two-part clop, muffled by grass
        d = 0.12
        t = np.arange(int(d * SR)) / SR
        f1, f2 = rng.uniform(700, 900), rng.uniform(260, 340)
        clop = np.sin(2 * np.pi * f1 * t) * np.exp(-t * 90) + 0.7 * np.sin(2 * np.pi * f2 * t) * np.exp(
            -t * 45
        )
        grass = _bp_fast(rng.standard_normal(len(t)), 1500, 6000) * np.exp(-t * 40) * 0.25
        return (_lp_fast(clop, 2400) * 0.4 * weight + grass * weight).astype(np.float32)
    if kind == "patter":  # a tiny soft tick in the sand
        d = 0.05
        t = np.arange(int(d * SR)) / SR
        return (_bp_fast(rng.standard_normal(len(t)), 2000, 8000) * np.exp(-t * 120) * 0.12 * weight).astype(
            np.float32
        )
    # scrape: a slow scaly drag plus a claw click
    d = 0.35
    t = np.arange(int(d * SR)) / SR
    drag = _bp_fast(rng.standard_normal(len(t)), 600, 3000) * np.sin(np.pi * t / d) ** 2 * 0.12
    click = np.zeros_like(t)
    c = int(0.25 * SR)
    click[c : c + 200] = np.sin(2 * np.pi * 2600 * np.arange(200) / SR) * np.exp(-np.arange(200) / 40) * 0.25
    return ((drag + click) * weight).astype(np.float32)


def splash(rng: np.random.Generator) -> np.ndarray:
    d = 1.2
    t = np.arange(int(d * SR)) / SR
    burst = _lp_fast(rng.standard_normal(len(t)), 3000) * np.exp(-t * 4) * 0.5
    for _ in range(14):
        o = rng.uniform(0.05, 0.9)
        bt = t - o
        m = bt > 0
        f0 = rng.uniform(500, 1400)
        burst[m] += np.sin(2 * np.pi * f0 * (1 + 3 * bt[m]) * bt[m]) * np.exp(-bt[m] * 40) * 0.08
    return burst.astype(np.float32)


def log_roll(rng: np.random.Generator) -> np.ndarray:
    """A heavy log grinding over: a creaking, wobbling low saw and the thump of it landing."""
    d = 1.6
    t = np.arange(int(d * SR)) / SR
    f = 55 + 25 * np.sin(2 * np.pi * 1.7 * t) + rng.uniform(-3, 3)
    saw = 2 * ((np.cumsum(f) / SR) % 1.0) - 1
    creak = _lp_fast(saw, 700) * np.clip(t / 0.2, 0, 1) * np.clip((1.2 - t) / 0.3, 0, 1) * 0.35
    thump = np.zeros_like(t)
    m = t > 1.2
    tt = t[m] - 1.2
    thump[m] = np.sin(2 * np.pi * 50 * tt) * np.exp(-tt * 9) * 0.7
    return (creak + thump).astype(np.float32)


def footsteps_track(
    species: str, touchdowns: list[tuple[float, float]], seconds: float, seed: int = 0
) -> np.ndarray:
    """A stereo footstep track from (time, pan) touchdown events (from the gait planner's stance starts)."""
    rng = np.random.default_rng(seed)
    out = np.zeros((int(seconds * SR) + SR, 2), np.float32)
    kind = FOOT[species]
    for t, pan in touchdowns:
        _place(out, t, footstep(kind, rng, weight=rng.uniform(0.8, 1.1)), pan=pan)
    return out[: int(seconds * SR)]


def touchdowns_from_plan(plan, fps: int, cam_x: float = 0.0) -> list[tuple[float, float]]:
    """Touchdown events (seconds, pan) from a locomotion plan: each frame a foot goes from swing to stance."""
    events = []
    legs = plan[0].stance.keys() if plan else []
    for i in range(1, len(plan)):
        for leg in legs:
            if plan[i].stance[leg] and not plan[i - 1].stance[leg]:
                x = plan[i].feet[leg][0] - cam_x
                events.append((i / fps, max(-0.8, min(0.8, x / 4.0))))
    return events
