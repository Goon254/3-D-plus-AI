"""Blind species reads of the design images (REVIEW_QUEUE "Blind species read"; DECISIONS #111)

    python scripts/blind_read.py                         # table for every locked design (design/<char>/approved.json)
    python scripts/blind_read.py --copy DIR              # copy the locked silhouettes/thumbnails to DIR as a1..aN
                                                         # (anonymous names) for a reader with no context
    python scripts/blind_read.py --record kiki v6 --reader "sub-agent, no context" \\
        --silhouette "meerkat,70,prairie dog;otter" --thumbnail "meerkat,60,mongoose;weasel"

A reviewer who knows the brief reads the species into the shape; a stranger may not. The reader names the animal from
the black silhouette first, then from the 96 px thumbnail, with a first-instinct confidence (0-100) and what else it
could be. Answers are stored in ``design/<char>/<version>/blind_read.json`` with the images' SHA-256 (a re-render voids
them). Verdicts: clear (named, confidence >= 75), weak (named, unsure), misread. Exit 1 if any locked design has a
misread; weak reads are design notes, not failures.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animatica.design.brief import load_brief  # noqa: E402
from animatica.design.critic import (  # noqa: E402
    BLIND_VIEWS,
    blind_verdict,
    load_blind_read,
    record_blind_read,
)


def locked() -> dict[str, str]:
    out = {}
    for p in sorted((ROOT / "design").glob("*/approved.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        out[rec["character"]] = rec["version"]
    return out


def parse_answer(s: str) -> dict:
    """``"zebra,50,horse;donkey"`` -> animal, confidence, alternatives."""
    parts = [p.strip() for p in s.split(",")]
    if len(parts) < 2:
        raise SystemExit(f"answer {s!r}: expected 'animal,confidence[,alt;alt]'")
    alts = [a.strip() for a in parts[2].split(";") if a.strip()] if len(parts) > 2 else []
    return {"animal": parts[0], "confidence": float(parts[1]), "alternatives": alts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--copy", metavar="DIR")
    ap.add_argument("--record", nargs=2, metavar=("CHAR", "VERSION"))
    ap.add_argument("--reader", default="unnamed")
    ap.add_argument("--silhouette")
    ap.add_argument("--thumbnail")
    a = ap.parse_args()

    if a.copy:
        dst = Path(a.copy)
        dst.mkdir(parents=True, exist_ok=True)
        for i, (char, ver) in enumerate(locked().items(), 1):
            for view, fname in BLIND_VIEWS.items():
                shutil.copy(ROOT / "design" / char / ver / fname, dst / f"a{i}-{view}.png")
            print(f"a{i} = {char} {ver}")
        return 0

    if a.record:
        char, ver = a.record
        if not (a.silhouette and a.thumbnail):
            raise SystemExit("--record needs --silhouette and --thumbnail")
        rec = record_blind_read(
            ROOT / "design" / char / ver,
            a.reader,
            silhouette=parse_answer(a.silhouette),
            thumbnail=parse_answer(a.thumbnail),
        )
        print(json.dumps(blind_verdict(load_brief(char), rec)))
        return 0

    bad = 0
    print(f"{'character':<11} {'ver':<4} {'silhouette':<40} {'thumbnail':<40}")
    for char, ver in locked().items():
        rec = load_blind_read(ROOT / "design" / char / ver)
        if rec is None:
            print(f"{char:<11} {ver:<4} pending (no blind read of these exact images)")
            continue
        v = blind_verdict(load_brief(char), rec)
        cells = []
        for view in BLIND_VIEWS:
            r = rec[view]
            alts = "/".join(r["alternatives"][:2])
            cells.append(f"{v[view]}: {r['animal']} {r['confidence']:.0f} ({alts})")
        bad += "misread" in v.values()
        print(f"{char:<11} {ver:<4} {cells[0]:<40} {cells[1]:<40}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
