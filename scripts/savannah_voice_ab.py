"""Voice A/B reel: the first casting vs the new one, then Kokoro vs a trial engine (Chatterbox) on 3 lines.

    python scripts/savannah_voice_ab.py --out output/voice-ab

* **Part 1, before/after**, per character: a spoken slate ("Tembo, before."), the character's two sample lines
  in the first casting (one stock voice, large pitch shift, flat delivery, dry), then "Tembo, after." and the
  same lines in the new casting (a two-voice blend, shift within +-2 semitones, mood pace, pauses, breaths,
  emphasis, placed outdoors).
* **Part 2, engine test**: three lines in the new Kokoro casting and in Chatterbox (MIT; see
  ``scripts/tts_trial_worker.py``), conditioned on the same character's Kokoro take so the voices match. Both
  are placed outdoors the same way.

Every take is matched to the same RMS level before it goes in the reel (louder always sounds "better"), and
every take is transcribed by faster-whisper; ``voice_ab.json`` lists the word error rates and the timestamps of
each section. Writes ``voices_ab.m4a`` (AAC, -16 LUFS).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animatica.audio import delivery, tts, voice_fx  # noqa: E402

SR = tts.SAMPLE_RATE
TRIAL_PY = Path(
    os.environ.get(
        "ANIMATICA_TRIAL_PYTHON",
        Path.home() / ".cache" / "animatica" / "chatterbox-venv" / "Scripts" / "python.exe",
    )
)
ENGINE_LINES = [  # (character, line, mood, chatterbox exaggeration)
    (
        "narrator",
        "Far away, where the grass grows golden and the sky goes on forever, the rains were late.",
        None,
        0.5,
    ),
    ("kiki", "She's gone. Nobody panic. EVERYBODY PANIC!", "scared", 0.8),
    ("bibi_kobe", "When you walk *slowly*, you learn to look up.", "wise", 0.45),
]
NAMES = {
    "narrator": "Narrator",
    "tembo": "Tembo",
    "zuri": "Zuri",
    "kiki": "Kiki",
    "neema": "Neema",
    "bibi_kobe": "Bibi Kobe",
}
TARGET_RMS_DB = -21.0


def level(a: np.ndarray) -> np.ndarray:
    """Match RMS over the voiced part (frames above -45 dBFS) to TARGET_RMS_DB."""
    b = int(0.02 * SR)
    fr = a[: len(a) // b * b].reshape(-1, b)
    r = np.sqrt(np.mean(fr**2, axis=1))
    v = fr[r > 10 ** (-45 / 20)]
    rms = float(np.sqrt(np.mean(v**2))) if v.size else 1e-3
    return (a * (10 ** (TARGET_RMS_DB / 20) / max(rms, 1e-6))).astype(np.float32)


def wer(ref: str, hyp: str) -> float:
    norm = lambda s: re.sub(r"[^a-z' ]", " ", s.lower().replace("-", " ")).split()  # noqa: E731
    r, h = norm(ref), norm(hyp)
    d = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        prev, d[0] = d.copy(), i
        for j in range(1, len(h) + 1):
            d[j] = min(prev[j] + 1, d[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
    return round(float(d[len(h)]) / max(1, len(r)), 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "output" / "voice-ab"))
    ap.add_argument("--no-trial", action="store_true", help="skip the Chatterbox part")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    (out / "takes").mkdir(parents=True, exist_ok=True)
    d = json.loads((ROOT / "films" / "savannah" / "06_voices.json").read_text(encoding="utf-8"))
    cast, prev = d["cast"], d["previous"]
    slate_spec = tts.VoiceSpec(engine="kokoro", voice="af_heart", natural=False)

    reel: list[np.ndarray] = []
    t = 0.0
    index: list[dict] = []
    takes: list[dict] = []  # every take, for ASR

    def add(x: np.ndarray, gap: float = 0.5) -> float:
        nonlocal t
        start = t
        reel.extend([x, np.zeros(int(gap * SR), np.float32)])
        t += (len(x) + int(gap * SR)) / SR
        return start

    def slate(text: str) -> None:
        p = out / "takes" / f"slate_{len(index)}.wav"
        x, _ = tts.read_wav(tts.synthesize(text, p, slate_spec)["path"])
        add(level(x) * 0.6, 0.35)

    def take(name: str, text: str, mood: str | None, new: bool, tag: str) -> Path:
        if new:
            c = cast[name]
            spec = tts.VoiceSpec(
                engine="kokoro", voice=c["voice"], pitch=c["pitch"], rate=c["rate"], mood=mood
            )
        else:
            c = prev[name]
            spec = tts.VoiceSpec(
                engine="kokoro", voice=c["voice"], pitch=c["pitch"], rate=c["rate"], natural=False
            )
        p = out / "takes" / f"{tag}.wav"
        tts.synthesize(text if new else delivery.plain(text), p, spec)
        return p

    def placed(p: Path, seed: int) -> np.ndarray:
        x, _ = tts.read_wav(p)
        return voice_fx.place_outdoor(x, SR, seed=seed)

    # ---- part 1: before / after
    add(np.zeros(int(0.3 * SR), np.float32), 0)
    for name, c in cast.items():
        lines = [(s, None) if isinstance(s, str) else tuple(s) for s in c["samples"]]
        for new in (False, True):
            tag = "after" if new else "before"
            slate(f"{NAMES[name]}, {tag}.")
            start = t
            for i, (text, mood) in enumerate(lines):
                p = take(name, text, mood, new, f"{name}_{tag}_{i}")
                x = placed(p, i) if new else tts.read_wav(p)[0]
                add(level(x), 0.45)
                takes.append(
                    {
                        "part": "casting",
                        "who": name,
                        "version": tag,
                        "text": delivery.plain(text),
                        "wav": str(p),
                    }
                )
            index.append(
                {
                    "part": "casting",
                    "who": name,
                    "version": tag,
                    "start_s": round(start, 2),
                    "end_s": round(t, 2),
                    "voice": c["voice"] if new else prev[name]["voice"],
                    "shift_semitones": round(12 * np.log2((c if new else prev[name])["pitch"]), 2),
                }
            )
        add(np.zeros(int(0.4 * SR), np.float32), 0)

    # ---- part 2: engine test
    trial = not a.no_trial and TRIAL_PY.exists()
    if trial:
        kok = {}
        for i, (name, text, mood, _) in enumerate(ENGINE_LINES):
            kok[i] = take(name, text, mood, True, f"engine_kokoro_{i}")
        # reference: the character's own (dry) Kokoro take of a *different* line, so Chatterbox copies the voice,
        # not the delivery of the line under test
        reqs = []
        for i, (name, text, _mood, ex) in enumerate(ENGINE_LINES):
            other = [
                s
                for s in cast[name]["samples"]
                if delivery.plain(s[0] if isinstance(s, list) else s) != delivery.plain(text)
            ]
            ref = take(
                name, other[0][0] if isinstance(other[0], list) else other[0], None, True, f"engine_ref_{i}"
            )
            reqs.append(
                {
                    "text": delivery.plain(text).replace("EVERYBODY PANIC", "Everybody panic"),
                    "out": str(out / "takes" / f"engine_chatterbox_{i}.wav"),
                    "ref": str(ref),
                    "exaggeration": ex,
                    "cfg": 0.4 if ex >= 0.7 else 0.5,
                }
            )
        r = subprocess.run(
            [str(TRIAL_PY), "-I", str(ROOT / "scripts" / "tts_trial_worker.py")],
            input=json.dumps({"chatterbox": reqs}),
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if r.returncode != 0:
            raise SystemExit(f"chatterbox failed: {r.stderr[-600:]}")
        slate("Engine test. Kokoro, then Chatterbox.")
        for i, (name, text, _mood, _) in enumerate(ENGINE_LINES):
            for eng, p in (("kokoro", kok[i]), ("chatterbox", Path(reqs[i]["out"]))):
                slate(f"{eng.capitalize()}.")
                x, sr = tts.read_wav(p)
                x = voice_fx.resample(x, sr, SR) if sr != SR else x
                start = add(level(voice_fx.place_outdoor(x, SR, seed=i)), 0.6)
                index.append(
                    {
                        "part": "engine",
                        "who": name,
                        "version": eng,
                        "start_s": round(start, 2),
                        "end_s": round(t, 2),
                    }
                )
                takes.append(
                    {
                        "part": "engine",
                        "who": name,
                        "version": eng,
                        "text": delivery.plain(text),
                        "wav": str(p),
                    }
                )

    # ---- intelligibility: faster-whisper round trip on every take
    if TRIAL_PY.exists():
        r = subprocess.run(
            [str(TRIAL_PY), "-I", str(ROOT / "scripts" / "tts_trial_worker.py")],
            input=json.dumps({"asr": [tk["wav"] for tk in takes]}),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        heard = json.loads(r.stdout).get("asr", {}) if r.returncode == 0 else {}
        for tk in takes:
            tk["heard"] = heard.get(tk["wav"], "")
            tk["wer"] = wer(tk["text"], tk["heard"]) if tk["heard"] else None

    mix = np.concatenate(reel)
    mix = mix / max(1.0, float(np.abs(mix).max()) / 0.95)
    wav = out / "voices_ab.wav"
    tts.write_wav(wav, mix, SR)
    m4a = out / "voices_ab.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(wav),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "48000",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            str(m4a),
        ],
        check=True,
    )

    def mean_wer(part: str, version: str) -> float | None:
        w = [
            tk["wer"]
            for tk in takes
            if tk["part"] == part and tk["version"] == version and tk.get("wer") is not None
        ]
        return round(float(np.mean(w)), 3) if w else None

    rep = {
        "m4a": str(m4a),
        "seconds": round(len(mix) / SR, 1),
        "wer": {
            k: mean_wer(*k.split(":"))
            for k in ("casting:before", "casting:after", "engine:kokoro", "engine:chatterbox")
        },
        "sections": index,
        "takes": [{k: v for k, v in tk.items() if k != "wav"} for tk in takes],
    }
    (out / "voice_ab.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({"m4a": rep["m4a"], "seconds": rep["seconds"], "wer": rep["wer"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
