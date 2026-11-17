"""The art-director rubric (DESIGN_STAGE.md §4): score a candidate against its brief, list what fails, and
turn the fixable failures into a :class:`~animatica.design.variants.Morph` edit for the next round.

Checks, each with a weight:

* **proportions** — every brief range (weight 1 each; partial credit just outside the range).
* **features** — every required silhouette/marking feature present (hard).
* **materials** — pattern contrast at least the brief's minimum (hard); no near-black body region except the
  brief's intended accents (hard: the "flat black block" class).
* **silhouette** (from a rendered sheet, :mod:`.image_checks`) — the side view shows a neck notch between head
  and shoulders (hard: the melted-head class); no floating parts (hard); no large dark blob (hard).
* **species read** (from the vision critic, :mod:`.critic`) — the silhouette and the 96 px thumbnail are each
  named as the species unprompted (hard).

``score`` is 0–10: the weighted pass fraction × 10, minus 1.5 per hard failure. A design is ``ready`` for the
owner only with score ≥ 9, no hard failure and a completed species read.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from animatica.creatures.species import Species
from animatica.design.brief import Brief
from animatica.design.measure import features, materials, proportions
from animatica.design.variants import Morph

READY_SCORE = 9.0
HARD_PENALTY = 1.5

# metric -> morph field that changes it, and the exponent of the response (area metrics move as k^2)
LEVERS: dict[str, tuple[str, float]] = {
    "head_body": ("head", 1.0),
    "eye_head": ("eye", 1.0),
    "ear_head": ("ear", 2.0),
    "neck_head": ("neck", 1.0),
    "leg_thickness": ("leg", 1.0),
    "snout": ("snout", 1.0),
}
STEP = (0.85, 1.2)  # one round never changes a part by more than this


@dataclass
class Check:
    id: str
    group: str
    passed: bool
    hard: bool
    weight: float
    earned: float
    message: str
    value: Any = None
    fix: dict[str, float] | None = None  # morph fields to multiply (or set, for lift_dark)


@dataclass
class Result:
    character: str
    score: float
    ready: bool
    hard_failures: list[str]
    pending: list[str]
    checks: list[Check] = field(default_factory=list)
    edit: dict[str, float] = field(default_factory=dict)
    manual: list[str] = field(default_factory=list)  # failures no morph can fix (base-mesh edits)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["checks"] = [asdict(c) for c in self.checks]
        return d


def _range_checks(brief: Brief, sp: Species) -> list[Check]:
    p = proportions(sp)
    out = []
    for m, (lo, hi) in brief.ranges.items():
        v = p[m]
        width = max(hi - lo, 1e-6)
        miss = lo - v if v < lo else v - hi if v > hi else 0.0
        earned = 1.0 if miss == 0 else max(0.0, 1.0 - miss / (0.5 * width))
        fix = None
        if miss and m in LEVERS:
            lever, power = LEVERS[m]
            target = lo + 0.25 * width if v < lo else hi - 0.25 * width
            k = (target / v) ** (1 / power) if v > 0 else STEP[1]
            fix = {lever: round(min(STEP[1], max(STEP[0], k)), 4)}
        side = "below" if v < lo else "above"
        out.append(
            Check(
                id=f"range:{m}",
                group="proportions",
                passed=miss == 0,
                hard=False,
                weight=1.0,
                earned=round(earned, 3),
                message=f"{m} {v:.3f} in [{lo}, {hi}]" if miss == 0 else f"{m} {v:.3f} {side} [{lo}, {hi}]",
                value=v,
                fix=fix,
            )
        )
    return out


def _design_checks(brief: Brief, sp: Species) -> list[Check]:
    out = []
    have = features(sp)
    for f in brief.features:
        ok = f in have
        out.append(
            Check(
                f"feature:{f}", "features", ok, True, 1.0, float(ok), f"{f} {'present' if ok else 'MISSING'}"
            )
        )
    mats = materials(sp)
    for key, need in brief.pattern_contrast_min.items():
        got = mats["pattern_contrast"].get(key, 1.0)
        ok = got >= need
        out.append(
            Check(
                f"contrast:{key}",
                "materials",
                ok,
                True,
                1.0,
                float(ok),
                f"{key} pattern contrast {got} (min {need})",
                got,
            )
        )
    dark = [d for d in mats["dark_regions"] if d["material"] not in brief.dark_ok]
    ok = not dark
    msg = (
        "no near-black body regions"
        if ok
        else "near-black body regions read as flat black blocks: "
        + ", ".join(f"{d['material']} on {'/'.join(d['bones'])}" for d in dark)
    )
    out.append(
        Check(
            "materials:flat_black",
            "materials",
            ok,
            True,
            1.0,
            float(ok),
            msg,
            dark,
            None if ok else {"lift_dark": 0.7},
        )
    )
    return out


def _image_checks(brief: Brief, img: dict[str, Any]) -> list[Check]:
    out = []
    if brief.neck_notch_min is not None and "neck_notch" in img:
        v = float(img["neck_notch"])
        ok = v >= brief.neck_notch_min
        out.append(
            Check(
                "silhouette:neck_notch",
                "silhouette",
                ok,
                True,
                1.5,
                1.5 * ok,
                f"side neck notch {v:.3f} (min {brief.neck_notch_min}): head {'separate from' if ok else 'MELTS INTO'} the body",
                v,
                None if ok else {"neck": 0.9},
            )
        )
    if "floating_parts" in img:
        n = int(img["floating_parts"])
        ok = n <= brief.max_floating_parts
        out.append(
            Check("silhouette:floating", "silhouette", ok, True, 1.0, float(ok), f"{n} floating part(s)", n)
        )
    if "dark_blob" in img:
        v = float(img["dark_blob"])
        ok = v <= 0.12
        out.append(
            Check(
                "materials:dark_blob",
                "materials",
                ok,
                True,
                1.0,
                float(ok),
                f"largest near-black blob {v:.0%} of the figure (max 12%)",
                v,
                None if ok else {"lift_dark": 0.7},
            )
        )
    return out


def _read_checks(brief: Brief, critique: dict[str, Any]) -> list[Check]:
    from animatica.design.critic import reads_as

    out = []
    for view in ("silhouette", "thumbnail"):
        said = str(critique.get(f"{view}_species", ""))
        ok, why = reads_as(brief, said)
        out.append(
            Check(
                f"read:{view}",
                "species read",
                ok,
                True,
                2.0,
                2.0 * ok,
                f"{view} read as {said!r}: {why}",
                said,
            )
        )
    return out


def score(
    brief: Brief,
    sp: Species,
    image_metrics: dict[str, Any] | None = None,
    critique: dict[str, Any] | None = None,
) -> Result:
    checks = _range_checks(brief, sp) + _design_checks(brief, sp)
    pending = []
    if image_metrics:
        checks += _image_checks(brief, image_metrics)
    else:
        pending.append("silhouette")
    if critique and critique.get("silhouette_species") and critique.get("thumbnail_species"):
        checks += _read_checks(brief, critique)
    else:
        pending.append("species read")
    total = sum(c.weight for c in checks)
    earned = sum(c.earned for c in checks)
    hard = [c.id for c in checks if c.hard and not c.passed]
    s = max(0.0, min(10.0, 10.0 * earned / total - HARD_PENALTY * len(hard)))
    edit: dict[str, float] = {}
    manual = []
    for c in checks:
        if c.passed:
            continue
        if c.fix:
            for k, v in c.fix.items():
                edit[k] = max(edit.get(k, 0.0), v) if k == "lift_dark" else edit.get(k, 1.0) * v
        elif c.group in ("proportions", "features") or c.id == "silhouette:floating":
            manual.append(c.message)
    for note in (critique or {}).get("issues", []):
        manual.append(f"critic: {note}")
    return Result(
        character=brief.character,
        score=round(s, 2),
        ready=s >= READY_SCORE and not hard and not pending,
        hard_failures=hard,
        pending=pending,
        checks=checks,
        edit={k: round(v, 4) for k, v in edit.items()},
        manual=manual,
    )


def edit_morph(current: Morph, edit: dict[str, float]) -> Morph:
    """Apply a rubric edit to the current morph (multipliers compose; ``lift_dark`` takes the max)."""
    step = Morph(**{k: v for k, v in edit.items() if k != "lift_dark"}, lift_dark=edit.get("lift_dark", 0.0))
    return current.combine(step)
