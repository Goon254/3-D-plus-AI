"""Face test: a cast member says a line in a 3/4 close-up, with Rhubarb lip sync and an expression track.

    python scripts/creature_face_test.py elephant --out output/face-tests

Kokoro voice per character (stock voices only), Rhubarb visemes -> mouth shape keys, expression track ->
brows + smile/frown, idle layers (breathing, blinks, ear/tail/trunk) from the gait module while standing.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from creature_walk_test import set_ops  # noqa: E402

from animatica.audio import lipsync, tts  # noqa: E402
from animatica.core.engine import BlenderSession  # noqa: E402
from animatica.creatures.build import build_creature  # noqa: E402
from animatica.creatures.face import BROW_COLOR, face_keys, face_ops, refresh_rest  # noqa: E402
from animatica.creatures.gait import GAITS, Waypoint  # noqa: E402
from animatica.creatures.perform import walk_keys  # noqa: E402
from animatica.creatures.species import SPECIES  # noqa: E402

# lines from films/savannah/04_screenplay.md, with the emotional beats as an expression track
CAST = {
    "elephant": (
        "Tembo",
        "Then I'll find it. For everyone!",
        tts.VoiceSpec(engine="kokoro", voice="am_puck", pitch=1.12, rate=1.0),
        [(0.0, "worried"), (0.9, "determined"), (2.4, "happy")],
    ),
    "zebra": (
        "Zuri",
        "I thought fastest was best. I'm sorry.",
        tts.VoiceSpec(engine="kokoro", voice="af_bella", pitch=1.08, rate=1.06),
        [(0.0, "proud"), (1.4, "sad")],
    ),
    "meerkat": (
        "Kiki",
        "Danger! Oh. It's a rock.",
        tts.VoiceSpec(engine="kokoro", voice="af_sky", pitch=1.22, rate=1.12),
        [(0.0, "scared"), (1.1, "surprised"), (1.8, "happy")],
    ),
    "giraffe": (
        "Neema",
        "There! I see her stripes!",
        tts.VoiceSpec(engine="kokoro", voice="af_nicole", pitch=1.04, rate=0.98),
        [(0.0, "curious"), (0.6, "surprised"), (1.3, "happy")],
    ),
    "tortoise": (
        "Bibi Kobe",
        "When you walk slowly, you learn to look up.",
        tts.VoiceSpec(engine="kokoro", voice="bf_emma", pitch=0.86, rate=0.84),
        [(0.0, "neutral"), (1.2, "happy")],
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("species", choices=sorted(CAST))
    ap.add_argument("--out", default="output/face-tests")
    ap.add_argument("--fps", type=int, default=24)
    a = ap.parse_args()
    name, line, voice, track = CAST[a.species]
    sp = SPECIES[a.species]
    out = Path(a.out).resolve() / a.species
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    wav = out / "line.wav"
    info = tts.synthesize(line, wav, voice)
    cues, engine = lipsync.lipsync(wav, line)
    lead, tail = 0.6, 1.0
    seconds = lead + info["duration"] + tail
    yaw = 30.0  # three-quarter toward the camera (rest faces -Y, the camera's side)
    ops, meta = build_creature(a.species, sp, at=(0.0, 0.0), yaw=yaw)
    fops, face = face_ops(a.species, sp, meta.root, meta.rig, BROW_COLOR[a.species])
    n = int(round(seconds * a.fps)) + 1
    still = [Waypoint(0.0, 0.0, 0.0), Waypoint(seconds, 0.0, 0.0)]
    keys, plan = walk_keys(meta, GAITS[a.species]["walk"], still, a.fps, 1, seed=5, yaw0=yaw)
    scene = set_ops(max(meta.length, meta.head_height) / 1.6, max(meta.length, meta.head_height)) + [
        {"op": "set_frame_range", "start": 1, "end": n, "fps": a.fps},
    ]
    with BlenderSession(workdir=out) as eng:
        for bid, batch in (("set", scene), ("creature", ops + fops)):
            r = eng.run_batch({"batch_id": bid, "ops": batch})
            if not r.ok:
                print(json.dumps({"batch": bid, "errors": r.errors[:5]}, indent=1))
                return 1
            if r.warnings:
                print(json.dumps({"batch": bid, "warnings": r.warnings[:5]}))
        q = eng.run_batch(
            {
                "batch_id": "q",
                "ops": [
                    {"op": "query", "ids": [b["id"] for b in face["brows"].values()], "fields": ["transform"]}
                ],
            }
        )
        refresh_rest(face, q.data["objects"])
        fkeys = face_keys(face, [(t + lead, e) for t, e in track], cues, a.fps, 1, n, line_start=lead)
        r = eng.run_batch({"batch_id": "anim", "ops": keys + fkeys})
        if not r.ok:
            print(json.dumps({"batch": "anim", "errors": r.errors[:5]}, indent=1))
            return 1
        # camera: a close-up on where the head really is (measured on the posed rig; the meerkat stands up)
        mid = n // 2
        m = eng.run_batch(
            {
                "batch_id": "m",
                "ops": [
                    {
                        "op": "inspect",
                        "subjects": [meta.root],
                        "frames": [mid],
                        "bone_tails": [f"{meta.rig}:head"],
                    }
                ],
            }
        )
        head = m.data["inspect"]["frames"][str(mid)]["bone_tails"][f"{meta.rig}:head"]
        size = max(sp.head_size) * (3.2 if sp.name != "giraffe" else 3.6)
        cam = [head[0] + size * 0.55, head[1] - size * 1.7, head[2] - size * 0.05]
        eng.run_batch(
            {
                "batch_id": "cam",
                "ops": [
                    {"op": "create_empty", "id": "cam_aim", "location": [round(v, 3) for v in head]},
                    {
                        "op": "add_camera",
                        "id": "cam",
                        "location": [round(v, 3) for v in cam],
                        "lens": 55,
                        "look_at": "cam_aim",
                    },
                    {"op": "set_camera_active", "id": "cam", "frame": 1},
                ],
            }
        )
        eng.run_batch(
            {
                "batch_id": "rs",
                "ops": [
                    {
                        "op": "set_render",
                        "engine": "cycles",
                        "resolution": [960, 540],
                        "samples": 16,
                        "fps": a.fps,
                        "device": "optix",
                        "look": "AgX - Medium High Contrast",
                    },
                    {"op": "save", "path": str(out / f"{a.species}_face.blend")},
                ],
            }
        )
        r = eng.run_batch(
            {"batch_id": "render", "ops": [{"op": "render_final", "output_dir": str(out / "frames")}]}
        )
        if not r.ok:
            print(r.errors)
            return 1
    mp4 = out / f"{a.species}_face.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-framerate",
            str(a.fps),
            "-i",
            str(out / "frames" / "frame_%04d.png"),
            "-itsoffset",
            str(lead),
            "-i",
            str(wav),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
    )
    report = {
        "species": a.species,
        "character": name,
        "line": line,
        "voice": voice.voice,
        "lipsync": engine,
        "cues": len(cues),
        "seconds": round(seconds, 2),
        "render_s": r.data.get("render_seconds"),
    }
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
