"""Best-of-N design loop (DESIGN_STAGE.md §3–4): candidates → sheets → rubric → pick → apply critique → repeat.

    python scripts/design_loop.py kiki                      # 6 candidates, up to 5 rounds
    python scripts/design_loop.py --all --res 384 --samples 8

Each round renders N morph candidates around the current best (:data:`animatica.design.variants.SPREAD`), scores
every sheet, keeps the best and applies its rubric edit as the next round's starting morph. Stops when the best
is ``ready``, when no fixable failure is left, or after ``--rounds``. Writes ``<out>/<character>/loop.json`` (every
candidate's score, hard failures and morph), ``<out>/<character>/r<k>_c<i>/`` (sheets) and a ``contact.png`` per
round, and prints the winner. The species read stays *pending* until a vision model or a recorded critique has
looked at the winner's sheet (see ``animatica.design.critic``), so in the cloud a winner is never ``ready``
on its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from design_sheet import sheet_for  # noqa: E402
from PIL import Image  # noqa: E402

from animatica.creatures.species import SPECIES  # noqa: E402
from animatica.design.brief import Brief, all_briefs, load_brief  # noqa: E402
from animatica.design.rubric import edit_morph  # noqa: E402
from animatica.design.variants import Morph, candidates  # noqa: E402


def rank_key(doc: dict) -> tuple:
    """Higher score first, then fewer hard failures, then the smallest change from the base design."""
    change = sum(abs(v - (0.0 if k == "lift_dark" else 1.0)) for k, v in doc["morph"].items())
    return (-doc["score"], len(doc["hard_failures"]), change)


def contact(docs: list[dict], out: Path) -> Path:
    tiles = [Image.open(d["sheet"]).convert("RGB") for d in docs]
    w = 640
    tiles = [t.resize((w, int(t.size[1] * w / t.size[0]))) for t in tiles]
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    h = max(t.size[1] for t in tiles)
    sheet = Image.new("RGB", (cols * w, rows * h), (246, 244, 239))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * w, (i // cols) * h))
    sheet.save(out)
    return out


def run(brief: Brief, out: Path, n: int, rounds: int, res: int, samples: int, device: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    start = Morph()
    log: dict = {"character": brief.character, "rounds": []}
    best: dict | None = None
    seen: set[str] = set()
    for k in range(rounds):
        docs = []
        for i, (m, _sp) in enumerate(candidates(SPECIES[brief.species], n, start, brief.dark_ok)):
            key = json.dumps(m.as_dict(), sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            d = sheet_for(
                brief, m, out / f"r{k}_c{i}", res, samples, device, label=f"round {k} candidate {i}"
            )
            docs.append(d)
            print(
                json.dumps(
                    {"round": k, "c": i, "score": d["score"], "hard": d["hard_failures"], "morph": d["morph"]}
                )
            )
        if not docs:
            break
        docs.sort(key=rank_key)
        contact(docs, out / f"r{k}_contact.png")
        log["rounds"].append(
            [
                {
                    k2: d[k2]
                    for k2 in (
                        "morph",
                        "score",
                        "ready",
                        "hard_failures",
                        "pending",
                        "edit",
                        "manual",
                        "sheet",
                    )
                }
                for d in docs
            ]
        )
        if best is None or rank_key(docs[0]) < rank_key(best):
            best = docs[0]
        if best["ready"] or not best["edit"]:
            break
        start = edit_morph(Morph(**{k2: v for k2, v in best["morph"].items()}), best["edit"])
    assert best is not None
    log["winner"] = {
        k2: best[k2] for k2 in ("morph", "score", "ready", "hard_failures", "pending", "manual", "sheet")
    }
    log["runner_ups"] = [
        {k2: d[k2] for k2 in ("morph", "score", "sheet")}
        for d in sorted((d for r in log["rounds"] for d in r), key=rank_key)
        if d["sheet"] != best["sheet"]
    ][:2]
    (out / "loop.json").write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")
    return log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("characters", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--out", default=str(ROOT / "output" / "design-loop"))
    ap.add_argument("--res", type=int, default=512)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--device", default="auto")
    a = ap.parse_args()
    names = list(all_briefs()) if a.all else a.characters
    if not names:
        ap.error("name a character or pass --all")
    for ch in names:
        log = run(load_brief(ch), Path(a.out) / ch, a.n, a.rounds, a.res, a.samples, a.device)
        print(json.dumps({"character": ch, "winner": log["winner"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
