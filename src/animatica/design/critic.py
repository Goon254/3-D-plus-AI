"""The vision critic: does the design read as its species, unprompted? (DESIGN_STAGE.md §4)

Three questions, asked in separate calls so the answer to one can't prime the next, and never naming the
species before the model has named it:

1. the black **silhouette** alone: "what animal is this?"
2. the **96 px thumbnail** alone: same question.
3. the full **sheet** with the brief (and reference images when the brief lists local copies): list concrete
   mismatches and appeal problems (eye patches, leg thickness, head separate from body...).

Sources, in order: a live vision provider (``animatica.core.llm``, needs ``ANTHROPIC_API_KEY``), else a
**recorded critique** — ``critique.json`` next to the sheet, written by a person or a reviewer agent who looked
at exactly that sheet. A recorded critique carries the sheet's SHA-256, so a critique of an older render is
never applied to a new one. With neither, the species read stays *pending* and the design can't be ``ready``.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from animatica.core.llm import LLMError, Provider
from animatica.design.brief import Brief

ASK_NAME = (
    "You are an art director for a children's animated film. Look at the image and say which animal it shows. "
    'Reply as JSON: {"animal": "<one common name>", "confidence": 0-1, "alternatives": ["..."]}. '
    "Do not guess from context; judge only what you see."
)
ASK_REVIEW = (
    "You are a strict art director for a kids' animated film (ages 4-9). The image is a character design sheet "
    "(front, side, 3/4, back, silhouette, 96 px thumbnail, face close-ups). Compare it with the brief. List "
    "concrete, fixable problems only: species-read problems, proportions, eyes (seated in sockets, lids, size), "
    "head separate from body, flat black areas, floating parts, pattern/colour against the palette, appeal. "
    'Reply as JSON: {"issues": ["..."], "appeal": 1-10, "species_fidelity": 1-10}.'
)


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z]+", s.lower()))


def reads_as(brief: Brief, said: str) -> tuple[bool, str]:
    """Is ``said`` (a free-text answer) the brief's species and not one of its known confusions?"""
    w = _words(said)
    hit = [n for n in brief.names if set(n.split()) <= w or n.rstrip("s") in w]
    wrong = [c for c in brief.confusions if set(c.split()) <= w]
    if hit and not wrong:
        return True, f"named {hit[0]}"
    if hit and wrong:
        return False, f"ambiguous: {hit[0]} but also {', '.join(wrong)}"
    if wrong:
        return False, f"misread as {', '.join(wrong)} (a known confusion)"
    return False, "not identified as " + " / ".join(brief.names)


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_recorded(path: str | Path, sheet: str | Path) -> dict[str, Any] | None:
    """A recorded critique, only if it was written for exactly this sheet image."""
    p = Path(path)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("sheet_sha256") != sha256(sheet):
        return None
    return d


def record(path: str | Path, sheet: str | Path, reviewer: str, **answers: Any) -> dict[str, Any]:
    """Write a recorded critique for ``sheet`` (``silhouette_species``, ``thumbnail_species``, ``issues``...)."""
    d = {"reviewer": reviewer, "sheet": Path(sheet).name, "sheet_sha256": sha256(sheet), **answers}
    Path(path).write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    return d


def ask_vision(
    provider: Provider, brief: Brief, silhouette: Path, thumbnail: Path, sheet: Path
) -> dict[str, Any] | None:
    """Ask a live vision model the three questions; ``None`` when the provider can't see or fails."""
    if not provider.supports_vision:
        return None
    try:
        sil = provider.complete_json(
            "design_read", ASK_NAME, {"view": "silhouette"}, images=[silhouette], max_tokens=300
        )
        thu = provider.complete_json(
            "design_read", ASK_NAME, {"view": "thumbnail"}, images=[thumbnail], max_tokens=300
        )
        payload = {
            "brief": {
                k: brief.raw.get(k)
                for k in ("species", "age", "personality", "shape_language", "palette", "features")
            }
        }
        rev = provider.complete_json("design_review", ASK_REVIEW, payload, images=[sheet], max_tokens=1200)
    except LLMError:
        return None
    return {
        "reviewer": f"vision:{provider.name}",
        "silhouette_species": str(sil.get("animal", "")),
        "thumbnail_species": str(thu.get("animal", "")),
        "issues": [str(i) for i in rev.get("issues", [])],
        "appeal": rev.get("appeal"),
        "species_fidelity": rev.get("species_fidelity"),
    }


