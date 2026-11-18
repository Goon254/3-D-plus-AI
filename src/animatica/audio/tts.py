"""Local text-to-speech.

Engines, tried in order (``engine="auto"``):
  1. Chatterbox (MIT code and weights) on the GPU via CUDA PyTorch — default. Each character's voice is
     steered by that character's own Kokoro take (a blend of stock voices, below), so the cast keeps its
     approved casting; every take passes a Whisper speech-recognition check or falls back to Kokoro.
     Runs in its own venv (``chatterbox_worker.py``; the core never imports torch).
  2. Kokoro-82M (Apache-2.0 weights) via kokoro-onnx — fallback, and the Chatterbox conditioning voice
  3. Piper (GPL-3.0-or-later) with a CC0/CC-BY-dataset voice — fallback
  4. espeak-ng (GPL, external program)
  5. ``synth``: a dependency-free numpy "robot babble" voice so the pipeline always runs (CI)

Engines 2–3 run in ``adapters/tts_worker`` — a separate, GPL-licensed process with a JSON contract —
so this Apache-2.0 core never imports GPL code (see docs/research/03 and docs/DECISIONS.md).

Voice cloning is intentionally not supported. ``VoiceSpec.consent`` exists as the hook for a future
feature and must be an explicit, recorded consent from the voice owner; it is ignored tonight.
"""

from __future__ import annotations

import hashlib
import json
import math
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
CHATTERBOX_WORKER = Path(__file__).with_name("chatterbox_worker.py")
LINE_CACHE_VERSION = "lines-v1"  # bump to invalidate every cached take
CHATTERBOX_MAX_WER = 0.1  # regenerate (next seed) above this word error rate ...
CHATTERBOX_FALLBACK_WER = 0.25  # ... and fall back to Kokoro if the best of the tries is still above this
CHATTERBOX_MAX_DRIFT_ST = 5.0  # fall back if the take's median pitch leaves the character's voice by more
DEFAULT_REF_TEXT = "Hello there. I have been walking all morning, and I think it is going to be a lovely day."
# mood -> Chatterbox exaggeration (0.5 = neutral; higher is more animated)
EXAGGERATION = {
    "neutral": 0.5,
    "happy": 0.6,
    "excited": 0.75,
    "laughing": 0.75,
    "proud": 0.6,
    "dignified": 0.45,
    "sad": 0.4,
    "worried": 0.6,
    "scared": 0.8,
    "surprised": 0.7,
    "curious": 0.55,
    "determined": 0.6,
    "quietly": 0.35,
    "wise": 0.45,
}


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
    ref_text: str | None = None  # Chatterbox: the line the character's Kokoro conditioning take speaks
    exaggeration: float | None = None  # Chatterbox: override the mood's exaggeration
    cache: bool = True  # reuse an identical earlier take from the line cache


def chatterbox_python() -> Path:
    base = Path.home() / ".cache" / "animatica" / "chatterbox-venv"
    exe = base / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return Path(os.environ.get("ANIMATICA_CHATTERBOX_PYTHON", exe))


def lines_dir() -> Path:
    return Path(os.environ.get("ANIMATICA_LINE_CACHE", CACHE / "lines"))


_CODE_HASH: list[str] = []


def _code_hash() -> str:
    """Hash of the code that shapes a take (this module, delivery, voice_fx, both workers): editing any of
    them invalidates the cache, so a cached take is always what the current code would speak."""
    if not _CODE_HASH:
        here = Path(__file__).parent
        h = hashlib.sha256()
        for f in (here / "tts.py", here / "delivery.py", here / "voice_fx.py", CHATTERBOX_WORKER, WORKER):
            # line endings normalised: a checkout with CRLF must not invalidate every cached take
            h.update(f.read_bytes().replace(b"\r\n", b"\n") if f.exists() else b"")
        _CODE_HASH.append(h.hexdigest()[:12])
    return _CODE_HASH[0]


