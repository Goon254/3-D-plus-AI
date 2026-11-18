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
    if tod in ("dawn", "midday", "afternoon"):  # a distant hornbill now and then
        for _ in range(int(seconds / 14)):
            _place(out, rng.uniform(0, seconds), hornbill(rng), pan=rng.uniform(-0.8, 0.8), gain=0.05)
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


def drip(rng: np.random.Generator) -> np.ndarray:
    """One water drop into a puddle: a short upward 'plip' (a resonant bubble whose pitch rises)."""
    d = 0.35
    t = np.arange(int(d * SR)) / SR
    f0 = rng.uniform(900, 1300)
    ph = 2 * np.pi * np.cumsum(f0 * (1 + 2.2 * np.clip(t / 0.06, 0, 1))) / SR
    plip = np.sin(ph) * np.exp(-t * 32) * 0.5
    tick = _lp_fast(rng.standard_normal(len(t)), 6000) * np.exp(-t * 400) * 0.25
    return (plip + tick).astype(np.float32)


def slurp(rng: np.random.Generator) -> np.ndarray:
    """A trunk sucking up water: gurgling, rising noise with a wobble, then a comic stop."""
    d = 1.1
    t = np.arange(int(d * SR)) / SR
    noise = _bp_fast(rng.standard_normal(len(t)), 300, 1800)
    gurgle = 0.6 + 0.4 * np.sin(2 * np.pi * (7 + 5 * t) * t)
    env = np.clip(t / 0.15, 0, 1) * np.clip((0.95 - t) / 0.08, 0, 1)
    sweep = np.sin(2 * np.pi * np.cumsum(180 + 260 * t) / SR) * 0.25
    return ((noise * 0.6 * gurgle + sweep) * env * 0.6).astype(np.float32)


SFX = {"splash": splash, "drip": drip, "slurp": slurp}


def sfx(kind: str, seed: int = 0, pan: float = 0.0) -> np.ndarray:
    """A stereo one-shot SFX by name (``SFX`` keys + ``log_roll``)."""
    rng = np.random.default_rng(seed)
    fn = {**SFX, "log_roll": log_roll, **CALLS}[kind]
    mono = fn(rng)
    out = np.zeros((len(mono), 2), np.float32)
    _place(out, 0.0, mono, pan=pan)
    return out


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


# ------------------------------------------------------------------------------- footsteps, v2 (11-18)
# The owner (animatic 11-18): "animal movement sounds are poor". v1 was one tone per species with no ground.
# Every step is now three layers: the foot itself (species: pad, hoof, paw, plastron), the ground under it
# (a granular dirt crunch: dozens of tiny grains) and the grass it pushes through (a short brushed rustle),
# scaled by the animal's weight and the gait's force, with small random variation so no two steps match.


def _grains(rng: np.random.Generator, d: float, n: int, lo: float, hi: float, decay: float) -> np.ndarray:
    """``n`` tiny noise grains over ``d`` seconds (dirt and grit crunching), band-limited to lo..hi Hz."""
    m = int(d * SR)
    out = np.zeros(m, np.float32)
    for _ in range(n):
        g = int(rng.uniform(0.002, 0.007) * SR)
        o = int(rng.beta(1.3, 3.0) * max(1, m - g))
        out[o : o + g] += rng.standard_normal(g).astype(np.float32) * np.hanning(g) * rng.uniform(0.3, 1.0)
    t = np.arange(m) / SR
    return (_bp_fast(out, lo, hi) * np.exp(-t * decay)).astype(np.float32)


def _rustle(rng: np.random.Generator, d: float) -> np.ndarray:
    m = int(d * SR)
    t = np.arange(m) / SR
    flutter = 0.6 + 0.4 * np.abs(np.sin(2 * np.pi * rng.uniform(18, 30) * t))
    env = np.sin(np.pi * np.clip(t / d, 0, 1)) ** 1.5 * flutter
    return (_bp_fast(rng.standard_normal(m), 2500, 9000) * env).astype(np.float32)


# species -> (foot voice, weight, grass rustle level)
FOOT2 = {
    "elephant": ("pad", 1.0, 0.25),
    "giraffe": ("hoof_heavy", 0.75, 0.3),
    "zebra": ("hoof", 0.6, 0.35),
    "meerkat": ("paw", 0.15, 0.2),
    "tortoise": ("plastron", 0.3, 0.15),
}


