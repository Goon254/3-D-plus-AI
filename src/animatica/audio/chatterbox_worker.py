"""Chatterbox TTS worker (MIT code and weights) with a faster-whisper (MIT) speech-recognition check.

A standalone script that runs in its own venv: torch is not a project dependency, and the core never imports
it. ``animatica.audio.tts`` calls it with JSON on stdin and reads JSON on stdout:

    {"device": "auto"|"cuda"|"cpu",
     "takes": [{"text", "out", "ref", "exaggeration"?, "cfg"?, "seed"?, "max_wer"?, "tries"?}, ...]}
    -> {"ok": true, "device": "cuda", "results": [{"path", "sample_rate", "duration", "heard", "wer",
                                                   "tries", "words": [[word, start, end], ...]}, ...]}

Each take is generated, transcribed by Whisper (``base.en``) and scored by word error rate against its text.
A take above ``max_wer`` is generated again with the next seed (up to ``tries`` times) and the best one is kept,
so a garbled or truncated take never reaches the film. The word timestamps let the core time emphasis.

``ref`` steers the speaker. The core passes the character's own Kokoro take (a blend of synthetic stock voices,
Apache-2.0), never a recording of a real person: voice cloning of people stays behind the consent hook (PLAN
section 7). Chatterbox output carries its built-in Perth watermark.

Setup (Windows; the RTX 50 series needs a CUDA 12.8 build of torch >= 2.7):

    py -3.13 -m venv ~/.cache/animatica/chatterbox-venv
    ~/.cache/animatica/chatterbox-venv/Scripts/python -m pip install chatterbox-tts faster-whisper
    ~/.cache/animatica/chatterbox-venv/Scripts/python -m pip install --no-deps --force-reinstall \\
        torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
"""

from __future__ import annotations

import json
import re
import sys
import wave

import numpy as np


def _write(path: str, a, sr: int) -> None:
    a = np.clip(np.asarray(a, np.float32).reshape(-1), -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((a * 32767).astype("<i2").tobytes())


def _norm(s: str) -> list[str]:
    return re.sub(r"[^a-z' ]", " ", s.lower().replace("-", " ")).split()


def wer(ref: str, hyp: str) -> float:
    """Word error rate (Levenshtein over words) of ``hyp`` against ``ref``."""
    r, h = _norm(ref), _norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


def _to16k(a: np.ndarray, sr: int) -> np.ndarray:
    return np.interp(np.arange(0, len(a), sr / 16000), np.arange(len(a)), a).astype(np.float32)


def main() -> None:
    req = json.loads(sys.stdin.read())
    real_stdout, sys.stdout = sys.stdout, sys.stderr  # the libraries print progress: keep stdout for the JSON
    try:
        import torch
        from chatterbox.tts import ChatterboxTTS
        from faster_whisper import WhisperModel

        dev = req.get("device", "auto")
        if dev == "auto":
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        model = ChatterboxTTS.from_pretrained(device=dev)
        asr = WhisperModel("base.en", device="cpu", compute_type="int8")
        results = []
        for t in req["takes"]:
            best = None
            seed0 = int(t.get("seed", 0))
            tries = max(1, int(t.get("tries", 3)))
            for k in range(tries):
                torch.manual_seed(seed0 + k)
                wav = model.generate(
                    t["text"],
                    audio_prompt_path=t.get("ref"),
                    exaggeration=float(t.get("exaggeration", 0.5)),
                    cfg_weight=float(t.get("cfg", 0.5)),
                )
                a = wav.squeeze(0).detach().cpu().numpy().astype(np.float32)
                segs, _ = asr.transcribe(
                    _to16k(a, model.sr), beam_size=5, language="en", word_timestamps=True
                )
                segs = list(segs)
                heard = " ".join(s.text.strip() for s in segs)
                words = [
                    [w.word.strip(), round(w.start, 3), round(w.end, 3)] for s in segs for w in s.words or []
                ]
                e = wer(t["text"], heard)
                if best is None or e < best["wer"]:
                    best = {"a": a, "heard": heard, "wer": round(e, 3), "words": words, "tries": k + 1}
                if e <= float(t.get("max_wer", 0.1)):
                    break
            a = best.pop("a")
            _write(t["out"], a, model.sr)
            results.append({"path": t["out"], "sample_rate": model.sr, "duration": len(a) / model.sr, **best})
        out = {"ok": True, "device": dev, "results": results}
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    real_stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
