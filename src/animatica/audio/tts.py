"""Local text-to-speech.

Engines, tried in order (``engine="auto"``):
  1. Kokoro-82M (Apache-2.0 weights) via kokoro-onnx — default
  2. Piper (GPL-3.0-or-later) with a CC0/CC-BY-dataset voice — fallback
  3. espeak-ng (GPL, external program)
  4. ``synth``: a dependency-free numpy "robot babble" voice so the pipeline always runs (CI)

Engines 1–2 run in ``adapters/tts_worker`` — a separate, GPL-licensed process with a JSON contract —
so this Apache-2.0 core never imports GPL code (see docs/research/03 and docs/DECISIONS.md).

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

SAMPLE_RATE = 24000  # Kokoro's native rate: no resampling of the main engine
CACHE = Path(os.environ.get("ANIMATICA_CACHE", Path.home() / ".cache" / "animatica"))
REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER = Path(
    os.environ.get("ANIMATICA_TTS_WORKER", REPO_ROOT / "adapters" / "tts_worker" / "animatica_tts_worker.py")
)
PIPER_VOICES = ("en-us-kathleen-low", "en-us-libritts-high")  # CC0 / CC BY 4.0 datasets


@dataclass
class VoiceSpec:
    engine: str = "auto"
    voice: str = "am_puck"  # Kokoro voice id, or a blend of stock voices "af_bella:0.6+af_jessica:0.4"
    piper_model: str = "en-us-kathleen-low"
    speaker: int | None = None
    pitch: float = 1.0  # >1 = higher (applied post-TTS)
    rate: float = 1.0  # speaking-rate multiplier
    robot: float = 0.0  # 0..1 subtle ring-mod "robot" colouring
    consent: str | None = None  # reserved for future consented voice cloning; unused
    natural: bool = True  # Kokoro: phrase pauses, breaths and *emphasis* (animatica.audio.delivery)
    mood: str | None = None  # delivery mood: a face expression name or a parenthetical word ("quietly")


def voices_dir() -> Path:
    return Path(os.environ.get("ANIMATICA_VOICES_DIR", CACHE / "voices"))


def kokoro_dir() -> Path:
    return Path(os.environ.get("ANIMATICA_KOKORO_DIR", CACHE / "kokoro"))


def find_piper_model(name: str) -> Path | None:
    for base in (voices_dir(), Path.cwd() / "voices"):
        for cand in (base / name / f"{name}.onnx", base / f"{name}.onnx"):
            if cand.exists():
                return cand
    return None


def _worker_python() -> str:
    return os.environ.get("ANIMATICA_TTS_PYTHON", sys.executable)


def _has_module(mod: str) -> bool:
    # probe in a subprocess: never import GPL engines into this process
    try:
        r = subprocess.run(
            [
                _worker_python(),
                "-c",
                f"import importlib.util,sys; sys.exit(0 if importlib.util.find_spec({mod!r}) else 1)",
            ],
            capture_output=True,
            timeout=60,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def available_engines() -> list[str]:
    engines = []
    if (
        (kokoro_dir() / "kokoro-v1.0.onnx").exists()
        and (kokoro_dir() / "voices-v1.0.bin").exists()
        and _has_module("kokoro_onnx")
    ):
        engines.append("kokoro")
    if any(find_piper_model(v) for v in PIPER_VOICES) and _has_module("piper"):
        engines.append("piper")
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        engines.append("espeak")
    engines.append("synth")
    return engines


def _worker(req: dict) -> dict:
    out = subprocess.run(
        [_worker_python(), "-I", str(WORKER)],
        input=json.dumps(req),
        text=True,
        capture_output=True,
        timeout=600,
    )
    try:
        res = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"tts worker crashed: {out.stderr[-400:]}") from None
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "tts worker failed"))
    return res


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
    """Windowed-sinc resampling (see :func:`animatica.audio.voice_fx.resample`); linear interpolation
    aliased and imaged, which added a metallic fizz to voices."""
    from .voice_fx import resample as _rs

    return _rs(a, sr_from, sr_to)


def _kokoro(text: str, out: Path, voice: VoiceSpec) -> None:
    _worker(
        {
            "engine": "kokoro",
            "text": text,
            "voice": voice.voice,
            "speed": voice.rate,
            "out": str(out),
            "model_dir": str(kokoro_dir()),
        }
    )


def _kokoro_natural(text: str, out: Path, voice: VoiceSpec) -> None:
    """Kokoro with natural delivery.

    The whole line is spoken in one call (phrases spoken on their own lose the sentence context and Kokoro
    over-releases their last consonant: "panic." came back as "panicked"). Emphasised words are stressed in
    the phoneme string and lifted in level (timed by rendering the line up to and through each word). Then
    the model's own short gaps at the phrase boundaries are widened to the punctuation pauses of
    :mod:`animatica.audio.delivery`, with a soft breath in the longer ones; the rate is varied by mood; the
    small pitch shift comes last. Two worker calls: phonemize, then every take in one batch.
    """
    from . import delivery as dl
    from . import voice_fx as fx

    phrases = dl.plan(text, voice.mood)
    spoken, emphasis = dl.spoken(text)
    n_words = len(spoken.split())
    rate = dl.line_rate(dl.plain(text), voice.rate, voice.mood)
    base = {"engine": "kokoro", "model_dir": str(kokoro_dir()), "voice": voice.voice, "speed": rate}
    tmp = out.with_suffix("")
    emph = None
    if emphasis:
        ph = _worker({**base, "batch": [{"phonemize": spoken}]})["results"][0]["phonemes"]
        emph = dl.emphasise_phonemes(ph, emphasis, n_words)
    main = {"out": f"{tmp}.line.wav", **({"phonemes": emph} if emph else {"text": spoken})}
    takes = [main]
    if emph:
        for kk in sorted({x for k in emphasis for x in (k, k + 1) if 0 < x < n_words}):
            takes.append({"phonemes": dl.prefix_phonemes(emph, kk), "out": f"{tmp}.w{kk}.wav"})
    res = {t["path"]: t for t in _worker({**base, "batch": takes})["results"]}
    a, sr = read_wav(main["out"])
    for f in out.parent.glob(f"{tmp.name}.*.wav"):
        f.unlink(missing_ok=True)
    if emph:
        g = np.ones(len(a), np.float32)
        lift = 10 ** (dl.EMPHASIS_DB / 20)
        for k in sorted(set(emphasis)):
            t0 = res.get(f"{tmp}.w{k}.wav", {}).get("duration", 0.0) if k > 0 else 0.0
            t1 = res.get(f"{tmp}.w{k + 1}.wav", {}).get("duration") if k + 1 < n_words else None
            s0 = max(0, int((t0 - 0.03) * sr))
            s1 = len(a) if t1 is None else min(len(a), int((t1 + 0.03) * sr))
            if s1 - s0 > 6:
                ramp = min(int(0.03 * sr), (s1 - s0) // 3)
                w = np.full(s1 - s0, lift, np.float32)
                w[:ramp] = np.linspace(1, lift, ramp)
                w[len(w) - ramp :] = np.linspace(lift, 1, ramp)
                g[s0:s1] = np.maximum(g[s0:s1], w)
        a = a * g
    a = _widen_pauses(a, sr, phrases, seed=zlib.crc32(text.encode("utf-8")) % 10_000)
    if voice.pitch != 1.0:
        a = fx.pitch_shift(a, sr, voice.pitch)
    write_wav(out, a / (np.abs(a).max() + 1e-6) * 0.85, sr)


def _silences(a: np.ndarray, sr: int, min_s: float = 0.04, floor_db: float = -38.0) -> list[tuple[int, int]]:
    """Runs of near-silence (10 ms frames below ``floor_db`` re the peak), excluding the line's ends."""
    hop = int(0.01 * sr)
    n = len(a) // hop
    if n < 3:
        return []
    r = np.sqrt(np.mean(a[: n * hop].reshape(n, hop) ** 2, axis=1))
    quiet = r < (np.abs(a).max() + 1e-9) * 10 ** (floor_db / 20)
    runs, k = [], 0
    while k < n:
        if quiet[k]:
            e = k
            while e < n and quiet[e]:
                e += 1
            if k > 0 and e < n and (e - k) * hop >= min_s * sr:
                runs.append((k * hop, e * hop))
            k = e
        else:
            k += 1
    return runs


