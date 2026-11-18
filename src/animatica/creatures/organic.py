"""Organic bodies: one continuous mesh grown from a skeleton graph (Blender Skin modifier + Subdivision).

The graph follows the anatomy rather than a stack of primitives: a tapering spine with a belly mass;
shoulder and haunch muscle masses where the limbs join; thigh, knee, cannon/ankle and foot nodes down
each leg; a tapering neck into a cranium-head-nose chain; tail and trunk chains. Skin radii are
``(x, y)``. On a horizontal edge x is the width and y the height; on a vertical edge x is the width and y
the depth.

The bones are unchanged, so the gait system keeps working, and the mesh is skinned with bone-heat weights.
"""

from __future__ import annotations

import math

from .species import Species

V3 = tuple[float, float, float]


def _lerp(a: V3, b: V3, u: float) -> V3:
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u)


def _rx(v: V3, deg: float) -> V3:
    a = math.radians(deg)
    return (v[0], v[1] * math.cos(a) - v[2] * math.sin(a), v[1] * math.sin(a) + v[2] * math.cos(a))


class Graph:
    def __init__(self) -> None:
        self.verts: list[list[float]] = []
        self.radii: list[list[float]] = []
        self.edges: list[list[int]] = []
        self.spine: set[int] = set()  # nodes whose (x, y) radii are (width, height) of the barrel

    def node(self, p: V3, rx: float, ry: float | None = None) -> int:
        self.verts.append([round(c, 4) for c in p])
        self.radii.append([round(max(rx, 0.002), 4), round(max(ry if ry is not None else rx, 0.002), 4)])
        return len(self.verts) - 1

    def link(self, a: int, b: int) -> None:
        self.edges.append([a, b])

    def chain(self, start: int, points: list[tuple[V3, float, float]]) -> int:
        prev = start
        for p, rx, ry in points:
            i = self.node(p, rx, ry)
            self.link(prev, i)
            prev = i
        return prev


