"""Set test: the savannah at a time of day, with cast members standing in it.

python scripts/savannah_set_test.py --tod sunset --out output/set-tests
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animatica.core.engine import BlenderSession  # noqa: E402
from animatica.creatures.build import build_creature  # noqa: E402
from animatica.creatures.species import SPECIES  # noqa: E402
from animatica.sets.savannah import Layout, savannah_set  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tod", default="sunset", choices=["dawn", "midday", "afternoon", "sunset", "night"])
    ap.add_argument("--out", default="output/set-tests")
    ap.add_argument("--frame", type=int, default=24)
    ap.add_argument("--samples", type=int, default=32)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    layout = Layout(
        water=(3.5, 9.0, 3.2),
        acacias=[(-6.0, 11.0, 1.0), (12.0, 22.0, 0.8), (-16.0, 30.0, 0.9)],
        mounds=[(7.5, 4.0, 0.9)],
        action=[(0.0, 2.0, 4.5)],
    )
    ops = savannah_set(layout, a.tod)
    for cid, sp, at, yaw in (
        ("tembo", "elephant", (-1.2, 2.5), 60.0),
        ("neema", "giraffe", (1.6, 4.2), 110.0),
    ):
        c, _ = build_creature(cid, SPECIES[sp], at=at, yaw=yaw)
        ops += c
    ops += [
        {"op": "create_empty", "id": "aim", "location": [0.6, 5.0, 1.2]},
        {"op": "add_camera", "id": "cam", "location": [-3.5, -6.5, 1.55], "lens": 30, "look_at": "aim"},
        {"op": "set_camera_active", "id": "cam", "frame": 1},
        {"op": "set_frame_range", "start": 1, "end": 48, "fps": 24},
        {
            "op": "render_preview",
            "camera": "cam",
            "frame": a.frame,
            "engine": "cycles",
            "samples": a.samples,
            "resolution": [1280, 720],
            "path": str(out / f"set_{a.tod}.png"),
            "device": "optix",
        },
    ]
    with BlenderSession(workdir=out) as eng:
        r = eng.run_batch({"batch_id": "set", "ops": ops})
        print(
            json.dumps(
                {
                    "ok": r.ok,
                    "errors": r.errors[:4],
                    "warnings": r.warnings[:4],
                    "device": r.data.get("device"),
                }
            )
        )
        if r.ok:
            eng.run_batch(
                {"batch_id": "save", "ops": [{"op": "save", "path": str(out / f"set_{a.tod}.blend")}]}
            )
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
