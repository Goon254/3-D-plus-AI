"""Critic checks for the cast's rigs, measured on the deformed meshes in Blender (``inspect``):

* ``eye_socket``: each eyeball sits 50-80 % deep in the skin (target 65 %), at every inspected frame, and its
  depth does not drift more than :data:`EYE_DRIFT` of the diameter as the head and neck move (an eye that
  "pops" out of its socket when the rig bends). ``brow_float`` / ``lid_float``: a brow or lid whose closest
  point is more than :data:`SKIN_GAP` of its size off the skin.
* ``part_float``: an appendage (ear, mane, ossicone, muzzle, nose) whose closest point is more than
  :data:`PART_GAP` of its size off the mesh it grows from (:func:`part_seating`). Zuri v2's ears hovered 3.6 cm
  (20 %) above her head in the packet's motion test and no check saw it: the side silhouette hides the gap.
* ``texture_swim``: the texture coordinates of each deforming coat (zebra stripes, giraffe patches, tortoise
  scales) must not move as the rig deforms: p95 drift under :data:`SWIM_P95` metres. Coats that read
  ``rest_position`` measure 0; Object coordinates (the deformed position) measure the full body motion.

* outline (design sheets, :func:`outline_probe` / :func:`outline_summary`): how much of each eye and brow is drawn
  outside the head's outline from each sheet view. A near eye that breaks the outline is the googly-eye class; a
  brow outside it reads as a dash floating in the air (cloud reviews 11-18 15:36, 18:36, 21:36).

``rig_probe`` builds the ``inspect`` op; ``rig_checks`` turns its report into :class:`~animatica.agents.critic.Issue`.
"""

from __future__ import annotations

from typing import Any

from ..agents.critic import Issue
from .build import CreatureMeta

EYE_EMBED = (0.5, 0.8)
EYE_DRIFT = 0.1  # share of the eye's diameter
SKIN_GAP = 0.12  # share of the brow's / lid's size
SWIM_P95 = 0.002  # metres
PART_GAP = 0.03  # share of the part's size: an appendage must touch (or sink into) what it grows from


def deforming_meshes(meta: CreatureMeta) -> list[str]:
    """The skinned meshes whose texture could swim: the body (and the elephant's trunk)."""
    out = [f"{meta.cid}_body"]
    if meta.trunk_bones:
        out.append(f"{meta.cid}_trunk")
    return out


def part_seating(meta: CreatureMeta, extras: list[str], muzzle: bool) -> list[dict[str, str]]:
    """``skin`` seating pairs for the appendages: each ear, extra (by id, as in ``Species.extras``) and the
    muzzle against the mesh it grows from. Ears grow from the body mesh even where the head is separate
    (the elephant's sit on the neck), ossicone tips from their ossicone, the nose from the muzzle."""
    cid, body = meta.cid, f"{meta.cid}_body"
    pairs = [{"target": f"{cid}_{b}", "surface": body, "kind": "skin"} for b in meta.ear_bones]
    if muzzle:
        pairs.append({"target": f"{cid}_muzzle", "surface": body, "kind": "skin"})
    for ex in extras:
        if ex.startswith("ossitip_"):
            surf = f"{cid}_ossicone_{ex.rsplit('_', 1)[1]}"
        elif ex == "nose" and muzzle:
            surf = f"{cid}_muzzle"
        else:
            surf = body
        pairs.append({"target": f"{cid}_{ex}", "surface": surf, "kind": "skin"})
    return pairs