def cache_key(text: str, voice: VoiceSpec, engine: str) -> str:
    """Content address of a take: the text, every field that changes the audio, the engine, the cache version."""
    fields = {k: v for k, v in voice.__dict__.items() if k not in ("cache", "engine", "consent")}
    blob = json.dumps([LINE_CACHE_VERSION, _code_hash(), engine, text, fields], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def exaggeration_for(voice: VoiceSpec) -> float:
    if voice.exaggeration is not None:
        return float(voice.exaggeration)
    return EXAGGERATION.get((voice.mood or "neutral").lower(), 0.5)


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
        if chatterbox_python().exists():
            engines.append("chatterbox")  # needs Kokoro for its conditioning take
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


def _trim(a: np.ndarray, sr: int, floor_db: float = -45.0, pad: float = 0.05) -> tuple[np.ndarray, int]:
    """Cut leading/trailing near-silence (Chatterbox sometimes trails a breathy tail), keeping ``pad`` s.
    Returns the trimmed audio and the number of samples cut from the start."""
    hop = int(0.01 * sr)
    n = len(a) // hop
    if n < 3:
        return a, 0
    r = np.sqrt(np.mean(a[: n * hop].reshape(n, hop) ** 2, axis=1))
    loud = np.where(r >= (np.abs(a).max() + 1e-9) * 10 ** (floor_db / 20))[0]
    if not len(loud):
        return a, 0
    s0 = max(0, int(loud[0]) * hop - int(pad * sr))
    s1 = min(len(a), (int(loud[-1]) + 1) * hop + int(pad * sr))
    return a[s0:s1], s0


def _align_words(spoken_words: list[str], heard: list[list]) -> dict[int, tuple[float, float]]:
    """Map each spoken word index to the (start, end) of the matching recognised word."""
    import difflib

    def n(w: str) -> str:
        return re.sub(r"[^a-z']", "", w.lower())

    a = [n(w) for w in spoken_words]
    b = [n(w[0]) for w in heard]
    out: dict[int, tuple[float, float]] = {}
    for blk in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            out[blk.a + k] = (float(heard[blk.b + k][1]), float(heard[blk.b + k][2]))
    return out


def _chatterbox_post(text: str, src: Path, out: Path, voice: VoiceSpec, words: list[list]) -> float:
    """The delivery pass on a Chatterbox take: emphasis lift timed by the recognised words, the mood's pace
    (the conditioning take already carries the character's own rate and pitch shift), punctuation pauses
    and breaths. Writes ``out`` at :data:`SAMPLE_RATE`; returns its duration."""
    from . import delivery as dl

    a, sr = read_wav(src)
    a, cut = _trim(a, sr)
    lead = cut / sr  # word times are relative to the untrimmed take
    spoken, emphasis = dl.spoken(text)
    if emphasis and words:
        times = _align_words(spoken.split(), words)
        g = np.ones(len(a), np.float32)
        lift = 10 ** (dl.EMPHASIS_DB / 20)
        for k in sorted(set(emphasis)):
            if k not in times:
                continue
            s0 = max(0, int((times[k][0] - lead - 0.03) * sr))
            s1 = min(len(a), int((times[k][1] - lead + 0.03) * sr))
            if s1 - s0 > 6:
                ramp = min(int(0.03 * sr), (s1 - s0) // 3)
                w = np.full(s1 - s0, lift, np.float32)
                w[:ramp] = np.linspace(1, lift, ramp)
                w[len(w) - ramp :] = np.linspace(lift, 1, ramp)
                g[s0:s1] = np.maximum(g[s0:s1], w)
        a = a * g
    pace = dl.line_rate(dl.plain(text), 1.0, voice.mood)
    if abs(pace - 1.0) > 0.01:
        a = _time_stretch(a, int(len(a) / pace))
    a = _widen_pauses(a, sr, dl.plan(text, voice.mood), seed=zlib.crc32(text.encode("utf-8")) % 10_000)
    if sr != SAMPLE_RATE:
        a, sr = resample(a, sr, SAMPLE_RATE), SAMPLE_RATE
    a = a / (np.abs(a).max() + 1e-6) * 0.85
    write_wav(out, a, sr)
    return len(a) / sr


def asr_prompt(text: str) -> str:
    """The proper names in a line (capitalised words that don't start a sentence), primed into Whisper so it
    spells the cast's names as written ("Neema", not "Nima")."""
    seen: list[str] = []
    start = True
    for tok in text.replace("*", "").split():
        word = tok.strip(".,!?;:\"'()")
        if not start and word[:1].isupper() and word[1:].islower() and word not in seen:
            seen.append(word)
        start = tok.endswith((".", "!", "?"))
    return ", ".join(seen) + "." if seen else ""


def _drift_st(take: Path, ref: Path) -> float:
    """Semitones between the take's median pitch and its conditioning take's (0 if either is unvoiced)."""
    from .voice_fx import f0_median

    if not take.exists() or not ref.exists():
        return 0.0
    a, sa = read_wav(take)
    b, sb = read_wav(ref)
    fa, fb = f0_median(a, sa), f0_median(b, sb)
    return 12 * math.log2(fa / fb) if fa > 0 and fb > 0 else 0.0


def _run_chatterbox(takes: list[dict]) -> list[dict]:
    r = subprocess.run(
        [str(chatterbox_python()), "-I", str(CHATTERBOX_WORKER)],
        input=json.dumps({"device": os.environ.get("ANIMATICA_CHATTERBOX_DEVICE", "auto"), "takes": takes}),
        text=True,
        capture_output=True,
        timeout=3600,
    )
    try:
        res = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"chatterbox worker crashed: {r.stderr[-400:]}") from None
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "chatterbox worker failed"))
    return res["results"]


