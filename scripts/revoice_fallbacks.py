"""Re-voice the savannah lines that fell back to Kokoro, with Chatterbox, until they pass.

    python scripts/revoice_fallbacks.py              # every line whose cached take is a Kokoro fallback
    python scripts/revoice_fallbacks.py --rounds 6   # more fresh seeds per line

A line falls back to Kokoro when Chatterbox's best of three seeds is misheard by Whisper (word error rate over
``tts.CHATTERBOX_FALLBACK_WER``) or drifts out of the character's voice (median pitch more than
``tts.CHATTERBOX_MAX_DRIFT_ST`` from the character's reference take). The owner heard the difference in the
animatic (11-18). This script retries only those lines, each round with fresh seeds (and, from the third round
on, a little less exaggeration, which steadies the pitch), and writes a passing take into the line cache under
the same key the scene uses, so ``savannah_scene.py`` picks it up and every other cached take stays as it is.
A line that never passes keeps its fallback and is reported.
"""

from __future__ import annotations

import argparse
import json
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animatica.audio import delivery as dl  # noqa: E402
from animatica.audio import tts  # noqa: E402
from animatica.production.scene import load_scenes  # noqa: E402

FILM = ROOT / "films" / "savannah"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--only", default="", help="comma-separated scene ids")
    a = ap.parse_args()
    casting = json.loads((FILM / "06_voices.json").read_text(encoding="utf-8"))
    cast, engine = casting["cast"], casting.get("engine", "kokoro")
    work = tts.lines_dir() / "revoice"
    work.mkdir(parents=True, exist_ok=True)
    todo = []
    for sid, spec in load_scenes(FILM / "07_scenes.json").items():
        if a.only and sid not in a.only.split(","):
            continue
        for i, ln in enumerate(spec.lines):
            c = cast[ln.who]
            voice = tts.VoiceSpec(
                engine=engine,
                voice=c["voice"],
                pitch=c["pitch"],
                rate=c["rate"],
                mood=ln.expr[0][1] if ln.expr else None,
                ref_text=c.get("ref_text"),
            )
            key = tts.cache_key(ln.text, voice, "chatterbox")
            meta = tts.lines_dir() / f"{key}.json"
            info = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None
            if info is None or info.get("fallback") or info.get("engine") != "chatterbox":
                todo.append((sid, i, ln, voice, key, (info or {}).get("fallback", "not voiced yet")))
    print(f"{len(todo)} line(s) to re-voice")
    for sid, i, ln, _v, _k, why in todo:
        print(f"  {sid} line {i} {ln.who}: {ln.text!r} ({why})")
    if not todo:
        return 0
    jobs = []
    for sid, i, ln, voice, key, _why in todo:
        ref_spec = tts.VoiceSpec(**{**voice.__dict__, "engine": "kokoro", "mood": None, "ref_text": None})
        ref_text = voice.ref_text or tts.DEFAULT_REF_TEXT
        ref = tts.synthesize(
            ref_text,
            tts.lines_dir() / "refs" / f"{tts.cache_key(ref_text, ref_spec, 'kokoro')}.wav",
            ref_spec,
        )["path"]
        spoken, _ = dl.spoken(ln.text)
        ex = tts.exaggeration_for(voice)
        jobs.append(
            {
                "sid": sid,
                "i": i,
                "ln": ln,
                "voice": voice,
                "key": key,
                "take": {
                    "text": spoken,
                    "out": str(work / f"{key}.cb.wav"),
                    "ref": ref,
                    "exaggeration": ex,
                    "cfg": 0.4 if ex >= 0.7 else 0.5,
                    "seed": zlib.crc32(ln.text.encode("utf-8")) % 1000,
                    "max_wer": tts.CHATTERBOX_MAX_WER,
                    "tries": 3,
                    "prompt": tts.asr_prompt(ln.text),
                },
                "done": None,
            }
        )
    for r in range(a.rounds):
        open_ = [j for j in jobs if j["done"] is None]
        if not open_:
            break
        takes = []
        for j in open_:
            t = dict(j["take"], seed=j["take"]["seed"] + 101 * (r + 1), tries=4)
            if r >= 2:  # calmer delivery: a steadier pitch
                t["exaggeration"] = max(0.3, j["take"]["exaggeration"] - 0.1 * (r - 1))
            takes.append(t)
        print(f"round {r + 1}: {len(takes)} line(s)", flush=True)
        got = tts._run_chatterbox(takes)
        for j, g, t in zip(open_, got, takes, strict=True):
            if "error" in g:
                print(f"  {j['sid']} line {j['i']}: worker error {g['error'][:120]}")
                continue
            drift = tts._drift_st(Path(t["out"]), Path(t["ref"]))
            ok = g["wer"] <= tts.CHATTERBOX_FALLBACK_WER and abs(drift) <= tts.CHATTERBOX_MAX_DRIFT_ST
            print(
                f"  {j['sid']} line {j['i']} {j['ln'].who}: wer {g['wer']} heard {g['heard']!r} drift {drift:+.1f} st -> {'PASS' if ok else 'retry'}"
            )
            if ok:
                out = work / f"{j['key']}.wav"
                dur = tts._chatterbox_post(
                    j["ln"].text, Path(t["out"]), out, j["voice"], g.get("words") or []
                )
                info = {
                    "path": str(out),
                    "engine": "chatterbox",
                    "duration": round(dur, 3),
                    "heard": g["heard"],
                    "wer": g["wer"],
                    "tries": g["tries"],
                    "pitch_drift_st": round(drift, 2),
                    "revoiced": {"round": r + 1, "seed": t["seed"], "exaggeration": t["exaggeration"]},
                }
                tts._to_cache(j["key"], info)
                j["done"] = info
    left = [j for j in jobs if j["done"] is None]
    for j in left:
        print(f"STILL KOKORO: {j['sid']} line {j['i']} {j['ln'].who}: {j['ln'].text!r}")
    print(f"re-voiced {len(jobs) - len(left)} of {len(jobs)}")
    return 1 if left else 0


if __name__ == "__main__":
    raise SystemExit(main())