def footstep2(species: str, rng: np.random.Generator, force: float = 1.0) -> np.ndarray:
    kind, weight, grass = FOOT2[species]
    if kind == "pad":  # a padded pillar: a deep, soft thud you feel, a puff of dust, a squash of grass
        d = 0.45
        t = np.arange(int(d * SR)) / SR
        f = 48 * (1 + 0.6 * np.exp(-t * 30))
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11) * (1 - np.exp(-t * 400))
        thud = _lp_fast(rng.standard_normal(len(t)), 260) * np.exp(-t * 22) * 0.9
        foot = body * 0.9 + thud + _grains(rng, d, 40, 300, 2500, 9) * 0.25
    elif kind in ("hoof", "hoof_heavy"):  # a keratin knock on hard dry ground: click, knock, a little ring
        heavy = kind == "hoof_heavy"
        d = 0.3 if heavy else 0.22
        t = np.arange(int(d * SR)) / SR
        f1 = rng.uniform(1300, 1700) * (0.7 if heavy else 1.0)
        f2 = rng.uniform(380, 460) * (0.6 if heavy else 1.0)
        click = rng.standard_normal(len(t)) * np.exp(-t * 600) * 0.6
        knock = np.sin(2 * np.pi * f1 * t) * np.exp(-t * 120) * 0.35 + np.sin(2 * np.pi * f2 * t) * np.exp(
            -t * 55
        )
        body = np.sin(2 * np.pi * (90 if heavy else 130) * t) * np.exp(-t * 30) * 0.6
        foot = _bp_fast(click, 1500, 7000) + knock * 0.8 + body + _grains(rng, d, 30, 800, 6000, 18) * 0.5
    elif kind == "paw":  # tiny clawed paws: a scratch and a tick in the sand
        d = 0.07
        t = np.arange(int(d * SR)) / SR
        foot = (
            _grains(rng, d, 8, 3000, 11000, 60) * 1.4 + rng.standard_normal(len(t)) * np.exp(-t * 900) * 0.2
        )
    else:  # plastron: a heavy shell set down: a dull low bump, a scaly drag, a claw click
        d = 0.5
        t = np.arange(int(d * SR)) / SR
        bump = _lp_fast(rng.standard_normal(len(t)), 220) * np.exp(-t * 16) * 1.2
        drag = (
            _bp_fast(rng.standard_normal(len(t)), 700, 3500)
            * np.sin(np.pi * np.clip(t / 0.35, 0, 1)) ** 2
            * 0.18
        )
        click = np.zeros_like(t)
        c = int(rng.uniform(0.05, 0.12) * SR)
        click[c : c + 160] = (
            np.sin(2 * np.pi * 2900 * np.arange(160) / SR) * np.exp(-np.arange(160) / 30) * 0.4
        )
        foot = bump + drag + click
    x = np.asarray(foot, np.float32)
    r = _rustle(rng, rng.uniform(0.12, 0.22))
    out = np.zeros(max(len(x), len(r)), np.float32)
    out[: len(x)] += x
    out[: len(r)] += r * grass
    return (out * weight * force * rng.uniform(0.85, 1.1)).astype(np.float32)


def footsteps_track2(
    species: str,
    touchdowns: list[tuple[float, float]],
    seconds: float,
    seed: int = 0,
    gains: list[float] | None = None,
    force: float = 1.0,
) -> np.ndarray:
    """A stereo footstep track from (time, pan) touchdowns, each scaled by ``gains`` (distance)."""
    rng = np.random.default_rng(seed)
    out = np.zeros((int(seconds * SR) + SR, 2), np.float32)
    for k, (t, pan) in enumerate(touchdowns):
        g = gains[k] if gains else 1.0
        if g > 0.01:
            _place(out, t, footstep2(species, rng, force), pan=pan, gain=0.5 * g)
    return out[: int(seconds * SR)]


# ------------------------------------------------------------------------------------ animal calls
# Synthesised (no samples, no licences), stylised for a kids' film rather than field-recording real.


def _formant(x: np.ndarray, centres: list[tuple[float, float, float]]) -> np.ndarray:
    """Sum of band-passes (centre Hz, width Hz, gain): a crude vocal tract."""
    out = np.zeros(len(x), np.float32)
    for c, w, g in centres:
        out += _bp_fast(x, max(40.0, c - w / 2), c + w / 2) * g
    return out


def _saw(f: np.ndarray) -> np.ndarray:
    ph = np.cumsum(f) / SR
    return (2 * (ph % 1.0) - 1).astype(np.float32)


def trumpet(rng: np.random.Generator, size: float = 1.0) -> np.ndarray:
    """An elephant calf's trumpet: a brassy, rising, wavering blare with a breathy attack."""
    d = 1.1 * size
    t = np.arange(int(d * SR)) / SR
    f0 = rng.uniform(380, 460) / size**0.3
    f = f0 * (0.8 + 0.45 * np.clip(t / 0.25, 0, 1) - 0.15 * np.clip((t - 0.7 * d) / (0.3 * d), 0, 1))
    f = f * (1 + 0.03 * np.sin(2 * np.pi * 7.5 * t))
    buzz = _saw(f) + 0.5 * _saw(f * 2.01)
    env = np.clip(t / 0.05, 0, 1) * np.clip((d - t) / 0.25, 0, 1)
    breath = _bp_fast(rng.standard_normal(len(t)), 1200, 5000) * np.exp(-t * 6) * 0.3
    v = _formant(buzz, [(900, 500, 1.0), (1800, 700, 0.7), (3000, 1200, 0.35)])
    x = (v * 0.5 + breath) * env
    return (x / (np.abs(x).max() + 1e-9) * 0.7).astype(np.float32)


