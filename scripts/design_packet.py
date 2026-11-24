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

    python scripts/design_packet.py --refresh

re-scores every packet without rendering anything and rewrites its ``scores.json``, ``README.md`` and the index:
the sheet's stored image metrics and recorded critique (``design/<char>/<version>/score.json``) with today's rubric
and the current rig stress record. Run it after ``rig_stress_test.py``: the packets the owner reads showed a
``foot_plant`` failure for five days after the rig fixed it (cloud review 11-24 00:36, DECISIONS #122).
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

from animatica.creatures.species import SPECIES  # noqa: E402
from animatica.design.brief import all_briefs, load_brief  # noqa: E402
from animatica.design.rubric import score as rubric_score  # noqa: E402
from animatica.design.variants import apply_morph, morph_from_dict  # noqa: E402

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


# image checks added to the rubric after a sheet was rendered: its stored metrics hold no input for them, so a
# re-score without rendering cannot score them (they are listed as such, never counted as passed)
LATE_IMAGE_CHECKS = {
    "outline": ("face:eye_outline", "face:brow_outline"),
    "stripe_rings": ("materials:stripe_rings",),
}
LATE_NOTES = {
    "face:eye_outline": "the eye and brow outlines were measured on later renders (DECISIONS #89, #115): open in"
    " docs/REVIEW_QUEUE.md",
    "face:brow_outline": "the eye and brow outlines were measured on later renders (DECISIONS #89, #115): open in"
    " docs/REVIEW_QUEUE.md",
    "materials:stripe_rings": "the stripe rings were measured on a later render (DECISIONS #96)",
}


def current_score(char: str, root: Path | None = None) -> dict[str, Any]:
    """The current design's rubric result, re-scored without rendering: the image metrics and the recorded critique
    stored with the sheet (``design/<char>/<version>/score.json``), today's rubric (checks on the built meshes run
    again) and the current rig stress record (``design/<char>/rig_stress.json``). ``unscored`` lists the image checks
    the stored render has no metrics for."""
    base = root or ROOT
    brief = load_brief(char)
    vs = [p for p in (base / "design" / char).glob("v*") if re.fullmatch(r"v\d+", p.name)]
    ver = max(vs, key=lambda p: int(p.name[1:]))
    sheet = json.loads((ver / "score.json").read_text(encoding="utf-8"))
    stress = json.loads((base / "design" / char / "rig_stress.json").read_text(encoding="utf-8"))
    sp = apply_morph(SPECIES[brief.species], morph_from_dict(sheet["morph"]), brief.dark_ok)
    img = sheet["image_metrics"]
    result = rubric_score(brief, sp, img, sheet.get("critique"), stress).as_dict()
    striped = sp.coat.get("pattern") in ("stripes", "bands")
    unscored = [
        cid
        for key, ids in LATE_IMAGE_CHECKS.items()
        if key not in img and (key != "stripe_rings" or striped)
        for cid in ids
    ]
    return {
        "version": ver.name,
        "image_metrics": img,
        "critique": sheet.get("critique"),
        "stress": stress,
        "unscored": unscored,
        "rendered_score": sheet["score"],
        **result,
    }


def packet(char: str, notes: dict[str, Any]) -> dict[str, Any]:
    ver = current_version(char)
    out = ROOT / "design" / "packets" / char
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(ver / "sheet.jpg", out / "sheet.jpg")
    stress = json.loads((ROOT / "design" / char / "rig_stress.json").read_text(encoding="utf-8"))
    # the clip ends a beat after the line and runs back 10 s: the turn's end, the stop, the expressions, the line
    end = min(stress["seconds"], stress["timeline"]["line_end"] + 1.2)
    clip(ROOT / "output" / "rig-stress" / char / "motion.mp4", out / "motion.mp4", max(0.0, end - CLIP))
    loop = json.loads((ROOT / "design" / char / "loop" / "loop.json").read_text(encoding="utf-8"))
    runners = []
    for i, r in enumerate(loop["runner_ups"][:2], 1):
        Image.open(ROOT / r["sheet"]).convert("RGB").save(out / f"runner_up_{i}.jpg", quality=85)
        runners.append({"file": f"runner_up_{i}.jpg", "score": r["score"], "morph": r["morph"]})
    return write_packet(char, notes, runners, round(max(0.0, end - CLIP), 2))


def refresh(char: str, notes: dict[str, Any]) -> dict[str, Any]:
    """Re-score an existing packet (``current_score``) and rewrite its ``scores.json`` and ``README.md``; the
    sheet, the motion clip and the runner-ups are kept as they are."""
    old = json.loads((ROOT / "design" / "packets" / char / "scores.json").read_text(encoding="utf-8"))
    return write_packet(char, notes, old["runner_ups"], old["motion_test"]["clip_start_s"])


def write_packet(
    char: str, notes: dict[str, Any], runners: list[dict[str, Any]], clip_start: float
) -> dict[str, Any]:
    brief = load_brief(char)
    out = ROOT / "design" / "packets" / char
    score = current_score(char)
    stress = score["stress"]
    failed = [c for c in score["checks"] if not c["passed"]]
    scores = {
        "character": char,
        "species": brief.species,
        "version": score["version"],
        "score": score["score"],
        "ready": score["ready"],
        "rendered_score": score["rendered_score"],
        "hard_failures": score["hard_failures"],
        "pending": score["pending"],
        "unscored": score["unscored"],
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
            "clip_start_s": clip_start,
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
        f"# {n.get('name', char)} ({brief.species}), design {score['version']}",
        "",
        n.get("summary", ""),
        "",
        "| | |",
        "|---|---|",
        f"| Rubric | **{score['score']}** / 10, {'ready' if score['ready'] else 'not ready'}"
        + (
            f" (re-scored with today's rubric and rig stress record; {score['rendered_score']} when rendered)"
            if score["score"] != score["rendered_score"]
            else ""
        )
        + " |",
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
    if score["unscored"]:
        lines += [
            "",
            "Not scored (added to the rubric after this sheet was rendered; a re-render scores them): "
            + ", ".join(f"`{c}`" for c in score["unscored"])
            + ". Not counted as passed; "
            + "; ".join(dict.fromkeys(LATE_NOTES[c] for c in score["unscored"]))
            + ".",
        ]
    lines += ["", "## Still open", ""] + ([f"* {x}" for x in n.get("open", [])] or ["* nothing known"])
    lines += ["", "## Runner-ups", "", n.get("runners", ""), "", "Approve, or reply with notes."]
    (out / "README.md").write_text("\n".join(x for x in lines) + "\n", encoding="utf-8")
    return scores


INDEX_HEAD = """# Design packets (DESIGN_STAGE §6): for owner approval

One folder per character: `sheet.jpg`, a 10-second `motion.mp4` with the character's line, `scores.json`, the
design loop's two runner-ups, and a one-page `README.md`. Built by `scripts/design_packet.py --all` from the
current design (`design/<char>/v*`), its rig stress report (`design/<char>/rig_stress.json`) and the loop log
(`design/<char>/loop/`); the notes are in `notes.json`. This index is written from the packets' `scores.json` and
`design/<char>/approved.json` (`design_packet.py --index` rebuilds it alone), so it can't fall behind them.
"""

INDEX_FOOT = """
Read the scores this way: "ready" needs 9.0+, no hard failure, the species read and appeal 8+. The species read and
appeal come from a recorded critique (no live vision key on this machine). The runner-ups' 10.0s were scored
*without* a species read, so they don't compete with the current designs' numbers. An approved design is locked to
its species parameters (`design/<char>/approved.json`); production may not change it.
"""


def index(root: Path | None = None) -> str:
    """The packets' index README, from each packet's ``scores.json``, the approvals and ``notes.json``."""
    base = root or ROOT
    packets = base / "design" / "packets"
    npath = packets / "notes.json"
    notes = json.loads(npath.read_text(encoding="utf-8")) if npath.exists() else {}
    rows = [
        "| Character | Design | Owner | Rubric | Ready | Rig stress | Asks of you |",
        "|---|---|---|---|---|---|---|",
    ]
    for sp in sorted(packets.glob("*/scores.json")):
        char = sp.parent.name
        sc = json.loads(sp.read_text(encoding="utf-8"))
        ap = base / "design" / char / "approved.json"
        appr = json.loads(ap.read_text(encoding="utf-8")) if ap.exists() else None
        n = notes.get(char, {})
        mine = appr is not None and appr.get("version") == sc["version"]
        owner = (
            f"**approved** {appr['version']}"
            if mine
            else (f"approved {appr['version']}" if appr else "waiting")
        )
        if sc["ready"]:
            ready = "yes"
        else:
            why = sc["hard_failures"] or [
                c["id"] for c in sc["failed_checks"] if c["id"].startswith("critic:")
            ]
            ready = "no: " + ", ".join(f"`{w}`" for w in why) if why else "no"
        mc = sc["motion_checks"]
        ask = n.get("ask") or ("nothing: locked" if mine else "approve or give notes")
        rows.append(
            f"| [{n.get('name', char)}]({char}/README.md) | {sc['version']} | {owner} | {sc['score']} | {ready} "
            f"| {sum(c['passed'] for c in mc)} / {len(mc)} | {ask} |"
        )
    text = INDEX_HEAD + "\n" + "\n".join(rows) + "\n" + INDEX_FOOT
    (packets / "README.md").write_text(text, encoding="utf-8")
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("characters", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--index", action="store_true", help="only rebuild design/packets/README.md")
    ap.add_argument(
        "--refresh", action="store_true", help="re-score every packet (no render) and rewrite its pages"
    )
    ap.add_argument("--notes", default=str(ROOT / "design" / "packets" / "notes.json"))
    a = ap.parse_args()
    if a.index:
        index()
        return 0
    notes = json.loads(Path(a.notes).read_text(encoding="utf-8")) if Path(a.notes).exists() else {}
    if a.refresh:
        names = a.characters or sorted(
            p.parent.name for p in (ROOT / "design" / "packets").glob("*/scores.json")
        )
    else:
        names = list(all_briefs()) if a.all else a.characters
    if not names:
        ap.error("name a character or pass --all")
    for ch in names:
        s = refresh(ch, notes) if a.refresh else packet(ch, notes)
        print(json.dumps({k: s[k] for k in ("character", "version", "score", "ready", "hard_failures")}))
    index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
