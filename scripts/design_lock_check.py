"""Are the owner-approved designs still the designs the owner approved? (DESIGN_STAGE.md §1; DECISIONS #110)

    python scripts/design_lock_check.py                  # every design/<char>/approved.json
    python scripts/design_lock_check.py kiki zuri        # some
    python scripts/design_lock_check.py --json out.json  # also write the numbers

Renders each locked design afresh (scripts/design_sheet.py, no morph, the sheet's fixed cameras; ~25 s per character
on 2 CPU cores) into ``--out`` and compares its silhouette and 96 px thumbnail with the files committed at approval
(``design/<char>/<version>/``). Exit 1 if any changed. Run it after touching the creature builder, the face, the
materials or the Blender adapter; the unit test only checks the species parameters.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from animatica.design.brief import load_brief  # noqa: E402
from animatica.design.lock import compare_locked  # noqa: E402
from animatica.design.variants import Morph  # noqa: E402


def locked() -> dict[str, str]:
    out = {}
    for p in sorted((ROOT / "design").glob("*/approved.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        out[rec["character"]] = rec["version"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("characters", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "output" / "design_lock"))
    ap.add_argument("--device", default="auto")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    from design_sheet import sheet_for  # imports Blender-side helpers; only when rendering

    versions = locked()
    names = a.characters or list(versions)
    unknown = [n for n in names if n not in versions]
    if unknown:
        ap.error(f"not approved (no design/<char>/approved.json): {', '.join(unknown)}")
    results = []
    for ch in names:
        render = Path(a.out) / ch
        sheet_for(load_brief(ch), Morph(), render, device=a.device, label="lock check")
        r = compare_locked(ch, versions[ch], ROOT / "design" / ch / versions[ch], render)
        print(r.line(), flush=True)
        results.append(r)
    if a.json:
        Path(a.json).write_text(json.dumps([r.as_dict() for r in results], indent=1) + "\n", encoding="utf-8")
    changed = [r.character for r in results if not r.ok]
    if changed:
        print(
            f"CHANGED: {', '.join(changed)} no longer match(es) the approved files; a new version needs the owner."
        )
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
