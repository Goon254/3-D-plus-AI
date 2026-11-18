"""A tortoise carapace mesh: a high dome with a flared rim, raised scutes and leopard-tortoise markings.

The baseline shell was a scaled UV sphere: a ball with panel lines painted by a random Voronoi, spots that read as
holes, and a pale plastron disc showing underneath (review 11-17 06:36). This builds the shell as real geometry:

* **profile**: radius ``sin(phi)``, height ``cos(phi) ** DOME`` (steep sides, a high rounded top); the rim flares
  outward over its last 14 %, lifts over the neck and tail openings, then the underside tucks in to a flat,
  darker plastron.
* **scutes** sit on a fixed layout in the shell's azimuthal map (``s`` from the apex, ``theta`` around): five
  vertebrals down the midline, four costals each side, and a ring of 24 marginals. Each one is raised as a slight
  pyramid (peak at its centre, a groove at every seam; Voronoi distance-to-edge in the map).
* **markings** are painted per vertex so they follow the geometry: a pale areola in each plate, dark rays
  radiating from it, a dark seam. No blotch at the centre (blotches read as holes).

Coordinates are root space relative to the shell's ``location``: +X left, -Y front, +Z up.
"""

from __future__ import annotations

import math

DOME = 0.85  # profile exponent: < 1 = steeper sides and a fuller, higher top
FLARE = (
    -0.02
)  # the marginal rim tucks in a little (negative): v2's outward 0.05 hung like a skirt (owner 11-17)
RAISE = 0.045  # scute relief (fraction of the radius from the shell centre)
SEAM = 0.11  # seam ramp width in the map: smaller = sharper plates

GROUND = (0.62, 0.38, 0.09)  # leopard tortoise ochre (linear RGB)
AREOLA = (0.78, 0.56, 0.17)
RAY = (0.06, 0.035, 0.015)
SEAM_C = (0.05, 0.03, 0.012)
PLASTRON = (0.2, 0.13, 0.05)  # darker than the top and in shadow: never a pale disc


def scute_centres() -> list[tuple[float, float]]:
    """Scute centres in the map (x = s sin(theta), y = s cos(theta); +y towards the tail)."""
    c = [(0.0, y) for y in (-0.62, -0.31, 0.0, 0.31, 0.62)]
    c += [(sx * 0.5, y) for sx in (1, -1) for y in (-0.42, -0.14, 0.14, 0.42)]
    c += [(0.93 * math.sin(2 * math.pi * k / 24), 0.93 * math.cos(2 * math.pi * k / 24)) for k in range(24)]
    return c


def _two_nearest(p: tuple[float, float], cs: list[tuple[float, float]]) -> tuple[float, float, int]:
    d1 = d2 = 1e9
    i1 = -1
    for i, (cx, cy) in enumerate(cs):
        d = math.hypot(p[0] - cx, p[1] - cy)
        if d < d1:
            d1, d2, i1 = d, d1, i
        elif d < d2:
            d2 = d
    return d1, d2, i1


def _mix(a: tuple[float, ...], b: tuple[float, ...], t: float) -> tuple[float, float, float]:
    t = max(0.0, min(1.0, t))
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def mark_colour(
    x: float, y: float, cs: list[tuple[float, float]]
) -> tuple[tuple[float, float, float], float]:
    """(colour, relief 0..1) at map point (x, y): areola, radiating rays, dark seam; relief peaks at the centre."""
    d1, d2, i = _two_nearest((x, y), cs)
    edge = (d2 - d1) / 2  # distance to the seam
    rel = d1 / max(1e-6, d1 + edge)  # 0 at the plate's centre, 1 at its seam
    cx, cy = cs[i]
    ang = math.atan2(y - cy, x - cx)
    rays = 0.5 + 0.5 * math.cos(6 * ang + 1.7 * i)  # six rays per plate, each plate turned differently
    # soft-edged rays: the colour is per vertex, so a hard threshold shows the mesh as stair-steps
    ray = _smooth((rays - 0.5) / 0.42) * _smooth((rel - 0.3) / 0.15) * (1 - _smooth((rel - 0.82) / 0.1))
    c = _mix(AREOLA, GROUND, _smooth((rel - 0.12) / 0.25))
    c = _mix(c, RAY, 0.9 * ray)
    c = _mix(c, SEAM_C, 1 - _smooth(edge / 0.025))
    relief = 0.7 * min(1.0, edge / SEAM) + 0.3 * (1 - rel)
    return c, relief


