"""Species body plans for the savannah cast (dimensions in metres, root space).

Root space: the origin is the body centre at rest height ``body_z`` above the ground. +X is the animal's
left, -Y its front, +Z up. Ratios follow ``knowledge/species/<animal>.md``, stylized for appeal (big
eyes, rounded forms), never against the anatomy: an elephant keeps pillar legs and never trots, a
giraffe's forelegs are longer than its hind legs, and so on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

V3 = tuple[float, float, float]


@dataclass(frozen=True)
class Chain:
    base: V3
    tip: V3
    bones: int
    r0: float  # radius at the base
    r1: float  # radius at the tip


@dataclass(frozen=True)
class Extra:
    """A decorative mesh rigidly carried by a bone (ossicones, mane, hooves, muzzle, eye patches...)."""

    id: str
    shape: str
    size: V3
    loc: V3
    bone: str
    mat: str
    rot: V3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Species:
    name: str
    body_z: float
    torso: V3  # full size (width, length, depth)
    torso_at: V3
    torso_rot: float  # pitch (deg, + = front up)
    shoulder: V3  # left shoulder joint; right is mirrored
    hip: V3
    fore_foot: tuple[float, float]  # left fore foot (x, y) at rest; hind likewise
    hind_foot: tuple[float, float]
    leg_r: tuple[float, float, float, float]  # fore upper, fore lower, hind upper, hind lower radius
    foot: tuple[str, float, float]  # shape (hoof|pad|paw), radius, height
    knee_bend: float  # rest bend as a fraction of the joint-to-foot height
    neck: Chain
    head_at: V3
    head_size: V3
    head_pitch: float  # deg, + = nose down
    eye: tuple[float, float, float, float]  # x, y, z offset from the head centre, radius
    ear: tuple[str, V3, V3, V3]  # shape, size, offset from head centre (left), rotation (deg)
    tail: Chain
    tuft: float  # radius of the tail-tip tuft (0 = none)
    coat: dict[str, Any]
    mats: dict[str, dict[str, Any]]
    part_mats: dict[str, str] = field(default_factory=dict)  # part id suffix -> material key
    trunk: Chain | None = None
    extras: tuple[Extra, ...] = ()
    gait: str = "walk"
    muzzle: tuple[V3, V3] | None = None  # size, offset from head centre


def _m(color: str, rough: float = 0.75, **kw: Any) -> dict[str, Any]:
    return {"base_color": color, "roughness": rough, "specular": 0.25, **kw}


EYE_WHITE = _m("#F6F2EA", 0.35)
IRIS = _m("#20160F", 0.12, specular=0.6)
GLINT = {"base_color": "#FFFFFF", "emission": "#FFFFFF", "emission_strength": 2.5, "roughness": 0.2}

SPECIES: dict[str, Species] = {
    # A ~1-year-old calf: 1.2 m at the shoulder, barrel body, pillar legs, big ears, a floppy trunk.
    "elephant": Species(
        name="elephant",
        body_z=0.78,
        torso=(0.72, 1.02, 0.8),
        torso_at=(0.0, 0.02, 0.04),
        torso_rot=2.0,
        shoulder=(0.2, -0.28, -0.12),
        hip=(0.2, 0.3, -0.12),
        fore_foot=(0.2, -0.3),
        hind_foot=(0.2, 0.3),
        leg_r=(0.13, 0.115, 0.13, 0.11),
        foot=("pad", 0.125, 0.09),
        knee_bend=0.12,  # pillar legs: nearly straight; the body vaults over them (gait planner)
        neck=Chain((0.0, -0.38, 0.12), (0.0, -0.5, 0.22), 1, 0.27, 0.27),
        head_at=(0.0, -0.66, 0.3),
        head_size=(0.5, 0.48, 0.5),
        head_pitch=8.0,
        eye=(0.15, -0.2, 0.07, 0.068),
        # African ears hang down the sides of the head (top of the head to below the jaw), skin outside
        ear=("disc", (0.05, 0.36, 0.5), (0.25, 0.1, -0.12), (0.0, -8.0, 12.0)),
        tail=Chain((0.0, 0.5, 0.12), (0.0, 0.58, -0.32), 3, 0.025, 0.015),
        tuft=0.035,
        trunk=Chain((0.0, -0.86, 0.2), (0.0, -0.98, -0.5), 5, 0.085, 0.04),
        coat=_m(
            "#8F8C88", 0.85, noise=0.25, noise_scale=6.0, grain=0.2, grain_scale=60.0, bump=0.3, sheen=0.15
        ),
        mats={
            "ear_inner": _m("#B79189", 0.8, noise=0.2, noise_scale=8.0),
            "nail": _m("#77736E", 0.8, noise=0.3, noise_scale=10.0),
            "tuft": _m("#3A3430", 0.9),
        },
        part_mats={"foot": "nail", "tuft": "tuft"},
    ),
    # Young giraffe: withers 1.9 m, head at 3.2 m; forelegs longer than hind legs (back slopes down to
    # the rump); 7 cervical vertebrae animated as a 4-bone chain; ossicones with tufts; patch coat.
    "giraffe": Species(
        name="giraffe",
        body_z=1.55,
        torso=(0.48, 1.05, 0.6),
        torso_at=(0.0, 0.0, 0.0),
        torso_rot=10.0,
        shoulder=(0.15, -0.36, 0.02),
        hip=(0.14, 0.38, -0.1),
        fore_foot=(0.15, -0.38),
        hind_foot=(0.14, 0.38),
        leg_r=(0.075, 0.05, 0.085, 0.05),
        foot=("hoof", 0.06, 0.07),
        knee_bend=0.2,
        neck=Chain((0.0, -0.42, 0.18), (0.0, -0.78, 1.45), 4, 0.13, 0.075),
        head_at=(0.0, -0.95, 1.52),
        head_size=(0.19, 0.44, 0.21),
        head_pitch=22.0,
        eye=(0.085, -0.05, 0.05, 0.052),
        ear=("leaf", (0.05, 0.035, 0.14), (0.1, 0.1, 0.06), (0.0, 70.0, -20.0)),
        tail=Chain((0.0, 0.5, 0.0), (0.0, 0.62, -0.7), 3, 0.025, 0.015),
        tuft=0.05,
        coat=_m(
            "#F1DFB4",
            0.8,
            pattern="patches",
            pattern_color="#9A5428",
            pattern_scale=4.2,
            pattern_width=0.55,
            sheen=0.25,
            sheen_tint="#FFE8C0",
        ),
        mats={
            "hoof": _m("#3A2E26", 0.5),
            "tuft": _m("#2E2420", 0.9),
            "muzzle": _m("#E9D6B0", 0.8),
            "ossicone": _m("#B07A48", 0.8),
        },
        part_mats={"foot": "hoof", "tuft": "tuft"},
        muzzle=((0.16, 0.16, 0.15), (0.0, -0.2, -0.04)),
        extras=(
            Extra(
                "ossicone_L",
                "cylinder",
                (0.04, 0.04, 0.13),
                (0.05, 0.1, 0.13),
                "head",
                "ossicone",
                (-15, 0, 0),
            ),
            Extra(
                "ossicone_R",
                "cylinder",
                (0.04, 0.04, 0.13),
                (-0.05, 0.1, 0.13),
                "head",
                "ossicone",
                (-15, 0, 0),
            ),
            Extra("ossitip_L", "uv_sphere", (0.055, 0.055, 0.05), (0.05, 0.09, 0.2), "head", "tuft"),
            Extra("ossitip_R", "uv_sphere", (0.055, 0.055, 0.05), (-0.05, 0.09, 0.2), "head", "tuft"),
        ),
    ),
    # Young plains zebra: 1.15 m at the shoulder; big head, sturdy neck, erect striped mane, tasselled tail;
    # broad stripes, vertical on the body and horizontal on the legs.
    "zebra": Species(
        name="zebra",
        body_z=0.86,
        torso=(0.42, 1.0, 0.5),
        torso_at=(0.0, 0.0, 0.02),
        torso_rot=0.0,
        shoulder=(0.12, -0.33, -0.06),
        hip=(0.13, 0.33, -0.02),
        fore_foot=(0.12, -0.34),
        hind_foot=(0.13, 0.34),
        leg_r=(0.065, 0.04, 0.08, 0.04),
        foot=("hoof", 0.05, 0.06),
        knee_bend=0.2,
        neck=Chain((0.0, -0.4, 0.12), (0.0, -0.62, 0.58), 3, 0.13, 0.095),
        head_at=(0.0, -0.8, 0.58),
        head_size=(0.2, 0.46, 0.24),
        head_pitch=40.0,
        eye=(0.09, -0.07, 0.06, 0.058),
        ear=("leaf", (0.06, 0.035, 0.17), (0.065, 0.12, 0.15), (-10.0, 0.0, 12.0)),
        tail=Chain((0.0, 0.5, 0.14), (0.0, 0.63, -0.3), 3, 0.03, 0.018),
        tuft=0.055,
        coat=_m(
            "#F3F0E8",
            0.8,
            pattern="stripes",
            pattern_color="#1C1A1A",
            pattern_scale=2.6,
            pattern_width=0.46,
            pattern_axis="y",
            pattern_distort=2.5,
            sheen=0.2,
        ),
        mats={
            "legs": _m(
                "#F3F0E8",
                0.8,
                pattern="stripes",
                pattern_color="#1C1A1A",
                pattern_scale=4.2,
                pattern_width=0.46,
                pattern_axis="z",
                pattern_distort=1.0,
            ),
            "neck": _m(
                "#F3F0E8",
                0.8,
                pattern="stripes",
                pattern_color="#1C1A1A",
                pattern_scale=3.4,
                pattern_width=0.46,
                pattern_axis="z",
                pattern_distort=1.5,
            ),
            "hoof": _m("#222020", 0.5),
            "tuft": _m("#161414", 0.9),
            "muzzle": _m("#2A2626", 0.6),
            "mane": _m(
                "#F3F0E8",
                0.9,
                pattern="stripes",
                pattern_color="#1C1A1A",
                pattern_scale=9.0,
                pattern_width=0.5,
                pattern_axis="y",
                pattern_distort=0.5,
            ),
        },
        part_mats={"foot": "hoof", "tuft": "tuft", "leg": "legs", "neck": "neck"},
        muzzle=((0.17, 0.16, 0.15), (0.0, -0.21, -0.03)),
        # along the top of the neck: offset back/up from neck_1's head, tilted 25 deg forward like the neck
        extras=(
            Extra("mane", "uv_sphere", (0.05, 0.15, 0.56), (0.0, 0.085, 0.13), "neck_1", "mane", (25, 0, 0)),
        ),
    ),
    # Meerkat on all fours: 0.32 m head+body, thin tapering tail (not bushy), dark eye patches, banded back.
    "meerkat": Species(
        name="meerkat",
        body_z=0.105,
        torso=(0.1, 0.27, 0.11),
        torso_at=(0.0, 0.0, 0.0),
        torso_rot=0.0,
        shoulder=(0.035, -0.085, -0.02),
        hip=(0.04, 0.085, -0.015),
        fore_foot=(0.036, -0.09),
        hind_foot=(0.042, 0.085),
        leg_r=(0.016, 0.012, 0.02, 0.013),
        foot=("paw", 0.014, 0.012),
        knee_bend=0.22,
        neck=Chain((0.0, -0.12, 0.015), (0.0, -0.165, 0.05), 2, 0.035, 0.03),
        head_at=(0.0, -0.205, 0.06),
        head_size=(0.075, 0.1, 0.075),
        head_pitch=8.0,
        eye=(0.024, -0.03, 0.013, 0.014),
        ear=("disc", (0.012, 0.022, 0.022), (0.036, 0.015, 0.02), (0.0, 0.0, 0.0)),
        tail=Chain((0.0, 0.13, 0.0), (0.0, 0.31, 0.05), 4, 0.009, 0.004),
        tuft=0.0,
        coat=_m(
            "#C9AA7E",
            0.85,
            pattern="bands",
            pattern_color="#7A6044",
            pattern_scale=6.0,
            pattern_width=0.12,
            pattern_axis="y",
            pattern_distort=2.0,
            sheen=0.3,
        ),
        mats={
            "paw": _m("#3A2E24", 0.7),
            "patch": _m("#2E241C", 0.8),
            "muzzle": _m("#D8C09A", 0.8),
            "tail": _m("#B89A70", 0.85),
        },
        part_mats={"foot": "paw", "tail": "tail"},
        muzzle=((0.04, 0.06, 0.04), (0.0, -0.055, -0.012)),
        extras=(
            Extra(
                "patch_L",
                "uv_sphere",
                (0.03, 0.012, 0.024),
                (0.024, -0.028, 0.011),
                "head",
                "patch",
                (0, 0, -15),
            ),
            Extra(
                "patch_R",
                "uv_sphere",
                (0.03, 0.012, 0.024),
                (-0.024, -0.028, 0.011),
                "head",
                "patch",
                (0, 0, 15),
            ),
        ),
    ),
    # Leopard tortoise elder: high-domed spotted shell (0.55 m), splayed scaly forelegs, columnar hind legs.
    "tortoise": Species(
        name="tortoise",
        body_z=0.2,
        torso=(0.44, 0.56, 0.31),
        torso_at=(0.0, 0.0, 0.02),
        torso_rot=0.0,
        shoulder=(0.15, -0.17, -0.08),
        hip=(0.14, 0.18, -0.08),
        fore_foot=(0.23, -0.21),
        hind_foot=(0.2, 0.2),
        leg_r=(0.045, 0.04, 0.05, 0.045),
        foot=("pad", 0.045, 0.03),
        knee_bend=0.25,
        neck=Chain((0.0, -0.22, -0.05), (0.0, -0.32, 0.0), 2, 0.045, 0.04),
        head_at=(0.0, -0.37, 0.02),
        head_size=(0.085, 0.12, 0.075),
        head_pitch=0.0,
        eye=(0.032, -0.03, 0.015, 0.018),
        ear=("none", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        tail=Chain((0.0, 0.26, -0.08), (0.0, 0.31, -0.11), 1, 0.018, 0.01),
        tuft=0.0,
        coat=_m("#BBA57E", 0.9, grain=0.35, grain_scale=90.0, bump=0.4),
        mats={
            "shell": _m(
                "#E0C26C",
                0.55,
                pattern="spots",
                pattern_color="#33241A",
                pattern_scale=17.0,
                pattern_width=0.3,
                bump=0.25,
                grain=0.1,
                grain_scale=40.0,
            ),
            "plastron": _m("#D9C48A", 0.7),
            "nail": _m("#4A3E30", 0.6),
        },
        part_mats={"torso": "shell", "foot": "nail"},
        extras=(Extra("plastron", "uv_sphere", (0.4, 0.5, 0.08), (0.0, 0.0, -0.13), "chest", "plastron"),),
    ),
}

CAST = {
    "tembo": "elephant",
    "zuri": "zebra",
    "kiki": "meerkat",
    "neema": "giraffe",
    "bibi_kobe": "tortoise",
}
