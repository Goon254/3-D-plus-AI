"""Lip sync: audio (+ optional transcript) -> timed mouth shapes (visemes).

Uses Rhubarb Lip Sync (MIT, external binary) when available; otherwise an amplitude/spectral fallback
that produces the same Preston-Blair-style shape set (A–H, X), so downstream code never changes.

Viseme -> mouth shape-key weights (``open``, ``wide``, ``round``) for a simple stylized mouth.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .tts import CACHE, read_wav

# Rhubarb shapes: A=MBP closed, B=slightly open (most consonants), C=open (EH, AE), D=wide open (AA),
# E=rounded (AO, ER), F=puckered (UW, OW, W), G=F/V teeth on lip, H=L tongue, X=idle/rest
VISEME_WEIGHTS: dict[str, dict[str, float]] = {
    "A": {"open": 0.0, "wide": 0.0, "round": 0.0},
    "B": {"open": 0.25, "wide": 0.45, "round": 0.0},
    "C": {"open": 0.55, "wide": 0.35, "round": 0.0},
    "D": {"open": 1.0, "wide": 0.2, "round": 0.0},
    "E": {"open": 0.55, "wide": 0.0, "round": 0.6},
    "F": {"open": 0.2, "wide": 0.0, "round": 1.0},
    "G": {"open": 0.12, "wide": 0.3, "round": 0.0},
    "H": {"open": 0.45, "wide": 0.15, "round": 0.0},
    "X": {"open": 0.0, "wide": 0.0, "round": 0.0},
}
SHAPE_KEYS = ("open", "wide", "round")


@dataclass
class Cue:
    start: float
    end: float
    value: str


def find_rhubarb() -> str | None:
    env = os.environ.get("ANIMATICA_RHUBARB")
    if env and Path(env).exists():
        return env
    which = shutil.which("rhubarb")
    if which:
        return which
    for pattern in ("*/rhubarb", "*/rhubarb.exe"):  # Linux/macOS and Windows release layouts
        for cand in sorted((CACHE / "rhubarb").glob(pattern)):
            if cand.is_file():
                return str(cand)
    return None


def rhubarb_cues(wav: str | Path, transcript: str | None = None) -> list[Cue]:
    exe = find_rhubarb()
    if not exe:
        raise FileNotFoundError("rhubarb not found")
    # -o file, not stdout: the Windows build writes nothing to stdout with -q (lip sync silently fell back
    # to the amplitude estimator there)
    with tempfile.TemporaryDirectory() as td:
        out_json = Path(td) / "cues.json"
        cmd = [exe, "-f", "json", "-q", "--extendedShapes", "GHX", "-o", str(out_json), str(wav)]
        if transcript:
            dialog = Path(td) / "dialog.txt"
            dialog.write_text(transcript, encoding="utf-8")
            cmd[1:1] = ["--dialogFile", str(dialog)]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
        data = json.loads(out_json.read_text(encoding="utf-8"))
    return [Cue(c["start"], c["end"], c["value"]) for c in data["mouthCues"]]


def amplitude_cues(wav: str | Path, fps: float = 60.0) -> list[Cue]:
    """Fallback: RMS energy picks openness; spectral centroid picks wide vs round."""
    a, sr = read_wav(wav)
    hop = int(sr / fps)
    cues: list[Cue] = []
    if hop <= 0 or len(a) < hop:
        return [Cue(0.0, len(a) / max(sr, 1), "X")]
    frames = len(a) // hop
    rms = np.array([np.sqrt(np.mean(a[i * hop : (i + 1) * hop] ** 2)) for i in range(frames)])
    peak = max(rms.max(), 1e-6)
    for i in range(frames):
        seg = a[i * hop : (i + 1) * hop]
        level = rms[i] / peak
        if level < 0.08:
            v = "X" if level < 0.03 else "A"
        else:
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
            freqs = np.fft.rfftfreq(len(seg), 1 / sr)
            centroid = float((spec * freqs).sum() / (spec.sum() + 1e-9))
            if level > 0.7:
                v = "D"
            elif centroid < 900:
                v = "F" if level < 0.35 else "E"
            elif centroid > 2500:
                v = "B"
            else:
                v = "C" if level > 0.35 else "B"
        t0, t1 = i / fps, (i + 1) / fps
        if cues and cues[-1].value == v:
            cues[-1].end = t1
        else:
            cues.append(Cue(t0, t1, v))
    # enforce a minimum cue length so the mouth doesn't flicker
    merged: list[Cue] = []
    for c in cues:
        if merged and (c.end - c.start) < 0.05:
            merged[-1].end = c.end
        else:
            merged.append(c)
    return merged


def lipsync(wav: str | Path, transcript: str | None = None, engine: str = "auto") -> tuple[list[Cue], str]:
    if engine in ("auto", "rhubarb") and find_rhubarb():
        try:
            return rhubarb_cues(wav, transcript), "rhubarb"
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
            if engine == "rhubarb":
                raise
    return amplitude_cues(wav), "amplitude"


def cues_to_keyframes(
    cues: list[Cue], fps: int, offset_frame: int, transition: float = 0.06
) -> dict[str, list]:
    """Convert cues to batched keyframes per shape key: {"open": [[frame, value, interp], ...], ...}.

    Each cue gets a key at its start (reached ``transition`` seconds after the previous shape) so the
    mouth eases between shapes instead of popping. Frames are deduplicated (strictly increasing).
    """
    out: dict[str, dict[int, float]] = {k: {} for k in SHAPE_KEYS}
    for c in cues:
        w = VISEME_WEIGHTS.get(c.value, VISEME_WEIGHTS["X"])
        f_start = offset_frame + int(round(c.start * fps))
        f_hold = offset_frame + int(round(max(c.start + transition, (c.start + c.end) / 2) * fps))
        for k in SHAPE_KEYS:
            out[k][f_start] = out[k].get(f_start, w[k]) if f_start in out[k] else w[k]
            if f_hold > f_start:
                out[k][f_hold] = w[k]
    if cues:
        f_end = offset_frame + int(round(cues[-1].end * fps)) + 2
        for k in SHAPE_KEYS:
            out[k][f_end] = 0.0
    return {k: [[f, round(v, 3), "BEZIER"] for f, v in sorted(d.items())] for k, d in out.items()}
