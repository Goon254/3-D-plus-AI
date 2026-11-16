"""Walk-test clip for one savannah species: idle -> walk across frame -> idle, rendered on the GPU.

    python scripts/creature_walk_test.py elephant --out output/walk-tests [--quality draft|final]

Also *measures* foot slide in the rendered rig: the world position of every foot bone tip (after IK) is
read each frame, and the worst drift while the planner says that foot is planted is reported.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animatica.core.engine import BlenderSession  # noqa: E402
from animatica.creatures.build import build_creature  # noqa: E402
from animatica.creatures.gait import GAITS, LEGS, Waypoint  # noqa: E402
from animatica.creatures.perform import walk_keys  # noqa: E402
from animatica.creatures.species import SPECIES  # noqa: E402

QUAL = {"draft": ((960, 540), 12), "final": ((1280, 720), 24)}


def set_ops(scale: float, length: float, seed: int = 3) -> list[dict]:
    rng = random.Random(seed)
    ops: list[dict] = [
        {"op": "create_primitive", "id": "ground", "shape": "plane", "size": [400, 400, 1]},
        {
            "op": "set_material",
            "targets": ["ground"],
            "material": {
                "base_color": "#B8975A",
                "roughness": 1.0,
                "specular": 0.1,
                "noise": 0.35,
                "noise_scale": 0.6,
                "grain": 0.35,
                "grain_scale": 18.0 / scale,
                "bump": 0.3,
                "fade_to": "#E9C48C",
                "fade_start": 12.0 * scale,
                "fade_end": 70.0 * scale,
            },
        },
        {"op": "set_world", "zenith": "#6E9BD1", "horizon": "#F2CF94", "glow": "#F7B977", "strength": 1.1},
        {
            "op": "add_light",
            "id": "sun",
            "light_type": "sun",
            "energy": 4.2,
            "color": "#FFE2B0",
            "rotation": [52, 0, 35],
            "size": 2.0,
        },
    ]
    ids = []
    for i in range(60):  # pebbles: fixed references on the ground, so any foot slide would show
        x, y = rng.uniform(-length * 2.2, length * 2.2), rng.uniform(-length * 0.6, length * 1.8)
        r = rng.uniform(0.008, 0.03) * scale * 3
        ids.append(f"pebble_{i}")
        ops.append(
            {
                "op": "create_primitive",
                "id": ids[-1],
                "shape": "ico_sphere",
                "radius": round(r, 4),
                "segments": 32,
                "scale": [1.3, 1.0, 0.55],
                "location": [round(x, 3), round(y, 3), round(r * 0.2, 4)],
                "smooth": True,
            }
        )
    ops.append(
        {"op": "set_material", "targets": ids, "material": {"base_color": "#6E6050", "roughness": 0.9}}
    )
    return ops


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("species", choices=sorted(SPECIES))
    ap.add_argument("--out", default="output/walk-tests")
    ap.add_argument("--quality", default="draft", choices=sorted(QUAL))
    ap.add_argument("--gait", default="walk")
    ap.add_argument("--fps", type=int, default=24)
    a = ap.parse_args()
    sp = SPECIES[a.species]
    gait = GAITS[a.species][a.gait]
    out = Path(a.out).resolve() / a.species
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    ops, meta = build_creature(a.species, sp, at=(0.0, 0.0), yaw=90.0)
    v = gait.nominal_speed(meta.leg)
    walk_s = 6.0
    dist = v * walk_s * 0.82  # eased start/stop: average speed is a bit below nominal
    x0 = -dist / 2
    pts = [
        Waypoint(0.0, x0, 0.0),
        Waypoint(1.2, x0, 0.0),
        Waypoint(1.2 + walk_s, x0 + dist, 0.0),
        Waypoint(8.7, x0 + dist, 0.0),
    ]
    ops[0]["location"][0] = x0  # start where the path starts
    for o in ops:
        if o.get("op") == "create_empty" and o["id"].startswith(f"{a.species}_ik_"):
            o["location"][0] += x0
    keys, plan = walk_keys(meta, gait, pts, a.fps, 1, seed=11)
    n = len(plan)
    scale = max(meta.length, meta.head_height) / 1.6  # framing scale relative to a ~1.6 m animal
    # camera: 3/4 side view from the camera's side (-Y), at about shoulder height, tracking with a lag
    size = max(meta.length, meta.head_height)
    aim_z = meta.head_height * 0.55
    if sp.default_pose == "sentinel":  # it stands up when it stops: frame the upright height too
        upright = meta.body_z + 0.75 * meta.length
        size = max(size, upright * 1.25)
        aim_z = upright * 0.5
    dist_cam = size * 1.9 + dist * 0.3
    cam_keys, aim_keys = [], []
    cx = x0
    for i, p in enumerate(plan):
        cx += (p.root[0] - cx) * 0.06  # lagging follow: the animal leads, the camera eases after it
        f = i + 1
        cam_keys.append(
            [
                f,
                [
                    round(cx + dist_cam * 0.38, 3),
                    round(-dist_cam, 3),
                    round(meta.body_z * 0.9 + size * 0.12, 3),
                ],
                "LINEAR",
            ]
        )
        aim_keys.append([f, [round(cx - 0.05 * size, 3), 0.0, round(aim_z, 3)], "LINEAR"])
    scene = set_ops(scale, size)
    scene += [
        {"op": "create_empty", "id": "cam_aim", "location": aim_keys[0][1]},
        {"op": "add_camera", "id": "cam", "location": cam_keys[0][1], "lens": 40, "look_at": "cam_aim"},
        {"op": "set_camera_active", "id": "cam", "frame": 1},
        {"op": "insert_keyframes", "target": "cam", "property": "location", "keys": cam_keys},
        {"op": "insert_keyframes", "target": "cam_aim", "property": "location", "keys": aim_keys},
        {"op": "set_frame_range", "start": 1, "end": n, "fps": a.fps},
    ]
    res_xy, samples = QUAL[a.quality]
    with BlenderSession(workdir=out) as eng:
        for bid, batch in (("set", scene), ("creature", ops), ("anim", keys)):
            r = eng.run_batch({"batch_id": bid, "ops": batch})
            if not r.ok:
                print(json.dumps({"batch": bid, "errors": r.errors[:5]}, indent=1))
                return 1
        # measure the rendered rig: foot bone tips after IK, every frame
        tails = [f"{meta.rig}:leg_{leg}_lo" for leg in LEGS]
        r = eng.run_batch(
            {
                "batch_id": "measure",
                "ops": [
                    {
                        "op": "inspect",
                        "subjects": [meta.root],
                        "frames": list(range(1, n + 1)),
                        "bone_tails": tails,
                    }
                ],
            }
        )
        fr = r.data["inspect"]["frames"]
        slide = 0.0
        reach = 0.0
        worst: dict = {}
        for leg in LEGS:
            ref = f"{meta.rig}:leg_{leg}_lo"
            for i in range(1, n):
                if plan[i - 1].stance[leg] and plan[i].stance[leg]:
                    p0, p1 = fr[str(i)]["bone_tails"][ref], fr[str(i + 1)]["bone_tails"][ref]
                    slide = max(slide, math.hypot(p1[0] - p0[0], p1[1] - p0[1]))
                tip = fr[str(i)]["bone_tails"][ref]
                want = plan[i - 1].feet[leg]
                miss = math.dist(tip, want)
                if miss > reach:
                    reach = miss
                    worst = {
                        "leg": leg,
                        "frame": i,
                        "stance": plan[i - 1].stance[leg],
                        "tip": tip,
                        "want": [round(c, 3) for c in want],
                    }
        report = {
            "species": a.species,
            "gait": a.gait,
            "frames": n,
            "leg_m": round(meta.leg, 3),
            "speed_mps": round(v, 3),
            "max_stance_slide_mm": round(slide * 1000, 2),
            "max_ik_miss_mm": round(reach * 1000, 2),
            "worst_miss": worst,
        }
        print(json.dumps(report))
        eng.run_batch(
            {
                "batch_id": "render-setup",
                "ops": [
                    {
                        "op": "set_render",
                        "engine": "cycles",
                        "resolution": list(res_xy),
                        "samples": samples,
                        "fps": a.fps,
                        "device": "optix",
                        "look": "AgX - Medium High Contrast",
                    },
                    {"op": "save", "path": str(out / f"{a.species}.blend")},
                ],
            }
        )
        r = eng.run_batch(
            {"batch_id": "render", "ops": [{"op": "render_final", "output_dir": str(out / "frames")}]}
        )
        if not r.ok:
            print(r.errors)
            return 1
        report["render_s"] = r.data.get("render_seconds")
        report["device"] = r.data.get("device")
    mp4 = out / f"{a.species}_walk.mp4"
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
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
    )
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
