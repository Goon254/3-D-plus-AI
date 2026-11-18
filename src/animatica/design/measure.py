"""Measure a species design: proportions, silhouette features and materials (no Blender needed).

Every metric is a dimensionless ratio, so briefs can state appeal ranges independent of the animal's size:

* ``head_body``    longest head dimension / body length (torso, or the shell for a tortoise). Babies: big.
* ``eye_head``     eye diameter / head height. Kids'-film eyes are large.
* ``eye_spacing``  distance between the eye centres / head width (1.0 = eyes on the head's sides).
* ``neck_head``    neck radius where it meets the head / half the head's smaller cross-section. Below 1 the
                   neck is visibly narrower than the head (the melted-elephant failure was ~1).
* ``elongation``   body length / body depth (a meerkat at 2.8 walks like a weasel, at 2.2 like a hamster).
* ``belly_gap``    daylight under the belly / body depth (legs long enough to read).
* ``leg_thickness`` lower fore-leg radius / body width.
* ``ear_head``     ear area / head side area.
* ``neck_length``  neck chain length / body height above the ground.
* ``snout``        muzzle length / head length (0 when the species has no separate muzzle).
"""

from __future__ import annotations

import math
from typing import Any

from animatica.creatures import shell as shell_mod
from animatica.creatures.species import Species


def _hex(linear: tuple[float, float, float]) -> str:
    """Linear RGB (vertex colours) -> sRGB hex."""

    def enc(c: float) -> int:
        c = max(0.0, min(1.0, c))
        v = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(v * 255)

    return "#" + "".join(f"{enc(c):02X}" for c in linear)


def luminance(hex_color: str) -> float:
    """Relative luminance (WCAG, linear sRGB) of ``#RRGGBB``: 0 = black, 1 = white."""
    h = hex_color.lstrip("#")
    c = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours (1 = identical, 21 = black on white)."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def body_length(sp: Species) -> float:
    return max(sp.torso[1], sp.shell[0][1] if sp.shell else 0.0)


def proportions(sp: Species) -> dict[str, float]:
    hw, hl, hh = sp.head_size
    ex, _ey, _ez, er = sp.eye
    blen = body_length(sp)
    depth = sp.torso[2]
    belly = sp.body_z + sp.torso_at[2] - depth / 2
    ear_area = sp.ear[1][1] * sp.ear[1][2] if sp.ear[0] != "none" else 0.0
    neck_len = math.dist(sp.neck.base, sp.neck.tip)
    out = {
        "head_body": max(sp.head_size) / blen,
        "eye_head": 2 * er / hh,
        "eye_spacing": 2 * abs(ex) / hw,
        "neck_head": sp.neck.r1 / (min(hw, hh) / 2),
        "elongation": sp.torso[1] / depth,
        "belly_gap": belly / depth,
        "leg_thickness": sp.leg_r[1] / sp.torso[0],
        "ear_head": ear_area / (hl * hh),
        "neck_length": neck_len / sp.body_z,
        "snout": sp.muzzle[0][1] / hl if sp.muzzle else 0.0,
    }
    return {k: round(v, 4) for k, v in out.items()}


def _patterns(sp: Species) -> set[str]:
    out = set()
    for m in [sp.coat, *sp.mats.values()]:
        if m.get("pattern"):
            out.add(str(m["pattern"]))
    if sp.shell is not None and sp.mats.get("shell", {}).get("vertex_color"):
        out.add("scutes")  # the carapace mesh paints its scute marks per vertex (creatures.shell)
    return out


def features(sp: Species) -> set[str]:
    """Silhouette and marking features the design has (brief ``features`` must all be present)."""
    f: set[str] = set()
    if sp.trunk is not None:
        f.add("trunk")
    if sp.shell is not None:
        f.add("shell")
    if sp.tuft > 0:
        f.add("tail_tuft")
    if sp.eye_patch is not None:
        f.add("eye_patch")
    if sp.ear[0] != "none":
        f.add("ears")
    if sp.ear[0] != "none" and sp.ear[1][1] * sp.ear[1][2] > 0.5 * sp.head_size[1] * sp.head_size[2]:
        f.add("big_ears")
    if sp.muzzle is not None:
        f.add("muzzle")
    if sp.default_pose == "sentinel":
        f.add("sentinel")
    if sp.separate_head:
        f.add("separate_head")
    for ex in sp.extras:
        f.add(ex.id.rstrip("_LR").split("_")[0])  # ossicone_L -> ossicone, mane -> mane
    f |= {f"pattern:{p}" for p in _patterns(sp)}
    return f


def materials(sp: Species) -> dict[str, Any]:
    """Coat/part luminances, pattern contrast, and dark parts that may read as flat black blocks.

    ``dark_regions`` lists body-mesh regions (bone prefixes -> material) whose colour is near-black
    (luminance < 0.02), or that carries a near-black ``marks`` entry: a whole leg segment painted that dark
    reads as a black stick at thumbnail size.
    Small accents (nose, tail tip, nails) are not regions of the body mesh and are not listed.
    """
    coat = str(sp.coat["base_color"])
    lum = {"coat": round(luminance(coat), 4)}
    for k, m in sp.mats.items():
        if "base_color" in m:
            lum[k] = round(luminance(str(m["base_color"])), 4)
    contrast = {}
    for k, m in {"coat": sp.coat, **sp.mats}.items():
        if m.get("pattern_color"):
            contrast[k] = round(contrast_ratio(str(m["base_color"]), str(m["pattern_color"])), 2)
        elif m.get("vertex_color") and k == "shell":  # painted marks: the ochre ground against the dark rays
            contrast[k] = round(contrast_ratio(_hex(shell_mod.GROUND), _hex(shell_mod.RAY)), 2)
    dark = []
    for bones, key in sp.regions:
        m = sp.mats.get(key, {})
        if "base_color" in m and luminance(str(m["base_color"])) < 0.02:
            dark.append({"material": key, "bones": list(bones)})
            continue
        # a near-black mark painted over the region (the meerkat's paw shade) is a black block too
        marks = [i for i, mk in enumerate(m.get("marks") or []) if luminance(str(mk["color"])) < 0.02]
        if marks:
            dark.append({"material": key, "bones": list(bones), "marks": marks})
    return {"luminance": lum, "pattern_contrast": contrast, "dark_regions": dark}


def describe(sp: Species) -> dict[str, Any]:
    return {
        "species": sp.name,
        "proportions": proportions(sp),
        "features": sorted(features(sp)),
        "materials": materials(sp),
    }
