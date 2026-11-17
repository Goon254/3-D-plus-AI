"""Critic checks for the cast's rigs, measured on the deformed meshes in Blender (``inspect``):

* ``eye_socket``: each eyeball sits 50-80 % deep in the skin (target 65 %), at every inspected frame, and its
  depth does not drift more than :data:`EYE_DRIFT` of the diameter as the head and neck move (an eye that
  "pops" out of its socket when the rig bends). ``brow_float`` / ``lid_float``: a brow or lid whose closest
  point is more than :data:`SKIN_GAP` of its size off the skin.
* ``texture_swim``: the texture coordinates of each deforming coat (zebra stripes, giraffe patches, tortoise
  scales) must not move as the rig deforms: p95 drift under :data:`SWIM_P95` metres. Coats that read
  ``rest_position`` measure 0; Object coordinates (the deformed position) measure the full body motion.

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


def deforming_meshes(meta: CreatureMeta) -> list[str]:
    """The skinned meshes whose texture could swim: the body (and the elephant's trunk)."""
    out = [f"{meta.cid}_body"]
    if meta.trunk_bones:
        out.append(f"{meta.cid}_trunk")
    return out


def rig_probe(meta: CreatureMeta, frames: list[int], brows: bool = True) -> dict[str, Any]:
    """An ``inspect`` op measuring eye seating, brow/lid contact and coat swim over ``frames``."""
    surf = meta.head_surface or f"{meta.cid}_body"
    seating = [{"target": e, "surface": surf, "kind": "eye"} for e in meta.eyes]
    seating += [{"target": lid, "surface": surf, "kind": "skin"} for lid in meta.lids]
    if brows:
        seating += [{"target": f"{meta.cid}_brow_{s}", "surface": surf, "kind": "skin"} for s in ("L", "R")]
    return {
        "op": "inspect",
        "subjects": [meta.root],
        "frames": frames,
        "seating": seating,
        "swim": deforming_meshes(meta),
    }


def rig_checks(report: dict[str, Any], shot: str = "rig") -> tuple[list[Issue], dict[str, Any]]:
    """Issues from an ``inspect`` report made by :func:`rig_probe`, plus a summary (worst values)."""
    issues: list[Issue] = []
    embeds: dict[str, list[float]] = {}
    gaps: dict[str, list[float]] = {}
    swim: dict[str, float] = {}
    for fr in report.get("frames", {}).values():
        for tid, v in (fr.get("seating") or {}).items():
            if "embed" in v:
                embeds.setdefault(tid, []).append(v["embed"])
            elif "gap" in v:
                gaps.setdefault(tid, []).append(v["gap"] / max(v["size"], 1e-6))
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
    for tid, gs in gaps.items():
        if max(gs) > SKIN_GAP:
            kind = "brow_float" if "_brow_" in tid else "lid_float"
            issues.append(
                Issue(shot, kind, "warning", f"{tid} floats {max(gs):.0%} of its size off the skin")
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