def critique_for(
    brief: Brief,
    sheet_dir: Path,
    provider: Provider | None = None,
) -> dict[str, Any] | None:
    """Live critique when possible, else the recorded one for this exact sheet, else ``None`` (pending)."""
    sheet, sil, thumb = sheet_dir / "sheet.png", sheet_dir / "silhouette.png", sheet_dir / "thumb96.png"
    if provider is not None and all(p.exists() for p in (sheet, sil, thumb)):
        live = ask_vision(provider, brief, sil, thumb, sheet)
        if live:
            (sheet_dir / "critique.json").write_text(
                json.dumps({**live, "sheet": sheet.name, "sheet_sha256": sha256(sheet)}, indent=2) + "\n",
                encoding="utf-8",
            )
            return live
    if sheet.exists():
        return load_recorded(sheet_dir / "critique.json", sheet)
    return None


# --- Blind reads (REVIEW_QUEUE "Blind species read for recorded critiques") ---------------------------------
#
# A reviewer who knows the brief reads "meerkat" into a shape a stranger calls "mongoose". Until a live vision
# key exists, a reader with no context (a fresh sub-agent, a person who hasn't seen the brief) names the animal
# from ``silhouette.png`` alone, then from ``thumb96.png`` alone, with a confidence and what else it could be.
# The answers are recorded next to the images with both files' SHA-256, so a re-render voids them.

BLIND_FILE = "blind_read.json"
BLIND_VIEWS = {"silhouette": "silhouette.png", "thumbnail": "thumb96.png"}
BLIND_CLEAR = 75  # a first-instinct confidence (0-100) below this is a weak read, not a clear one


def record_blind_read(sheet_dir: str | Path, reader: str, **views: dict[str, Any]) -> dict[str, Any]:
    """Record a blind reader's answers, e.g. ``silhouette={"animal": "zebra", "confidence": 50,
    "alternatives": ["horse"]}``, for the images in ``sheet_dir`` as they are now."""
    d = Path(sheet_dir)
    if set(views) != set(BLIND_VIEWS):
        raise ValueError(f"a blind read needs exactly {sorted(BLIND_VIEWS)}")
    out: dict[str, Any] = {"reader": reader}
    for view, fname in BLIND_VIEWS.items():
        a = views[view]
        conf = float(a["confidence"])
        if not 0 <= conf <= 100:
            raise ValueError(f"{view}: confidence {conf} is not 0-100")
        out[view] = {
            "image": fname,
            "sha256": sha256(d / fname),
            "animal": str(a["animal"]),
            "confidence": conf,
            "alternatives": [str(x) for x in a.get("alternatives", [])],
        }
    (d / BLIND_FILE).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def load_blind_read(sheet_dir: str | Path) -> dict[str, Any] | None:
    """The recorded blind read, only if both images are still exactly the ones that were read."""
    d = Path(sheet_dir)
    p = d / BLIND_FILE
    if not p.exists():
        return None
    r = json.loads(p.read_text(encoding="utf-8"))
    for view, fname in BLIND_VIEWS.items():
        if view not in r or not (d / fname).exists() or r[view].get("sha256") != sha256(d / fname):
            return None
    return r


def blind_verdict(brief: Brief, read: dict[str, Any]) -> dict[str, str]:
    """Per view: ``clear`` (named unprompted, confidence ≥ BLIND_CLEAR), ``weak`` (named, but unsure) or
    ``misread`` (another animal, or a known confusion first). The alternatives are reported, not judged:
    the reader was asked what else it could be."""
    out = {}
    for view in BLIND_VIEWS:
        a = read[view]
        ok, _why = reads_as(brief, a["animal"])
        if not ok:
            out[view] = "misread"
        elif a["confidence"] < BLIND_CLEAR:
            out[view] = "weak"
        else:
            out[view] = "clear"
    return out