def _from_cache(key: str, out: Path) -> dict | None:
    meta = lines_dir() / f"{key}.json"
    wav = lines_dir() / f"{key}.wav"
    if not (meta.exists() and wav.exists()):
        return None
    if wav.resolve() != out.resolve():
        shutil.copyfile(wav, out)
    return {**json.loads(meta.read_text(encoding="utf-8")), "path": str(out), "cached": True}


def _to_cache(key: str, info: dict) -> None:
    lines_dir().mkdir(parents=True, exist_ok=True)
    dst = lines_dir() / f"{key}.wav"
    if Path(info["path"]).resolve() != dst.resolve():
        shutil.copyfile(info["path"], dst)
    keep = {k: v for k, v in info.items() if k not in ("path", "cached")}
    (lines_dir() / f"{key}.json").write_text(json.dumps(keep), encoding="utf-8")


def _single(text: str, out: Path, voice: VoiceSpec, engines: list[str]) -> dict:
    last_err = None
    for eng in engines:
        if eng == "chatterbox":
            continue
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


def _engines_for(voice: VoiceSpec, avail: list[str] | None) -> list[str]:
    if voice.engine == "auto":
        return avail if avail is not None else available_engines()
    return [voice.engine] + (["kokoro"] if voice.engine == "chatterbox" else [])