def _widen_pauses(a: np.ndarray, sr: int, phrases: list, seed: int = 0) -> np.ndarray:
    """Stretch the gap at each phrase boundary to the phrase's planned pause and breathe in the long ones.

    Boundaries are matched to the silences Kokoro left, in order, near where the text says they fall
    (character share of the line); a boundary with no silence nearby is left as the model spoke it."""
    from . import voice_fx as fx

    bounds = phrases[:-1]
    if not bounds:
        return a
    gaps = _silences(a, sr)
    total = sum(len(p.text) for p in phrases)
    dur = len(a)
    used: set[int] = set()
    inserts: list[tuple[int, int, bool]] = []  # (sample position, extra samples, breath)
    acc = 0
    for p in bounds:
        acc += len(p.text)
        expect = dur * acc / max(1, total)
        cand = [(abs((g0 + g1) / 2 - expect), gi) for gi, (g0, g1) in enumerate(gaps) if gi not in used]
        cand = [c for c in cand if c[0] < 0.22 * dur]
        if not cand:
            continue
        gi = min(cand)[1]
        if inserts and gi <= max(u for u in used):
            continue  # keep boundaries in order
        used.add(gi)
        g0, g1 = gaps[gi]
        extra = int(p.pause * sr) - (g1 - g0)
        if extra > 0 or p.breath:
            inserts.append(((g0 + g1) // 2, max(0, extra), p.breath))
    out, last = [], 0
    peak = float(np.abs(a).max()) + 1e-9
    for pos, extra, br in inserts:
        out.append(a[last:pos])
        gap = np.zeros(extra, np.float32)
        if br:
            # the breath ends ~60 ms before the next phrase; it may reach back into the model's own gap
            b = fx.breath(sr, 0.24, seed=seed + pos) * (peak / 0.85)
            if len(gap) < len(b) + int(0.06 * sr):
                gap = np.zeros(len(b) + int(0.06 * sr), np.float32)
            e = len(gap) - int(0.06 * sr)
            gap[e - len(b) : e] += b
        out.append(gap)
        last = pos
    out.append(a[last:])
    return np.concatenate(out).astype(np.float32)


def _piper(text: str, out: Path, voice: VoiceSpec) -> None:
    model = find_piper_model(voice.piper_model) or next(
        (m for m in map(find_piper_model, PIPER_VOICES) if m), None
    )
    if model is None:
        raise RuntimeError("no piper voice model found; run scripts/setup_assets.sh")
    cfg = json.loads(Path(str(model) + ".json").read_text(encoding="utf-8"))
    speaker = voice.speaker if int(cfg.get("num_speakers", 1)) > 1 else None
    _worker(
        {
            "engine": "piper",
            "text": text,
            "voice": str(model),
            "speaker": speaker,
            "speed": voice.rate,
            "out": str(out),
        }
    )


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
        sig = src * (1 + 0.6 * np.sin(2 * np.pi * formants[0] / 8 * t)) + 0.3 * np.sin(
            2 * np.pi * formants[1] * t
        )
        env = np.minimum(1, t / 0.02) * np.minimum(1, (dur - t) / 0.04)
        chunks.append((sig * env).astype(np.float32))
    audio = np.concatenate(
        [np.zeros(int(sr * 0.05), np.float32), *chunks, np.zeros(int(sr * 0.1), np.float32)]
    )
    audio = audio / (np.abs(audio).max() + 1e-6) * 0.6
    write_wav(out, audio, sr)


def _post(path: Path, voice: VoiceSpec, pitched: bool = False) -> float:
    a, sr = read_wav(path)
    if voice.pitch != 1.0 and not pitched:
        # pitch shift: sinc-resample, then WSOLA back to length (voice_fx.pitch_shift)
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
    """WSOLA time-stretch to ``target_len`` samples without changing pitch.

    Plain overlap-add with fixed hops imprints the hop rate on the signal (a buzz at sr/hop and its
    harmonics: 93.75 Hz at 24 kHz, which a pitch tracker heard as the voice). WSOLA shifts each frame by up to
    a quarter window to line up with the natural continuation of the previous one, so the waveform stays
    continuous and the voice keeps its own pitch.
    """
    if len(a) < win * 2 or target_len <= 0:
        return resample(a, len(a), target_len) if len(a) else a
    hop = win // 2  # Hann at 50 % overlap sums to a constant
    tol = win // 4
    alpha = (len(a) - win) / max(1, target_len - win)  # input samples per output sample
    n_frames = max(1, (target_len - win) // hop + 1)
    pad = np.pad(a.astype(np.float32), (tol, win + tol))
    w = np.hanning(win).astype(np.float32)
    out = np.zeros(target_len + win, np.float32)
    norm = np.zeros_like(out)
    prev = None  # input position of the previously copied frame
    for i in range(n_frames):
        nominal = int(i * hop * alpha) + tol
        if prev is None:
            pos = nominal
        else:
            natural = pad[prev + hop : prev + hop + win]  # what would follow the last frame seamlessly
            lo, hi = nominal - tol, nominal + tol
            region = pad[lo : hi + win]
            # cross-correlation of the continuation with every candidate start in [lo, hi]
            c = np.correlate(region, natural, mode="valid")
            pos = lo + int(np.argmax(c))
        seg = pad[pos : pos + win]
        o = i * hop
        out[o : o + win] += seg * w
        norm[o : o + win] += w
        prev = pos
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
            natural = eng == "kokoro" and voice.natural
            if natural:
                _kokoro_natural(text, out, voice)
            else:
                spoken = text.replace("*", "")
                {"kokoro": _kokoro, "piper": _piper, "espeak": _espeak, "synth": _synth}[eng](
                    spoken, out, voice
                )
            duration = _post(out, voice, pitched=natural)
            return {"path": str(out), "engine": eng, "duration": round(duration, 3)}
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"all TTS engines failed: {last_err}")
