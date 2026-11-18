"""Long-form production, step 2: a scene's sound mix (pure numpy, 48 kHz stereo).

Layers: dialogue (placed at the scheduled line starts), the scene's music cue (re-timed to the scene by
the Composer, then ducked under every line), the location ambience bed, per-species footsteps from the
gait planner's touchdowns, and one-shot SFX. Ambience, footsteps and SFX dip 6 dB under lines; music dips
~18 dB. The report measures dialogue clarity (voice level over everything else inside the lines).
Loudness normalisation to -14 LUFS happens once on the whole film (ffmpeg loudnorm) so scenes keep their
relative dynamics.
"""

from __future__ import annotations

import numpy as np

SR = 48000
MUSIC_GAIN = 0.55
MUSIC_DUCK = 0.88  # 1 - 0.88 = 0.12 -> about -18 dB under a line
BG_DUCK = 0.5  # -6 dB
DUCK_ATTACK = 0.25  # seconds before a line the duck starts
DUCK_RELEASE = 0.4
DUCK_SMOOTH = 0.3
MIN_CLARITY_DB = 12.0  # every line sits at least this far above everything else (owner: SC 10's narrator)


def to_stereo(x: np.ndarray, sr: int) -> np.ndarray:
    """Mono/stereo at ``sr`` -> stereo float32 at SR (windowed-sinc resample: linear interpolation imaged
    the 24 kHz TTS into a metallic fizz above 12 kHz)."""
    from ..audio.voice_fx import resample

    if x.ndim == 2:
        x = x.mean(axis=1)
    y = resample(x, sr, SR)
    return np.stack([y, y], axis=1)


def dialogue(x: np.ndarray, sr: int, seed: int = 0, distance: float = 2.5) -> np.ndarray:
    """A dry TTS line placed in the savannah (EQ, light compression, outdoor reflections, room tone) as
    stereo at SR. It starts ``voice_fx.PRE`` seconds before the first word: place it that much early."""
    from ..audio.voice_fx import place_outdoor

    return to_stereo(place_outdoor(x, sr, seed=seed, distance=distance), sr)


def place(track: np.ndarray, t: float, sig: np.ndarray, gain: float = 1.0) -> tuple[int, int]:
    s = max(0, int(round(t * SR)))
    e = min(len(track), s + len(sig))
    if e > s:
        track[s:e] += sig[: e - s] * gain
    return s, e


def duck_envelope(n: int, windows: list[tuple[int, int]]) -> np.ndarray:
    duck = np.zeros(n, np.float32)
    for s, e in windows:
        duck[max(0, s - int(DUCK_ATTACK * SR)) : min(n, e + int(DUCK_RELEASE * SR))] = 1.0
    k = max(1, int(DUCK_SMOOTH * SR))
    # moving average via cumulative sum (fast for minutes of audio)
    c = np.cumsum(np.concatenate([np.zeros(k, np.float32), duck]))
    sm = (c[k:] - c[:-k]) / k
    # centre the window
    sm = np.concatenate([sm[k // 2 :], np.full(k // 2, sm[-1] if len(sm) else 0.0, np.float32)])[:n]
    return np.clip(sm, 0.0, 1.0).astype(np.float32)


def db(x: np.ndarray) -> float:
    return 20 * float(np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12))


def fit(x: np.ndarray, n: int, fade_in: float = 0.6) -> np.ndarray:
    """Trim/pad a stereo signal to ``n`` samples with a short fade-in."""
    y = np.zeros((n, 2), np.float32)
    m = min(n, len(x))
    y[:m] = x[:m]
    f = min(m, int(fade_in * SR))
    if f:
        y[:f] *= np.linspace(0, 1, f, dtype=np.float32)[:, None]
    return y


def mix_scene(
    seconds: float,
    lines: list[tuple[float, np.ndarray]],
    music: np.ndarray | None = None,
    ambience: np.ndarray | None = None,
    steps: np.ndarray | None = None,
    sfx: list[tuple[float, np.ndarray]] | None = None,
) -> tuple[np.ndarray, dict]:
    """Mix one scene. ``lines``: (start seconds, stereo voice at SR). Returns (stereo mix, report)."""
    n = int(round(seconds * SR))
    voices = np.zeros((n, 2), np.float32)
    windows = [place(voices, t, v * 0.9) for t, v in lines]
    duck = duck_envelope(n, windows)
    bg = np.zeros((n, 2), np.float32)
    if music is not None:
        bg += fit(music, n) * MUSIC_GAIN * (1.0 - MUSIC_DUCK * duck)[:, None]
    dip = (1.0 - BG_DUCK * duck)[:, None]
    if ambience is not None:
        bg += fit(ambience, n, fade_in=0.3) * dip
    if steps is not None:
        bg += fit(steps, n, fade_in=0.0) * 0.8 * dip
    for t, sig in sfx or []:
        place(bg, t, sig, gain=0.9)
    # every line clears the bed by MIN_CLARITY_DB: where music, steps and ambience still crowd a line (a long
    # narration over a whole herd walking, SC 10), the bed dips further under that line, with smooth ramps
    extra = np.ones(n, np.float32)
    line_clarity = []
    for s0, e0 in windows:
        if e0 - s0 < SR // 10:
            continue
        c = db(voices[s0:e0]) - db(bg[s0:e0])
        if c < MIN_CLARITY_DB:
            g = 10 ** ((c - MIN_CLARITY_DB - 1.0) / 20)
            r = int(0.3 * SR)
            a0, b0 = max(0, s0 - r), min(n, e0 + r)
            env = np.ones(b0 - a0, np.float32)
            env[s0 - a0 : e0 - a0] = g
            ramp_in = np.linspace(1.0, g, s0 - a0, dtype=np.float32)
            env[: s0 - a0] = ramp_in
            env[e0 - a0 :] = np.linspace(g, 1.0, b0 - e0, dtype=np.float32)
            extra[a0:b0] = np.minimum(extra[a0:b0], env)
    bg *= extra[:, None]
    for s0, e0 in windows:
        if e0 - s0 >= SR // 10:
            line_clarity.append(db(voices[s0:e0]) - db(bg[s0:e0]))
    mix = bg + voices
    inside = duck > 0.99
    clarity = db(voices[inside]) - db(bg[inside]) if inside.any() else None
    peak = float(np.abs(mix).max()) if n else 0.0
    if peak > 0.98:
        mix *= 0.98 / peak
    return mix, {
        "seconds": round(seconds, 3),
        "lines": len(lines),
        "dialogue_clarity_db": None if clarity is None else round(clarity, 1),
        "min_line_clarity_db": round(min(line_clarity), 1) if line_clarity else None,
        "music_rms_db": None if music is None else round(db(fit(music, n)), 1),
        "peak": round(min(peak, 0.98), 3),
    }
