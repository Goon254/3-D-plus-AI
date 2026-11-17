"""Voice casting check: render each character's sample lines, measure the voices, check they are distinct.

    python scripts/savannah_voices.py --out output/savannah-voices

Writes one WAV per line, a casting reel (``voices.wav``, each character in turn), and ``voices.json`` with
median pitch (F0, autocorrelation over voiced frames) and spectral centroid per character. Two characters
count as distinct if their median F0 differs by >= 8 % or their centroid by >= 10 %.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animatica.audio import tts  # noqa: E402
from animatica.audio.voice_fx import f0_median  # noqa: E402


def centroid(a: np.ndarray, sr: int) -> float:
    p = np.abs(np.fft.rfft(a)) ** 2
    f = np.fft.rfftfreq(len(a), 1 / sr)
    return float((p * f).sum() / max(p.sum(), 1e-12))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cast", default=str(ROOT / "films" / "savannah" / "06_voices.json"))
    ap.add_argument("--out", default=str(ROOT / "output" / "savannah-voices"))
    a = ap.parse_args()
    cast = json.loads(Path(a.cast).read_text(encoding="utf-8"))["cast"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stats: dict[str, dict] = {}
    reel: list[np.ndarray] = []
    sr = tts.SAMPLE_RATE
    for name, c in cast.items():
        audio = []
        for i, sample in enumerate(c["samples"]):
            line, mood = (sample, None) if isinstance(sample, str) else sample
            spec = tts.VoiceSpec(
                engine="kokoro", voice=c["voice"], pitch=c["pitch"], rate=c["rate"], mood=mood
            )
            info = tts.synthesize(line, out / f"{name}_{i}.wav", spec)
            x, sr = tts.read_wav(info["path"])
            audio.append(x)
            reel += [x, np.zeros(int(0.45 * sr), np.float32)]
        reel.append(np.zeros(int(0.5 * sr), np.float32))
        x = np.concatenate(audio)
        stats[name] = {
            "voice": c["voice"],
            "shift_semitones": round(12 * np.log2(c["pitch"]), 2),
            "f0_hz": round(f0_median(x, sr), 1),
            "centroid_hz": round(centroid(x, sr)),
        }
    names = list(stats)
    clashes = []
    for i, p in enumerate(names):
        for q in names[i + 1 :]:
            a0, b0 = stats[p]["f0_hz"], stats[q]["f0_hz"]
            ac, bc = stats[p]["centroid_hz"], stats[q]["centroid_hz"]
            df0 = abs(a0 - b0) / max(min(a0, b0), 1)
            dc = abs(ac - bc) / max(min(ac, bc), 1)
            if df0 < 0.08 and dc < 0.10:
                clashes.append((p, q, round(df0, 3), round(dc, 3)))
    import wave

    mix = np.concatenate(reel)
    with wave.open(str(out / "voices.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())
    rep = {"voices": stats, "clashes": clashes}
    (out / "voices.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for n in names:
        s = stats[n]
        print(f"{n:10s} {s['voice']:10s} F0 {s['f0_hz']:6.1f} Hz   centroid {s['centroid_hz']:5d} Hz")
    print("clashes:", clashes or "none")
    return 0 if not clashes else 1


if __name__ == "__main__":
    raise SystemExit(main())