def rig_probe(
    meta: CreatureMeta, frames: list[int], brows: bool = True, parts: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """An ``inspect`` op measuring eye seating, brow/lid contact, appendage contact (``parts``, from
    :func:`part_seating`) and coat swim over ``frames``."""
    surf = meta.head_surface or f"{meta.cid}_body"
    seating = [{"target": e, "surface": surf, "kind": "eye"} for e in meta.eyes]
    seating += [{"target": lid, "surface": surf, "kind": "skin"} for lid in meta.lids]
    if brows:
        seating += [{"target": f"{meta.cid}_brow_{s}", "surface": surf, "kind": "skin"} for s in ("L", "R")]
    seating += parts or []
    return {
        "op": "inspect",
        "subjects": [meta.root],
        "frames": frames,
        "seating": seating,
        "swim": deforming_meshes(meta),
    }


def rig_checks(
    report: dict[str, Any], shot: str = "rig", parts: list[dict[str, str]] | None = None
) -> tuple[list[Issue], dict[str, Any]]:
    """Issues from an ``inspect`` report made by :func:`rig_probe`, plus a summary (worst values)."""
    issues: list[Issue] = []
    embeds: dict[str, list[float]] = {}
    gaps: dict[str, list[float]] = {}
    worst_at: dict[str, tuple[float, str]] = {}  # the frame of each part's biggest gap, for the message
    swim: dict[str, float] = {}
    for fkey, fr in report.get("frames", {}).items():
        for tid, v in (fr.get("seating") or {}).items():
            if "embed" in v:
                embeds.setdefault(tid, []).append(v["embed"])
            elif "gap" in v:
                g = v["gap"] / max(v["size"], 1e-6)
                gaps.setdefault(tid, []).append(g)
                if g > worst_at.get(tid, (-1.0, ""))[0]:
                    worst_at[tid] = (g, str(fkey))
        for mid, v in (fr.get("swim") or {}).items():
            swim[mid] = max(swim.get(mid, 0.0), v["p95"])
    for tid, es in embeds.items():
        lo, hi = min(es), max(es)
        if lo < EYE_EMBED[0] or hi > EYE_EMBED[1]:
            issues.append(
                Issue(
                    shot,
                    "eye_socket",
                    "error",
                    f"{tid} is {lo:.0%}-{hi:.0%} deep in the skin (want {EYE_EMBED[0]:.0%}-{EYE_EMBED[1]:.0%})",
                )
            )
        elif hi - lo > EYE_DRIFT:
            issues.append(
                Issue(
                    shot, "eye_socket", "error", f"{tid} moves in its socket by {hi - lo:.0%} of its diameter"
                )
            )
    part_ids = {p["target"] for p in parts or []}
    for tid, gs in gaps.items():
        if tid in part_ids:
            if max(gs) > PART_GAP:
                issues.append(
                    Issue(shot, "part_float", "error", f"{tid} floats {max(gs):.0%} of its size off its base")
                )
            continue
        if max(gs) > SKIN_GAP:
            kind = "brow_float" if "_brow_" in tid else "lid_float"
            issues.append(
                Issue(
                    shot,
                    kind,
                    "warning",
                    f"{tid} floats {max(gs):.0%} of its size off the skin (frame {worst_at[tid][1]})",
                )
            )
    for mid, p95 in swim.items():
        if p95 > SWIM_P95:
            issues.append(
                Issue(shot, "texture_swim", "error", f"{mid}'s coat pattern slides {p95 * 1000:.1f} mm (p95)")
            )
    summary = {
        "eye_embed": {k: [round(min(v), 3), round(max(v), 3)] for k, v in embeds.items()},
        "skin_gap": {k: round(max(v), 3) for k, v in gaps.items()},
        "swim_p95_mm": {k: round(v * 1000, 2) for k, v in swim.items()},
    }
    return issues, summary


def outline_probe(
    meta: CreatureMeta,
    brows: list[str],
    views: dict[str, tuple[float, float, float]],
    frame: int = 1,
    backdrop: bool = False,
) -> dict[str, Any]:
    """An ``inspect`` op measuring, from each of ``views`` (name -> direction toward the camera), the share of each
    eye and brow that lies outside the head surface's outline.

    ``backdrop``: the brows only, against the head *and* the eyes and lids: the share drawn against the backdrop.
    In a 3/4 view the far eye peeks past the far cheek (a drawing convention the eye measure allows), and its brow
    sits on it: outside the head's outline, but drawn on the eye, not floating in the air (DECISIONS #115)."""
    surf = meta.head_surface or f"{meta.cid}_body"
    surfaces = [surf]
    targets = list(meta.eyes) + list(brows)
    if backdrop:
        surfaces += list(meta.eyes) + [lid for lid in meta.lids if lid.endswith("_up")]
        targets = list(brows)
    return {
        "op": "inspect",
        "subjects": [meta.root],
        "frames": [frame],
        "outline": [
            {"target": t, "surfaces": surfaces, "views": [list(v) for v in views.values()]} for t in targets
        ],
    }


def backdrop_summary(report: dict[str, Any], views: list[str], brows: list[str]) -> dict[str, Any]:
    """From a ``backdrop`` probe: per view the worst brow's share drawn against the backdrop, and the worst view."""
    fr = next(iter(report["frames"].values()))["outline"]
    per = {
        name: max((fr[t]["views"][i] for t in brows if t in fr), default=0.0) for i, name in enumerate(views)
    }
    worst = max(per, key=lambda k: per[k]) if per else ""
    return {"views": per, "brow_backdrop": round(per.get(worst, 0.0), 3), "brow_backdrop_view": worst}


def outline_summary(
    report: dict[str, Any], views: list[str], eyes: list[str], brows: list[str]
) -> dict[str, Any]:
    """Per view: the near eye's share outside the head's outline (the smaller of the two: in a 3/4 view the far
    eye peeking past the far cheek is a drawing convention) and the worst brow's. ``eye`` / ``brow`` are the
    worst over the views, with the view named."""
    fr = next(iter(report["frames"].values()))["outline"]
    out: dict[str, Any] = {"views": {}}
    worst = {"eye": (0.0, ""), "brow": (0.0, "")}
    for i, name in enumerate(views):
        e = [fr[t]["views"][i] for t in eyes if t in fr]
        b = [fr[t]["views"][i] for t in brows if t in fr]
        row = {"eye": min(e) if e else 0.0, "brow": max(b) if b else 0.0}
        out["views"][name] = row
        for k in worst:
            if row[k] > worst[k][0]:
                worst[k] = (row[k], name)
    for k, (v, name) in worst.items():
        out[k] = round(v, 3)
        out[f"{k}_view"] = name
    return out
