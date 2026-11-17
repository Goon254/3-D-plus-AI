# SPDX-License-Identifier: GPL-3.0-or-later
"""Animatica TTS worker — runs text-to-speech engines in their own process.

Kept separate from the Apache-2.0 core because the engines pull in GPL code (espeak-ng via
kokoro-onnx's phonemizer; Piper is GPL-3.0-or-later since 2025). The core talks to this worker only
through a JSON contract on stdin/stdout:

    request : {"text": str, "engine": "kokoro"|"piper", "voice": str, "speed": float, "out": "path.wav",
               "model_dir": str}
              kokoro also takes "phonemes" (IPA) instead of text, a blend voice "a:0.6+b:0.4", and
              "batch": [take, ...] (one model load; a take {"phonemize": text} returns its phonemes)
    response: {"ok": true, "path": str, "sample_rate": int, "duration": float, "engine": str}
              {"ok": false, "error": str}

Voices: Kokoro-82M (Apache-2.0 weights). Piper fallback only with voices whose training data is
CC0/CC-BY (see THIRD_PARTY.md). No voice cloning.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import wave


def _write_wav(path: str, samples, sr: int) -> None:
    import numpy as np

    a = np.clip(np.asarray(samples, dtype="float32"), -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((a * 32767).astype("<i2").tobytes())


_KOKORO = {}


def _kokoro_model(d: str):
    from kokoro_onnx import Kokoro

    if d not in _KOKORO:
        _KOKORO[d] = Kokoro(os.path.join(d, "kokoro-v1.0.onnx"), os.path.join(d, "voices-v1.0.bin"))
    return _KOKORO[d]


def kokoro_style(k, voice: str):
    """A stock voice id, or a blend of stock voices' style vectors: ``"af_bella:0.6+af_jessica:0.4"``
    (weights are normalised). Blending mixes two existing voices; it does not clone anyone."""
    if "+" not in voice and ":" not in voice:
        return voice
    parts = [p.split(":") for p in voice.split("+")]
    ws = [float(p[1]) if len(p) > 1 else 1.0 for p in parts]
    tot = sum(ws) or 1.0
    st = sum((w / tot) * k.get_voice_style(p[0]) for p, w in zip(parts, ws))
    return st.astype("float32")


def kokoro(req: dict) -> dict:
    """One take, or ``batch``: a list of takes rendered with one model load. A take speaks ``text`` or, with
    ``phonemes``, a phoneme string (Kokoro's IPA vocabulary: stress marks, length marks)."""
    k = _kokoro_model(req["model_dir"])
    takes = req.get("batch") or [req]
    outs = []
    for t in takes:
        style = kokoro_style(k, t.get("voice") or req.get("voice") or "af_heart")
        if t.get("phonemize"):
            outs.append({"phonemes": k.tokenizer.phonemize(t["phonemize"], t.get("lang", "en-us"))})
            continue
        ph = t.get("phonemes")
        samples, sr = k.create(
            ph if ph else t["text"],
            voice=style,
            speed=float(t.get("speed", req.get("speed", 1.0))),
            lang=t.get("lang", "en-us"),
            is_phonemes=bool(ph),
        )
        _write_wav(t["out"], samples, sr)
        outs.append({"path": t["out"], "sample_rate": sr, "duration": len(samples) / sr})
    if req.get("batch"):
        return {"ok": True, "engine": "kokoro", "results": outs}
    return {"ok": True, "engine": "kokoro", **outs[0]}


def piper(req: dict) -> dict:
    model = req["voice"]
    cmd = [sys.executable, "-m", "piper", "-m", model, "-f", req["out"]]
    if req.get("speaker") is not None:
        cmd += ["-s", str(req["speaker"])]
    if req.get("speed", 1.0) != 1.0:
        cmd += ["--length-scale", f"{1.0 / float(req['speed']):.3f}"]
    subprocess.run(cmd, input=req["text"], text=True, check=True, capture_output=True, timeout=300)
    with wave.open(req["out"]) as w:
        sr, n = w.getframerate(), w.getnframes()
    return {"ok": True, "path": req["out"], "sample_rate": sr, "duration": n / sr, "engine": "piper"}


def main() -> None:
    req = json.loads(sys.stdin.read())
    try:
        out = {"kokoro": kokoro, "piper": piper}[req["engine"]](req)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
