"""The savannah set: ground, wind-blown grass, acacias, termite mounds, a watering hole with reeds, rocks,
distant mountains, and a sky per time of day (dawn, midday, sunset, night with stars).

Everything is procedural (no downloaded assets): ops for the Blender adapter. The action area around the
origin is kept flat with short grass so the animals' planted feet stay visible; trees and mounds are placed
around it. Scenes pass their own layout (where the water is, which trees) via :class:`Layout`.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

V3 = tuple[float, float, float]

SKY: dict[str, dict[str, Any]] = {
    # zenith, horizon, glow, sun elevation/azimuth (deg), sun colour/energy, world strength, stars, clouds
    "dawn": {
        "haze": "#E8C6A0",
        "hills": "#9C8FA6",
        "zenith": "#6E8CC6",
        "horizon": "#F6C38C",
        "glow": "#EFA07E",
        "elev": 7,
        "az": 115,
        "sun": "#FFC896",
        "energy": 2.6,
        "strength": 0.9,
        "stars": 0.0,
        "clouds": 0.35,
        "cloud": "#FFD9C0",
    },
    "midday": {
        "haze": "#C9B48A",
        "hills": "#8A7560",
        "zenith": "#3E7ED0",
        "horizon": "#CADBE4",
        "glow": "#D9DDD2",  # a faintly warm, dusty glow low in the sky
        "elev": 62,
        "az": 160,
        "sun": "#FFF3E0",
        "energy": 4.6,
        "strength": 1.0,
        "stars": 0.0,
        "clouds": 0.55,
        "cloud": "#FFFFFF",
    },
    "afternoon": {
        "haze": "#D2BA90",
        "hills": "#9E8876",
        "zenith": "#4C7FC4",
        "horizon": "#EBD8B0",
        "glow": "#E9C58E",
        "elev": 28,
        "az": 230,
        "sun": "#FFE2B0",
        "energy": 4.0,
        "strength": 0.95,
        "stars": 0.0,
        "clouds": 0.45,
        "cloud": "#FFF2E0",
    },
    "sunset": {
        "haze": "#E9B07E",
        "hills": "#8E6F7E",
        "zenith": "#5868AC",
        "horizon": "#F5AE66",
        "glow": "#E57F66",
        "elev": 6,
        "az": 250,
        "sun": "#FFB066",
        "energy": 3.0,
        "strength": 0.85,
        "stars": 0.0,
        "clouds": 0.4,
        "cloud": "#F7A88A",
    },
    "night": {
        "haze": "#2A3A68",
        "hills": "#25305A",
        "zenith": "#0C1434",
        "horizon": "#2E4078",
        "glow": "#4A5C96",
        "elev": 24,
        "az": 205,  # the moon low behind the action (cameras look toward +Y): a rim on every back and ear
        "sun": "#C4D2FF",
        "energy": 2.4,
        "strength": 1.0,
        "stars": 1.0,
        "clouds": 0.0,
        "cloud": "#3A4670",
        # night only: a soft cool fill from the camera side, so faces read in moonlight
        "fill": ("#9DB0E8", 1.8),
    },
}

GROUND = "#B39558"
# far grass seen through the haze, per time of day: between the near grass and the hills, never brighter
# than the sky at the horizon
FAR_GROUND = {
    "dawn": "#A68D6E",
    "midday": "#B09C78",
    "afternoon": "#B0966E",
    "sunset": "#A27C5E",
    "night": "#1E2846",
}
GRASS_BASE, GRASS_TIP = "#6F6A2E", "#DCBC6E"


@dataclass
class Layout:
    """Where things are in a scene (metres; the action happens around the origin)."""

    action: list[tuple[float, float, float]] = field(default_factory=lambda: [(0.0, 0.0, 4.0)])  # short grass
    water: tuple[float, float, float] | None = None  # (x, y, radius)
    acacias: list[tuple[float, float, float]] = field(
        default_factory=lambda: [(-7.0, 9.0, 1.0), (11.0, 16.0, 0.85)]
    )
    mounds: list[tuple[float, float, float]] = field(default_factory=lambda: [(5.5, 7.0, 1.0)])
    paths: list[tuple[float, float, float]] = field(default_factory=list)  # grass cleared (x, y, r)
    reeds_at: float = 90.0  # degrees: which side of the water the reeds grow on (90 = the back, +Y)
    grass_density: float = 14.0
    # grass gets denser toward the cameras: (x, y, radius, density multiplier); default: in front of each action
    # circle on the camera side (-Y), see dense_regions()
    dense: list[tuple[float, float, float, float]] | None = None
    camera_side: tuple[float, float] = (0.0, -1.0)
    grass_extent: float = 34.0
    seed: int = 7


def _m(color: str, rough: float = 0.85, **kw: Any) -> dict[str, Any]:
    return {"base_color": color, "roughness": rough, "specular": 0.25, **kw}


def grass_tuft(blades: int = 9, height: float = 0.42, seed: int = 1) -> tuple[list, list]:
    """A clump of curved, tapering blades (one mesh, instanced thousands of times by ``scatter``)."""
    rng = random.Random(seed)
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    seg = 4
    for _ in range(blades):
        a = rng.uniform(0, 2 * math.pi)
        lean = rng.uniform(0.15, 0.45)
        h = height * rng.uniform(0.6, 1.15)
        w = rng.uniform(0.008, 0.014)
        base = (rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03))
        start = len(verts)
        for k in range(seg + 1):
            u = k / seg
            out = lean * h * u * u  # curls outward toward the tip
            cx, cy = base[0] + math.cos(a) * out, base[1] + math.sin(a) * out
            half = w * (1 - u) + 0.0008
            px, py = -math.sin(a) * half, math.cos(a) * half
            z = h * u
            verts += [
                [round(cx - px, 4), round(cy - py, 4), round(z, 4)],
                [round(cx + px, 4), round(cy + py, 4), round(z, 4)],
            ]
        for k in range(seg):
            i = start + 2 * k
            faces.append([i, i + 1, i + 3, i + 2])
    return verts, faces


def acacia_ops(tid: str, at: tuple[float, float], scale: float, seed: int) -> list[dict[str, Any]]:
    """Umbrella thorn acacia: a leaning trunk that forks into spreading branches under a flat-topped canopy."""
    rng = random.Random(seed)
    x0, y0 = at
    s = scale
    fork = (x0 + rng.uniform(-0.3, 0.3) * s, y0 + rng.uniform(-0.3, 0.3) * s, 2.2 * s)
    verts = [[x0, y0, 0.0], [x0 + (fork[0] - x0) * 0.5, y0 + (fork[1] - y0) * 0.5, 1.1 * s], list(fork)]
    radii = [[0.2 * s, 0.2 * s], [0.15 * s, 0.15 * s], [0.13 * s, 0.13 * s]]
    edges = [[0, 1], [1, 2]]
    tips: list[tuple[float, float, float]] = []
    nb = rng.randint(3, 5)
    for b in range(nb):
        a = 2 * math.pi * (b + rng.uniform(-0.2, 0.2)) / nb
        reach = rng.uniform(1.6, 2.6) * s
        mid = [fork[0] + math.cos(a) * reach * 0.45, fork[1] + math.sin(a) * reach * 0.45, fork[2] + 0.9 * s]
        tip = [
            fork[0] + math.cos(a) * reach,
            fork[1] + math.sin(a) * reach,
            fork[2] + rng.uniform(1.3, 1.7) * s,
        ]
        i = len(verts)
        verts += [mid, tip]
        radii += [[0.07 * s, 0.07 * s], [0.035 * s, 0.035 * s]]
        edges += [[2, i], [i, i + 1]]
        tips.append(tuple(tip))
    ops: list[dict[str, Any]] = [
        {
            "op": "create_skin_mesh",
            "id": f"{tid}_trunk",
            "vertices": [[round(c, 3) for c in v] for v in verts],
            "edges": edges,
            "radii": radii,
            "subdivisions": 2,
            "tags": ["set", "tree"],
        },
        {
            "op": "set_material",
            "targets": [f"{tid}_trunk"],
            "material": _m(
                "#4A3A2C",
                0.9,
                noise=0.3,
                noise_scale=6.0,
                grain=0.3,
                grain_scale=40.0,
                bump=0.4,
                fade_to="#E9D2A6",
                fade_start=25.0,
                fade_end=160.0,
                name=f"{tid}_bark",
            ),
        },
    ]
    # the canopy: layered foliage clumps with sky between them, not one cushion. An upper tier of flattened
    # clumps on jittered rings over the crown (some positions skipped: gaps), a lower tier hanging under the
    # branch tips. Small metaball radii relative to their spacing keep the clumps apart.
    els = []
    top = max(t[2] for t in tips)
    crown = max(math.dist(t[:2], fork[:2]) for t in tips) + 0.7 * s
    cx, cy = (
        sum(t[0] for t in tips) / len(tips) * 0.5 + fork[0] * 0.5,
        sum(t[1] for t in tips) / len(tips) * 0.5 + fork[1] * 0.5,
    )

    def clump(x: float, y: float, z: float, r: float, flat: float) -> None:
        els.append(
            {
                "type": "ellipsoid",
                "co": [round(x, 3), round(y, 3), round(z, 3)],
                "radius": round(r / 0.575, 3),
                "size": [1.0, 1.0, flat],
            }
        )

    # the umbrella thorn's crown is a wide, flat, layered table (owner 11-18: "better acacia canopies"):
    # a thin top tier spread past the branch tips, and lower shelves under it, sky showing between
    crown *= 1.25
    clump(cx, cy, top + 0.35 * s, 0.8 * s, 0.26)
    for ring, n, rr in ((0.4, 6, 0.6), (0.78, 12, 0.55), (1.08, 15, 0.45)):
        a0 = rng.uniform(0, 2 * math.pi)
        for k in range(n):
            if rng.random() < 0.22:
                continue  # a gap in the canopy
            a = a0 + 2 * math.pi * (k + rng.uniform(-0.2, 0.2)) / n
            d = crown * ring * rng.uniform(0.9, 1.1)
            clump(
                cx + math.cos(a) * d,
                cy + math.sin(a) * d,
                top + rng.uniform(0.05, 0.22) * s - ring * 0.18 * s,
                rr * s * rng.uniform(0.8, 1.15),
                rng.uniform(0.22, 0.3),
            )
    for t in tips:  # the lower tier, under and just outside each branch tip
        a = math.atan2(t[1] - fork[1], t[0] - fork[0]) + rng.uniform(-0.4, 0.4)
        clump(t[0] + math.cos(a) * 0.5 * s, t[1] + math.sin(a) * 0.5 * s, top - 0.5 * s, 0.55 * s, 0.26)
    ops += [
        {
            "op": "create_metaball_mesh",
            "id": f"{tid}_canopy",
            "elements": els,
            "resolution": round(0.09 * s, 3),
            "tags": ["set", "tree"],
        },
        {
            "op": "add_modifier",
            "target": f"{tid}_canopy",
            "type": "displace",
            "params": {"noise_scale": 0.35 * s, "strength": 0.28 * s},  # leafy, broken edges
        },
        {
            "op": "set_material",
            "targets": [f"{tid}_canopy"],
            "material": _m(
                "#4C6A2C",
                0.9,
                noise=0.5,
                noise_scale=3.0,
                grain=0.45,
                grain_scale=14.0 / s,
                bump=0.6,
                tip_color="#8AA046",
                tip_height=(top + 0.8 * s),
                fade_to="#E9D2A6",
                fade_start=25.0,
                fade_end=160.0,
                name=f"{tid}_leaves",
            ),
        },
    ]
    return ops


def baobab_ops(pid: str, height: float, width: float, seed: int, **obj: Any) -> list[dict[str, Any]]:
    """A baobab centred on its origin (``height`` tall, base ``width`` across, like the cylinder it replaces):
    a swollen bottle trunk with a fluted, pinkish-grey bark, and a crown of short, crooked, root-like branches
    with a few sparse leaf tufts (dry season). ``obj`` (location, rotation, parent) places the trunk object."""
    rng = random.Random(seed)
    h, w = height, width / 2
    z0 = -h / 2
    prof = [(0.0, 1.0), (0.12, 0.93), (0.35, 0.98), (0.6, 0.86), (0.8, 0.68), (0.9, 0.55)]
    verts = [
        [round(rng.uniform(-0.03, 0.03) * w, 3), round(rng.uniform(-0.03, 0.03) * w, 3), round(z0 + u * h, 3)]
        for u, _ in prof
    ]
    radii = [[round(w * k, 3), round(w * k * rng.uniform(0.92, 1.0), 3)] for _, k in prof]
    edges = [[i, i + 1] for i in range(len(prof) - 1)]
    top = len(verts) - 1
    tips = []
    nb = rng.randint(5, 7)
    for b in range(nb):
        a = 2 * math.pi * (b + rng.uniform(-0.25, 0.25)) / nb
        reach = w * rng.uniform(1.0, 1.7)
        rise = h * rng.uniform(0.14, 0.24)
        bend = rng.uniform(-0.5, 0.5)
        i = len(verts)
        p1 = [math.cos(a) * reach * 0.5, math.sin(a) * reach * 0.5, z0 + 0.9 * h + rise * 0.55]
        p2 = [math.cos(a + bend) * reach, math.sin(a + bend) * reach, z0 + 0.9 * h + rise]
        verts += [[round(c, 3) for c in p1], [round(c, 3) for c in p2]]
        radii += [[round(w * 0.2, 3)] * 2, [round(w * 0.07, 3)] * 2]
        edges += [[top, i], [i, i + 1]]
        tips.append(p2)
        if rng.random() < 0.6:  # a twig
            j = len(verts)
            p3 = [
                p2[0] + math.cos(a - 0.8) * w * 0.35,
                p2[1] + math.sin(a - 0.8) * w * 0.35,
                p2[2] + h * 0.06,
            ]
            verts.append([round(c, 3) for c in p3])
            radii.append([round(w * 0.04, 3)] * 2)
            edges.append([i + 1, j])
    ops: list[dict[str, Any]] = [
        {
            "op": "create_skin_mesh",
            "id": pid,
            "vertices": verts,
            "edges": edges,
            "radii": radii,
            "subdivisions": 2,
            "tags": ["set", "tree"],
            **obj,
        },
        {
            "op": "set_material",
            "targets": [pid],
            "material": _m(
                "#8E7868",
                0.85,
                noise=0.35,
                noise_scale=2.0,
                pattern="stripes",
                pattern_color="#7A6556",
                pattern_scale=9.0,
                pattern_width=0.25,
                pattern_axis="x",
                pattern_distort=3.0,
                bump=0.5,
                name=f"{pid}_bark",
            ),
        },
    ]
    els = []
    for t in tips:
        if rng.random() < 0.55:
            els.append(
                {
                    "type": "ellipsoid",
                    "co": [round(t[0], 3), round(t[1], 3), round(t[2] + 0.1 * w, 3)],
                    "radius": round(w * rng.uniform(0.35, 0.5) / 0.575, 3),
                    "size": [1.0, 1.0, 0.45],
                }
            )
    if els:
        ops += [
            {
                "op": "create_metaball_mesh",
                "id": f"{pid}_leaves",
                "elements": els,
                "resolution": round(0.08 * w, 3),
                "parent": pid,
                "tags": ["set", "tree"],
            },
            {
                "op": "add_modifier",
                "target": f"{pid}_leaves",
                "type": "displace",
                "params": {"noise_scale": 0.3 * w, "strength": 0.2 * w},
            },
            {
                "op": "set_material",
                "targets": [f"{pid}_leaves"],
                "material": _m(
                    "#5A7432",
                    0.9,
                    noise=0.5,
                    noise_scale=3.0,
                    grain=0.4,
                    grain_scale=14.0,
                    bump=0.6,
                    name=f"{pid}_leaf",
                ),
            },
        ]
    return ops


def log_ops(pid: str, length: float, width: float, seed: int, **obj: Any) -> list[dict[str, Any]]:
    """A fallen log centred on its origin along its local Z (like the cylinder it replaces): a slightly
    crooked, tapering trunk with knots and a broken branch stub, dark furrowed bark, pale cut ends."""
    rng = random.Random(seed)
    r = width / 2
    n = 7
    verts, radii = [], []
    for k in range(n):
        u = k / (n - 1)
        verts.append(
            [
                round(rng.uniform(-0.04, 0.04) * r, 3),
                round(rng.uniform(-0.06, 0.06) * r, 3),
                round((u - 0.5) * length, 3),
            ]
        )
        rr = r * (1.06 - 0.16 * u) * rng.uniform(0.95, 1.05)
        radii.append([round(rr, 3), round(rr * 0.94, 3)])
    edges = [[k, k + 1] for k in range(n - 1)]
    i = len(verts)  # a broken branch stub
    base = verts[2]
    verts += [
        [base[0] + r * 0.9, base[1], base[2] + r * 0.2],
        [base[0] + r * 1.5, base[1] + r * 0.2, base[2] + r * 0.5],
    ]
    radii += [[round(r * 0.32, 3)] * 2, [round(r * 0.2, 3)] * 2]
    edges += [[2, i], [i, i + 1]]
    ops: list[dict[str, Any]] = [
        {
            "op": "create_skin_mesh",
            "id": pid,
            "vertices": [[round(c, 3) for c in v] for v in verts],
            "edges": edges,
            "radii": radii,
            "subdivisions": 2,
            "tags": ["set", "prop"],
            **obj,
        },
        {
            "op": "set_material",
            "targets": [pid],
            "material": _m(
                "#5A4330",
                0.9,
                noise=0.4,
                noise_scale=3.0,
                pattern="stripes",
                pattern_color="#3E2E21",
                pattern_scale=14.0,
                pattern_width=0.3,
                pattern_axis="x",
                pattern_distort=4.0,
                bump=0.7,
                name=f"{pid}_bark",
            ),
        },
    ]
    ends = []
    for k, zc in ((0, verts[0][2]), (1, verts[n - 1][2])):
        eid = f"{pid}_end{k}"
        ends.append(eid)
        rr = radii[0][0] if k == 0 else radii[n - 1][0]
        ops.append(
            {
                "op": "create_primitive",
                "id": eid,
                "shape": "cylinder",
                "size": [round(rr * 1.5, 3), round(rr * 1.42, 3), 0.02],
                "location": [
                    verts[0 if k == 0 else n - 1][0],
                    verts[0 if k == 0 else n - 1][1],
                    round(zc - (-1 if k == 0 else 1) * rr * 0.25, 3),
                ],
                "segments": 24,
                "parent": pid,
                "tags": ["set", "prop"],
            }
        )
    ops.append(
        {
            "op": "set_material",
            "targets": ends,
            "material": _m(
                "#B08A5E",
                0.8,
                noise=0.45,
                noise_scale=12.0,
                grain=0.4,
                grain_scale=40.0,
                name=f"{pid}_endgrain",
            ),
        }
    )
    return ops


def mound_ops(mid: str, at: tuple[float, float], scale: float, seed: int) -> list[dict[str, Any]]:
    """Termite mound: lumpy stacked masses tapering to a few chimneys, red-ochre earth."""
    rng = random.Random(seed)
    els = []
    h = 2.2 * scale
    for k in range(7):
        u = k / 6
        r = (0.75 - 0.55 * u) * scale
        els.append(
            {
                "type": "ball",
                "co": [
                    round(at[0] + rng.uniform(-0.12, 0.12) * scale, 3),
                    round(at[1] + rng.uniform(-0.12, 0.12) * scale, 3),
                    round(u * h, 3),
                ],
                "radius": round(r / 0.575, 3),
            }
        )
    for c in range(2):  # chimneys
        els.append(
            {
                "type": "capsule",
                "co": [
                    round(at[0] + (0.25 - 0.5 * c) * scale, 3),
                    round(at[1] + 0.1 * scale, 3),
                    round(h * (0.75 + 0.1 * c), 3),
                ],
                "radius": round(0.14 * scale / 0.575, 3),
                "size": [0.35 * scale, 0, 0],
                "rotation": [0, -80 + 15 * c, 0],
            }
        )
    return [
        {
            "op": "create_metaball_mesh",
            "id": mid,
            "elements": els,
            "resolution": round(0.05 * scale, 3),
            "tags": ["set", "mound"],
        },
        {
            "op": "add_modifier",
            "target": mid,
            "type": "displace",
            "params": {"noise_scale": 0.35 * scale, "strength": 0.12 * scale},
        },
        {
            "op": "set_material",
            "targets": [mid],
            "material": _m(
                "#A35F36",
                0.95,
                noise=0.35,
                noise_scale=3.0,
                grain=0.4,
                grain_scale=30.0,
                bump=0.5,
                name=f"{mid}_earth",
            ),
        },
    ]


def _reed_corner(wx: float, wy: float, wr: float, at: float, u: float, v: float) -> list[float]:
    """A corner of the reed bed: (u, v) in water radii across/away from the rim on the ``at`` side."""
    a = math.radians(at - 90.0)
    x, y = u * wr, v * wr
    return [
        round(wx + x * math.cos(a) - y * math.sin(a), 4),
        round(wy + x * math.sin(a) + y * math.cos(a), 4),
        0,
    ]


def water_ops(wid: str, x: float, y: float, r: float, seed: int) -> list[dict[str, Any]]:
    """Watering hole: an irregular water surface ringed by dark wet mud, with reeds along one side."""
    rng = random.Random(seed)
    n = 72
    wob = [rng.uniform(0.85, 1.12) for _ in range(6)]
    lobe = (rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi))

    def shape(a: float) -> float:
        """The outline's radius factor at angle ``a``: a lopsided, lobed puddle (owner 11-18: "natural,
        irregular"), not an ellipse with a ripple. Shared by the water and its banks, so they nest."""
        k = 1 + 0.12 * sum(math.sin(a * (j + 2) + wob[j] * 3) * (wob[j] - 1) * 4 for j in range(3))
        return k + 0.13 * math.sin(2 * a + lobe[0]) + 0.07 * math.sin(3 * a + lobe[1])

    def ring(rad: float, z: float, jitter: float = 0.0) -> list[list[float]]:
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            k = shape(a) * (1 + jitter * math.sin(a * 11 + wob[3] * 7) * math.sin(a * 5 + wob[4] * 5))
            pts.append([round(x + math.cos(a) * rad * k, 3), round(y + math.sin(a) * rad * k * 0.8, 3), z])
        return pts

    def bank(bid: str, profile: list[tuple[float, float, float]]) -> dict[str, Any]:
        """A ring band through ``profile`` = [(radius factor, height, edge jitter), ...] inside to out."""
        verts: list[list[float]] = []
        for f, z, jit in profile:
            verts += ring(r * f, z, jit)
        faces = []
        for k in range(len(profile) - 1):
            for i in range(n):
                a, b = k * n + i, k * n + (i + 1) % n
                faces.append([a, b, b + n, a + n])
        return {
            "op": "create_mesh",
            "id": bid,
            "vertices": verts,
            "faces": faces,
            "smooth": True,
            "tags": ["set", "water"],
        }

    def disc(did: str, rad: float, z: float) -> dict[str, Any]:
        rim = ring(rad, z)
        verts = [[x, y, z]] + rim
        faces = [[0, 1 + i, 1 + (i + 1) % n] for i in range(n)]
        return {
            "op": "create_mesh",
            "id": did,
            "vertices": verts,
            "faces": faces,
            "smooth": True,
            "tags": ["set", "water"],
        }

    return [
        disc(f"{wid}_mud", r * 1.05, -0.03),  # the wet floor under the water
        # the wet mud bank: from under the waterline up to a trodden lip (hoof-churned, glistening)
        bank(
            f"{wid}_bank", [(0.94, -0.02, 0.0), (1.06, 0.035, 0.02), (1.16, 0.075, 0.04), (1.24, 0.07, 0.05)]
        ),
        {
            "op": "set_material",
            "targets": [f"{wid}_mud", f"{wid}_bank"],
            "material": _m(
                "#4A3826",
                0.35,
                noise=0.45,
                noise_scale=5.0,
                grain=0.35,
                grain_scale=60.0,
                bump=0.55,
                name=f"{wid}_mud",
            ),
        },
        # the dry, cracked outer bank, sloping back down into the grass
        bank(f"{wid}_dry", [(1.24, 0.07, 0.05), (1.36, 0.045, 0.08), (1.52, 0.0, 0.12), (1.62, -0.02, 0.14)]),
        {
            "op": "set_material",
            "targets": [f"{wid}_dry"],
            "material": _m(
                "#8C6E4C",
                0.95,
                noise=0.5,
                noise_scale=3.0,
                grain=0.4,
                grain_scale=35.0,
                bump=0.5,
                name=f"{wid}_dry",
            ),
        },
        disc(wid, r, 0.012),
        {
            "op": "set_material",
            "targets": [wid],
            "material": {
                "base_color": "#4E5E52",
                "roughness": 0.04,
                "specular": 0.6,
                "noise": 0.15,
                "noise_scale": 3.0,
                "name": f"{wid}_water",
            },
        },
    ]


