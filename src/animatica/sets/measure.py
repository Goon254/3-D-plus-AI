"""Set assets measured as built, before anything renders (DESIGN_STAGE §8: a human catch becomes a check).

The acacia canopy is a metaball mesh (``create_metaball_mesh``). Blender's metaball field is evaluated here
exactly as the adapter builds it (``op_create_metaball_mesh``: per element ``stiffness · (1 − d²/r²)³`` with ``d``
in the element's frame divided by its ``size``, summed, surface at ``threshold``), on a voxel grid, so the shape
is measured without Blender. The displace modifier the set adds afterwards (leafy edges, a few cm) is not
modelled; it roughens the outline but does not change the shape language measured here.

Three numbers per canopy (:func:`canopy_shape`), each from a human catch:

* ``table``: the crown's width over its depth in the narrowest of eight side views. An umbrella thorn's crown is
  a flat table; a ball or a dome reads as a garden tree.
* ``sky``: in the worst side view, the share of the crown's outline (row by row, between its left and right
  edge) where sky shows through. One solid cushion (the 11-16 set) shows none; the owner asked for clumps with
  gaps (DECISIONS #51).
* ``round``: the share of the canopy's volume in separate clumps that are less than ``FLORET_MIN`` times as
  wide as they are thick: round florets on a stalk read as broccoli (the owner's note on the 11-17 clumps).

Calibration (seeds 1-79, scales 1.0 and 0.85; DECISIONS #98): the 11-16 cushion fails ``sky`` (0 %), the 11-17
clumps fail ``round`` (8-64 %, roundest floret 1.4-2.3:1), the 11-18 layered tables pass everything (table
6.4-7.6, sky 14-25 %, round 0 %, roundest 3.0-3.5:1).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

TABLE_MIN = 3.0  # crown width / depth in every side view
SKY_MIN = 0.05  # share of the side outline where sky shows through, worst view
FLORET_MIN = 2.6  # a clump at least this many times as wide as it is thick is a shelf, not a floret
ROUND_MAX = 0.05  # share of the canopy's volume allowed in round florets
SIDE_VIEWS = 8  # side directions, every 22.5°


def _element_box(el: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    half = float(el["radius"]) * np.asarray(el.get("size") or (1.0, 1.0, 1.0), float)
    co = np.asarray(el["co"], float)
    return co - half, co + half


def metaball_grid(
    elements: list[dict[str, Any]], step: float, threshold: float = 0.6
) -> tuple[np.ndarray, np.ndarray]:
    """Voxels inside the metaball surface: a boolean grid (x, y, z) and the world position of voxel (0, 0, 0).

    Only ellipsoid and ball elements without rotation are supported (what the set uses); anything else raises.
    """
    boxes = []
    for el in elements:
        kind = el.get("type", "ball").lower()
        if kind not in ("ball", "ellipsoid") or any(el.get("rotation") or ()) or el.get("negative"):
            raise ValueError(f"unsupported metaball element for measuring: {el!r}")
        boxes.append(_element_box(el))
    lo = np.min([b[0] for b in boxes], axis=0) - step
    hi = np.max([b[1] for b in boxes], axis=0) + step
    shape = tuple(int(n) for n in np.ceil((hi - lo) / step) + 1)
    field = np.zeros(shape, np.float32)
    for el, (b0, b1) in zip(elements, boxes, strict=True):
        i0 = np.maximum(np.floor((b0 - lo) / step).astype(int), 0)
        i1 = np.minimum(np.ceil((b1 - lo) / step).astype(int) + 1, shape)
        axes = [lo[k] + step * np.arange(i0[k], i1[k]) for k in range(3)]
        size = np.asarray(el.get("size") or (1.0, 1.0, 1.0), float)
        if el.get("type", "ball").lower() == "ball":
            size = np.ones(3)
        dx, dy, dz = ((axes[k] - el["co"][k]) / size[k] for k in range(3))
        q = (
            1.0
            - (dx[:, None, None] ** 2 + dy[None, :, None] ** 2 + dz[None, None, :] ** 2)
            / float(el["radius"]) ** 2
        )
        np.clip(q, 0.0, None, out=q)
        field[i0[0] : i1[0], i0[1] : i1[1], i0[2] : i1[2]] += float(el.get("stiffness", 2.0)) * q**3
    return field >= threshold, lo


def components(grid: np.ndarray) -> list[np.ndarray]:
    """Face-connected clumps of a voxel grid, each as an (n, 3) array of voxel indices."""
    label = np.zeros(grid.shape, np.int32)
    out = []
    nx, ny, nz = grid.shape
    for start in zip(*np.nonzero(grid), strict=True):
        if label[start]:
            continue
        label[start] = len(out) + 1
        stack, pts = [start], []
        while stack:
            x, y, z = stack.pop()
            pts.append((x, y, z))
            for q in (
                (x + 1, y, z),
                (x - 1, y, z),
                (x, y + 1, z),
                (x, y - 1, z),
                (x, y, z + 1),
                (x, y, z - 1),
            ):
                if 0 <= q[0] < nx and 0 <= q[1] < ny and 0 <= q[2] < nz and grid[q] and not label[q]:
                    label[q] = label[start]
                    stack.append(q)
        out.append(np.asarray(pts))
    return out


def side_outline(grid: np.ndarray, angle: float) -> np.ndarray:
    """The canopy seen from the side along ``angle`` (radians, in the ground plane), orthographic: a boolean
    image indexed (horizontal position across the view, height)."""
    cols = grid.any(axis=2)
    xs, ys = np.nonzero(cols)
    u = -math.sin(angle) * xs + math.cos(angle) * ys
    ub = np.round(u - u.min()).astype(int)
    img = np.zeros((int(ub.max()) + 1, grid.shape[2]), bool)
    for b, x, y in zip(ub, xs, ys, strict=True):
        img[b] |= grid[x, y]
    return img


def canopy_shape(elements: list[dict[str, Any]], step: float) -> dict[str, Any]:
    """``table``, ``sky`` and ``round`` (see the module docstring) plus the clump count and the roundest clump."""
    grid, _ = metaball_grid(elements, step)
    if not grid.any():
        raise ValueError("the canopy's metaballs produce no surface")
    zs = np.nonzero(grid.any(axis=(0, 1)))[0]
    depth = zs[-1] - zs[0] + 1
    tables, skies = [], []
    for k in range(SIDE_VIEWS):
        img = side_outline(grid, math.pi * k / SIDE_VIEWS)
        cs = np.nonzero(img.any(axis=1))[0]
        tables.append((cs[-1] - cs[0] + 1) / depth)
        span = 0
        for row in img.T:
            r = np.nonzero(row)[0]
            if len(r):
                span += r[-1] - r[0] + 1
        skies.append(1.0 - img.sum() / span)
    flats, vols = [], []
    for c in components(grid):
        thick = np.ptp(c[:, 2]) + 1
        wide = max(np.ptp(c[:, 0]), np.ptp(c[:, 1])) + 1
        flats.append(wide / thick)
        vols.append(len(c))
    flats_a, vols_a = np.asarray(flats), np.asarray(vols)
    return {
        "table": round(float(min(tables)), 2),
        "sky": round(float(min(skies)), 3),
        "round": round(float(vols_a[flats_a < FLORET_MIN].sum() / vols_a.sum()), 3),
        "clumps": len(flats),
        "roundest": round(float(flats_a.min()), 2),
    }


def canopy_problems(shape: dict[str, Any]) -> list[str]:
    """What a canopy measurement fails, in words (empty when it passes)."""
    out = []
    if shape["table"] < TABLE_MIN:
        out.append(f"crown {shape['table']:.1f}:1 wide to deep (a flat table is >= {TABLE_MIN:.0f}:1)")
    if shape["sky"] < SKY_MIN:
        out.append(f"one solid cushion: {shape['sky']:.0%} sky through the crown (min {SKY_MIN:.0%})")
    if shape["round"] > ROUND_MAX:
        out.append(
            f"broccoli: {shape['round']:.0%} of the canopy in round florets under {FLORET_MIN:.1f}:1 "
            f"(max {ROUND_MAX:.0%})"
        )
    return out


_CACHE: dict[tuple[float, int], dict[str, Any]] = {}


def acacia_shape(scale: float, seed: int) -> dict[str, Any]:
    """:func:`canopy_shape` of the set's acacia (``sets.savannah.acacia_ops``) at this scale and seed, measured
    on a grid of 4 cm × scale. Cached: every scene of a film shares the layout's seeds."""
    from animatica.sets.savannah import acacia_ops

    key = (round(float(scale), 4), int(seed))
    if key not in _CACHE:
        ops = acacia_ops("acacia", (0.0, 0.0), float(scale), int(seed))
        canopy = next(o for o in ops if o["op"] == "create_metaball_mesh")
        _CACHE[key] = canopy_shape(canopy["elements"], 0.04 * float(scale))
    return _CACHE[key]
