"""Generated part meshes that a primitive can't stand in for (owner review 11-17, Zuri):

* :func:`mane_ridge`: a short, bristly mane that follows the neck. v2's mane was one ellipsoid tilted on a
  neck bone, a flat board that ignored the neck's curve. This is a closed ridge lofted along the neck's top line,
  rooted under the skin, standing a fixed height proud of it, with a comb of short teeth along the crest
  (a zebra's mane is short, stiff and upright). It is skinned to the whole neck chain, so it bends with it.
* :func:`hoof`: a real hoof instead of a cylinder: a flat sole wider than the coronet, a front wall sloped back
  (about 50 degrees, as a horse's), a rounder heel, and a slight flare at the ground.

Coordinates are root space (+X left, -Y front, +Z up), as everywhere in ``creatures``.
"""

from __future__ import annotations

import math
from typing import Any

V = list[float]


def _norm(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def mane_line(sp: Any, stations: int = 25) -> list[tuple[tuple[float, float, float], float]]:
    """The neck's axis for :func:`mane_ridge`: [(point, neck radius), ...] from just behind the neck's base (the
    withers) to just past its tip (the poll). Shared by the build and the design rubric's mane checks."""
    n0, n1 = sp.neck.base, sp.neck.tip
    out = []
    for i in range(stations):
        u = -0.08 + 1.14 * i / (stations - 1)
        uc = min(1.0, max(0.0, u))
        p = tuple(a + (b - a) * u for a, b in zip(n0, n1, strict=True))
        out.append((p, sp.neck.r0 + (sp.neck.r1 - sp.neck.r0) * uc))
    return out


TUFT = 0.05  # crest ripple of a toothed mane ridge (share of its height)


def mane_ridge(
    line: list[tuple[tuple[float, float, float], float]],
    height: float,
    width: float,
    teeth: int = 0,
    sink: float = 0.25,
) -> tuple[list[V], list[list[int]]]:
    """(vertices, faces) of a closed ridge along ``line`` = [(point on the neck's axis, neck radius), ...].

    The ridge rises from ``sink`` x radius under the dorsal skin to ``height`` above it, ``width`` across at the
    root, thinner at the crest; ``teeth`` alternating tall/short crest stations make it bristly. Its ends taper.
    """
    n = len(line)
    verts: list[V] = []
    for i, (p, r) in enumerate(line):
        a = line[min(n - 1, i + 1)][0]
        b = line[max(0, i - 1)][0]
        axis = _norm((a[0] - b[0], a[1] - b[1], a[2] - b[2]))
        # the dorsal direction: perpendicular to the axis in the body's mid-plane, pointing up/back
        up = _norm((0.0, axis[2], -axis[1])) if abs(axis[1]) + abs(axis[2]) > 1e-6 else (0.0, 0.0, 1.0)
        if up[2] < 0:
            up = (0.0, -up[1], -up[2])
        u = i / max(1, n - 1)
        taper = (
            math.sin(math.pi * min(1.0, max(0.0, u)) * 0.5 + math.pi * 0.25) ** 0.7
        )  # ends lower and thinner
        tooth = 1.0
        if teeth:
            # a soft brush (owner 11-18): the crest ripples gently over ``teeth`` tufts instead of v3's
            # alternating +-22 % saw teeth, which read as a serrated blade in the silhouette
            tooth = 1.0 + TUFT * math.sin(math.pi * teeth * u)
        h = height * taper * tooth
        w = width * (0.6 + 0.4 * taper)
        root = r * (1 - sink)
        for dist, half in ((root, w / 2), (r + h, w * 0.3)):  # a rounder brush top
            c = (p[0] + up[0] * dist, p[1] + up[1] * dist, p[2] + up[2] * dist)
            verts.append([round(c[0] + half, 5), round(c[1], 5), round(c[2], 5)])
            verts.append([round(c[0] - half, 5), round(c[1], 5), round(c[2], 5)])
    # per station: 0 root+x, 1 root-x, 2 top+x, 3 top-x; a quad loop around 0-2-3-1
    faces: list[list[int]] = []
    loop = (0, 2, 3, 1)
    for i in range(n - 1):
        s, t = 4 * i, 4 * (i + 1)
        for k in range(4):
            a, b = loop[k], loop[(k + 1) % 4]
            faces.append([s + a, t + a, t + b, s + b])
    faces.append([0, 1, 3, 2])  # end caps
    e = 4 * (n - 1)
    faces.append([e + 0, e + 2, e + 3, e + 1])
    return verts, [f[::-1] for f in faces]  # outward winding (positive signed volume)


def hoof(radius: float, height: float, seg: int = 32) -> tuple[list[V], list[list[int]]]:
    """(vertices, faces) of a closed hoof centred on its sole's centre (z = 0 at the ground, up to ``height``).

    The sole is ``radius`` across (a touch longer than wide, rounder at the heel); the coronet at the top is 72 %
    of it and set back, so the front wall slopes; the wall flares a little just above the ground.
    """
    rings = [  # (height share, size share, how far the ring sits back of the sole's centre, share of radius)
        (0.0, 1.0, 0.0),
        (0.12, 1.03, 0.02),  # the flare at the ground
        (0.55, 0.88, 0.14),
        (1.0, 0.72, 0.26),
    ]
    verts: list[V] = [[0.0, 0.0, 0.0]]
    for hz, sz, back in rings:
        for k in range(seg):
            a = 2 * math.pi * k / seg
            x = math.sin(a) * radius * sz
            yf = -math.cos(a)  # +1 front (-Y), -1 heel
            y = -yf * radius * sz * (1.08 if yf > 0 else 0.92) + back * radius
            verts.append([round(x, 5), round(y, 5), round(hz * height, 5)])
    verts.append([0.0, round(rings[-1][2] * radius, 5), round(height, 5)])
    faces: list[list[int]] = []
    for k in range(seg):  # sole (faces down)
        faces.append([0, 1 + (k + 1) % seg, 1 + k])
    for j in range(len(rings) - 1):
        a, b = 1 + j * seg, 1 + (j + 1) * seg
        for k in range(seg):
            k2 = (k + 1) % seg
            faces.append([a + k, a + k2, b + k2, b + k])
    top, last = len(verts) - 1, 1 + (len(rings) - 1) * seg
    for k in range(seg):
        faces.append([last + k, last + (k + 1) % seg, top])
    return verts, [f[::-1] for f in faces]  # outward winding (positive signed volume)
