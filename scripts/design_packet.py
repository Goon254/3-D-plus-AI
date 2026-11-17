"""Design packets for the owner (DESIGN_STAGE.md §6): one folder per character in ``design/packets/<char>/``.

    python scripts/design_packet.py --all

Each packet holds what the owner approves from:

* ``sheet.jpg``: the current design sheet (``design/<char>/<version>/``, scored with its recorded critique and the
  rig stress test);
* ``motion.mp4``: 10 seconds of the rig stress take (``scripts/rig_stress_test.py``): the turn and stop, head turns,
  every expression and the character's line in their own voice;
* ``scores.json``: the rubric result: score, ready, hard failures, every failed check, the stress-test checks;
* ``runner_up_1.jpg``, ``runner_up_2.jpg``: the design loop's next two candidates (``design/<char>/loop/loop.json``);
* ``README.md``: the one-page note: what changed, what the checks say, what is still open.

Inputs must already exist: run the stress test first, then ``design_sheet.py --rescore`` on the current version.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from animatica.design.brief import all_briefs, load_brief  # noqa: E402

CLIP = 10.0  # seconds


def current_version(char: str) -> Path:
    vs = [p for p in (ROOT / "design" / char).glob("v*") if re.fullmatch(r"v\d+", p.name)]
    return max(vs, key=lambda p: int(p.name[1:]))


def clip(src: Path, dst: Path, start: float) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{CLIP:.2f}"]
        + ["-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", str(dst)],
        check=True,
    )


def packet(char: str, notes: dict[str, Any]) -> dict[str, Any]:
    brief = load_brief(char)
    ver = current_version(char)
    out = ROOT / "design" / "packets" / char
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(ver / "sheet.jpg", out / "sheet.jpg")
    score = json.loads((ver / "score.json").read_text(encoding="utf-8"))
    stress = json.loads((ROOT / "design" / char / "rig_stress.json").read_text(encoding="utf-8"))
    # the clip ends a beat after the line and runs back 10 s: the turn's end, the stop, the expressions, the line
    end = min(stress["seconds"], stress["timeline"]["line_end"] + 1.2)
    clip(ROOT / "output" / "rig-stress" / char / "motion.mp4", out / "motion.mp4", max(0.0, end - CLIP))
    loop = json.loads((ROOT / "design" / char / "loop" / "loop.json").read_text(encoding="utf-8"))
    runners = []
    for i, r in enumerate(loop["runner_ups"][:2], 1):
        Image.open(ROOT / r["sheet"]).convert("RGB").save(out / f"runner_up_{i}.jpg", quality=85)
        runners.append({"file": f"runner_up_{i}.jpg", "score": r["score"], "morph": r["morph"]})
    failed = [c for c in score["checks"] if not c["passed"]]
    scores = {
        "character": char,
        "species": brief.species,
        "version": ver.name,
        "score": score["score"],
        "ready": score["ready"],
        "hard_failures": score["hard_failures"],
        "pending": score["pending"],
        "failed_checks": [{"id": c["id"], "hard": c["hard"], "message": c["message"]} for c in failed],
        "motion_checks": [
            {"id": c["id"], "passed": c["passed"], "message": c["message"]}
            for c in score["checks"]
            if c["group"] == "motion"
        ],
        "critique": {
            k: (score.get("critique") or {}).get(k)
            for k in ("silhouette_species", "thumbnail_species", "appeal")
        },
        "image_metrics": score["image_metrics"],
        "runner_ups": runners,
        "motion_test": {
            "file": "motion.mp4",
            "from_take": f"output/rig-stress/{char}/motion.mp4",
            "clip_start_s": round(max(0.0, end - CLIP), 2),
            "line": stress["line"],
            "turn_degrees": stress.get("turn_degrees"),
            "sit_stand": stress["sit_stand"],
        },
    }
    (out / "scores.json").write_text(json.dumps(scores, indent=1) + "\n", encoding="utf-8")
    n = notes.get(char, {})
    crit = scores["critique"]

    def fmt_morph(m: dict[str, float]) -> str:
        d = {k: v for k, v in m.items() if v not in (1.0, 0.0)}
        return ", ".join(f"{k} × {v:g}" for k, v in d.items()) or "the base design"

    lines = [
        f"# {n.get('name', char)} ({brief.species}), design {ver.name}",
        "",
        n.get("summary", ""),
        "",
        "| | |",
        "|---|---|",
        f"| Rubric | **{score['score']}** / 10, {'ready' if score['ready'] else 'not ready'} |",
        f"| Silhouette reads as | {crit['silhouette_species'] or '—'} |",
        f"| 96 px thumbnail reads as | {crit['thumbnail_species'] or '—'} |",
        f"| Appeal (critic) | {crit['appeal'] if crit['appeal'] is not None else '—'} |",
        f"| Rig stress test | {sum(c['passed'] for c in scores['motion_checks'])} / {len(scores['motion_checks'])} checks pass |",
        "",
        "## Files",
        "",
        "* `sheet.jpg`: turnaround, expressions, silhouette, thumbnail, rubric panel.",
        f"* `motion.mp4`: 10 s from the rig stress take: {n.get('motion', 'turn, stop, head turns, every expression, then the line')}"
        f' — "{stress["line"]}"',
        f"* `runner_up_1.jpg`: {fmt_morph(runners[0]['morph'])} ({runners[0]['score']})." if runners else "",
        f"* `runner_up_2.jpg`: {fmt_morph(runners[1]['morph'])} ({runners[1]['score']})."
        if len(runners) > 1
        else "",
        "* `scores.json`: every number above, the failed checks and the stress-test checks.",
        "",
        "## Failed checks",
        "",
    ]
    lines += [f"* `{c['id']}`{' (hard)' if c['hard'] else ''}: {c['message']}" for c in failed] or ["* none"]
    lines += ["", "## Still open", ""] + ([f"* {x}" for x in n.get("open", [])] or ["* nothing known"])
    lines += ["", "## Runner-ups", "", n.get("runners", ""), "", "Approve, or reply with notes."]
    (out / "README.md").write_text("\n".join(x for x in lines) + "\n", encoding="utf-8")
    return scores


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("characters", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--notes", default=str(ROOT / "design" / "packets" / "notes.json"))
    a = ap.parse_args()
    names = list(all_briefs()) if a.all else a.characters
    if not names:
        ap.error("name a character or pass --all")
    notes = json.loads(Path(a.notes).read_text(encoding="utf-8")) if Path(a.notes).exists() else {}
    for ch in names:
        s = packet(ch, notes)
        print(json.dumps({k: s[k] for k in ("character", "version", "score", "ready", "hard_failures")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
