"""Species body plans for the savannah cast (dimensions in metres, root space).

Root space: the origin is the body centre at rest height ``body_z`` above the ground. +X is the animal's
left, -Y its front, +Z up. Ratios follow ``knowledge/species/<animal>.md``, stylized for appeal (big
eyes, rounded sculpted masses), never against the anatomy: an elephant keeps pillar legs and never
trots, a giraffe's forelegs are longer than its hind legs, and so on.

Bodies are organic (``organic.body_graph``: one skin-modifier mesh with muscle masses). The fields
below describe the skeleton the mesh is grown on, the masses, and per-species skin/fur shading.
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
    """A decorative mesh rigidly carried by a bone (ossicones, mane, muzzle, eye patches...)."""

    id: str
    shape: str
    size: V3
    loc: V3  # relative to the head centre (head bone, rotated with the head pitch) or the bone's head
    bone: str
    mat: str
    rot: V3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Species:
    name: str
    body_z: float
    torso: V3  # body mass (width, length, depth)
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
    part_mats: dict[str, str] = field(default_factory=dict)  # part kind -> material key
    trunk: Chain | None = None
    extras: tuple[Extra, ...] = ()
    gait: str = "walk"
    muzzle: tuple[V3, V3] | None = None  # size, offset from head centre (a separately coloured muzzle)
    regions: tuple[tuple[tuple[str, ...], str], ...] = ()  # (bone prefixes, material key) on the body mesh
    nails: int = 0  # toenails/claws on each skin-grown foot
    shell: tuple[V3, V3] | None = None  # (size, centre) of a tortoise carapace
    default_pose: str = "stand"  # "sentinel": the meerkat stands up when it stops
    # legs ("F" fore, "H" hind) whose feet stay level while planted instead of rocking with the shin (#69)
    level_feet: str = "FH"
    # a soft dark patch painted on the skin around and behind each eye: (colour, strength)
    eye_patch: tuple[str, float] | None = None
    separate_head: bool = False  # sculpt the head as its own mesh on the head bone (no melting into the body)
    # organic heads: the face tapers to this tip as one cone (offset from the head centre, tip radius), so a
    # pointed snout grows out of the face instead of being a separate tube stuck on it
    snout_tip: tuple[V3, float] | None = None
    # a jaw-corner mass under the back of the skull (radius as a fraction of the head width): it gives the
    # head a chin and throat line where the neck enters, so the head never slopes straight into the chest
    jaw: float = 0.0
    belly_tuck: float = 0.0  # 0..1: the loins and belly draw up behind the ribcage (a lean waist, not a tube)
    # 0..1: denser metaball runs and a finer surface, so a small body is smooth instead of lumpy (bumps
    # between the overlapping balls show at sheet size on a 30 cm animal)
    smooth: float = 0.0
    # the eye patch's edge: the share of its radius over which it fades (lower = crisper)
    patch_soft: float = 0.55
    # disc ears as a cupped, thick mesh (creatures.ear): the rim bends this share of the ear's height out of plane
    ear_cup: float = 0.0
    # added to every expression's upper-lid value: negative opens the neutral eye wider (a sleepy look otherwise)
    lid_bias: float = 0.0
    # the most a brow may lift (eye radii): a big-eyed head has its brows near the top of the skull, and lifting
    # them further floats them off the head (Kiki's surprised brows hung in the air above it)
    brow_max: float = 1.0
    brow_bias: float = (
        0.0  # added to every expression's brow lift (eye radii): + rests the brows higher (less grumpy)
    )
    # added to every expression's brow tilt (degrees): - lifts the outer ends. A round skull curves the brows'
    # outer ends down, which reads as worried at rest (Tembo, owner review 11-17)
    brow_tilt: float = 0.0
    # the eye patch's radii multipliers (across, back, up) relative to the default teardrop
    patch_shape: tuple[float, float, float] = (1.0, 1.0, 1.0)
    # 0..1 the withers rise: the chest (and the shoulder muscle) sit higher than the back line, a hunched walk
    hunch: float = 0.0
    # a mane ridge along the neck's top line (creatures.parts.mane_ridge): (height, root width, teeth) in metres
    mane: tuple[float, float, int] | None = None
    # eyeball centre this many radii under the skin (None: eyes.EMBED_DEPTH, 0.3 = 65 % buried). On a round skull
    # with side-set eyes the skin's edge cuts diagonally over a deep eye and reads as a worried lid (Tembo)
    eye_embed: float | None = None
    brow_size: tuple[float, float] = (
        1.0,
        1.0,
    )  # brow length and thickness multipliers (slimmer = friendlier)


def _m(color: str, rough: float = 0.75, **kw: Any) -> dict[str, Any]:
    return {"base_color": color, "roughness": rough, "specular": 0.3, **kw}


EYE_WHITE = _m("#F6F2EA", 0.3)
IRIS = _m("#1E140D", 0.1, specular=0.7)
GLINT = {"base_color": "#FFFFFF", "emission": "#FFFFFF", "emission_strength": 2.5, "roughness": 0.2}

_ZEBRA_STRIPES = {"pattern": "stripes", "pattern_color": "#1A1818", "pattern_width": 0.46}
# the meerkat's rest height; her paw shade is painted at the ground (root z = -body_z), so both use this
_MEERKAT_BODY_Z = 0.118  # v6 (owner 11-18): v4's height on all fours (v5's lower body read as a weasel)

SPECIES: dict[str, Species] = {
    # About a year old: 1.1 m at the shoulder; big domed head (calves are head-heavy), barrel body,
    # pillar legs; a short calf trunk; ears hanging down the sides of the head; subtle wrinkles.
    "elephant": Species(
        name="elephant",
        body_z=0.72,
        torso=(0.64, 0.86, 0.7),
        torso_at=(0.0, 0.02, 0.05),
        torso_rot=3.0,
        shoulder=(0.19, -0.27, -0.1),
        hip=(0.19, 0.29, -0.08),
        fore_foot=(0.19, -0.29),
        hind_foot=(0.19, 0.29),
        leg_r=(0.13, 0.11, 0.135, 0.105),
        foot=("pad", 0.12, 0.08),
        knee_bend=0.12,  # pillar legs: nearly straight; the body vaults over them (gait planner)
        # a short visible neck, narrower than both the body and the head
        neck=Chain((0.0, -0.36, 0.14), (0.0, -0.52, 0.24), 1, 0.21, 0.19),
        head_at=(0.0, -0.74, 0.36),
        head_size=(0.66, 0.56, 0.68),
        head_pitch=6.0,
        eye=(0.17, -0.22, 0.1, 0.088),
        # angled forward so the big ears frame the face instead of showing their edge
        ear=("disc", (0.06, 0.48, 0.62), (0.31, 0.1, -0.28), (0.0, -8.0, 38.0)),
        ear_cup=0.16,  # cupped, thick, a rolled top edge: never a fin edge-on
        lid_bias=-1.0,  # lids drawn up at rest: a part-open lid slopes with his side-set eyes (worried, owner 11-17)
        brow_tilt=-8.0,  # owner 11-17: soften his resting worried brows (outer ends up)
        brow_bias=0.15,
        brow_size=(0.9, 0.8),
        eye_embed=0.1,  # 55 % buried: the skin's edge no longer slopes across the eye (owner 11-17: worried)
        brow_max=1.35,  # a big skull: room for surprise above the raised resting brows
        tail=Chain((0.0, 0.48, 0.14), (0.0, 0.58, -0.3), 3, 0.03, 0.014),
        tuft=0.035,
        trunk=Chain((0.0, -0.98, 0.2), (0.0, -1.06, -0.3), 5, 0.095, 0.045),
        coat=_m(
            "#918D88",
            0.82,
            noise=0.22,
            noise_scale=5.0,
            wrinkles=0.45,
            wrinkle_scale=14.0,
            subsurface=0.12,
            subsurface_radius=0.03,
            grain=0.15,
            grain_scale=70.0,
            bump=0.15,
        ),
        mats={"nail": _m("#D9CCB2", 0.45), "tuft": _m("#3A3430", 0.9)},
        part_mats={"tuft": "tuft"},
        nails=3,
        separate_head=True,
    ),
    # Young giraffe: withers 1.9 m, head at 3.2 m; long straight legs (forelegs longer, so the back slopes
    # to the rump); 7 cervical vertebrae animated as a 4-bone chain; tufted ossicones; patch coat.
    "giraffe": Species(
        name="giraffe",
        body_z=1.55,
        torso=(0.5, 1.05, 0.62),
        torso_at=(0.0, 0.0, 0.0),
        torso_rot=10.0,
        shoulder=(0.15, -0.36, 0.02),
        hip=(0.14, 0.38, -0.08),
        fore_foot=(0.15, -0.38),
        hind_foot=(0.14, 0.38),
        # sturdier legs (the baseline's read as stilts); still long, slim cannons
        leg_r=(0.105, 0.072, 0.118, 0.072),
        foot=("hoof", 0.075, 0.075),
        knee_bend=0.1,
        neck=Chain((0.0, -0.42, 0.18), (0.0, -0.78, 1.45), 4, 0.14, 0.08),
        head_at=(0.0, -0.95, 1.52),
        # a bigger head and eyes so her face reads at 96 px (a young giraffe is head-heavy)
        head_size=(0.27, 0.55, 0.295),
        head_pitch=22.0,
        eye=(0.12, -0.06, 0.068, 0.08),
        brow_bias=0.3,  # her low resting brows read as a scowl
        brow_tilt=6.0,  # owner 11-17: friendlier brows: slimmer, lighter, the inner ends a touch up (soft, not a scowl)
        brow_size=(0.72, 0.5),
        # the heavy "brows" were her upper lids: brown caps sloping over the top third of each eye. Drawn up at
        # rest, with the eyes a little shallower, the face opens up (surprise widens through the irises)
        lid_bias=-1.0,
        eye_embed=0.15,
        brow_max=0.7,  # rig stress test: a surprised lift of 1.0 floated her brows 16 % off the skin
        ear=("leaf", (0.05, 0.035, 0.15), (0.1, 0.1, 0.06), (0.0, 70.0, -20.0)),
        tail=Chain((0.0, 0.5, 0.0), (0.0, 0.62, -0.7), 3, 0.028, 0.014),
        tuft=0.05,
        coat=_m(
            "#F2DFB2",
            0.8,
            pattern="patches",
            pattern_color="#9A5428",
            pattern_scale=4.2,
            pattern_width=0.55,
            fur=0.45,
            sheen_tint="#FFE8C0",
        ),
        mats={
            "hoof": _m("#3A2E26", 0.5),
            "tuft": _m("#2E2420", 0.9),
            "muzzle": _m("#EBD9B4", 0.8, fur=0.3),
            "ossicone": _m("#B07A48", 0.8),
            "shins": _m(
                "#F5E8C8",
                0.8,
                pattern="patches",
                pattern_color="#A86233",
                pattern_scale=9.0,
                pattern_width=0.4,
                fur=0.4,
            ),
        },
        part_mats={"foot": "hoof", "tuft": "tuft"},
        # owner 11-17: a smaller, less pouty muzzle (v2's 0.21 x 0.21 x 0.18 bulb pushed a lower lip out)
        muzzle=((0.16, 0.15, 0.125), (0.0, -0.22, -0.04)),
        regions=((("leg_LF_lo", "leg_RF_lo", "leg_LH_lo", "leg_RH_lo"), "shins"),),
        extras=(
            Extra(
                "ossicone_L",
                "cylinder",
                (0.045, 0.045, 0.14),
                (0.06, 0.11, 0.185),
                "head",
                "ossicone",
                (-15, 0, 0),
            ),
            Extra(
                "ossicone_R",
                "cylinder",
                (0.045, 0.045, 0.14),
                (-0.06, 0.11, 0.185),
                "head",
                "ossicone",
                (-15, 0, 0),
            ),
            Extra("ossitip_L", "uv_sphere", (0.06, 0.06, 0.055), (0.06, 0.1, 0.26), "head", "tuft"),
            Extra("ossitip_R", "uv_sphere", (0.06, 0.06, 0.055), (-0.06, 0.1, 0.26), "head", "tuft"),
        ),
    ),
    # Young plains zebra: 1.15 m at the shoulder; big head, sturdy neck, erect striped mane, tasselled tail;
    # broad stripes, vertical on the body, horizontal on the legs, rings around the neck.
    "zebra": Species(
        name="zebra",
        # v3 (owner 11-17): a stockier zebra, not a pony: deeper chest, thicker neck and legs, a bigger head
        body_z=0.82,
        torso=(0.47, 0.98, 0.57),
        torso_at=(0.0, 0.0, 0.02),
        torso_rot=0.0,
        shoulder=(0.12, -0.33, -0.06),
        hip=(0.13, 0.33, -0.02),
        fore_foot=(0.12, -0.34),
        hind_foot=(0.13, 0.34),
        leg_r=(0.085, 0.052, 0.1, 0.052),
        foot=("hoof", 0.058, 0.075),  # a real hoof mesh (creatures.parts.hoof)
        knee_bend=0.16,
        neck=Chain((0.0, -0.4, 0.12), (0.0, -0.62, 0.56), 3, 0.165, 0.118),
        head_at=(0.0, -0.81, 0.57),
        head_size=(0.24, 0.53, 0.29),
        head_pitch=40.0,
        eye=(0.108, -0.077, 0.068, 0.064),
        # big, round-tipped ears (a zebra's are broader than a horse's): part of the species read. The base sits 8.5 cm
        # up the head, sunk ~1 cm into it: at 15 cm the ears hovered 3.6 cm above the head (qa part_float)
        ear=("leaf", (0.085, 0.04, 0.18), (0.07, 0.12, 0.085), (-10.0, 0.0, 16.0)),
        tail=Chain((0.0, 0.5, 0.14), (0.0, 0.63, -0.3), 3, 0.032, 0.018),
        tuft=0.055,
        coat=_m(
            "#F3F0E8",
            0.8,
            **_ZEBRA_STRIPES,
            pattern_scale=2.6,
            pattern_axis="y",
            pattern_distort=2.5,
            pattern_tilt=-0.8,  # slanted flank stripes sweep over the haunch into the hind leg
            pattern_chevron=1.4,  # stripes wrap as chevrons: no bullseyes on the chest, rump or forehead
            fur=0.5,
        ),
        mats={
            "legs": _m(
                "#F3F0E8",
                0.8,
                **_ZEBRA_STRIPES,
                pattern_scale=4.2,
                pattern_axis="z",
                pattern_distort=1.0,
                fur=0.5,
            ),
            "neck": _m(
                "#F3F0E8",
                0.8,
                **_ZEBRA_STRIPES,
                pattern_scale=3.4,
                pattern_axis="z",
                pattern_distort=1.5,
                fur=0.5,
            ),
            "hoof": _m("#222020", 0.5),
            "tuft": _m("#161414", 0.9),
            # a soft charcoal-brown nose, not a black ball: it continues the face
            "muzzle": _m("#3B3431", 0.7, fur=0.3),
            "mane": _m(
                "#F3F0E8", 0.9, **_ZEBRA_STRIPES, pattern_scale=9.0, pattern_axis="y", pattern_distort=0.5
            ),
        },
        part_mats={"foot": "hoof", "tuft": "tuft"},
        # narrower than the face and sunk into it, so it reads as the end of the nose, not a clown nose
        muzzle=((0.17, 0.165, 0.135), (0.0, -0.215, -0.04)),
        # real zebras: neck stripes run vertically like the body's; only the legs turn horizontal
        regions=((("leg_LF_lo", "leg_RF_lo", "leg_LH_lo", "leg_RH_lo"), "legs"),),
        # a short, stiff, striped mane standing along the neck's crest from withers to poll (v2's was a board)
        mane=(0.11, 0.06, 14),
        lid_bias=-1.0,  # lids drawn up at rest: the grey caps over her eyes read sleepy (surprise widens the irises)
    ),
    # Meerkat: 0.32 m head+body. Kids'-film proportions: a big round head with a pointed snout, a short deep
    # chest (not a tube), a tail shorter than the body that tapers from a thick base, small dark crescent
    # ears on the sides of the head, dark eye patches, lower legs a darker shade of the coat (never black
    # boots). Stands up into the sentinel pose whenever it stops (straight, paws tucked, tail as a tripod).
    "meerkat": Species(
        name="meerkat",
        # length/depth 2.04: a meerkat, not a weasel tube (2.8) nor a hamster ball (1.6)
        # v4: a slimmer barrel on shorter, slightly bent legs (v3 read as a mongoose: bulky body, stilts)
        body_z=_MEERKAT_BODY_Z,
        # v6 (owner 11-18): v4's body (v5's lower, longer, hunched one read as a weasel) with v5's patches
        torso=(0.086, 0.198, 0.09),
        torso_at=(0.0, 0.0, 0.0),
        torso_rot=4.0,
        shoulder=(0.027, -0.07, -0.016),
        hip=(0.031, 0.068, -0.012),
        fore_foot=(0.028, -0.072),
        hind_foot=(0.032, 0.07),
        leg_r=(0.016, 0.0125, 0.0185, 0.0135),  # v4: slimmer haunches (v3 had bulbous hips)
        foot=("paw", 0.012, 0.01),
        knee_bend=0.3,
        # the head is carried forward and only a little up on a neck that enters the back of the skull, so
        # there is a nape and a throat line (a mongoose-family profile, not a dog's raised head)
        neck=Chain((0.0, -0.092, 0.018), (0.0, -0.142, 0.05), 2, 0.026, 0.017),
        # a big round head (head_body 0.45) that tapers into a pointed snout
        head_at=(0.0, -0.184, 0.062),
        head_size=(0.07, 0.096, 0.066),
        head_pitch=2.0,
        eye=(0.024, -0.022, 0.013, 0.0145),
        # small dark crescents on the sides of the head, at eye level, a little behind the eyes
        ear=("disc", (0.008, 0.021, 0.019), (0.033, 0.016, 0.012), (0.0, 0.0, -12.0)),
        # shorter than head+body; a thick base tapering to a fine dark tip
        tail=Chain((0.0, 0.104, 0.004), (0.0, 0.264, -0.05), 4, 0.017, 0.0042),
        tuft=0.007,  # the dark tail tip
        coat=_m(
            "#B68A56", 0.85, noise=0.18, noise_scale=40.0, fur=0.6, fur_scale=500.0, sheen_tint="#F2D2A0"
        ),
        mats={
            # faint, irregular bands across the top of the back and rump only (not hoops round the body)
            "back": _m(
                "#B08452",
                0.85,
                pattern="bands",
                pattern_color="#A67D4D",  # v5: faint (owner 11-17)
                pattern_scale=6.0,
                pattern_width=0.08,
                pattern_axis="y",
                pattern_distort=2.0,
                pattern_above=0.024,
                pattern_fade=0.014,
                fur=0.6,
                fur_scale=500.0,
            ),
            # the coat down the leg, darkening only over the paw itself (v3's dark lower legs read as socks)
            "paw": _m(
                "#B68A56",
                0.82,
                fur=0.5,
                fur_scale=500.0,
                marks=[
                    {
                        "at": [0.0, 0.0, -_MEERKAT_BODY_Z],
                        "radii": [1.0, 1.0, 0.026],
                        "color": "#6E4E2E",
                        "soft": 0.6,
                    }
                ],
            ),
            "ear": _m("#3A281A", 0.8),
            "muzzle": _m("#BE925C", 0.8, fur=0.4, fur_scale=500.0),
            "nose": _m("#1E1612", 0.4),
            "tailtip": _m("#1E150F", 0.8),
        },
        part_mats={"tuft": "tailtip"},
        # a pointed face: a long, narrow, tapering snout, pale, with a dark nose
        muzzle=((0.026, 0.05, 0.024), (0.0, -0.05, -0.022)),
        regions=(
            (("hips", "chest"), "back"),
            (("leg_LF_lo", "leg_RF_lo", "leg_LH_lo", "leg_RH_lo"), "paw"),
            (("tail_3",), "tailtip"),
        ),
        extras=(Extra("nose", "uv_sphere", (0.012, 0.009, 0.009), (0.0, -0.077, -0.016), "head", "nose"),),
        # the face itself tapers to the nose as one cone; a chin/throat line where the neck enters the skull;
        # the waist tucks up behind the ribs
        snout_tip=((0.0, -0.072, -0.017), 0.0065),
        jaw=0.36,
        belly_tuck=0.85,
        # the meerkat's dark "spectacles", painted softly round the eyes (the eyes stay visible in them)
        # v5 (owner 11-17): softer, lighter patches, a crescent behind and below each eye, not raccoon rings
        eye_patch=("#40291A", 1.0),  # lighter than v4's near-black #24180E
        patch_shape=(1.0, 0.95, 0.9),
        brow_max=0.3,
        patch_soft=0.4,  # a softer edge than v4's 0.28 (rings), still dark enough to read round the eye
        smooth=1.0,
        default_pose="sentinel",
        # all four paws stay level (#69); the hind paws pivot at the heel into the sentinel, counter-rotated
        # by the body's pitch so the soles stay flat on the ground as she rises (perform.walk_keys, #70)
        level_feet="FH",
    ),
    # Leopard tortoise elder: a high-domed carapace of geometric scutes (dark heart and growth rings in each
    # plate); thick, scaly, elephant-like legs; a wise old head on an extendable neck.
    "tortoise": Species(
        name="tortoise",
        body_z=0.2,
        torso=(0.36, 0.46, 0.2),
        torso_at=(0.0, 0.0, -0.02),
        torso_rot=0.0,
        shoulder=(0.14, -0.16, -0.07),
        hip=(0.13, 0.17, -0.07),
        fore_foot=(0.22, -0.2),
        hind_foot=(0.19, 0.2),
        leg_r=(0.05, 0.046, 0.058, 0.052),
        foot=("pad", 0.05, 0.03),
        knee_bend=0.25,
        neck=Chain((0.0, -0.21, -0.05), (0.0, -0.32, 0.0), 2, 0.046, 0.04),
        head_at=(0.0, -0.37, 0.02),
        head_size=(0.09, 0.125, 0.078),
        head_pitch=0.0,
        eye=(0.034, -0.03, 0.015, 0.019),
        ear=("none", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        tail=Chain((0.0, 0.25, -0.08), (0.0, 0.31, -0.11), 1, 0.02, 0.01),
        tuft=0.0,
        coat=_m(
            "#B9A27A",
            0.85,
            pattern="scales",
            pattern_color="#7D6A4E",
            pattern_scale=55.0,
            subsurface=0.08,
            grain=0.2,
            grain_scale=120.0,
        ),
        mats={
            # colour is painted per vertex by creatures.shell (areola, radiating rays, dark seams) so the marks
            # sit on the raised scutes; a fine grain and a satin sheen on top
            "shell": _m("#E3C46A", 0.45, vertex_color=True, grain=0.15, grain_scale=60.0),
            "nail": _m("#4A3E30", 0.6),
        },
        part_mats={},
        nails=3,
        shell=((0.46, 0.58, 0.46), (0.0, 0.0, 0.07)),
    ),
}

CAST = {
    "tembo": "elephant",
    "zuri": "zebra",
    "kiki": "meerkat",
    "neema": "giraffe",
    "bibi_kobe": "tortoise",
}