def zebra_bark(rng: np.random.Generator) -> np.ndarray:
    """A zebra's 'kwa-ha': a few nasal, braying barks."""
    parts = []
    for i in range(int(rng.integers(2, 4))):
        d = rng.uniform(0.16, 0.24)
        t = np.arange(int(d * SR)) / SR
        f = rng.uniform(520, 640) * (1 + 0.35 * np.sin(np.pi * t / d)) * (0.85 if i % 2 else 1.0)
        buzz = _saw(f) * (0.6 + 0.4 * np.sin(2 * np.pi * 60 * t))
        v = _formant(buzz, [(700, 300, 1.0), (1500, 500, 0.6), (2600, 900, 0.3)])
        env = np.sin(np.pi * np.clip(t / d, 0, 1)) ** 0.7
        parts += [v * env, np.zeros(int(rng.uniform(0.05, 0.1) * SR), np.float32)]
    x = np.concatenate(parts)
    return (x / (np.abs(x).max() + 1e-9) * 0.6).astype(np.float32)


def meerkat_chirp(rng: np.random.Generator, alarm: bool = False) -> np.ndarray:
    """Meerkat peeps (contact) or a rapid, harsher alarm chatter."""
    n = int(rng.integers(5, 9)) if alarm else int(rng.integers(2, 4))
    parts = []
    for _ in range(n):
        d = rng.uniform(0.03, 0.05) if alarm else rng.uniform(0.06, 0.1)
        t = np.arange(int(d * SR)) / SR
        f = rng.uniform(2600, 3400) * (1 + (0.25 if alarm else -0.3) * t / d)
        tone = np.sin(2 * np.pi * np.cumsum(f) / SR)
        if alarm:
            tone = tone * 0.6 + _bp_fast(rng.standard_normal(len(t)), 2500, 7000) * 0.6
        parts += [tone * np.sin(np.pi * t / d) ** 2, np.zeros(int((0.035 if alarm else 0.09) * SR))]
    return (np.concatenate(parts) * 0.35).astype(np.float32)


def giraffe_hum(rng: np.random.Generator) -> np.ndarray:
    """A giraffe's soft low hum (they hum at night) with a breathy snort at the end."""
    d = 1.6
    t = np.arange(int(d * SR)) / SR
    f = 92 * (1 + 0.02 * np.sin(2 * np.pi * 3 * t))
    hum = (
        _formant(_saw(f), [(300, 200, 1.0), (700, 300, 0.4)]) * np.sin(np.pi * np.clip(t / 1.2, 0, 1)) ** 1.2
    )
    sn = np.zeros_like(t)
    m = t > 1.25
    sn[m] = _bp_fast(rng.standard_normal(int(m.sum())), 400, 2500) * np.exp(-(t[m] - 1.25) * 14) * 0.6
    x = hum * 0.7 + sn
    return (x / (np.abs(x).max() + 1e-9) * 0.5).astype(np.float32)


def tortoise_huff(rng: np.random.Generator) -> np.ndarray:
    """An old tortoise's slow exhale: a soft, low hiss with a creak of effort."""
    d = 0.9
    t = np.arange(int(d * SR)) / SR
    hiss = _bp_fast(rng.standard_normal(len(t)), 500, 3000) * np.sin(np.pi * t / d) ** 2
    grunt = np.sin(2 * np.pi * np.cumsum(140 - 30 * t / d) / SR) * np.exp(-t * 5) * 0.25
    return ((hiss * 0.35 + grunt) * 0.7).astype(np.float32)


