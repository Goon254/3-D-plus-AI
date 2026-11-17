"""Eye and coat test for the cast: are the eyes seated in their sockets, the brows and lids on the skin, and
the coat patterns pinned to it while the rig walks?

    python scripts/creature_eye_test.py --out output/eye-tests            # all five
    python scripts/creature_eye_test.py zebra meerkat --no-render         # measure only

Per species: the creature stands, then walks (neck, body and legs deform), with blinks and an expression
track that moves the brows and lids. ``animatica.creatures.qa`` measures the deformed meshes every 6th frame
(eye embed and drift, brow/lid gap, coat-texture drift) and two 3/4 head close-ups are rendered (standing,
mid-stride) on OptiX. Writes ``eye_report.json`` and ``eye_sheet.jpg`` (one row per species).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from creature_walk_test import set_ops  # noqa: E402

from animatica.core.engine import BlenderSession  # noqa: E402
from animatica.creatures.build import build_creature  # noqa: E402
from animatica.creatures.face import BROW_COLOR, face_keys, face_ops, refresh_rest  # noqa: E402
from animatica.creatures.gait import GAITS, Waypoint  # noqa: E402
from animatica.creatures.perform import walk_keys  # noqa: E402
from animatica.creatures.qa import rig_checks, rig_probe  # noqa: E402
from animatica.creatures.species import SPECIES  # noqa: E402

TRACK = [(0.0, "neutral"), (0.8, "surprised"), (1.8, "sad"), (2.8, "happy")]


def run(eng: BlenderSession, bid: str, ops: list[dict]) -> dict:
    r = eng.run_batch({"batch_id": bid, "ops": ops})
    if not r.ok:
        raise SystemExit(json.dumps({"batch": bid, "errors": r.errors[:6]}, indent=1))
    if r.warnings:
        print(json.dumps({"batch": bid, "warnings": r.warnings[:4]}))
    return r.data


def one(species: str, out: Path, fps: int, render: bool) -> dict:
    sp = SPECIES[species]
    d = out / species
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    yaw = 30.0
    ops, meta = build_creature(species, sp, at=(0.0, 0.0), yaw=yaw)
    fops, face = face_ops(species, sp, meta.root, meta.rig, BROW_COLOR[species])
    gait = GAITS[species]["walk"]
    stand, walk = 1.2, 2.6
    dist = gait.nominal_speed(meta.leg) * walk
    seconds = stand + walk
    pts = [Waypoint(0.0, 0.0, 0.0), Waypoint(stand, 0.0, 0.0), Waypoint(seconds, dist * 0.5, -dist * 0.87)]
    n = int(round(seconds * fps)) + 1
    keys, _plan = walk_keys(meta, gait, pts, fps, 1, seed=5, yaw0=yaw)
    scale = max(meta.length, meta.head_height) / 1.6
    with BlenderSession(workdir=d) as eng:
        run(eng, "set", set_ops(scale, max(meta.length, meta.head_height)))
        run(eng, "creature", ops + fops)
        q = run(
            eng,
            "q",
            [{"op": "query", "ids": [b["id"] for b in face["brows"].values()], "fields": ["transform"]}],
        )
        refresh_rest(face, q["objects"])
        run(
            eng,
            "anim",
            keys
            + face_keys(face, TRACK, None, fps, 1, n)
            + [{"op": "set_frame_range", "start": 1, "end": n, "fps": fps}],
        )
        frames = list(range(1, n + 1, 6))
        rep = run(eng, "probe", [rig_probe(meta, frames)])["inspect"]
        issues, summary = rig_checks(rep, species)
        stills = []
        if render:
            fw = int((stand + walk * 0.6) * fps)
            for tag, f in (("stand", int(stand * fps * 0.6)), ("walk", fw), ("body", fw)):
                m = run(
                    eng,
                    f"m{tag}",
                    [
                        {
                            "op": "inspect",
                            "subjects": [meta.root],
                            "frames": [f],
                            "bone_tails": [f"{meta.rig}:head"],
                        }
                    ],
                )
                fr_ = m["inspect"]["frames"][str(f)]
                head = fr_["bone_tails"][f"{meta.rig}:head"]
                size = max(sp.head_size) * 2.4
                cam = [head[0] + size * 0.9, head[1] - size * 1.5, head[2] + size * 0.15]
                if tag == "body":  # side-on, mid-stride: proportions and the coat on the move
                    head = fr_["subjects"][meta.root]["center"]
                    dist = max(meta.length, meta.head_height) * 2.3
                    cam = [head[0] + dist * 0.87, head[1] + dist * 0.5, head[2] + dist * 0.12]
                run(
                    eng,
                    f"cam{tag}",
                    [
                        {"op": "create_empty", "id": f"aim_{tag}", "location": [round(v, 3) for v in head]},
                        {
                            "op": "add_camera",
                            "id": f"cam_{tag}",
                            "location": [round(v, 3) for v in cam],
                            "lens": 60,
                            "look_at": f"aim_{tag}",
                        },
                        {"op": "set_camera_active", "id": f"cam_{tag}"},
                        {
                            "op": "set_render",
                            "engine": "cycles",
                            "resolution": [640, 400],
                            "samples": 24,
                            "device": "optix",
                            "look": "AgX - Medium High Contrast",
                        },
                        {"op": "render_final", "output_dir": str(d / tag), "frame_start": f, "frame_end": f},
                    ],
                )
                stills.append(str(next((d / tag).glob("*.png"))))
            run(eng, "save", [{"op": "save", "path": str(d / f"{species}_eyes.blend")}])
    res = {"species": species, "issues": [i.__dict__ for i in issues], **summary, "stills": stills}
    print(json.dumps({k: v for k, v in res.items() if k != "stills"}, indent=1))
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("species", nargs="*", default=["elephant", "giraffe", "zebra", "meerkat", "tortoise"])
    ap.add_argument("--out", default=str(ROOT / "output" / "eye-tests"))
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = [one(s, out, a.fps, not a.no_render) for s in a.species]
    (out / "eye_report.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    if not a.no_render:
        inputs, rows = [], []
        for i, r in enumerate(results):
            for s in r["stills"]:
                inputs += ["-i", s]
            rows.append(f"[{3 * i}][{3 * i + 1}][{3 * i + 2}]hstack=3[r{i}]")
        stack = (
            "".join(f"[r{i}]" for i in range(len(results))) + f"vstack={len(results)}"
            if len(results) > 1
            else "[r0]copy"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                *inputs,
                "-filter_complex",
                ";".join(rows) + ";" + stack,
                "-q:v",
                "3",
                str(out / "eye_sheet.jpg"),
            ],
            check=True,
        )
    bad = [i for r in results for i in r["issues"] if i["severity"] == "error"]
    print(f"{len(bad)} errors")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
