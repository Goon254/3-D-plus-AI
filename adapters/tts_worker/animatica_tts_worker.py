# SPDX-License-Identifier: GPL-3.0-or-later
"""Animatica TTS worker — runs text-to-speech engines in their own process.

Kept separate from the Apache-2.0 core because the engines pull in GPL code (espeak-ng via
kokoro-onnx's phonemizer; Piper is GPL-3.0-or-later since 2025). The core talks to this worker only
through a JSON contract on stdin/stdout:

    request : {"text": str, "engine": "kokoro"|"piper", "voice": str, "speed": float, "out": "path.wav",
               "model_dir": str}
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


def kokoro(req: dict) -> dict:
    from kokoro_onnx import Kokoro

    d = req["model_dir"]
    k = Kokoro(os.path.join(d, "kokoro-v1.0.onnx"), os.path.join(d, "voices-v1.0.bin"))
    samples, sr = k.create(req["text"], voice=req.get("voice") or "af_heart", speed=float(req.get("speed", 1.0)),
                           lang=req.get("lang", "en-us"))
    _write_wav(req["out"], samples, sr)
    return {"ok": True, "path": req["out"], "sample_rate": sr, "duration": len(samples) / sr, "engine": "kokoro"}


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