def sky_ops(tod: str) -> list[dict[str, Any]]:
    k = SKY[tod]
    elev, az = math.radians(k["elev"]), math.radians(k["az"])
    return [
        {
            "op": "set_world",
            "zenith": k["zenith"],
            "horizon": k["horizon"],
            "glow": k["glow"],
            "strength": k["strength"],
            "stars": k["stars"],
            "clouds": k["clouds"],
            "cloud_color": k["cloud"],
        },
        # a sun light's -Z points along its rotation; tilt down from vertical by (90 - elevation)
        {
            "op": "add_light",
            "id": "sun",
            "light_type": "sun",
            "energy": k["energy"],
            "color": k["sun"],
            "size": 0.25,
            "rotation": [round(90 - k["elev"], 2), 0, round(k["az"], 2)],
        },
        *(
            [
                {
                    "op": "create_primitive",
                    "id": "sun_disc",
                    "shape": "uv_sphere",
                    "radius": 9.0,
                    "segments": 32,
                    "location": [
                        round(-math.sin(az) * math.cos(elev) * 420, 1),
                        round(math.cos(az) * math.cos(elev) * 420, 1),
                        round(math.sin(elev) * 420, 1),
                    ],
                    "tags": ["set", "sky"],
                },
                {
                    "op": "set_material",
                    "targets": ["sun_disc"],
                    "material": {
                        "base_color": k["sun"],
                        "emission": k["sun"],
                        "emission_strength": 6.0,
                        "name": "sun_disc",
                    },
                },
            ]
            if k["elev"] < 12 and tod != "night"
            else []
        ),
        *(
            [
                {  # the moon: a big pale disc low in the sky behind the action
                    "op": "create_primitive",
                    "id": "moon_disc",
                    "shape": "uv_sphere",
                    "radius": 14.0,
                    "segments": 32,
                    "location": [
                        round(math.sin(az) * math.cos(elev) * 420, 1),  # where the light comes from
                        round(-math.cos(az) * math.cos(elev) * 420, 1),
                        round(math.sin(elev) * 420, 1),
                    ],
                    "tags": ["set", "sky"],
                },
                {
                    "op": "set_material",
                    "targets": ["moon_disc"],
                    "material": {
                        "base_color": "#F2F4FF",
                        "emission": "#EEF2FF",
                        "emission_strength": 4.0,
                        "name": "moon",
                    },
                },
                {
                    "op": "add_light",
                    "id": "moon_fill",
                    "light_type": "sun",
                    "energy": k["fill"][1],
                    "color": k["fill"][0],
                    "size": 1.5,
                    "rotation": [62.0, 0, 0.0],  # from the camera side (-Y), down onto the faces
                },
            ]
            if tod == "night"
            else []
        ),
    ]