def body_graph(
    sp: Species, legs: dict[str, tuple[V3, V3, V3]], shell: bool = False, include_tail: bool = True
) -> Graph:
    """Skeleton graph for ``sp``. ``legs`` maps LF/RF/LH/RH to (joint, knee, foot) in root space."""
    g = Graph()
    W, L, D = sp.torso
    cx, cy, cz = sp.torso_at
    tilt = math.tan(math.radians(sp.torso_rot))
    k = 0.35 if shell else 1.0  # under a shell the trunk of the body is hidden and slim

    def spine(u: float) -> V3:  # u in [-0.5, 0.5] along the body, -0.5 = front
        y = cy + u * L
        return (cx, y, cz - y * tilt)

    # spine: brisket, chest, mid, loins, rump (rounded ends; the chest is deepest)
    profile = [
        (-0.47, 0.55, 0.62),
        (-0.28, 0.95, 1.0),
        (0.0, 1.0, 0.96),
        (0.26, 0.93, 0.9),
        (0.45, 0.62, 0.66),
    ]
    if sp.belly_tuck and not shell:  # the waist draws up behind the ribs: shallower loins and rump
        t = sp.belly_tuck
        profile[3] = (0.26, 0.93 - 0.08 * t, 0.9 - 0.22 * t)
        profile[4] = (0.45, 0.62, 0.66 - 0.06 * t)
    hunch = [0.6, 1.0, 0.65, 0.25, 0.0]  # the withers rise over the chest and ease into the back (no step)
    ids = []
    for (u, fw, fd), h in zip(profile, hunch):
        x, y, z = spine(u)
        ids.append(g.node((x, y, z + sp.hunch * h * D * 0.16), W / 2 * fw * k, D / 2 * fd * k))
        g.spine.add(ids[-1])
    for a, b in zip(ids, ids[1:]):
        g.link(a, b)
    brisket, chest, mid, loins, rump = ids
    if not shell:  # belly mass (the barrel hangs a little below the spine line)
        # with a tucked waist the belly mass sits under the ribcage, not under the loins
        bx, by, bz = spine(0.02 - 0.16 * sp.belly_tuck)
        belly = g.node((bx, by, bz - D * 0.16), W * 0.4, D * 0.34)
        g.link(mid, belly)
    # legs: shoulder / haunch muscle mass -> joint -> thigh/forearm -> knee -> cannon/ankle -> foot
    for key, (J, K, F) in legs.items():
        fore = key[1] == "F"
        ru, rl = (sp.leg_r[0], sp.leg_r[1]) if fore else (sp.leg_r[2], sp.leg_r[3])
        anchor = chest if fore else loins
        lift = sp.hunch * D * 0.14 if fore else 0.0  # hunched shoulders: the shoulder muscle rides higher
        mass_at = (
            J[0] * 0.8,
            J[1] + (0.01 if fore else 0.03),
            J[2] + D * (0.12 if fore else 0.16) * k + lift,
        )
        mass_r = ru * (1.75 if fore else 2.05)
        top = g.chain(
            anchor,
            [
                (mass_at, mass_r * 0.9, mass_r),
                (J, ru * 1.3, ru * 1.4),
                (_lerp(J, K, 0.5), ru * 1.02, ru * 1.08),
                (K, rl * 1.12, rl * 1.12),
                (_lerp(K, F, 0.55), rl * 0.98, rl * 0.98),
                (_lerp(K, F, 0.9), rl * 0.9, rl * 0.9),
            ],
        )
        foot_r = sp.foot[1] * (1.0 if sp.foot[0] != "hoof" else 0.75)
        g.chain(top, [((F[0], F[1] - foot_r * 0.15, F[2] - sp.foot[2] * 0.35), foot_r, foot_r * 0.8)])
    # neck -> cranium -> head -> nose (the head is sculpted from three overlapping masses)
    n0, n1 = sp.neck.base, sp.neck.tip
    neck_pts = [
        (_lerp(n0, n1, u), sp.neck.r0 + (sp.neck.r1 - sp.neck.r0) * u) for u in (0.0, 0.34, 0.67, 1.0)
    ]
    top = g.chain(brisket, [(p, r * 0.98, r * 1.08) for p, r in neck_pts])
    if sp.separate_head:  # the head (and trunk) are their own meshes: see head_elements()
        if include_tail:
            g.chain(rump, [(p, r, r) for p, r in tail_points(sp)])
        return g
    hw, hl, hh = sp.head_size

    def hp(off: V3) -> V3:
        return (
            sp.head_at[0] + _rx(off, sp.head_pitch)[0],
            sp.head_at[1] + _rx(off, sp.head_pitch)[1],
            sp.head_at[2] + _rx(off, sp.head_pitch)[2],
        )

    cranium = g.chain(top, [(hp((0.0, hl * 0.18, hh * 0.08)), hw * 0.5, hh * 0.5)])
    head = g.chain(cranium, [(hp((0.0, -hl * 0.05, 0.0)), hw * 0.47, hh * 0.47)])
    nose = g.chain(head, [(hp((0.0, -hl * 0.36, -hh * 0.08)), hw * 0.33, hh * 0.32)])
    if sp.snout_tip:  # one cone from the face to the nose tip (radius tapers linearly)
        tip, rt = sp.snout_tip
        n0 = (0.0, -hl * 0.36, -hh * 0.08)
        r0 = (hw * 0.33 + hh * 0.32) / 2
        g.chain(nose, [(hp(_lerp(n0, tip, u)), r0 + (rt - r0) * u, r0 + (rt - r0) * u) for u in (0.5, 1.0)])
    if sp.jaw:  # the jaw corner: under the back of the skull, where the neck enters the head
        jr = hw * sp.jaw
        g.chain(head, [(hp((0.0, hl * 0.1, -hh * 0.3)), jr, jr)])
    if sp.trunk:  # the trunk grows from the face below the eyes, tapering to the tip
        t0, t1 = sp.trunk.base, sp.trunk.tip
        pts = [
            (_lerp(t0, t1, u), sp.trunk.r0 + (sp.trunk.r1 - sp.trunk.r0) * u)
            for u in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
        ]
        g.chain(nose, [(p, r, r) for p, r in pts])
    if include_tail:  # tail: from the rump, tapering
        g.chain(rump, [(p, r, r) for p, r in tail_points(sp)])
    return g


