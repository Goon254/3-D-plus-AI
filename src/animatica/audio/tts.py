"""Local text-to-speech.

Engines, tried in order (``engine="auto"``):
  1. Piper (MIT) with an open voice model (CC0 / CC-BY datasets only — see THIRD_PARTY.md)
  2. espeak-ng (GPL, invoked as an external program)
  3. ``synth``: a dependency-free numpy "robot babble" voice so the pipeline always runs (CI)

Voice cloning is intentionally not supported. ``VoiceSpec.consent`` exists as the hook for a future
feature and must be an explicit, recorded consent from the voice owner; it is ignored tonight.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import wave
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050
CACHE = Path(os.environ.get("ANIMATICA_CACHE", Path.home() / ".cache" / "animatica"))


@dataclass
class VoiceSpec:
    engine: str = "auto"
    model: str = "en-us-libritts-high"  # CC BY 4.0 dataset (LibriTTS); "en-us-kathleen-low" is CC0
    speaker: int | None = 20
    pitch: float = 1.0  # >1 = higher (applied post-TTS)
    rate: float = 1.0  # speaking-rate multiplier
    robot: float = 0.0  # 0..1 subtle ring-mod "robot" colouring
    consent: str | None = None  # reserved for future consented voice cloning; unused


def voices_dir() -> Path:
    return Path(os.environ.get("ANIMATICA_VOICES_DIR", CACHE / "voices"))


def find_piper_model(name: str) -> Path | None:
    for base in (voices_dir(), Path.cwd() / "voices"):
        for cand in (base / name / f"{name}.onnx", base / f"{name}.onnx"):
            if cand.exists():
                return cand
    return None


def _piper_available() -> bool:
    try:
        import piper  # noqa: F401

        return True
    except ImportError:
        return shutil.which("piper") is not None


def available_engines() -> list[str]:
    engines = []
    if _piper_available() and (find_piper_model(VoiceSpec().model) or find_piper_model("en-us-kathleen-low")):
        engines.append("piper")
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        engines.append("espeak")
    engines.append("synth")
    return engines


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("only 16-bit PCM supported")
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


def write_wav(path: str | Path, audio: np.ndarray, sr: int = SAMPLE_RATE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    a = np.clip(audio, -1, 1)
    if a.ndim == 1:
        ch = 1
        data = (a * 32767).astype("<i2").tobytes()
    else:
        ch = a.shape[1]
        data = (a * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data)
    return path


def resample(a: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to:
        return a
    n = int(round(len(a) * sr_to / sr_from))
    x = np.linspace(0, len(a) - 1, n)
    return np.interp(x, np.arange(len(a)), a).astype(np.float32)


def _piper(text: str, out: Path, voice: VoiceSpec) -> None:
    model = find_piper_model(voice.model) or find_piper_model("en-us-kathleen-low")
    if model is None:
        raise RuntimeError("no piper voice model found; run scripts/setup_assets.sh")
    cfg = json.loads(Path(str(model) + ".json").read_text())
    n_speakers = int(cfg.get("num_speakers", 1))
    cmd = [sys.executable, "-m", "piper", "-m", str(model), "-f", str(out)]
    if shutil.which("piper") and not _module_piper():
        cmd = ["piper", "-m", str(model), "-f", str(out)]
    if n_speakers > 1 and voice.speaker is not None:
        cmd += ["-s", str(min(voice.speaker, n_speakers - 1))]
    if voice.rate != 1.0:
        cmd += ["--length-scale", f"{1.0 / voice.rate:.3f}"]
    subprocess.run(cmd, input=text, text=True, check=True, capture_output=True, timeout=300)


def _module_piper() -> bool:
    try:
        import piper  # noqa: F401

        return True
    except ImportError:
        return False


def _espeak(text: str, out: Path, voice: VoiceSpec) -> None:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    assert exe
    wpm = int(165 * voice.rate)
    subprocess.run([exe, "-w", str(out), "-s", str(wpm), text], check=True, capture_output=True, timeout=120)


def syllables(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z']+", text)
    out: list[str] = []
    for w in words:
        parts = re.findall(r"[^aeiouy]*[aeiouy]+(?:[^aeiouy]*$|[^aeiouy](?=[^aeiouy]))?", w.lower()) or [w]
        out.extend(parts)
        out.append(" ")
    return out


def _synth(text: str, out: Path, voice: VoiceSpec) -> None:
    """Deterministic formant-ish babble: one voiced 'syllable' per text syllable. Not speech, but timed."""
    sr = SAMPLE_RATE
    rng = np.random.default_rng(zlib.crc32(text.encode()))
    chunks = []
    base = 150.0 * voice.pitch
    for syl in syllables(text):
        if syl == " ":
            chunks.append(np.zeros(int(sr * 0.06 / voice.rate), np.float32))
            continue
        dur = (0.13 + 0.02 * len(syl)) / voice.rate
        t = np.arange(int(sr * dur)) / sr
        f0 = base * (1 + 0.15 * rng.uniform(-1, 1)) * (1 - 0.15 * t / dur)
        phase = 2 * np.pi * np.cumsum(f0) / sr
        src = sum(np.sin(k * phase) / k for k in range(1, 12))
        vowel = "aeiou".find(next((c for c in syl if c in "aeiou"), "a"))
        formants = [(730, 1090), (530, 1840), (270, 2290), (570, 840), (300, 870)][max(vowel, 0)]
        sig = src * (1 + 0.6 * np.sin(2 * np.pi * formants[0] / 8 * t)) + 0.3 * np.sin(2 * np.pi * formants[1] * t)
        env = np.minimum(1, t / 0.02) * np.minimum(1, (dur - t) / 0.04)
        chunks.append((sig * env).astype(np.float32))
    audio = np.concatenate([np.zeros(int(sr * 0.05), np.float32), *chunks, np.zeros(int(sr * 0.1), np.float32)])
    audio = audio / (np.abs(audio).max() + 1e-6) * 0.6
    write_wav(out, audio, sr)


def _post(path: Path, voice: VoiceSpec) -> float:
    a, sr = read_wav(path)
    if voice.pitch != 1.0:
        # pitch shift by resampling + time-stretch back (simple overlap-add)
        shifted = resample(a, int(sr * voice.pitch), sr)
        a = _time_stretch(shifted, len(a))
    if voice.robot > 0:
        t = np.arange(len(a)) / sr
        ring = np.sin(2 * np.pi * 55 * t)
        a = (1 - voice.robot) * a + voice.robot * a * ring
        # short metallic comb
        d = int(sr * 0.004)
        a[d:] = a[d:] + 0.35 * voice.robot * a[:-d]
    a = a / (np.abs(a).max() + 1e-6) * 0.85
    a = resample(a, sr, SAMPLE_RATE)
    write_wav(path, a, SAMPLE_RATE)
    return len(a) / SAMPLE_RATE


def _time_stretch(a: np.ndarray, target_len: int, win: int = 1024) -> np.ndarray:
    if len(a) < win * 2 or target_len <= 0:
        return resample(a, len(a), target_len) if len(a) else a
    hop_out = win // 4
    n_frames = max(1, (target_len - win) // hop_out + 1)
    hop_in = (len(a) - win) / max(1, n_frames - 1)
    out = np.zeros(target_len + win, np.float32)
    norm = np.zeros_like(out)
    w = np.hanning(win).astype(np.float32)
    for i in range(n_frames):
        s = int(i * hop_in)
        seg = a[s : s + win]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        o = i * hop_out
        out[o : o + win] += seg * w
        norm[o : o + win] += w
    out = out[:target_len] / np.maximum(norm[:target_len], 1e-3)
    return out


def synthesize(text: str, out: str | Path, voice: VoiceSpec | None = None) -> dict:
    """Synthesize ``text`` to a mono 22.05 kHz WAV. Returns {path, engine, duration}."""
    voice = voice or VoiceSpec()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    engines = available_engines() if voice.engine == "auto" else [voice.engine]
    last_err = None
    for eng in engines:
        try:
            {"piper": _piper, "espeak": _espeak, "synth": _synth}[eng](text, out, voice)
            duration = _post(out, voice)
            return {"path": str(out), "engine": eng, "duration": round(duration, 3)}
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"all TTS engines failed: {last_err}")
