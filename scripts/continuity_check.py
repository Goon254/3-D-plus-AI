"""Continuity check for the savannah film: who is on stage in every shot, against the story's exits and
entrances (``animatica.production.continuity``), and the set's models as built (acacia crowns:
``set_canopy``). Pure Python, before anything renders.

    python scripts/continuity_check.py            # every scene; exit 1 on any violation
    python scripts/continuity_check.py --table    # also print who is on stage in each shot
    python scripts/continuity_check.py --cameras  # also staging tangents, back views, dead air (nothing
                                                  # on screen moves but the camera for > 4.5 s, across cuts)
                                                  # and crowding (a neighbour's headless legs or flank in a
                                                  # face shot) on approximate shot cameras
    python scripts/continuity_check.py --cameras --json out.json --diff last.json
                                                  # save the findings; print what is fixed / new since last.json
    python scripts/continuity_check.py --film films/<name>   # a feature-mode film folder

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

from animatica.production.continuity import (  # noqa: E402
    actor_speeds,
    check_scene,
    check_story,
    continuity_report,
    diff_reports,
    set_assets,
)
from animatica.production.framing import crowding  # noqa: E402
from animatica.production.pacing import dead_air, line_durations  # noqa: E402
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
    return line_durations(spec, json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(ROOT / "output" / "savannah-animatic"))
    ap.add_argument("--table", action="store_true")
    ap.add_argument(
        "--cameras",
        action="store_true",
        help="staging tangents, back views and dead air on approximate shot cameras",
    )
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument(
        "--film", default=str(FILM), help="the film folder (feature mode); default films/savannah"
    )
    ap.add_argument(
        "--json", metavar="PATH", help="also write the findings as JSON (counts per kind, each key)"
    )
    ap.add_argument(
        "--diff", metavar="PATH", help="an earlier --json report: print what is fixed and what is new"
    )
    a = ap.parse_args()
    film = Path(a.film)
    scenes = load_scenes(film / "07_scenes.json")
    bad = check_story(list(scenes.values()))
    for spec in scenes.values():
        secs = schedule(spec, durations(spec, Path(a.work)), actor_speeds(spec))
        shots = split_long(cut_list(spec, secs), secs)
        v, pres = check_scene(spec, shots, secs)
        bad += v
        bad += set_assets(spec)
        if a.cameras:
            poses = poses_from_paths(spec, secs, a.fps)
            cams = approx_cameras(spec, shots, poses, a.fps)
            bad += staging_tangent(spec, cams, poses, a.fps)
            bad += facing_away(spec, cams, poses, a.fps)
            bad += dead_air(spec, cams, poses, a.fps, secs)
            bad += crowding(spec, cams, poses, a.fps)
        if a.table:
            print(f"== {spec.id} {spec.title} ({secs:.1f}s)")
            for s0, s1, typ, subs, here in pres.shots:
                print(
                    f"  {s0:6.2f}-{s1:6.2f} {typ:4s} {','.join(subs) or '(set)':28s} on stage: {', '.join(here)}"
                )
    for v in bad:
        print(v)
    print(f"{len(bad)} continuity violation(s)")
    rep = continuity_report(bad, film=film.name, cameras=a.cameras, fps=a.fps)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    if a.diff:
        old = json.loads(Path(a.diff).read_text(encoding="utf-8"))
        if old.get("cameras") != a.cameras:
            print("note: only one of the two runs checked the cameras; camera findings are not compared")
        d = diff_reports(old, rep)
        for v in d["fixed"]:
            print(f"- fixed {v['scene']} {v['kind']} {v['who']} {v['detail']}")
        for v in d["new"]:
            print(f"+ new   {v['scene']} {v['kind']} {v['who']} {v['detail']}")
        print(f"since {a.diff}: {len(d['fixed'])} fixed, {len(d['new'])} new, {len(d['kept'])} still open")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