def carapace(
    half_width: float,
    half_length: float,
    height: float,
    rim_z: float,
    under_z: float,
    rings: int = 200,  # fine enough that no colour edge is narrower than two vertices (v2's 110 x 256 stair-stepped)
    seg: int = 480,
) -> tuple[list[list[float]], list[list[int]], list[list[float]]]:
    """(vertices, faces, colours) of a closed carapace + plastron. ``rim_z`` is the rim height and ``under_z``
    the plastron's, both relative to the shell's location; the apex is at ``rim_z + height``."""
    cs = scute_centres()
    verts: list[list[float]] = []
    cols: list[list[float]] = []

    def lift(th: float) -> float:  # the rim rises over the neck (front, theta = pi) and the tail (back)
        front = max(0.0, -math.cos(th)) ** 4
        back = max(0.0, math.cos(th)) ** 6
        return height * (0.16 * front + 0.1 * back)

    def add(r: float, z: float, th: float, colour: tuple[float, float, float]) -> None:
        verts.append(
            [round(half_width * r * math.sin(th), 5), round(half_length * r * math.cos(th), 5), round(z, 5)]
        )
        cols.append([round(c, 4) for c in colour])

    # apex
    c0, rel0 = mark_colour(0.0, 0.0, cs)
    add(0.0, rim_z + height * (1 + RAISE * 0.5 * rel0), 0.0, c0)
    profile: list[tuple[float, float, float | None]] = []  # (s, radius, underside depth or None on top)
    for j in range(1, rings + 1):
        s = j / rings
        r = math.sin(s * math.pi / 2)
        if s > 0.86:
            r += FLARE * ((s - 0.86) / 0.14) ** 2
        profile.append((s, r, None))
    # the lip, then the underside tucking in to the plastron: (radius, share of the depth to under_z)
    under = [
        (1.0 + FLARE + 0.01, 0.02),
        (1.0 + FLARE * 0.6, 0.12),
        (0.92, 0.45),
        (0.75, 0.8),
        (0.5, 0.95),
        (0.25, 1.0),
    ]
    profile += [(1.0, r, t) for r, t in under]
    for s, r, t in profile:
        for k in range(seg):
            th = 2 * math.pi * k / seg
            if t is None:
                z = rim_z + height * max(0.0, math.cos(s * math.pi / 2)) ** DOME + lift(th) * s**3
                col, relief = mark_colour(s * math.sin(th), s * math.cos(th), cs)
                rr = r * (1 + RAISE * relief * min(1.0, s * 3))  # no relief squeezed into the apex
                z = rim_z + (z - rim_z) * (1 + RAISE * relief * (1 - s) * 0.8)
                add(rr, z, th, col)
            else:
                z = rim_z + lift(th) * (1 - t) + (under_z - rim_z) * t
                add(r, z, th, SEAM_C if t < 0.1 else PLASTRON)
    # bottom centre
    add(0.0, under_z, 0.0, PLASTRON)
    faces: list[list[int]] = []
    for k in range(seg):  # counter-clockwise seen from outside (normals out)
        faces.append([0, 1 + (k + 1) % seg, 1 + k])
    n = len(profile)
    for i in range(n - 1):
        a, b = 1 + i * seg, 1 + (i + 1) * seg
        for k in range(seg):
            k2 = (k + 1) % seg
            faces.append([a + k, a + k2, b + k2, b + k])
    last, bottom = 1 + (n - 1) * seg, len(verts) - 1
    for k in range(seg):
        faces.append([last + k, last + (k + 1) % seg, bottom])
    return verts, faces, cols


def signed_volume(verts: list[list[float]], faces: list[list[int]]) -> float:
    """Positive when the faces wind outward (a closed mesh)."""
    v = 0.0
    for f in faces:
        p0 = verts[f[0]]
        for i in range(1, len(f) - 1):
            p1, p2 = verts[f[i]], verts[f[i + 1]]
            v += (
                p0[0] * (p1[1] * p2[2] - p1[2] * p2[1])
                - p0[1] * (p1[0] * p2[2] - p1[2] * p2[0])
                + p0[2] * (p1[0] * p2[1] - p1[1] * p2[0])
            )
    return v / 6
