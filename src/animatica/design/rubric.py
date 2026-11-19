"""The art-director rubric (DESIGN_STAGE.md §4): score a candidate against its brief, list what fails, and
turn the fixable failures into a :class:`~animatica.design.variants.Morph` edit for the next round.

Checks, each with a weight:

* **proportions** — every brief range (weight 1 each; partial credit just outside the range).
* **features** — every required silhouette/marking feature present (hard).
* **materials** — pattern contrast at least the brief's minimum (hard); no near-black body region except the
  brief's intended accents (hard: the "flat black block" class).
* **shape** — manes and hooves measured on the built meshes: a mane must follow the neck as a skinned ridge
  and stand at most :data:`MANE_STAND_MAX` of the neck's depth (hard: the board/fin class); its crest should
  step at most :data:`MANE_JAG_MAX` between neighbours (soft: saw-tooth); hooves must taper to the coronet
  and slope at the front wall (hard: the puck class).
* **silhouette** (from a rendered sheet, :mod:`.image_checks`) — the side view shows a neck notch between head
  and shoulders (hard: the melted-head class); no floating parts (hard); no large dark blob (hard).
* **face** — each expression (happy, surprised) visibly changes ≥ 3 % of the face close-up (soft: a weak
  expression lowers the score but needs a face-rig edit, not a morph). From the sheet's Blender session
  (``outline``): the near eye stays inside the head's outline in every sheet view (soft, :data:`EYE_OUTLINE_MAX`:
  the googly-eye class) and no brow is drawn beside the head (soft, :data:`BROW_OUTLINE_MAX`: the floating-dash
  class).
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
from animatica.design.fingerprint import staleness
from animatica.design.measure import features, hoof_shape, mane_shape, materials, proportions, shell_shape
from animatica.design.variants import Morph

READY_SCORE = 9.0
APPEAL_MIN = 8.0  # the critic's appeal rating a design needs before the owner sees it
EXPRESSION_MIN = 0.03  # share of the face close-up an expression must visibly change (calibrated 11-17)
HARD_PENALTY = 1.5
# manes and hooves (calibrated 11-18 on Zuri v2 vs v3: board 1.25 / ridge 0.49; puck 100 % / 90 deg vs 72 % / 66)
MANE_STAND_MAX = 0.6  # crest height above the skin / the neck's depth there
MANE_JAG_MAX = 0.2  # biggest crest step between neighbouring stations / the tallest crest
MANE_REACH_MIN = 0.85  # share of withers -> poll the mane's crest must cover (a zebra's runs to the poll)
EYE_OUTLINE_MAX = 0.08  # share of the near eye drawn outside the head's outline, any sheet view (Tembo: 0.02)
BROW_OUTLINE_MAX = 0.25  # share of a brow drawn outside the head's outline, any sheet view
HOOF_TAPER_MAX = 0.85  # coronet width / sole width
HOOF_WALL_MAX = 72.0  # front wall angle from the ground, degrees
# shells (11-19): the full-width band of the sides; a ball 0.65, a half-dome 0.30, Bibi Kobe v3 0.53
SHELL_SHOULDER_MAX = 0.4

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
    out += _part_shape_checks(sp)
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


def _part_shape_checks(sp: Species) -> list[Check]:
    """Manes, hooves and shells, measured on the meshes the build makes (:func:`~animatica.design.measure.mane_shape`,
    :func:`~animatica.design.measure.hoof_shape`, :func:`~animatica.design.measure.shell_shape`). Zuri v2's board mane and puck hooves were caught only by eye
    (review 11-17 15:36); a fixed v3's saw-tooth crest too (review 11-18 03:36)."""
    out: list[Check] = []
    mane = mane_shape(sp)
    if mane is not None:
        ok = bool(mane["follows_neck"])
        out.append(
            Check(
                "shape:mane_follows_neck",
                "shape",
                ok,
                True,
                1.0,
                float(ok),
                "the mane is a ridge skinned along the neck"
                if ok
                else "the mane is a rigid mesh on one neck bone: a board that ignores the neck's curve",
            )
        )
        ok = mane["stand"] <= MANE_STAND_MAX
        out.append(
            Check(
                "shape:mane_fin",
                "shape",
                ok,
                True,
                1.0,
                float(ok),
                f"the mane stands {mane['stand']:.2f} x the neck's depth (max {MANE_STAND_MAX})"
                + ("" if ok else ": a fin or plank, not a short upright mane"),
                mane["stand"],
            )
        )
        if "reach" in mane:
            ok = mane["reach"] >= MANE_REACH_MIN
            out.append(
                Check(
                    "shape:mane_reach",
                    "shape",
                    ok,
                    False,
                    0.5,
                    0.5 * ok,
                    f"the mane runs {mane['reach']:.0%} of the way from the withers to the poll (min {MANE_REACH_MIN:.0%})"
                    + ("" if ok else ": it stops short of the head"),
                    mane["reach"],
                )
            )
        ok = mane["jag"] <= MANE_JAG_MAX
        out.append(
            Check(
                "shape:mane_brush",
                "shape",
                ok,
                False,
                0.5,
                0.5 * ok,
                f"the mane's crest steps {mane['jag']:.0%} between neighbours (max {MANE_JAG_MAX:.0%})"
                + ("" if ok else ": a saw-tooth, not a brush"),
                mane["jag"],
            )
        )
    hoof = hoof_shape(sp)
    if hoof is not None:
        ok = hoof["taper"] <= HOOF_TAPER_MAX and hoof["wall_deg"] <= HOOF_WALL_MAX
        out.append(
            Check(
                "shape:hoof_puck",
                "shape",
                ok,
                True,
                1.0,
                float(ok),
                f"hooves: coronet {hoof['taper']:.0%} of the sole (max {HOOF_TAPER_MAX:.0%}), front wall "
                f"{hoof['wall_deg']:.0f} deg from the ground (max {HOOF_WALL_MAX:g})"
                + ("" if ok else ": flat-walled pucks, not hooves"),
                hoof,
            )
        )
    shell = shell_shape(sp)
    if shell is not None:
        ok = shell["shoulder"] <= SHELL_SHOULDER_MAX
        out.append(
            Check(
                "shape:shell_dome",
                "shape",
                ok,
                False,
                0.5,
                0.5 * ok,
                f"the shell keeps its full width up to {shell['shoulder']:.0%} of its height "
                f"(max {SHELL_SHOULDER_MAX:.0%})"
                + ("" if ok else ": a ball or barrel; a tortoise's dome curves in just above the rim"),
                shell,
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
    ol = img.get("outline")
    if ol:
        for part, limit, what in (
            ("eye", EYE_OUTLINE_MAX, "the eye bulges out of the head (googly)"),
            ("brow", BROW_OUTLINE_MAX, "the brow floats as a dash beside the head"),
        ):
            v = float(ol[part])
            ok = v <= limit
            out.append(
                Check(
                    f"face:{part}_outline",
                    "face",
                    ok,
                    False,
                    0.5,
                    0.5 if ok else 0.5 * max(0.0, 1.0 - (v - limit) / max(limit, 1e-6)),
                    f"{part} {v:.0%} outside the head's outline ({ol.get(f'{part}_view') or 'any'} view; max {limit:.0%})"
                    + ("" if ok else f": {what}"),
                    v,
                )
            )
    for expr in ("happy", "surprised"):
        k = f"expression_{expr}"
        if k in img:
            v = float(img[k])
            ok = v >= EXPRESSION_MIN
            out.append(
                Check(
                    f"face:{expr}",
                    "face",
                    ok,
                    False,
                    1.0,
                    1.0 if ok else round(v / EXPRESSION_MIN, 3),
                    f"{expr} changes {v:.1%} of the face close-up (min {EXPRESSION_MIN:.0%})"
                    + ("" if ok else ": the expression doesn't read"),
                    v,
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
    if critique.get("appeal") is not None:
        a = float(critique["appeal"])
        ok = a >= APPEAL_MIN
        out.append(
            Check(
                "critic:appeal",
                "appeal",
                ok,
                False,
                2.0,
                round(2.0 * min(a, 10.0) / 10.0, 3),
                f"art-director appeal {a:g}/10 (min {APPEAL_MIN:g})",
                a,
            )
        )
    return out


def _freshness_checks(stress: dict[str, Any], sp: Species) -> list[Check]:
    """Is the stress report about *this* design? Hard when it measured other species parameters (or carries no
    fingerprint); soft when only the shared rig/face code changed since (review 11-18 03:36: the v3 brows)."""
    st = staleness(stress, sp)
    out = [
        Check(
            "motion:fresh",
            "motion",
            st["species_ok"],
            True,
            1.0,
            1.0 if st["species_ok"] else 0.0,
            "the rig stress report measured these species parameters"
            if st["species_ok"]
            else (
                "the rig stress report measured other species parameters: re-run scripts/rig_stress_test.py"
                if st["recorded"]
                else "the rig stress report has no fingerprint: re-run scripts/rig_stress_test.py"
            ),
        )
    ]
    if st["species_ok"]:
        out.append(
            Check(
                "motion:fresh_code",
                "motion",
                st["code_ok"],
                False,
                0.5,
                0.5 if st["code_ok"] else 0.0,
                "the rig code is the one the stress test ran"
                if st["code_ok"]
                else "the rig/face code changed since the stress test ran: re-run scripts/rig_stress_test.py",
            )
        )
    return out


def _motion_checks(stress: dict[str, Any]) -> list[Check]:
    """The rig stress test (DESIGN_STAGE §5, ``scripts/rig_stress_test.py``): one check per measured class."""
    return [
        Check(
            f"motion:{c['id']}",
            "motion",
            bool(c["passed"]),
            bool(c.get("hard", True)),
            1.0,
            1.0 if c["passed"] else 0.0,
            str(c["message"]),
            c.get("value"),
        )
        for c in stress.get("checks", [])
    ]


def score(
    brief: Brief,
    sp: Species,
    image_metrics: dict[str, Any] | None = None,
    critique: dict[str, Any] | None = None,
    stress: dict[str, Any] | None = None,
) -> Result:
    """Rubric result. ``stress`` is a rig stress-test report; without one, motion is simply not scored here (the
    design packet always passes it, so nothing reaches the owner unmeasured)."""
    checks = _range_checks(brief, sp) + _design_checks(brief, sp)
    if stress:
        checks += _freshness_checks(stress, sp) + _motion_checks(stress)
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
        elif (
            c.group in ("proportions", "features", "shape", "face", "appeal") or c.id == "silhouette:floating"
        ):
            manual.append(c.message)
    for note in (critique or {}).get("issues", []):
        manual.append(f"critic: {note}")
    return Result(
        character=brief.character,
        score=round(s, 2),
        ready=s >= READY_SCORE
        and not hard
        and not pending
        and all(c.passed for c in checks if c.group == "appeal"),
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
