"""Render a design proposal beside its locked design (animatica.design.proposal; DECISIONS #112)

    python scripts/design_proposal.py design/proposals/kiki-v7          # render + score the sheet
    python scripts/design_proposal.py design/proposals/kiki-v7 --compare # also the locked-vs-proposal board
    python scripts/design_proposal.py --list                             # every proposal and its blind read

Writes the standard sheet into the proposal folder (``sheet.jpg``, ``silhouette.png``, ``thumb96.png``,
``score.json``) plus ``compare.jpg``: the locked design's silhouette and thumbnail next to the proposal's, the
silhouettes at the same scale, so the owner judges the change at a glance. The locked species is never touched;
approving a proposal is the owner's call (DESIGN_STAGE.md §6), after which it is copied into
``creatures/species.py`` and ``design/<char>/<version>/`` like any approved design.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from PIL import Image, ImageDraw  # noqa: E402

from animatica.creatures.species import SPECIES  # noqa: E402
from animatica.design.brief import load_brief  # noqa: E402
from animatica.design.critic import blind_verdict, load_blind_read  # noqa: E402
from animatica.design.proposal import (  # noqa: E402
    changed_fields,
    load_proposal,
    proposal_species,
    stress_summary,
)
from animatica.design.variants import Morph  # noqa: E402

PROPOSALS = ROOT / "design" / "proposals"


def compare_board(locked_dir: Path, prop_dir: Path, title: str) -> Path:
    """Locked | proposal, silhouette row over thumbnail row (thumbnails shown 3x, nearest-neighbour)."""
    tiles = []
    for d in (locked_dir, prop_dir):
        sil = Image.open(d / "silhouette.png").convert("RGB")
        th = Image.open(d / "thumb96.png").convert("RGB")
        th = th.resize((th.width * 3, th.height * 3), Image.NEAREST)
        tiles.append((sil, th))
    w = max(s.width for s, _ in tiles)
    cell = max(w, max(t.width for _, t in tiles))
    h = max(s.height for s, _ in tiles) + max(t.height for _, t in tiles) + 60
    board = Image.new("RGB", (cell * 2 + 30, h), (245, 243, 238))
    dr = ImageDraw.Draw(board)
    dr.text((10, 8), title, fill=(30, 30, 30))
    for i, (sil, th) in enumerate(tiles):
        x = 10 + i * (cell + 10)
        dr.text(
            (x, 26),
            ("locked " if i == 0 else "proposal ") + ("" if i else locked_dir.name),
            fill=(80, 80, 80),
        )
        board.paste(sil, (x, 44))
        board.paste(th, (x, 50 + sil.height))
    out = prop_dir / "compare.jpg"
    board.save(out, quality=90)
    return out


def render(prop_dir: Path, res: int, samples: int, device: str) -> dict:
    from design_sheet import sheet_for

    doc = load_proposal(prop_dir)
    brief = load_brief(doc["character"])
    sp = proposal_species(doc, SPECIES)
    # the proposal's own stress report (rig_stress_test.py --proposal), never the locked design's
    stress_path = prop_dir / "rig_stress.json"
    stress = json.loads(stress_path.read_text(encoding="utf-8")) if stress_path.exists() else None
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        res_doc = sheet_for(
            brief,
            Morph(),
            work,
            res,
            samples,
            device,
            label=f"{doc['character']} {doc['version']} (proposal on {doc['base']})",
            species=sp,
            with_stress=stress is not None,
            stress_path=stress_path,
        )
        for name in ("silhouette.png", "thumb96.png"):
            shutil.copy(work / name, prop_dir / name)
        Image.open(work / "sheet.png").convert("RGB").save(prop_dir / "sheet.jpg", quality=88)
    locked = SPECIES[sp.name]
    keep = {
        k: res_doc[k] for k in ("score", "ready", "hard_failures", "image_metrics", "design") if k in res_doc
    }
    keep["changed"] = sorted(changed_fields(locked, sp))
    keep["rig_stress"] = (
        stress_summary(stress, sp)
        if stress
        else "not run: python scripts/rig_stress_test.py --proposal <this folder> --no-render (CPU, ~1 min)"
    )
    (prop_dir / "score.json").write_text(json.dumps(keep, indent=1) + "\n", encoding="utf-8")
    return keep


def list_all() -> int:
    for d in sorted(PROPOSALS.glob("*/proposal.json")):
        doc = load_proposal(d)
        read = load_blind_read(d.parent)
        verdict = blind_verdict(load_brief(doc["character"]), read) if read else "not read"
        print(f"{doc['character']:10} {doc['version']:4} on {doc['base']:4}  blind: {verdict}")
        if doc.get("status"):
            print(f"{'':10} {doc['status']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("proposal", nargs="?")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--res", type=int, default=512)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--device", default="auto")
    a = ap.parse_args()
    if a.list:
        return list_all()
    if not a.proposal:
        ap.error("name a proposal folder or pass --list")
    prop_dir = Path(a.proposal).resolve()
    doc = load_proposal(prop_dir)
    out = render(prop_dir, a.res, a.samples, a.device)
    print(json.dumps({"score": out["score"], "hard": out["hard_failures"], "changed": out["changed"]}))
    if a.compare:
        locked_dir = ROOT / "design" / doc["character"] / doc["base"]
        print(
            compare_board(
                locked_dir, prop_dir, f"{doc['character']}: {doc['base']} (locked) vs {doc['version']}"
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
