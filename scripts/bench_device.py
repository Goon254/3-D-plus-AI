"""Benchmark one Cycles frame of a project .blend on each render device.

    python scripts/bench_device.py examples/showcase/hello-little-one/scene.blend --frame 300

Renders the frame at `--quality` (default final: 960x540, 16 spp, OIDN) once per device, in a fresh
adapter process each time, so every number includes kernel load + BVH build (what a one-frame critic
preview pays). `--warm N` also renders N more frames in the same process and reports the per-frame
average, which is what a full film render pays.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animatica.agents.editor import QUALITY  # noqa: E402
from animatica.core.engine import BlenderSession  # noqa: E402


def bench(blend: Path, device: str, frame: int, quality: str, warm: int) -> dict:
    _, res, samples = QUALITY[quality]
    with tempfile.TemporaryDirectory() as tmp, BlenderSession(workdir=tmp) as eng:
        eng.open(str(blend), workdir=tmp)
        setup = {"op": "set_render", "engine": "cycles", "resolution": list(res), "samples": samples}
        r = eng.run_batch({"batch_id": "bench-setup", "ops": [{**setup, "device": device}]})
        assert r.ok, r.errors

        def render(f0: int, f1: int) -> tuple[float, dict]:
            t0 = time.perf_counter()
            out = eng.run_batch(
                {
                    "batch_id": f"bench-{f0}",
                    "ops": [{"op": "render_final", "output_dir": tmp, "frame_start": f0, "frame_end": f1}],
                }
            )
            assert out.ok, out.errors
            return time.perf_counter() - t0, out

        first, out = render(frame, frame)
        row = {
            "device": out.data.get("device"),
            "requested": device,
            "resolution": f"{res[0]}x{res[1]}",
            "samples": samples,
            "first_frame_s": round(first, 2),
            "warnings": out.warnings,
        }
        if warm:
            secs, _ = render(frame + 1, frame + warm)
            row["warm_s_per_frame"] = round(secs / warm, 2)
        return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("blend", type=Path)
    ap.add_argument("--frame", type=int, default=300)
    ap.add_argument("--quality", default="final", choices=sorted(QUALITY))
    ap.add_argument("--devices", default="cpu,optix")
    ap.add_argument("--warm", type=int, default=0, help="extra frames rendered in the same process")
    a = ap.parse_args()
    rows = [bench(a.blend.resolve(), d, a.frame, a.quality, a.warm) for d in a.devices.split(",")]
    print(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