def dense_regions(layout: Layout) -> list[tuple[float, float, float, float]]:
    """Where the grass thickens: between each action circle and the cameras (foreground grass reads as depth;
    sparse tufts near the lens read as rows)."""
    if layout.dense is not None:
        return layout.dense
    hx, hy = layout.camera_side
    return [(x + hx * (r + 4.0), y + hy * (r + 4.0), r + 3.0, 2.6) for x, y, r in layout.action]


def savannah_set(layout: Layout, tod: str = "sunset") -> list[dict[str, Any]]:
    """Ops for a full savannah set at time of day ``tod``."""
    rng = random.Random(layout.seed)
    # aerial perspective: distance fades into a warm, dusty haze (not the sky's horizon colour, which made the
    # midday hills and the far grass read white); midday haze starts closer (heat and dust)
    hz = SKY[tod]["haze"]
    near, far = (14.0, 115.0) if tod in ("midday", "afternoon") else (18.0, 140.0)
    glow = {"midday": 0.2, "afternoon": 0.3, "dawn": 0.6, "sunset": 0.65}.get(tod, 1.0)
    haze = {"fade_to": hz, "fade_start": near, "fade_end": far, "fade_glow": glow}
    # the bare far ground beyond the grass fades to a hazy far-grass tone, not to the bright haze: lit by a low
    # sun plus the haze's glow it rendered as a white stripe under the hills (owner, animatic 11-18)
    ground_haze = {**haze, "fade_to": FAR_GROUND[tod], "fade_glow": glow * 0.2}
    ops: list[dict[str, Any]] = [
        {
            "op": "create_primitive",
            "id": "ground",
            "shape": "plane",
            "size": [1000, 1000, 1],
            "tags": ["set", "ground"],
        },
        {
            "op": "set_material",
            "targets": ["ground"],
            "material": _m(
                GROUND,
                1.0,
                specular=0.0,  # no grazing-angle sheen: it lit the far ground into a white strip
                noise=0.4,
                noise_scale=0.35,
                grain=0.35,
                grain_scale=14.0,
                bump=0.35,
                **ground_haze,
                name="savannah_ground",
            ),
        },
        # the grass field: one blade-clump template, scattered with wind; short in the action area, none in water
        {
            "op": "create_mesh",
            "id": "grass_tuft",
            "vertices": grass_tuft()[0],
            "faces": grass_tuft()[1],
            "smooth": True,
            "location": [0, 0, -50],
            "tags": ["set", "template"],
        },
        {
            "op": "set_material",
            "targets": ["grass_tuft"],
            "material": _m(
                GRASS_BASE,
                0.75,
                tip_color=GRASS_TIP,
                tip_height=0.4,
                sheen=0.3,
                sheen_tint="#FFE7B0",
                name="grass",
            ),
        },
        {
            "op": "create_primitive",
            "id": "grass_field",
            "shape": "plane",
            "size": [layout.grass_extent * 2, layout.grass_extent * 2, 1],
            "location": [0, 0, -0.02],  # under the ground: only its scattered grass shows
            "tags": ["set", "template"],
        },
    ]
    clear = list(layout.paths)
    if layout.water:
        wx, wy, wr = layout.water
        clear.append((wx, wy, wr * 1.2))
    ops += [
        {
            "op": "scatter",
            "id": "grass",
            "surface": "grass_field",
            "instance": "grass_tuft",
            "density": layout.grass_density,
            "dense": [list(c) for c in dense_regions(layout)],
            "seed": layout.seed,
            "scale": (0.6, 1.6),
            "clear": [list(c) for c in clear],
            "short": [list(c) for c in layout.action],
            "short_scale": 0.3,
            "wind": 0.18,
            "wind_speed": 0.7,
        },
    ]
    if layout.water:
        ops += water_ops("waterhole", *layout.water, seed=layout.seed)
        # reeds: taller, greener tufts along the back of the rim
        wx, wy, wr = layout.water
        rv, rf = grass_tuft(blades=7, height=1.0, seed=3)
        ops += [
            {
                "op": "create_mesh",
                "id": "reed_tuft",
                "vertices": rv,
                "faces": rf,
                "smooth": True,
                "location": [0, 0, -50],
                "tags": ["set", "template"],
            },
            {
                "op": "set_material",
                "targets": ["reed_tuft"],
                "material": _m("#4E6A2A", 0.7, tip_color="#B8B060", tip_height=0.9, name="reeds"),
            },
            {
                "op": "create_mesh",
                "id": "reed_bed",
                "vertices": [
                    _reed_corner(wx, wy, wr, layout.reeds_at, u, v)
                    for u, v in ((-1.2, 0.55), (1.2, 0.55), (1.1, 1.15), (-1.1, 1.15))
                ],
                "faces": [[0, 1, 2, 3]],
                "location": [0, 0, -0.02],
                "tags": ["set", "template"],
            },
            {
                "op": "scatter",
                "id": "reeds",
                "surface": "reed_bed",
                "instance": "reed_tuft",
                "density": 9.0,
                "seed": layout.seed + 1,
                "scale": (0.7, 1.3),
                "wind": 0.12,
                "wind_speed": 0.9,
            },
        ]
    for i, (x, y, s) in enumerate(layout.acacias):
        ops += acacia_ops(f"acacia_{i}", (x, y), s, layout.seed + 11 * i)
    for i, (x, y, s) in enumerate(layout.mounds):
        ops += mound_ops(f"mound_{i}", (x, y), s, layout.seed + 5 * i)
    # rocks: a few, half-buried
    rock_ids = []
    for i in range(14):
        a, d = rng.uniform(0, 2 * math.pi), rng.uniform(5.0, 26.0)
        x, y = math.cos(a) * d, math.sin(a) * d + 6.0
        if any(math.hypot(x - cx, y - cy) < r for cx, cy, r in clear + list(layout.action)):
            continue
        r = rng.uniform(0.12, 0.5)
        rock_ids.append(f"rock_{i}")
        ops.append(
            {
                "op": "create_primitive",
                "id": rock_ids[-1],
                "shape": "ico_sphere",
                "radius": round(r, 3),
                "segments": 48,
                "scale": [round(rng.uniform(1.0, 1.6), 2), 1.0, round(rng.uniform(0.45, 0.7), 2)],
                "location": [round(x, 2), round(y, 2), round(r * 0.15, 3)],
                "rotation": [0, 0, round(rng.uniform(0, 360), 1)],
                "smooth": True,
                "tags": ["set", "rock"],
            }
        )
    if rock_ids:
        ops.append(
            {
                "op": "set_material",
                "targets": rock_ids,
                "material": _m("#7D7066", 0.9, noise=0.3, noise_scale=4.0, bump=0.3, **haze, name="rocks"),
            }
        )
    # distant hills: warm, hazy humps (they dissolve into the haze colour with distance)
    # far and low (a few degrees above the horizon), many overlapping humps -> a ridgeline, not dunes
    mts = []
    for i in range(16):
        a = math.radians(20 + 140 * i / 15 + rng.uniform(-4, 4))
        d = rng.uniform(330, 420)
        h = rng.uniform(9, 24)
        r = rng.uniform(30, 55)
        mts.append(f"mountain_{i}")
        ops.append(
            {
                "op": "create_primitive",
                "id": mts[-1],
                "shape": "uv_sphere",
                "radius": round(r, 1),
                "segments": 32,
                "scale": [round(rng.uniform(1.6, 2.8), 2), 1.0, round(h / r, 3)],
                "location": [round(math.cos(a) * d, 1), round(math.sin(a) * d, 1), 0.0],
                "smooth": True,
                "tags": ["set", "far"],
            }
        )
    ops.append(
        {
            "op": "set_material",
            "targets": mts,
            "material": _m(
                SKY[tod]["hills"],
                1.0,
                noise=0.25,
                noise_scale=0.02,
                fade_to=hz,
                fade_start=120.0,
                fade_end=560.0,
                fade_glow=glow,
                name="mountains",
            ),
        }
    )
    ops += sky_ops(tod)
    return ops


