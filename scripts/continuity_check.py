"""Continuity check for the savannah film: who is on stage in every shot, against the story's exits and
entrances (``animatica.production.continuity``). Pure Python, before anything renders.

    python scripts/continuity_check.py            # every scene; exit 1 on any violation
    python scripts/continuity_check.py --table    # also print who is on stage in each shot
    python scripts/continuity_check.py --cameras  # also staging tangents on approximate shot cameras

Line lengths come from the last render's ``report.json`` (``--work``), else an estimate from the word count,
so the timing is the real one whenever the voices exist.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animatica.production.continuity import actor_speeds, check_scene, check_story  # noqa: E402
from animatica.production.scene import cut_list, load_scenes, schedule, split_long  # noqa: E402
from animatica.production.staging import (  # noqa: E402
    approx_cameras,
    facing_away,
    poses_from_paths,
    staging_tangent,
)

FILM = ROOT / "films" / "savannah"


def durations(spec, work: Path) -> list[float]:
    rp = work / spec.id / "report.json"
    if rp.exists():
        rep = json.loads(rp.read_text(encoding="utf-8"))
        got = {(ln["who"], ln["text"]): ln["end"] - ln["start"] for ln in rep.get("lines", [])}
        if all((ln.who, ln.text) in got for ln in spec.lines):
            return [got[(ln.who, ln.text)] for ln in spec.lines]
    return [0.6 + 0.36 * len(ln.text.split()) for ln in spec.lines]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(ROOT / "output" / "savannah-animatic"))
    ap.add_argument("--table", action="store_true")
    ap.add_argument(
        "--cameras", action="store_true", help="staging tangents and back views on approximate shot cameras"
    )
    ap.add_argument("--fps", type=int, default=24)
    a = ap.parse_args()
    scenes = load_scenes(FILM / "07_scenes.json")
    bad = check_story(list(scenes.values()))
    for spec in scenes.values():
        secs = schedule(spec, durations(spec, Path(a.work)), actor_speeds(spec))
        shots = split_long(cut_list(spec, secs), secs)
        v, pres = check_scene(spec, shots, secs)
        bad += v
        if a.cameras:
            poses = poses_from_paths(spec, secs, a.fps)
            cams = approx_cameras(spec, shots, poses, a.fps)
            bad += staging_tangent(spec, cams, poses, a.fps)
            bad += facing_away(spec, cams, poses, a.fps)
        if a.table:
            print(f"== {spec.id} {spec.title} ({secs:.1f}s)")
            for s0, s1, typ, subs, here in pres.shots:
                print(
                    f"  {s0:6.2f}-{s1:6.2f} {typ:4s} {','.join(subs) or '(set)':28s} on stage: {', '.join(here)}"
                )
    for v in bad:
        print(v)
    print(f"{len(bad)} continuity violation(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
