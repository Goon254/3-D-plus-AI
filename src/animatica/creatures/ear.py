"""A cupped ear mesh with thickness and a rolled top rim (the elephant calf's big ears).

The baseline ear was a flattened sphere: from 3/4 it showed its edge as a thin fin (review 11-17 06:36). This is a
closed lens-shaped shell in the ear's local frame (x = thickness, y = width, z = height, centred on the origin):

* the blade bends into a bowl (``cup``): the rim sits ``cup`` x the ear's height out along +x from the middle, so the
  concave side faces +x; the builder turns +x outward and forward, so the hollow of the ear is what you see;
* it is thick in the middle and thicker still along the rolled upper rim (an elephant's ear folds over at the top),
  so an edge-on ear still has body.
"""

from __future__ import annotations

import math

V = list[float]


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def cupped_ear(
    thickness: float,
    width: float,
    height: float,
    cup: float = 0.18,
    roll: float = 1.6,
    rings: int = 14,
    seg: int = 40,
) -> tuple[list[V], list[list[int]]]:
    """(vertices, faces) of a closed, outward-wound ear: an ellipse ``width`` x ``height`` cupped toward +x."""
    b, c = width / 2, height / 2

    def bowl(rho: float) -> float:  # the blade bends out toward +x away from the middle
        return cup * height * rho * rho

    # half thickness: full at the root, thinner toward the rim, rolled over along the top edge
    def half_t(rho: float, a: float) -> float:
        top = _smooth((math.sin(a) - 0.2) / 0.6) * _smooth((rho - 0.7) / 0.3)
        return thickness / 2 * ((1 - 0.45 * rho) + roll * top)

    verts: list[V] = []
    # outer face (+x side of the blade), from its centre out to the rim
    verts.append([round(bowl(0.0) + half_t(0.0, 0.0), 5), 0.0, 0.0])
    rows: list[tuple[float, int]] = []  # (rho, side): side +1 outer, 0 rim, -1 inner
    rows += [(i / rings, 1) for i in range(1, rings + 1)]
    rows.append((1.0, 0))
    rows += [(1 - i / rings, -1) for i in range(0, rings)]
    for rho, side in rows:
        r = rho if side else 1.0 + 0.6 * thickness / max(b, c)  # the rim bulges a little past the blade
        for k in range(seg):
            a = 2 * math.pi * k / seg
            y, z = b * r * math.cos(a), c * r * math.sin(a)
            x = bowl(min(rho, 1.0)) + side * half_t(min(rho, 1.0), a)
            verts.append([round(x, 5), round(y, 5), round(z, 5)])
    verts.append([round(bowl(0.0) - half_t(0.0, 0.0), 5), 0.0, 0.0])
    faces: list[list[int]] = []
    n = len(rows)
    for k in range(seg):
        faces.append([0, 1 + k, 1 + (k + 1) % seg])
    for i in range(n - 1):
        p, q = 1 + i * seg, 1 + (i + 1) * seg
        for k in range(seg):
            k2 = (k + 1) % seg
            faces.append([p + k, q + k, q + k2, p + k2])
    last, end = 1 + (n - 1) * seg, len(verts) - 1
    for k in range(seg):
        faces.append([last + k, end, last + (k + 1) % seg])
    return verts, faces
