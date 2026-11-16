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


def f0_median(a: np.ndarray, sr: int) -> float:
    """Median F0 over voiced 40 ms frames with YIN (cumulative-mean-normalised difference; first dip below
    0.15), which avoids the octave jumps a plain autocorrelation peak makes on bright voices."""
    win, hop = int(0.04 * sr), int(0.01 * sr)
    lo, hi = int(sr / 600), int(sr / 70)
    vals = []
    for s0 in range(0, len(a) - win - hi, hop):
        x = a[s0 : s0 + win + hi].astype(np.float64)
        if np.sqrt(np.mean(x[:win] ** 2)) < 0.02:
            continue
        d = np.array([np.sum((x[:win] - x[tau : tau + win]) ** 2) for tau in range(hi)])
        cm = d.copy()
        cm[1:] = d[1:] * np.arange(1, hi) / np.maximum(np.cumsum(d[1:]), 1e-12)
        cm[0] = 1.0
        below = np.where(cm[lo:] < 0.15)[0]
        if not len(below):
            continue
        k = lo + below[0]
        while k + 1 < hi and cm[k + 1] < cm[k]:  # walk to the bottom of the dip
            k += 1
        vals.append(sr / k)
    return float(np.median(vals)) if vals else 0.0


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
        spec = tts.VoiceSpec(engine="kokoro", voice=c["voice"], pitch=c["pitch"], rate=c["rate"])
        audio = []
        for i, line in enumerate(c["samples"]):
            info = tts.synthesize(line, out / f"{name}_{i}.wav", spec)
            x, sr = tts.read_wav(info["path"])
            audio.append(x)
            reel += [x, np.zeros(int(0.45 * sr), np.float32)]
        reel.append(np.zeros(int(0.5 * sr), np.float32))
        x = np.concatenate(audio)
        stats[name] = {
            "voice": c["voice"],
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