def bird_flock_ops(
    fid: str,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    t0: float,
    t1: float,
    n: int = 5,
    fps: int = 24,
    seed: int = 3,
    span: float = 0.8,
    color: str = "#2B2A33",
) -> list[dict[str, Any]]:
    """A loose flock of small birds flying from ``start`` to ``end`` between ``t0`` and ``t1`` seconds: each a
    body and two wings (a flat silhouette that reads against a dawn or sunset sky), flapping in bursts with
    glides between, bobbing a little, in a loose V that shuffles as it flies."""
    rng = random.Random(seed)
    h = span / 2
    verts = [
        [0.0, -0.22 * span, 0.0],
        [0.05 * span, 0.0, 0.0],
        [0.0, 0.3 * span, 0.0],
        [-0.05 * span, 0.0, 0.0],
        [h, 0.05 * span, 0.0],
        [-h, 0.05 * span, 0.0],
        [0.04 * span, -0.06 * span, 0.0],
        [-0.04 * span, -0.06 * span, 0.0],
    ]
    faces = [[0, 1, 2, 3], [1, 4, 6], [3, 7, 5]]

    def wings(z: float, fold: float = 1.0) -> list[list[float]]:
        v = [list(p) for p in verts]
        v[4] = [h * fold, 0.05 * span, z]
        v[5] = [-h * fold, 0.05 * span, z]
        return v

    keys = {"up": wings(0.55 * h, 0.8), "down": wings(-0.5 * h, 0.85)}
    dx, dy, dz = (end[i] - start[i] for i in range(3))
    yaw = math.degrees(math.atan2(dx, -dy)) + 180.0  # the bird's nose is +Y
    ops: list[dict[str, Any]] = []
    for b in range(n):
        bid = f"{fid}_{b}"
        side = (b + 1) // 2 * (1 if b % 2 else -1)
        off = (
            side * 0.9 + rng.uniform(-0.3, 0.3),
            abs(side) * 0.7 + rng.uniform(-0.2, 0.2),
            rng.uniform(-0.4, 0.4),
        )
        dt = rng.uniform(-0.2, 0.2)
        ops += [
            {"op": "create_mesh", "id": bid, "vertices": verts, "faces": faces, "tags": ["set", "birds"]},
            {"op": "add_shape_keys", "target": bid, "keys": keys},
            {"op": "set_material", "targets": [bid], "material": _m(color, 0.9, name=f"{fid}_mat")},
        ]
        loc, flap = [], []
        f0, f1 = 1 + int((t0 + dt) * fps), 1 + int((t1 + dt) * fps)
        phase = rng.uniform(0, 1)
        for f in range(f0, f1 + 1, 2):
            u = (f - f0) / max(1, f1 - f0)
            bob = 0.12 * math.sin(2 * math.pi * (u * 3 + phase))
            loc.append(
                [
                    f,
                    [
                        round(start[i] + (dx, dy, dz)[i] * u + off[i] + (bob if i == 2 else 0.0), 3)
                        for i in range(3)
                    ],
                    "LINEAR",
                ]
            )
            t = (f - f0) / fps
            burst = math.sin(2 * math.pi * (t / 1.6 + phase)) > -0.35  # flap, glide, flap
            w = math.sin(2 * math.pi * 6.0 * t) if burst else -0.15
            flap.append([f, round(max(0.0, w), 3), "LINEAR"])
        ops += [
            {"op": "insert_keyframes", "target": bid, "property": "location", "keys": loc},
            {
                "op": "insert_keyframes",
                "target": bid,
                "property": "rotation",
                "keys": [[f0, [0.0, 0.0, round(yaw, 1)], "LINEAR"]],
            },
            {"op": "insert_keyframes", "target": bid, "property": "shape_key:up", "keys": flap},
            {
                "op": "insert_keyframes",
                "target": bid,
                "property": "shape_key:down",
                "keys": [
                    [
                        k[0],
                        round(
                            max(0.0, -math.sin(2 * math.pi * 6.0 * (k[0] - f0) / fps)) * (k[1] > 0 or 0.3), 3
                        ),
                        "LINEAR",
                    ]
                    for k in flap
                ],
            },
        ]
    return ops