def synthesize_batch(items: list[tuple[str, str | Path, VoiceSpec | None]]) -> list[dict]:
    """Synthesize many lines, loading Chatterbox once for all of them. Returns one {path, engine, duration}
    per item (Chatterbox takes add ``heard``, ``wer`` and ``tries``; a fallback adds ``fallback``).

    Every take is content-addressed in the line cache (:func:`cache_key`), so a re-run of a scene only
    speaks the lines that changed. Chatterbox lines are steered by the character's Kokoro take of
    ``ref_text`` (itself cached). The worker checks each take with Whisper and regenerates it with the next
    seed above :data:`CHATTERBOX_MAX_WER`; if the best try is still above :data:`CHATTERBOX_FALLBACK_WER`, or
    the worker fails, the line is spoken by Kokoro instead.
    """
    from . import delivery as dl

    results: list[dict | None] = [None] * len(items)
    pending: list[tuple[int, str, Path, VoiceSpec, list[str], str]] = []
    avail = None
    for i, (text, out, voice) in enumerate(items):
        voice = voice or VoiceSpec()
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if voice.engine == "auto" and avail is None:
            avail = available_engines()
        engines = _engines_for(voice, avail)
        key = cache_key(text, voice, engines[0])
        hit = _from_cache(key, out) if voice.cache else None
        if hit:
            results[i] = hit
        else:
            pending.append((i, text, out, voice, engines, key))
    cb = [p for p in pending if p[4][0] == "chatterbox"]
    if cb:
        takes, refs = [], {}
        for _i, text, out, voice, _e, _k in cb:
            ref_spec = VoiceSpec(**{**voice.__dict__, "engine": "kokoro", "mood": None, "ref_text": None})
            ref_text = voice.ref_text or DEFAULT_REF_TEXT
            rk = cache_key(ref_text, ref_spec, "kokoro")
            if rk not in refs:
                refs[rk] = synthesize(ref_text, lines_dir() / "refs" / f"{rk}.wav", ref_spec)["path"]
            spoken, _ = dl.spoken(text)
            ex = exaggeration_for(voice)
            takes.append(
                {
                    "text": spoken,
                    "out": str(out.with_suffix(".cb.wav")),
                    "ref": refs[rk],
                    "exaggeration": ex,
                    "cfg": 0.4 if ex >= 0.7 else 0.5,
                    "seed": zlib.crc32(text.encode("utf-8")) % 1000,
                    "max_wer": CHATTERBOX_MAX_WER,
                    "tries": 3,
                    "prompt": asr_prompt(text),
                }
            )
        try:
            got = _run_chatterbox(takes)
        except Exception as e:  # noqa: BLE001
            got = [{"error": str(e)}] * len(cb)
        for (i, text, out, voice, engines, key), g, take in zip(cb, got, takes, strict=True):
            src = out.with_suffix(".cb.wav")
            drift = _drift_st(src, Path(take["ref"])) if "error" not in g else 0.0
            if "error" in g:
                why = g["error"]
            elif g["wer"] > CHATTERBOX_FALLBACK_WER:
                why = f"wer {g['wer']} > {CHATTERBOX_FALLBACK_WER} ({g['heard']!r})"
            elif abs(drift) > CHATTERBOX_MAX_DRIFT_ST:
                why = f"pitch drift {drift:+.1f} st from the character's voice"
            else:
                why = None
            if why is None:
                dur = _chatterbox_post(text, src, out, voice, g.get("words") or [])
                info = {
                    "path": str(out),
                    "engine": "chatterbox",
                    "duration": round(dur, 3),
                    "heard": g["heard"],
                    "wer": g["wer"],
                    "tries": g["tries"],
                    "pitch_drift_st": round(drift, 2),
                }
            else:
                info = {**_single(text, out, voice, engines), "fallback": why}
            src.unlink(missing_ok=True)
            results[i] = info
            if voice.cache and "error" not in g:
                _to_cache(key, info)  # a worker failure is not cached: the next run tries Chatterbox again
    for i, text, out, voice, engines, key in pending:
        if engines[0] == "chatterbox":
            continue
        info = _single(text, out, voice, engines)
        results[i] = info
        if voice.cache and info["engine"] != "synth":
            _to_cache(key, info)
    return results  # type: ignore[return-value]


def synthesize(text: str, out: str | Path, voice: VoiceSpec | None = None) -> dict:
    """Synthesize ``text`` to a mono 24 kHz WAV. Returns {path, engine, duration}."""
    return synthesize_batch([(text, out, voice)])[0]
