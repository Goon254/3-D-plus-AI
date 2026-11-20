"""Set problems measured on rendered frames of a film, animatic or set still (``animatica.sets.frames``).

    python scripts/frame_check.py examples/showcase/savannah-film/film_web.mp4          # a frame every 2 s
    python scripts/frame_check.py animatic.mp4 --every 1 --json out.json
    python scripts/frame_check.py examples/showcase/savannah-set-tests/set_midday.jpg   # stills too

Today: ``horizon_stripe`` (the owner's 11-16 note: a pale featureless band laid across the frame where the ground
meets the hills). Prints each frame with a stripe, joined into time ranges; exit 1 if any. With
the per-scene seconds of an ``animatic.json`` (``--animatic``), each range is named by scene. Needs ffmpeg for videos.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animatica.sets.frames import horizon_stripe, stripes_in_video  # noqa: E402

STILLS = {".png", ".jpg", ".jpeg", ".webp"}


def duration(video: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


def scene_at(t: float, bounds: list[tuple[str, float, float]]) -> str:
    for sid, a, b in bounds:
        if a <= t < b:
            return sid
    return ""


def ranges(hits: list[dict], every: float) -> list[dict]:
    """Join consecutive stripe frames (at most one sample apart, same label) into time ranges."""
    out: list[dict] = []
    for h in hits:
        if out and h["t"] - out[-1]["to"] <= every * 1.01 and h["label"] == out[-1]["label"]:
            out[-1]["to"] = h["t"]
            out[-1]["frames"] += 1
            out[-1]["span"] = max(out[-1]["span"], h["span"])
        else:
            out.append({"from": h["t"], "to": h["t"], "label": h["label"], "frames": 1, "span": h["span"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("media", nargs="+", help="videos or stills")
    ap.add_argument("--every", type=float, default=2.0, help="seconds between sampled frames")
    ap.add_argument("--animatic", help="an animatic.json with per-scene seconds, to name scenes")
    ap.add_argument("--offset", type=float, default=0.0, help="seconds before the first scene (title card)")
    ap.add_argument("--json", help="write the findings here")
    a = ap.parse_args()
    bounds: list[tuple[str, float, float]] = []
    if a.animatic:
        t = a.offset
        for s in json.loads(Path(a.animatic).read_text(encoding="utf-8"))["scenes"]:
            bounds.append((s["scene"], t, t + s["seconds"]))
            t += s["seconds"]
    report: dict[str, list] = {}
    for m in map(Path, a.media):
        if m.suffix.lower() in STILLS:
            r = horizon_stripe(m)
            hits = [{"t": 0.0, "label": m.name, **{k: r[k] for k in ("row", "span", "fill", "contrast")}}]
            report[str(m)] = hits if r["stripe"] else []
        else:
            n = int(duration(m) / a.every)
            times = [(i + 0.5) * a.every for i in range(n)]
            report[str(m)] = stripes_in_video(m, times, [scene_at(t, bounds) for t in times])
        found = report[str(m)]
        print(f"{m}: {len(found)} frame(s) with a horizon stripe")
        if m.suffix.lower() in STILLS:
            for h in found:
                print(f"  stripe at {h['row']:.0%} of the height, span {h['span']:.0%}")
        else:
            for r_ in ranges(found, a.every):
                where = f" {r_['label']}" if r_["label"] else ""
                m0, s0 = divmod(r_["from"], 60)
                m1, s1 = divmod(r_["to"], 60)
                print(
                    f"  {int(m0)}:{s0:04.1f}-{int(m1)}:{s1:04.1f}{where}: {r_['frames']} frame(s), "
                    f"span up to {r_['span']:.0%}"
                )
    if a.json:
        Path(a.json).write_text(json.dumps({"horizon_stripe": report}, indent=1) + "\n", encoding="utf-8")
    return 1 if any(report.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
