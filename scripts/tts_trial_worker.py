"""Trial-engine worker for voice A/B tests: Chatterbox TTS (MIT) and a faster-whisper (MIT) intelligibility check.

Runs in its own venv (torch is not a project dependency):

    py -3.13 -m venv ~/.cache/animatica/chatterbox-venv
    ~/.cache/animatica/chatterbox-venv/Scripts/python -m pip install torch==2.6.0 torchaudio==2.6.0 \\
        --index-url https://download.pytorch.org/whl/cpu
    ~/.cache/animatica/chatterbox-venv/Scripts/python -m pip install chatterbox-tts faster-whisper

JSON on stdin, JSON on stdout:

    {"chatterbox": [{"text", "out", "ref"?, "exaggeration"?, "cfg"?}, ...]}
    {"asr": ["a.wav", ...]}  ->  {"asr": {"a.wav": "transcript", ...}}

``ref`` is a short reference clip that steers the speaker. The A/B passes one of our own Kokoro takes
(a synthetic stock voice, Apache-2.0), never a recording of a real person: voice cloning of people
stays behind the consent hook (PLAN section 7). Chatterbox output carries its built-in Perth watermark.
"""

from __future__ import annotations

import json
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


def chatterbox(takes: list[dict]) -> list[dict]:
    import torch
    from chatterbox.tts import ChatterboxTTS

    torch.manual_seed(0)
    model = ChatterboxTTS.from_pretrained(device="cpu")
    out = []
    for t in takes:
        wav = model.generate(
            t["text"],
            audio_prompt_path=t.get("ref"),
            exaggeration=float(t.get("exaggeration", 0.5)),
            cfg_weight=float(t.get("cfg", 0.5)),
        )
        _write(t["out"], wav.squeeze(0).numpy(), model.sr)
        out.append({"path": t["out"], "sample_rate": model.sr, "duration": wav.shape[-1] / model.sr})
    return out


def asr(paths: list[str]) -> dict[str, str]:
    from faster_whisper import WhisperModel

    m = WhisperModel("base.en", device="cpu", compute_type="int8")
    res = {}
    for p in paths:
        with wave.open(p) as w:  # decode ourselves: the PyAV path in faster-whisper breaks on new av releases
            sr, raw = w.getframerate(), w.readframes(w.getnframes())
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
        x = np.interp(np.arange(0, len(x), sr / 16000), np.arange(len(x)), x).astype(np.float32)
        segs, _ = m.transcribe(x, beam_size=5, language="en")
        res[p] = " ".join(s.text.strip() for s in segs)
    return res


def main() -> None:
    req = json.loads(sys.stdin.read())
    out: dict = {}
    if req.get("chatterbox"):
        out["chatterbox"] = chatterbox(req["chatterbox"])
    if req.get("asr"):
        out["asr"] = asr(req["asr"])
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
