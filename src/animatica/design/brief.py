"""Design briefs: ``design/<character>/brief.json`` — what a character must measure and read as.

A brief is the research step's measurable output (DESIGN_STAGE.md §2): appeal ranges for the
:func:`~animatica.design.measure.proportions` ratios, silhouette features that must be present, the palette
and pattern-contrast targets, which near-black parts are intended (``dark_ok``), the silhouette checks, the
names a viewer must say unprompted (``read_as.names``) and the known confusions, and legal reference images.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from animatica.design.measure import proportions

DESIGN_DIR = Path(__file__).resolve().parents[3] / "design"
METRICS = frozenset(
    {
        "head_body",
        "eye_head",
        "eye_spacing",
        "neck_head",
        "elongation",
        "belly_gap",
        "leg_thickness",
        "ear_head",
        "neck_length",
        "snout",
    }
)


class BriefError(ValueError):
    pass


# Reference images (DESIGN_STAGE.md §2): free licences only. A link may be CC0, public domain, CC BY or
# CC BY-SA (with the author, which those licences require); a copy inside the repo (``local``) only CC0 or
# public domain, and attributed. NC / ND and unknown licences are refused (docs/research licence traps).
_COPYABLE = ("cc0", "public domain", "pd")
_LINKABLE = ("cc by ", "cc by-sa ")


def licence_kind(licence: str) -> str | None:
    """``"copyable"`` (CC0 / public domain), ``"linkable"`` (CC BY / CC BY-SA, any version) or ``None``."""
    s = " ".join(licence.lower().replace("_", " ").split())
    if s in _COPYABLE or s.startswith(("cc0 ", "public domain ", "pd-")):
        return "copyable"
    if any(s.startswith(p) for p in _LINKABLE) and not any(t in s for t in ("-nc", " nc", "-nd", " nd")):
        return "linkable"
    return None


def check_reference(character: str, ref: dict[str, Any]) -> None:
    """Raise :class:`BriefError` unless ``ref`` is a reference a design brief may carry."""
    if not ref.get("url") or not ref.get("license"):
        raise BriefError(f"{character}: every reference needs a url and a license")
    kind = licence_kind(str(ref["license"]))
    if kind is None:
        raise BriefError(f"{character}: reference {ref['url']} has a non-free licence {ref['license']!r}")
    if kind == "linkable" and not ref.get("author"):
        raise BriefError(f"{character}: reference {ref['url']} is {ref['license']}, which needs its author")
    if ref.get("local"):
        if kind != "copyable":
            raise BriefError(
                f"{character}: reference {ref['url']} is {ref['license']}: link it, never copy it into the repo"
            )
        if not (ref.get("author") or ref.get("source")):
            raise BriefError(f"{character}: a copied reference must be attributed (author or source)")


@dataclass(frozen=True)
class Brief:
    character: str
    species: str
    ranges: dict[str, tuple[float, float]]
    features: tuple[str, ...]
    names: tuple[str, ...]
    confusions: tuple[str, ...] = ()
    pattern_contrast_min: dict[str, float] = field(default_factory=dict)
    dark_ok: tuple[str, ...] = ()
    neck_notch_min: float | None = None
    max_floating_parts: int = 0
    references: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Brief:
        for k in ("character", "species", "ranges", "features", "read_as"):
            if k not in d:
                raise BriefError(f"brief is missing {k!r}")
        ranges = {}
        for m, r in d["ranges"].items():
            if m not in METRICS:
                raise BriefError(f"{d['character']}: unknown metric {m!r}")
            lo, hi = float(r[0]), float(r[1])
            if lo > hi:
                raise BriefError(f"{d['character']}: range for {m} is inverted ({lo} > {hi})")
            ranges[m] = (lo, hi)
        for ref in d.get("references", []):
            check_reference(d["character"], ref)
        sil = d.get("silhouette", {})
        names = tuple(n.lower() for n in d["read_as"].get("names", []))
        if not names:
            raise BriefError(f"{d['character']}: read_as.names is empty")
        return cls(
            character=d["character"],
            species=d["species"],
            ranges=ranges,
            features=tuple(d["features"]),
            names=names,
            confusions=tuple(n.lower() for n in d["read_as"].get("confusions", [])),
            pattern_contrast_min={k: float(v) for k, v in d.get("pattern_contrast_min", {}).items()},
            dark_ok=tuple(d.get("dark_ok", [])),
            neck_notch_min=sil.get("side_neck_notch_min"),
            max_floating_parts=int(sil.get("max_floating_parts", 0)),
            references=tuple(d.get("references", [])),
            raw=d,
        )

    def target(self, metric: str) -> float:
        lo, hi = self.ranges[metric]
        return (lo + hi) / 2


def load_brief(character: str, root: Path | None = None) -> Brief:
    p = (root or DESIGN_DIR) / character / "brief.json"
    return Brief.from_dict(json.loads(p.read_text(encoding="utf-8")))


def all_briefs(root: Path | None = None) -> dict[str, Brief]:
    base = root or DESIGN_DIR
    return {p.parent.name: load_brief(p.parent.name, base) for p in sorted(base.glob("*/brief.json"))}


def in_range(brief: Brief, metric: str, value: float) -> bool:
    lo, hi = brief.ranges[metric]
    return lo <= value <= hi


def unmet_ranges(brief: Brief, sp: Any) -> dict[str, tuple[float, float, float]]:
    """metric -> (value, lo, hi) for every brief range the species misses."""
    p = proportions(sp)
    return {m: (p[m], *brief.ranges[m]) for m in brief.ranges if not in_range(brief, m, p[m])}