# ------------------------------------------------------------------------ the climax: log and spring
def log_creak(rng: np.random.Generator) -> np.ndarray:
    """A heavy log giving way: wood creaking under strain (stick-slip: an irregular train of tiny impulses
    ringing the log's wood modes), a groan as it starts to roll, a rumble, then the thump as it lands."""
    d = 2.6
    t = np.arange(int(d * SR)) / SR
    n = len(t)
    imp = np.zeros(n, np.float32)
    ts = 0.0
    while ts < 1.7:
        rate = (35 + 140 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.9 * ts + 1.0))) * (0.4 + ts / 1.7)
        ts += 1.0 / rate * rng.uniform(0.7, 1.3)
        k = int(ts * SR)
        if k < n:
            imp[k] = rng.uniform(0.5, 1.0)
    wood = _formant(imp, [(320, 60, 1.0), (690, 90, 0.8), (1150, 140, 0.5), (2100, 260, 0.25)]) * 9
    groan = _formant(_saw(70 + 20 * np.sin(2 * np.pi * 0.7 * t)), [(220, 120, 1.0), (500, 200, 0.4)])
    groan *= np.clip((t - 0.9) / 0.4, 0, 1) * np.clip((1.9 - t) / 0.3, 0, 1) * 0.25
    roll = (
        _lp_fast(rng.standard_normal(n), 180)
        * np.clip((t - 1.3) / 0.2, 0, 1)
        * np.clip((2.0 - t) / 0.2, 0, 1)
    )
    thump = np.zeros(n, np.float32)
    m = t > 2.0
    tt = t[m] - 2.0
    thump[m] = (
        np.sin(2 * np.pi * 55 * tt) + _lp_fast(rng.standard_normal(int(m.sum())), 400) * 0.6
    ) * np.exp(-tt * 9)
    x = wood * np.clip((1.9 - t) / 0.3, 0, 1) + groan + roll * 0.6 + thump * 0.9
    return (x / (np.abs(x).max() + 1e-9) * 0.8).astype(np.float32)


def gush(rng: np.random.Generator) -> np.ndarray:
    """Water bursting up from the spring: a whoosh that swells, a rushing flow, and a froth of bubbles."""
    d = 3.5
    t = np.arange(int(d * SR)) / SR
    n = len(t)
    swell = np.clip(t / 0.35, 0, 1) ** 2 * np.clip((d - t) / 1.4, 0, 1)
    flow = _bp_fast(rng.standard_normal(n), 150, 2200) * (0.7 + 0.3 * np.sin(2 * np.pi * 2.3 * t))
    whoosh = _bp_fast(rng.standard_normal(n), 400, 5000) * np.exp(-t * 2.5) * np.clip(t / 0.08, 0, 1)
    bub = np.zeros(n, np.float32)
    for _ in range(70):
        s0 = int(rng.uniform(0.05, d - 0.3) * SR)
        bd = int(rng.uniform(0.02, 0.06) * SR)
        bt = np.arange(bd) / SR
        f0 = rng.uniform(350, 1400)
        b = np.sin(2 * np.pi * np.cumsum(f0 * (1 + 3 * bt / 0.05)) / SR) * np.exp(-bt * 60)
        bub[s0 : s0 + bd] += b[: len(bub[s0 : s0 + bd])]
    x = flow * swell * 0.8 + whoosh * 0.6 + bub * 0.25 * swell
    return (x / (np.abs(x).max() + 1e-9) * 0.8).astype(np.float32)


def spring_song(rng: np.random.Generator, seconds: float = 8.0) -> np.ndarray:
    """The singing spring: the water's shimmer tuned to a major chord (a glassy tone cluster that rises out of
    the bubbling and breathes), so 'its water sings' is something you hear."""
    t = np.arange(int(seconds * SR)) / SR
    x = np.zeros(len(t), np.float32)
    for i, f in enumerate((523.25, 659.25, 783.99, 1046.5, 1318.5)):  # C E G C E
        trem = 0.6 + 0.4 * np.sin(2 * np.pi * (0.35 + 0.13 * i) * t + rng.uniform(0, 6))
        x += (np.sin(2 * np.pi * f * t + 0.3 * np.sin(2 * np.pi * 5.1 * t)) * trem / (1 + i * 0.4)).astype(
            np.float32
        )
    env = np.clip(t / 1.8, 0, 1) ** 2 * np.clip((seconds - t) / 2.0, 0, 1)
    burble = _bp_fast(rng.standard_normal(len(t)), 600, 3000) * 0.15
    return ((x * 0.12 + burble) * env).astype(np.float32)


def hornbill(rng: np.random.Generator) -> np.ndarray:
    """A distant ground-hornbill-like 'took took took' (low hollow hoots) for the day beds."""
    parts = []
    for _ in range(int(rng.integers(3, 6))):
        d = 0.12
        t = np.arange(int(d * SR)) / SR
        parts += [
            np.sin(2 * np.pi * rng.uniform(260, 300) * t) * np.sin(np.pi * t / d) ** 2,
            np.zeros(int(0.22 * SR)),
        ]
    return (np.concatenate(parts) * 0.5).astype(np.float32)


CALLS = {
    "trumpet": trumpet,
    "zebra_bark": zebra_bark,
    "meerkat_chirp": meerkat_chirp,
    "meerkat_alarm": lambda rng: meerkat_chirp(rng, alarm=True),
    "giraffe_hum": giraffe_hum,
    "tortoise_huff": tortoise_huff,
    "log_creak": log_creak,
    "gush": gush,
    "spring_song": spring_song,
    "hornbill": hornbill,
}
