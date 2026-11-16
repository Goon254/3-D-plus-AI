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
        "zenith": "#3E7ED0",
        "horizon": "#D4E6F2",
        "glow": "#A9CDEB",
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
        "zenith": "#060A1E",
        "horizon": "#1C2850",
        "glow": "#2A3666",
        "elev": 35,
        "az": 300,
        "sun": "#9EB2FF",
        "energy": 0.7,
        "strength": 0.55,
        "stars": 1.0,
        "clouds": 0.0,
        "cloud": "#3A4670",
    },
}

GROUND = "#B39558"
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
    grass_density: float = 14.0
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
    # the flat canopy: overlapping flattened clumps at the branch tips plus a layer over the middle
    els = []
    top = max(t[2] for t in tips)
    for t in tips:
        els.append(
            {
                "type": "ellipsoid",
                "co": [round(t[0], 3), round(t[1], 3), round(top + 0.15 * s, 3)],
                "radius": round(1.5 * s / 0.575, 3),
                "size": [1.0, 1.0, 0.32],
            }
        )
    els.append(
        {
            "type": "ellipsoid",
            "co": [round(fork[0], 3), round(fork[1], 3), round(top + 0.3 * s, 3)],
            "radius": round(2.2 * s / 0.575, 3),
            "size": [1.0, 1.0, 0.25],
        }
    )
    ops += [
        {
            "op": "create_metaball_mesh",
            "id": f"{tid}_canopy",
            "elements": els,
            "resolution": round(0.12 * s, 3),
            "tags": ["set", "tree"],
        },
        {
            "op": "add_modifier",
            "target": f"{tid}_canopy",
            "type": "displace",
            "params": {"noise_scale": 0.9 * s, "strength": 0.35 * s},
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


def water_ops(wid: str, x: float, y: float, r: float, seed: int) -> list[dict[str, Any]]:
    """Watering hole: an irregular water surface ringed by dark wet mud, with reeds along one side."""
    rng = random.Random(seed)
    n = 48
    wob = [rng.uniform(0.85, 1.12) for _ in range(6)]

    def ring(rad: float, z: float) -> list[list[float]]:
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            k = 1 + 0.12 * sum(math.sin(a * (j + 2) + wob[j] * 3) * (wob[j] - 1) * 4 for j in range(3))
            pts.append([round(x + math.cos(a) * rad * k, 3), round(y + math.sin(a) * rad * k * 0.8, 3), z])
        return pts

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
        disc(f"{wid}_mud", r * 1.35, 0.004),
        {
            "op": "set_material",
            "targets": [f"{wid}_mud"],
            "material": _m(
                "#5A4630",
                0.45,
                noise=0.4,
                noise_scale=4.0,
                grain=0.3,
                grain_scale=50.0,
                bump=0.3,
                name=f"{wid}_mud",
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
    ]


def savannah_set(layout: Layout, tod: str = "sunset") -> list[dict[str, Any]]:
    """Ops for a full savannah set at time of day ``tod``."""
    rng = random.Random(layout.seed)
    horizon = SKY[tod]["horizon"]
    haze = {"fade_to": horizon, "fade_start": 18.0, "fade_end": 140.0}
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
                noise=0.4,
                noise_scale=0.35,
                grain=0.35,
                grain_scale=14.0,
                bump=0.35,
                **haze,
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
            "seed": layout.seed,
            "scale": (0.7, 1.5),
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
                    [wx - wr * 1.2, wy + wr * 0.55, 0],
                    [wx + wr * 1.2, wy + wr * 0.55, 0],
                    [wx + wr * 1.1, wy + wr * 1.15, 0],
                    [wx - wr * 1.1, wy + wr * 1.15, 0],
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
    # distant mountains: a hazy blue band (they dissolve into the horizon colour with distance)
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
                "#8C93AC", 1.0, fade_to=horizon, fade_start=150.0, fade_end=470.0, name="mountains"
            ),
        }
    )
    ops += sky_ops(tod)
    return ops