def head_elements(sp: Species) -> tuple[list[dict], float]:
    """A calf head sculpted as its own mass (metaballs, root space): a big forehead dome, cheeks, a broad face
    and chin. Carried rigidly by the head bone, so it never melts into the body."""
    hw, hl, hh = sp.head_size

    def hp(off: V3) -> list[float]:
        o = _rx(off, sp.head_pitch)
        return [round(sp.head_at[i] + o[i], 4) for i in range(3)]

    def ball(off: V3, r: float) -> dict:
        return {"type": "ball", "co": hp(off), "radius": round(r / SURFACE, 4)}

    els = [
        ball((0.0, hl * 0.06, hh * 0.04), hw * 0.44),  # the skull
        ball(
            (0.0, -hl * 0.06, hh * 0.24), hw * 0.36
        ),  # the forehead dome (calves have a high, round forehead)
        ball((0.0, -hl * 0.24, -hh * 0.06), hw * 0.3),  # the face where the trunk starts
        ball((hw * 0.22, -hl * 0.14, -hh * 0.14), hw * 0.22),  # cheeks
        ball((-hw * 0.22, -hl * 0.14, -hh * 0.14), hw * 0.22),
        ball((0.0, -hl * 0.12, -hh * 0.34), hw * 0.16),  # chin / lower lip
    ]
    return els, max(0.004, round(hw * 0.02, 4))


def tail_points(sp: Species) -> list[tuple[V3, float]]:
    t0, t1 = sp.tail.base, sp.tail.tip
    return [(_lerp(t0, t1, u), sp.tail.r0 + (sp.tail.r1 - sp.tail.r0) * u) for u in (0.0, 0.33, 0.66, 1.0)]


SURFACE = 0.575  # a metaball's surface sits at 0.575 x its radius (threshold 0.6, stiffness 2; measured)


def metaball_elements(g: Graph, smooth: float = 0.0) -> tuple[list[dict], float]:
    """Graph -> metaball elements: ellipsoids at spine nodes (the barrel keeps its width/height), and
    tapering runs of overlapping balls along every edge, so tubes taper smoothly and melt into the masses.
    ``smooth`` (0..1) packs the balls closer and refines the surface (fewer bumps between them).
    Returns (elements, resolution)."""
    els: list[dict] = []
    rmin = 1e9
    for i, (p, (rx, ry)) in enumerate(zip(g.verts, g.radii)):
        if i in g.spine:
            m = max(rx, ry)
            els.append(
                {
                    "type": "ellipsoid",
                    "co": p,
                    "radius": round(m / SURFACE, 4),
                    "size": [round(rx / m, 3), 1.0, round(ry / m, 3)],
                }
            )
        rmin = min(rmin, (rx + ry) / 2)
    for a, b in g.edges:
        pa, pb = g.verts[a], g.verts[b]
        ra, rb = sum(g.radii[a]) / 2, sum(g.radii[b]) / 2
        length = math.dist(pa, pb)
        n = max(1, int(length / ((0.4 - 0.22 * smooth) * min(ra, rb))))
        for j in range(n + 1):
            u = j / n
            r = ra + (rb - ra) * u
            co = [round(pa[c] + (pb[c] - pa[c]) * u, 4) for c in range(3)]
            # overlapping balls add up: shrink them so the run's surface sits at the target radius
            els.append({"type": "ball", "co": co, "radius": round(r / SURFACE * 0.8, 4)})
    return els, max(0.0035 * (1 - 0.4 * smooth), round(rmin * 0.28 * (1 - 0.4 * smooth), 4))
