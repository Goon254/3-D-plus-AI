"""Acting driven by the dialogue: what the voices say, timed off the real takes.

The owner's note on the animatic (11-18): "lips and acting don't match the voices". The mouths followed
Rhubarb, but nothing else listened to the audio: heads stayed still while talking, blinks were random, and
listeners never reacted. From each line's take this module derives:

* **Accents** (:func:`speech_accents`): syllable peaks of the voice's loudness envelope (local maxima,
  at least ``MIN_GAP`` apart), weighted by how loud they are. The speaker's head beats on them (a ``talk``
  gesture: small nods on the stressed syllables, a slow tilt across the phrase).
* **Phrase breaks** (:func:`pauses`): silences inside a line. The speaker blinks in them (people blink at
  phrase boundaries, not mid-word) and at the start of the line.
* **Listening** (:func:`dialogue_beats`): the addressee blinks as the line starts (the head turn toward the
  speaker comes from ``gesture.gaze_track``), nods at the end of a line addressed to them unless they
  answer straight away, and every on-stage listener gets a blink a beat into each line.

Explicit gestures in the spec win: an automatic beat is dropped where the same actor already has a written
gesture. Pure Python; ``scripts/savannah_scene.py`` feeds the result into the acting layers and the blinks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from animatica.creatures.gesture import Gesture

HOP_S = 0.01
MIN_GAP = 0.16  # seconds between accents (about a syllable)
PAUSE_S = 0.2  # a quieter stretch this long inside a line is a phrase break
LIP_LEAD_S = 1 / 24  # mouth shapes land a frame before the sound (the animator's rule: we see before we hear)


def envelope(x: np.ndarray, sr: int) -> np.ndarray:
    """RMS loudness per ``HOP_S`` frame, smoothed over ~50 ms."""
    x = np.asarray(x, np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    hop = max(1, int(sr * HOP_S))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0)
    e = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1))
    k = np.ones(5) / 5
    return np.convolve(e, k, mode="same")


def speech_accents(x: np.ndarray, sr: int) -> list[tuple[float, float]]:
    """(seconds into the take, strength 0..1) for each syllable peak of the voice."""
    e = envelope(x, sr)
    if not len(e) or e.max() <= 0:
        return []
    e = e / e.max()
    gap = int(MIN_GAP / HOP_S)
    peaks: list[tuple[float, float]] = []
    for i in range(1, len(e) - 1):
        if e[i] < 0.35 or e[i] < e[i - 1] or e[i] < e[i + 1]:
            continue
        lo, hi = max(0, i - gap), min(len(e), i + gap + 1)
        if e[i] < e[lo:hi].max():
            continue
        if peaks and i * HOP_S - peaks[-1][0] < MIN_GAP:
            continue
        peaks.append((round(i * HOP_S, 3), round(float(e[i]), 3)))
    # the loudest third are the stressed syllables: they get the full beat, the rest a light one
    if peaks:
        cut = float(np.quantile([p[1] for p in peaks], 0.66))
        peaks = [(t, 1.0 if w >= cut else 0.45) for t, w in peaks]
    return peaks


def pauses(x: np.ndarray, sr: int) -> list[float]:
    """Middles (seconds into the take) of the silences inside the line (not its lead-in or tail)."""
    e = envelope(x, sr)
    if not len(e) or e.max() <= 0:
        return []
    loud = e > 0.12 * e.max()
    idx = np.flatnonzero(loud)
    if not len(idx):
        return []
    first, last = idx[0], idx[-1]
    out, k = [], first
    min_len = int(PAUSE_S / HOP_S)
    while k < last:
        if not loud[k]:
            j = k
            while j < last and not loud[j]:
                j += 1
            if j - k >= min_len:
                out.append(round((k + j) / 2 * HOP_S, 3))
            k = j
        else:
            k += 1
    return out


@dataclass
class Beats:
    gestures: list[Gesture] = field(default_factory=list)
    blinks: dict[str, list[float]] = field(default_factory=dict)  # actor -> blink times (scene seconds)


def dialogue_beats(
    lines: list,
    takes: list[tuple[np.ndarray, int]],
    on_stage: dict[str, list[tuple[float, float]]],
    written: list[Gesture],
) -> Beats:
    """Automatic acting beats for a scheduled scene.

    ``lines``: the scene's lines (``who``, ``to``, ``start``, ``end``, ``offscreen``); ``takes``: each line's
    audio (samples, rate), aligned so sample 0 plays at ``line.start``; ``on_stage``: actor -> spans
    (seconds) it is on stage; ``written``: the spec's own gestures (they take precedence)."""
    out = Beats(blinks={c: [] for c in on_stage})

    def present(c: str, t: float) -> bool:
        return any(a <= t <= b for a, b in on_stage.get(c, []))

    def busy(c: str, t0: float, t1: float) -> bool:
        return any(g.who == c and g.start < t1 and g.start + g.dur > t0 for g in written)

    for i, (ln, (x, sr)) in enumerate(zip(lines, takes)):
        if ln.who not in on_stage or getattr(ln, "offscreen", False):
            speaker = None
        else:
            speaker = ln.who
        dur = max(0.2, ln.end - ln.start)
        if speaker:
            acc = [(ln.start + t, w) for t, w in speech_accents(x, sr)]
            if acc and not busy(speaker, ln.start, ln.end):
                g = Gesture(speaker, "talk", ln.start - 0.1, dur + 0.5)
                g.accents = acc  # type: ignore[attr-defined]
                out.gestures.append(g)
            out.blinks[speaker] += [ln.start - 0.05] + [ln.start + p for p in pauses(x, sr)]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        for c in on_stage:
            if c == ln.who or not present(c, ln.start + 0.3):
                continue
            # listeners blink as their attention moves to the speaker (the eyeline turn is gaze_track's)
            out.blinks[c].append(ln.start + 0.25 + 0.07 * (sum(map(ord, c)) % 3))
        to = getattr(ln, "to", "")
        if to and to in on_stage and present(to, ln.end) and to != ln.who:
            answers = nxt is not None and nxt.who == to and nxt.start - ln.end < 0.8
            if not answers and not busy(to, ln.end - 0.3, ln.end + 1.0):
                out.gestures.append(Gesture(to, "nod", ln.end - 0.15, 0.9, amount=0.45))
    for c in out.blinks:
        out.blinks[c] = sorted(round(t, 3) for t in out.blinks[c] if t > 0.1)
    return out
