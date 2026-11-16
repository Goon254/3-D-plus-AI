"""Art/Asset agent: builds the set, the character rig and props as batched ops.

Parameters over strokes: the LLM (or the scripted provider) chooses *recipe parameters* (colours,
proportions, set-dressing density, landmarks). The recipes below turn parameters into ops. Every
character recipe exposes the same rig interface, so the Animator works for all of them:

    hero_root (empty, on the floor; translate/yaw)            facing -Y in rest pose
      hero_body (mesh)                                        lean (rot X), bob/squash
        hero_head_pivot (empty)  -> hero_head, hero_eye_L/R (blink = scale Z), hero_mouth (shape keys
                                    open/wide/round), hero_antenna_pivot (secondary motion)
        hero_arm_pivot_L/R (empty) -> arm + hand (reach = rot X negative)
"""

from __future__ import annotations

import colorsys
import math
import random
import zlib
from typing import TYPE_CHECKING, Any

from ..core.llm import scripted
from ..core.plan import FilmPlan
from .base import Agent

if TYPE_CHECKING:
    from ..core.orchestrator import Context

SYSTEM = """You are the Art/Asset lead. Given a film plan, choose parameters for procedural recipes.
Return JSON: {"character": {"color": hex, "eye_color": hex, "trim_color": hex, "proportions": "chunky"|"slim",
"antenna": bool}, "prop": {"color": hex, "glow": 0..5}, "set": {"density": 0..3, "seed": int,
"landmarks": [up to 3 of: "sun_disc","moon","hills","fence","pile","tree_line","ruins","planet"]}}
Stay within the style bible palette and shape language."""


def shade(hex_color: str, light: float = 0.0, sat: float = 0.0) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    h, l_, s = colorsys.rgb_to_hls(r, g, b)
    l_ = min(1, max(0, l_ + light))
    s = min(1, max(0, s + sat))
    r, g, b = colorsys.hls_to_rgb(h, l_, s)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def mat(
    color: str,
    metallic: float = 0.0,
    roughness: float = 0.5,
    emission: str | None = None,
    strength: float = 0.0,
    name: str | None = None,
) -> dict[str, Any]:
    m: dict[str, Any] = {"base_color": color, "metallic": metallic, "roughness": roughness}
    if emission:
        m["emission"], m["emission_strength"] = emission, strength
    if name:
        m["name"] = name
    return m


# ------------------------------------------------------------------------------------------ mouth
def mouth_mesh(
    half_w: float = 0.07, half_h: float = 0.009, n: int = 20, open_mul: float = 7.0
) -> tuple[list, list, dict[str, list]]:
    """Ellipse fan in the XZ plane (faces -Y). Shape keys: open, wide, round (absolute positions)."""

    def ring(hw: float, hh: float, pinch: float = 0.0) -> list[tuple[float, float, float]]:
        pts = [(0.0, 0.0, 0.0)]
        for i in range(n):
            a = 2 * math.pi * i / n
            x, z = hw * math.cos(a), hh * math.sin(a)
            if pinch:  # flatten the top lip a little: friendlier "D" shape when open
                z = z * (1 - pinch) if z > 0 else z
            pts.append((round(x, 5), 0.0, round(z, 5)))
        return pts

    verts = ring(half_w, half_h)
    faces = [[0, 1 + i, 1 + (i + 1) % n] for i in range(n)]
    keys = {
        "open": ring(half_w * 0.85, half_h * open_mul, pinch=0.35),
        "wide": ring(half_w * 1.4, half_h * 2.2),
        "round": ring(half_w * 0.5, half_h * 5.0),
    }
    return verts, faces, keys


# ------------------------------------------------------------------------------------------ characters
def robot_ops(
    color: str, eye: str, trim: str, antenna: bool = True, scale: float = 1.0, **_: Any
) -> list[dict[str, Any]]:
    dark = "#1B1F27"
    ops: list[dict[str, Any]] = [
        {
            "op": "create_empty",
            "id": "hero_root",
            "location": [0, 0, 0],
            "scale": [scale] * 3,
            "tags": ["hero", "rig"],
        },
        {
            "op": "create_primitive",
            "id": "hero_body",
            "shape": "cube",
            "size": [0.62, 0.46, 0.5],
            "location": [0, 0, 0.55],
            "parent": "hero_root",
            "tags": ["hero"],
        },
        {
            "op": "add_modifier",
            "target": "hero_body",
            "type": "bevel",
            "params": {"width": 0.07, "segments": 4},
        },
        {
            "op": "create_primitive",
            "id": "hero_belly",
            "shape": "cube",
            "size": [0.4, 0.03, 0.22],
            "location": [0, -0.235, -0.04],
            "parent": "hero_body",
        },
        {
            "op": "add_modifier",
            "target": "hero_belly",
            "type": "bevel",
            "params": {"width": 0.012, "segments": 2},
        },
        {
            "op": "create_primitive",
            "id": "hero_chest_light",
            "shape": "uv_sphere",
            "radius": 0.035,
            "location": [0.12, -0.255, -0.04],
            "parent": "hero_body",
            "smooth": True,
            "segments": 16,
        },
    ]
    for side, x in (("L", 1), ("R", -1)):
        ops += [
            {
                "op": "create_primitive",
                "id": f"hero_tread_{side}",
                "shape": "cube",
                "size": [0.15, 0.62, 0.28],
                "location": [0.34 * x, 0, 0.14],
                "parent": "hero_root",
                "tags": ["hero"],
            },
            {
                "op": "add_modifier",
                "target": f"hero_tread_{side}",
                "type": "bevel",
                "params": {"width": 0.1, "segments": 6},
            },
        ]
        for j, y in enumerate((-0.2, 0.0, 0.2)):
            # wheel = un-rotated pivot (spins about local X, the axle) -> hub disc + spoke + off-centre bolt, so the
            # Animator can roll it by distance travelled and the eye reads "driving", not "gliding"
            ops += [
                {
                    "op": "create_empty",
                    "id": f"hero_wheel_{side}{j}",
                    "location": [0.43 * x, y, 0.14],
                    "parent": "hero_root",
                },
                {
                    "op": "create_primitive",
                    "id": f"hero_cog_{side}{j}",
                    "shape": "cylinder",
                    "radius": 0.075,
                    "depth": 0.03,
                    "rotation": [0, 90, 0],
                    "parent": f"hero_wheel_{side}{j}",
                    "segments": 16,
                },
                {
                    "op": "create_primitive",
                    "id": f"hero_spoke_{side}{j}",
                    "shape": "cube",
                    "size": [0.012, 0.13, 0.022],
                    "location": [0.017 * x, 0, 0],
                    "parent": f"hero_wheel_{side}{j}",
                },
                {
                    "op": "create_primitive",
                    "id": f"hero_bolt_{side}{j}",
                    "shape": "uv_sphere",
                    "radius": 0.016,
                    "location": [0.02 * x, 0, 0.048],
                    "parent": f"hero_wheel_{side}{j}",
                    "segments": 12,
                    "smooth": True,
                },
            ]
        ops += [
            # two-segment arm: shoulder pivot -> upper arm -> elbow pivot -> forearm + hand (arms can bend)
            {
                "op": "create_empty",
                "id": f"hero_arm_pivot_{side}",
                "location": [0.37 * x, 0, 0.12],
                "parent": "hero_body",
            },
            {
                "op": "create_primitive",
                "id": f"hero_arm_{side}",
                "shape": "cylinder",
                "radius": 0.04,
                "depth": 0.16,
                "location": [0.03 * x, 0, -0.08],
                "parent": f"hero_arm_pivot_{side}",
                "segments": 16,
                "smooth": True,
            },
            {
                "op": "create_empty",
                "id": f"hero_elbow_{side}",
                "location": [0.03 * x, 0, -0.16],
                "parent": f"hero_arm_pivot_{side}",
            },
            {
                "op": "create_primitive",
                "id": f"hero_elbow_joint_{side}",
                "shape": "uv_sphere",
                "radius": 0.045,
                "parent": f"hero_elbow_{side}",
                "smooth": True,
                "segments": 16,
            },
            {
                "op": "create_primitive",
                "id": f"hero_forearm_{side}",
                "shape": "cylinder",
                "radius": 0.037,
                "depth": 0.13,
                "location": [0, 0, -0.07],
                "parent": f"hero_elbow_{side}",
                "segments": 16,
                "smooth": True,
            },
            {
                "op": "create_primitive",
                "id": f"hero_hand_{side}",
                "shape": "uv_sphere",
                "radius": 0.065,
                "location": [0, 0, -0.16],
                "parent": f"hero_elbow_{side}",
                "smooth": True,
                "segments": 16,
            },
        ]
    ops += [
        {
            "op": "create_primitive",
            "id": "hero_neck",
            "shape": "cylinder",
            "radius": 0.07,
            "depth": 0.14,
            "location": [0, 0, 0.3],
            "parent": "hero_body",
            "segments": 16,
        },
        {"op": "create_empty", "id": "hero_head_pivot", "location": [0, 0, 0.33], "parent": "hero_body"},
        {
            "op": "create_primitive",
            "id": "hero_head",
            "shape": "cube",
            "size": [0.58, 0.46, 0.4],
            "location": [0, 0, 0.22],
            "parent": "hero_head_pivot",
            "tags": ["hero"],
        },
        {
            "op": "add_modifier",
            "target": "hero_head",
            "type": "bevel",
            "params": {"width": 0.1, "segments": 5},
        },
        {
            "op": "create_primitive",
            "id": "hero_face",
            "shape": "cube",
            "size": [0.48, 0.03, 0.32],
            "location": [0, -0.225, 0.22],
            "parent": "hero_head_pivot",
        },
        {
            "op": "add_modifier",
            "target": "hero_face",
            "type": "bevel",
            "params": {"width": 0.06, "segments": 4},
        },
    ]
    for side, x in (("L", 1), ("R", -1)):
        ops.append(
            {
                "op": "create_primitive",
                "id": f"hero_eye_{side}",
                "shape": "uv_sphere",
                "radius": 0.05,
                "scale": [1.0, 0.35, 1.25],
                "location": [0.115 * x, -0.243, 0.285],
                "parent": "hero_head_pivot",
                "smooth": True,
                "segments": 24,
            }
        )
        ops.append(
            {
                "op": "create_primitive",
                "id": f"hero_ear_{side}",
                "shape": "cylinder",
                "radius": 0.08,
                "depth": 0.06,
                "rotation": [0, 90, 0],
                "location": [0.31 * x, 0, 0.22],
                "parent": "hero_head_pivot",
                "segments": 20,
            }
        )
    # a big, readable mouth: lip sync is the emotional centre of the dialogue close-up
    verts, faces, keys = mouth_mesh(0.105, 0.011, open_mul=5.5)
    ops += [
        {
            "op": "create_mesh",
            "id": "hero_mouth",
            "vertices": verts,
            "faces": faces,
            "location": [0, -0.246, 0.145],
            "parent": "hero_head_pivot",
            "tags": ["hero", "mouth"],
        },
        {"op": "add_shape_keys", "target": "hero_mouth", "keys": keys},
        {
            "op": "create_empty",
            "id": "hero_antenna_pivot",
            "location": [0, 0, 0.41],
            "parent": "hero_head_pivot",
        },
    ]
    if antenna:
        ops += [
            {
                "op": "create_primitive",
                "id": "hero_antenna",
                "shape": "cylinder",
                "radius": 0.012,
                "depth": 0.22,
                "location": [0, 0, 0.11],
                "parent": "hero_antenna_pivot",
                "segments": 8,
            },
            {
                "op": "create_primitive",
                "id": "hero_antenna_tip",
                "shape": "uv_sphere",
                "radius": 0.035,
                "location": [0, 0, 0.24],
                "parent": "hero_antenna_pivot",
                "smooth": True,
                "segments": 16,
            },
        ]
    body = ["hero_body", "hero_head"]
    ops += [
        {"op": "set_material", "targets": body, "material": mat(color, 0.35, 0.38, name="hero_paint")},
        {
            "op": "set_material",
            "targets": [
                "hero_tread_L",
                "hero_tread_R",
                "hero_neck",
                "hero_arm_L",
                "hero_arm_R",
                "hero_forearm_L",
                "hero_forearm_R",
            ]
            + [f"hero_{k}_{s}{j}" for k in ("spoke", "bolt") for s in "LR" for j in range(3)],
            "material": mat(trim, 0.6, 0.45, name="hero_trim"),
        },
        {
            "op": "set_material",
            "targets": [f"hero_cog_{s}{j}" for s in "LR" for j in range(3)]
            + [
                "hero_ear_L",
                "hero_ear_R",
                "hero_hand_L",
                "hero_hand_R",
                "hero_belly",
                "hero_elbow_joint_L",
                "hero_elbow_joint_R",
            ],
            "material": mat(shade(color, -0.12), 0.7, 0.3, name="hero_metal"),
        },
        {
            "op": "set_material",
            "targets": ["hero_face"],
            "material": mat(dark, 0.2, 0.15, name="hero_screen"),
        },
        {
            "op": "set_material",
            "targets": ["hero_eye_L", "hero_eye_R", "hero_mouth"],
            "material": mat(eye, 0.0, 0.3, emission=eye, strength=4.0, name="hero_glow"),
        },
        {
            "op": "set_material",
            "targets": ["hero_chest_light"] + (["hero_antenna_tip"] if antenna else []),
            "material": mat("#FF4D4D", 0.0, 0.3, emission="#FF4D4D", strength=3.0, name="hero_led"),
        },
    ]
    if antenna:
        ops.append(
            {
                "op": "set_material",
                "targets": ["hero_antenna"],
                "material": mat(trim, 0.6, 0.4, name="hero_trim"),
            }
        )
    return ops


CREAM = "#F4E7D3"
DARK_FUR = "#2B1E1A"

# Species-defining parts, so a "fox" reads as a fox at a glance (review 14:50). Every species keeps the
# shared rig interface; unknown species fall back to the generic round creature.
SPECIES = {
    "fox": {
        "ears": {"radius": 0.115, "depth": 0.34, "x": 0.15, "z": 0.47, "tilt": 16, "tip": True},
        "muzzle": {"radius": 0.13, "scale": [0.8, 1.4, 0.66], "y": -0.28, "z": 0.12},
        "tail": "bushy",
        "legs": True,
        "chest": CREAM,
    },
    "cat": {
        "ears": {"radius": 0.105, "depth": 0.2, "x": 0.17, "z": 0.45, "tilt": 20, "tip": False},
        "muzzle": {"radius": 0.085, "scale": [1.1, 0.8, 0.75], "y": -0.27, "z": 0.12},
        "tail": "long",
        "legs": True,
        "chest": None,
    },
    "bunny": {
        "ears": {"long": True, "x": 0.09, "z": 0.5, "tilt": 10},
        "muzzle": {"radius": 0.08, "scale": [1.1, 0.8, 0.75], "y": -0.27, "z": 0.13},
        "tail": "puff",
        "legs": False,
        "chest": CREAM,
    },
}
SPECIES["dog"] = {**SPECIES["fox"], "ears": {**SPECIES["fox"]["ears"], "depth": 0.22, "tilt": 34}}
SPECIES["dog"]["tail"] = "long"
SPECIES["dog"]["chest"] = None


def critter_ops(
    color: str, eye: str, trim: str, scale: float = 1.0, species: str = "creature", **_: Any
) -> list[dict[str, Any]]:
    sp = SPECIES.get(species, {})
    chest = sp.get("chest") or shade(color, 0.22, -0.1)
    muzzle = sp.get("muzzle")
    fur_parts = [
        "hero_body",
        "hero_head",
        "hero_ear_L",
        "hero_ear_R",
        "hero_tail",
        "hero_arm_L",
        "hero_arm_R",
    ]
    cream_parts = ["hero_belly", "hero_foot_L", "hero_foot_R"]
    dark_parts = ["hero_eye_L", "hero_eye_R", "hero_nose"]

    def sphere(
        pid: str, radius: float, loc: list[float], parent: str, scl: list[float] | None = None, **kw: Any
    ):
        op = {"op": "create_primitive", "id": pid, "shape": "uv_sphere", "radius": radius, "location": loc}
        op.update({"parent": parent, "smooth": True, **kw})
        if scl:
            op["scale"] = scl
        return op

    ops: list[dict[str, Any]] = [
        {"op": "create_empty", "id": "hero_root", "scale": [scale] * 3, "tags": ["hero", "rig"]},
        sphere("hero_body", 0.36, [0, 0, 0.33], "hero_root", [1, 0.9, 0.85], tags=["hero"]),
        # chest/belly patch: cream bib on the fox, lighter belly otherwise
        sphere(
            "hero_belly",
            0.24,
            [0, -0.2, -0.04] if not sp else [0, -0.21, 0.04],
            "hero_body",
            [0.95, 0.5, 1.1],
        ),
        {"op": "create_empty", "id": "hero_head_pivot", "location": [0, 0, 0.24], "parent": "hero_body"},
        sphere("hero_head", 0.3, [0, 0, 0.22], "hero_head_pivot", tags=["hero"]),
        {
            "op": "create_empty",
            "id": "hero_antenna_pivot",
            "location": [0, 0.3, -0.02],
            "parent": "hero_body",
        },
    ]
    # ---------------------------------------------------------------- tail (secondary motion on the pivot)
    tail = sp.get("tail")
    if tail == "bushy":  # big plume sweeping up and back, white tip
        ops += [
            sphere(
                "hero_tail",
                0.17,
                [0, 0.2, 0.12],
                "hero_antenna_pivot",
                [0.72, 1.9, 0.72],
                rotation=[42, 0, 0],
            ),
            sphere(
                "hero_tail_tip",
                0.12,
                [0, 0.42, 0.32],
                "hero_antenna_pivot",
                [0.78, 1.05, 0.78],
                rotation=[42, 0, 0],
            ),
        ]
        cream_parts.append("hero_tail_tip")
    elif tail == "long":
        ops += [
            sphere(
                "hero_tail", 0.06, [0, 0.22, 0.14], "hero_antenna_pivot", [1, 4.2, 1], rotation=[48, 0, 0]
            ),
            sphere("hero_tail_tip", 0.065, [0, 0.36, 0.33], "hero_antenna_pivot"),
        ]
        fur_parts.append("hero_tail_tip")
    elif tail == "puff":
        ops.append(sphere("hero_tail", 0.12, [0, 0.06, 0.04], "hero_antenna_pivot"))
    else:
        ops.append(sphere("hero_tail", 0.11, [0, 0.1, 0.05], "hero_antenna_pivot", [0.8, 1.4, 0.8]))
    if tail == "puff":
        fur_parts.remove("hero_tail")
        cream_parts.append("hero_tail")

    ears = sp.get("ears")
    for side, x in (("L", 1), ("R", -1)):
        # ------------------------------------------------------------ ears: a matched pair, species shaped
        if ears and ears.get("long"):
            ops.append(
                sphere(
                    f"hero_ear_{side}",
                    0.075,
                    [ears["x"] * x, 0.02, ears["z"] + 0.12],
                    "hero_head_pivot",
                    [0.75, 0.42, 3.0],
                    rotation=[-6, ears["tilt"] * x, 0],
                )
            )
        else:
            e = ears or {"radius": 0.1, "depth": 0.24, "x": 0.16, "z": 0.47, "tilt": 18, "tip": False}
            ops.append(
                {
                    "op": "create_primitive",
                    "id": f"hero_ear_{side}",
                    "shape": "cone",
                    "radius": e["radius"],
                    "depth": e["depth"],
                    "location": [e["x"] * x, 0.0, e["z"]],
                    "rotation": [-8 if ears else 0, e["tilt"] * x, 0],
                    "scale": [1, 0.55, 1] if ears else [1, 1, 1],
                    "parent": "hero_head_pivot",
                    "smooth": True,
                    "segments": 24,
                }
            )
            if e.get("tip"):  # dark ear tips (fox)
                rt, h = math.radians(e["tilt"] * x), e["depth"] * 0.36
                # follow the ear's X (-8 deg) then Y (tilt) rotation so the tip sits on the ear's point
                up, back = h * math.cos(math.radians(8)), h * math.sin(math.radians(8))
                ops.append(
                    {
                        "op": "create_primitive",
                        "id": f"hero_ear_tip_{side}",
                        "shape": "cone",
                        "radius": e["radius"] * 0.42,
                        "depth": e["depth"] * 0.3,
                        "location": [e["x"] * x + math.sin(rt) * up, back, e["z"] + math.cos(rt) * up],
                        "rotation": [-8, e["tilt"] * x, 0],
                        "scale": [1.05, 0.6, 1],
                        "parent": "hero_head_pivot",
                        "smooth": True,
                        "segments": 24,
                    }
                )
                dark_parts.append(f"hero_ear_tip_{side}")
        # ------------------------------------------------------------ eyes: on the front of the face, with a
        # catch-light so they read as eyes (not painted ovals) at 480x270
        eye_x, eye_y, eye_z = (0.12, -0.255, 0.29) if sp else (0.11, -0.27, 0.28)
        ops += [
            sphere(
                f"hero_eye_{side}",
                0.05 if sp else 0.045,
                [eye_x * x, eye_y, eye_z],
                "hero_head_pivot",
                [1, 0.5, 1.3],
            ),
            # child of the eye (inherits its blink squash); same side on both eyes, like a real key light
            sphere(f"hero_eye_glint_{side}", 0.016, [-0.016, -0.046, 0.016], f"hero_eye_{side}"),
        ]
        # ------------------------------------------------------------ feet / legs
        if sp.get("legs"):
            # four stubby legs: front legs hang from the shoulders (the "arms": they lift to reach/wave),
            # hind legs are haunches + paws on the root
            ops += [
                sphere(f"hero_haunch_{side}", 0.15, [0.17 * x, 0.15, -0.14], "hero_body", [0.85, 1.05, 1.0]),
                sphere(f"hero_foot_{side}", 0.085, [0.17 * x, 0.1, 0.045], "hero_root", [1, 1.45, 0.55]),
                {
                    "op": "create_empty",
                    "id": f"hero_arm_pivot_{side}",
                    "location": [0.15 * x, -0.17, -0.1],
                    "parent": "hero_body",
                },
                sphere(f"hero_arm_{side}", 0.068, [0, 0, -0.13], f"hero_arm_pivot_{side}", [1, 1, 2.3]),
                sphere(
                    f"hero_paw_{side}", 0.072, [0, -0.025, -0.24], f"hero_arm_pivot_{side}", [1, 1.3, 0.62]
                ),
            ]
            fur_parts.append(f"hero_haunch_{side}")
            if species == "fox":  # black "socks"
                cream_parts.remove(f"hero_foot_{side}")
                dark_parts += [f"hero_foot_{side}", f"hero_paw_{side}"]
            else:
                cream_parts.append(f"hero_paw_{side}")
        else:
            ops += [
                sphere(f"hero_foot_{side}", 0.1, [0.16 * x, -0.06, 0.05], "hero_root", [1, 1.3, 0.5]),
                {
                    "op": "create_empty",
                    "id": f"hero_arm_pivot_{side}",
                    "location": [0.3 * x, -0.05, 0.05],
                    "parent": "hero_body",
                },
                sphere(
                    f"hero_arm_{side}", 0.07, [0.02 * x, 0, -0.08], f"hero_arm_pivot_{side}", [0.8, 0.8, 1.6]
                ),
            ]
    # ---------------------------------------------------------------- snout, nose, mouth
    if muzzle:
        tip_y = muzzle["y"] - muzzle["radius"] * muzzle["scale"][1]
        ops.append(
            sphere(
                "hero_muzzle",
                muzzle["radius"],
                [0, muzzle["y"], muzzle["z"]],
                "hero_head_pivot",
                muzzle["scale"],
            )
        )
        cream_parts.append("hero_muzzle")
        nose_loc = [0, tip_y + 0.01, muzzle["z"] + muzzle["radius"] * muzzle["scale"][2] * 0.55]
        # on the snout's front surface, below the nose: an ellipsoid at 45 % down is 0.89 of its depth
        mouth_loc = [
            0,
            muzzle["y"] - muzzle["radius"] * muzzle["scale"][1] * 0.89 - 0.012,
            muzzle["z"] - muzzle["radius"] * muzzle["scale"][2] * 0.45,
        ]
        nose_r = 0.042 if species in ("fox", "dog") else 0.028
    else:
        nose_loc, mouth_loc, nose_r = [0, -0.3, 0.19], [0, -0.29, 0.13], 0.03
    verts, faces, keys = mouth_mesh(0.075 if not muzzle else 0.065, 0.01, open_mul=6.0)
    ops += [
        {
            "op": "create_mesh",
            "id": "hero_mouth",
            "vertices": verts,
            "faces": faces,
            "location": mouth_loc,
            "parent": "hero_head_pivot",
            "tags": ["hero", "mouth"],
        },
        {"op": "add_shape_keys", "target": "hero_mouth", "keys": keys},
        sphere("hero_nose", nose_r, nose_loc, "hero_head_pivot", [1.25, 0.9, 0.8] if muzzle else None),
        {"op": "set_material", "targets": fur_parts, "material": mat(color, 0.0, 0.7, name="hero_fur")},
        {"op": "set_material", "targets": cream_parts, "material": mat(chest, 0.0, 0.8, name="hero_belly")},
        {
            "op": "set_material",
            "targets": dark_parts,
            "material": mat("#151515" if not sp else DARK_FUR, 0.0, 0.25, name="hero_eyes"),
        },
        {
            "op": "set_material",
            "targets": ["hero_eye_glint_L", "hero_eye_glint_R"],
            "material": mat("#FFFFFF", 0.0, 0.2, emission="#FFFFFF", strength=2.0, name="hero_eye_glint"),
        },
        {
            "op": "set_material",
            "targets": ["hero_mouth"],
            "material": mat("#5A1E24", 0.0, 0.4, name="hero_mouth"),
        },
    ]
    return ops


CHARACTER_RECIPES = {"robot": robot_ops, "critter": critter_ops}
HERO_HEIGHT = {"robot": 1.55, "critter": 1.05}
HERO_HEAD_Z = {"robot": 1.12, "critter": 0.8}  # world height of the face centre at scale 1


# ------------------------------------------------------------------------------------------ props
def prop_ops(
    kind: str, color: str, location: tuple[float, float, float], glow: float = 0.0
) -> tuple[list[dict], float]:
    """Returns (ops, height). Root: ``prop`` (empty at the floor); sway pivot: ``prop_pivot``."""
    x, y, z = location
    ops: list[dict[str, Any]] = [
        {"op": "create_empty", "id": "prop", "location": [x, y, z], "tags": ["prop", "rig"]},
        {"op": "create_empty", "id": "prop_pivot", "parent": "prop"},
    ]
    height = 0.45
    if kind == "flower":
        stem = 0.42
        ops += [
            {
                "op": "create_primitive",
                "id": "prop_stem",
                "shape": "cylinder",
                "radius": 0.014,
                "depth": stem,
                "location": [0, 0, stem / 2],
                "parent": "prop_pivot",
                "segments": 12,
                "smooth": True,
            },
            {
                "op": "create_primitive",
                "id": "prop_leaf_1",
                "shape": "uv_sphere",
                "radius": 0.07,
                "scale": [1.4, 0.25, 0.5],
                "location": [0.07, 0, 0.13],
                "rotation": [0, -30, 0],
                "parent": "prop_pivot",
                "smooth": True,
            },
            {
                "op": "create_primitive",
                "id": "prop_leaf_2",
                "shape": "uv_sphere",
                "radius": 0.06,
                "scale": [1.4, 0.25, 0.5],
                "location": [-0.06, 0, 0.22],
                "rotation": [0, 35, 0],
                "parent": "prop_pivot",
                "smooth": True,
            },
            {
                "op": "create_empty",
                "id": "prop_head",
                "location": [0, 0, stem],
                "rotation": [-15, 0, 0],
                "parent": "prop_pivot",
            },
            {
                "op": "create_primitive",
                "id": "prop_center",
                "shape": "uv_sphere",
                "radius": 0.042,
                "scale": [1, 0.6, 1],
                "parent": "prop_head",
                "smooth": True,
            },
        ]
        petals = []
        for i in range(7):
            a = 360 * i / 7
            ar = math.radians(a)
            pid = f"prop_petal_{i}"
            petals.append(pid)
            ops.append(
                {
                    "op": "create_primitive",
                    "id": pid,
                    "shape": "uv_sphere",
                    "radius": 0.06,
                    "scale": [1.25, 0.25, 0.6],
                    "location": [0.075 * math.cos(ar), 0.01, 0.075 * math.sin(ar)],
                    "rotation": [0, -a, 0],
                    "parent": "prop_head",
                    "smooth": True,
                    "segments": 20,
                }
            )
        ops += [
            {
                "op": "set_material",
                "targets": ["prop_stem", "prop_leaf_1", "prop_leaf_2"],
                "material": mat("#3F8F3A", 0, 0.6, name="prop_green"),
            },
            {
                "op": "set_material",
                "targets": petals,
                "material": mat(color, 0, 0.45, emission=color, strength=0.4 + glow, name="prop_petals"),
            },
            {
                "op": "set_material",
                "targets": ["prop_center"],
                "material": mat(
                    "#FFD23F", 0, 0.5, emission="#FFB000", strength=0.6 + glow, name="prop_center"
                ),
            },
        ]
        height = stem + 0.1
    elif kind == "lantern":
        ops += [
            {
                "op": "create_primitive",
                "id": "prop_base",
                "shape": "cylinder",
                "radius": 0.1,
                "depth": 0.04,
                "location": [0, 0, 0.02],
                "parent": "prop_pivot",
            },
            {
                "op": "create_primitive",
                "id": "prop_glass",
                "shape": "cylinder",
                "radius": 0.08,
                "depth": 0.22,
                "location": [0, 0, 0.15],
                "parent": "prop_pivot",
                "smooth": True,
            },
            {
                "op": "create_primitive",
                "id": "prop_cap",
                "shape": "cone",
                "radius": 0.11,
                "depth": 0.08,
                "location": [0, 0, 0.3],
                "parent": "prop_pivot",
            },
            {
                "op": "create_primitive",
                "id": "prop_handle",
                "shape": "torus",
                "radius": 0.05,
                "depth": 0.008,
                "rotation": [90, 0, 0],
                "location": [0, 0, 0.37],
                "parent": "prop_pivot",
            },
            {
                "op": "add_light",
                "id": "prop_light",
                "light_type": "point",
                "energy": 25 + 10 * glow,
                "color": color,
                "location": [0, 0, 0.15],
                "parent": "prop_pivot",
                "size": 0.05,
            },
            {
                "op": "set_material",
                "targets": ["prop_base", "prop_cap", "prop_handle"],
                "material": mat("#2B2B30", 0.8, 0.4, name="prop_iron"),
            },
            {
                "op": "set_material",
                "targets": ["prop_glass"],
                "material": mat(color, 0, 0.2, emission=color, strength=6 + glow, name="prop_flame"),
            },
        ]
        height = 0.42
    elif kind == "crystal":
        ops += [
            {
                "op": "create_primitive",
                "id": "prop_gem",
                "shape": "ico_sphere",
                "radius": 0.12,
                "scale": [0.8, 0.8, 2.0],
                "location": [0, 0, 0.22],
                "parent": "prop_pivot",
                "segments": 16,
            },
            {
                "op": "create_primitive",
                "id": "prop_gem_2",
                "shape": "ico_sphere",
                "radius": 0.07,
                "scale": [0.8, 0.8, 1.8],
                "location": [0.1, 0.03, 0.1],
                "rotation": [0, 25, 0],
                "parent": "prop_pivot",
                "segments": 16,
            },
            {
                "op": "create_primitive",
                "id": "prop_rock",
                "shape": "ico_sphere",
                "radius": 0.14,
                "scale": [1.2, 1, 0.4],
                "location": [0, 0, 0.02],
                "parent": "prop_pivot",
                "segments": 16,
            },
            {
                "op": "add_light",
                "id": "prop_light",
                "light_type": "point",
                "energy": 15 + 10 * glow,
                "color": color,
                "location": [0, 0, 0.3],
                "parent": "prop_pivot",
            },
            {
                "op": "set_material",
                "targets": ["prop_gem", "prop_gem_2"],
                "material": mat(color, 0.1, 0.05, emission=color, strength=3 + glow, name="prop_gem"),
            },
            {
                "op": "set_material",
                "targets": ["prop_rock"],
                "material": mat("#5C5852", 0, 0.9, name="prop_rock"),
            },
        ]
        height = 0.5
    elif kind == "mushroom":
        ops += [
            {
                "op": "create_primitive",
                "id": "prop_stalk",
                "shape": "cylinder",
                "radius": 0.05,
                "depth": 0.22,
                "location": [0, 0, 0.11],
                "parent": "prop_pivot",
                "smooth": True,
            },
            {
                "op": "create_primitive",
                "id": "prop_cap",
                "shape": "uv_sphere",
                "radius": 0.17,
                "scale": [1, 1, 0.55],
                "location": [0, 0, 0.24],
                "parent": "prop_pivot",
                "smooth": True,
            },
            {
                "op": "set_material",
                "targets": ["prop_stalk"],
                "material": mat("#F2E8CF", 0, 0.7, name="prop_stalk"),
            },
            {
                "op": "set_material",
                "targets": ["prop_cap"],
                "material": mat(color, 0, 0.5, emission=color, strength=0.2 + glow, name="prop_cap"),
            },
        ]
        dots = []
        for i in range(6):
            a = 2 * math.pi * i / 6
            did = f"prop_dot_{i}"
            dots.append(did)
            ops.append(
                {
                    "op": "create_primitive",
                    "id": did,
                    "shape": "uv_sphere",
                    "radius": 0.025,
                    "location": [0.11 * math.cos(a), 0.11 * math.sin(a), 0.3],
                    "parent": "prop_pivot",
                    "smooth": True,
                }
            )
        ops.append(
            {"op": "set_material", "targets": dots, "material": mat("#FFFFFF", 0, 0.6, name="prop_dots")}
        )
        height = 0.34
    elif kind == "star":
        verts, faces = [], []
        for ring_z in (-0.03, 0.03):
            for i in range(10):
                a = math.pi / 2 + 2 * math.pi * i / 10
                r = 0.16 if i % 2 == 0 else 0.07
                verts.append((r * math.cos(a), ring_z, r * math.sin(a)))
        verts += [(0, -0.05, 0), (0, 0.05, 0)]
        for i in range(10):
            j = (i + 1) % 10
            faces += [[20, j, i], [21, 10 + i, 10 + j], [i, j, 10 + j, 10 + i]]
        ops += [
            {
                "op": "create_mesh",
                "id": "prop_star",
                "vertices": verts,
                "faces": faces,
                "location": [0, 0, 0.25],
                "parent": "prop_pivot",
            },
            {
                "op": "add_light",
                "id": "prop_light",
                "light_type": "point",
                "energy": 20 + 10 * glow,
                "color": color,
                "location": [0, -0.1, 0.25],
                "parent": "prop_pivot",
            },
            {
                "op": "set_material",
                "targets": ["prop_star"],
                "material": mat(color, 0.2, 0.3, emission=color, strength=5 + glow, name="prop_star"),
            },
        ]
        height = 0.42
    else:  # ball / egg / book: simple solids
        shape = {
            "ball": ("uv_sphere", [1, 1, 1], 0.14),
            "egg": ("uv_sphere", [0.85, 0.85, 1.15], 0.13),
            "book": ("cube", [1, 1, 1], 0.1),
        }[kind]
        op: dict[str, Any] = {
            "op": "create_primitive",
            "id": "prop_body",
            "shape": shape[0],
            "parent": "prop_pivot",
            "smooth": shape[0] != "cube",
        }
        if kind == "book":
            op.update(size=[0.3, 0.22, 0.06], location=[0, 0, 0.03])
            height = 0.1
        else:
            op.update(radius=shape[2], scale=shape[1], location=[0, 0, shape[2] * shape[1][2]])
            height = 2 * shape[2] * shape[1][2]
        ops += [
            op,
            {
                "op": "set_material",
                "targets": ["prop_body"],
                "material": mat(color, 0.1, 0.35, name="prop_mat"),
            },
        ]
    return ops, height


# ------------------------------------------------------------------------------------------ sets
def _scatter_positions(
    rng: random.Random, n: int, rmin: float, rmax: float, front_ok: bool = False
) -> list[tuple[float, float]]:
    pts = []
    tries = 0
    while len(pts) < n and tries < n * 50:
        tries += 1
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(rmin, rmax)
        x, y = 0.0 + r * math.cos(a), r * math.sin(a)
        if not front_ok and y < -1.0 and abs(x) < 9:  # keep the camera side clear
            continue
        if -7 < x < 3.5 and -2.2 < y < 1.6:  # keep the hero's path clear
            continue
        pts.append((round(x, 3), round(y, 3)))
    return pts


def pebble_ops(plan: FilmPlan, seed: int, n: int = 36) -> list[dict[str, Any]]:
    """Small stones scattered around the stage: foreground scale cues so the ground isn't an empty plane.

    They stay off the hero's travel lane (|y| < 0.7 along x in -9..4) so wheels and feet never cut them.
    """
    rng = random.Random(seed * 7 + 3)
    ops: list[dict[str, Any]] = []
    ids: list[str] = []
    while len(ids) < n:
        x, y = rng.uniform(-9, 7), rng.uniform(-3.2, 4.5)
        if -9.5 < x < 4.5 and abs(y) < 0.7:
            continue
        r = rng.uniform(0.025, 0.09) * (1.6 if abs(y) > 2.5 else 1.0)
        pid = f"set_pebble_{len(ids)}"
        ops.append(
            {
                "op": "create_primitive",
                "id": pid,
                "shape": "ico_sphere",
                "radius": round(r, 3),
                "segments": 32,
                "scale": [round(rng.uniform(1.0, 1.6), 2), 1.0, round(rng.uniform(0.45, 0.7), 2)],
                "location": [round(x, 3), round(y, 3), round(r * 0.15, 3)],
                "rotation": [0, 0, round(rng.uniform(0, 360), 1)],
                "smooth": True,
                "tags": ["set", "pebble"],
            }
        )
        ids.append(pid)
    tone = shade(plan.style.palette.ground, -0.07 if plan.setting.kind != "snow" else -0.35)
    ops.append({"op": "set_material", "targets": ids, "material": mat(tone, 0, 0.85, name="set_pebble")})
    return ops


def set_ops(plan: FilmPlan, density: float, seed: int, landmarks: list[str]) -> list[dict[str, Any]]:
    kind = plan.setting.kind
    pal = plan.style.palette
    rng = random.Random(seed)
    # aerial perspective: distant surfaces dissolve into the horizon colour (no hard ground edge)
    haze = {"fade_to": pal.sky_horizon, "fade_start": 14.0, "fade_end": 85.0} if kind not in ("room",) else {}
    # fully rough, low specular: a grazing-angle sheen made a bright band at the horizon that cut distant
    # junk piles off from the ground (they read as floating roofs — review 10:36)
    ground = {
        **mat(pal.ground, 0, 1.0, name="set_ground"),
        "specular": 0.1,
        "noise": 0.5,
        "noise_scale": 0.3,
        # fine grit + bump so the ground reads as dirt/snow up close (review: "featureless ground")
        **(
            {"grain": 0.12 if kind == "snow" else 0.3, "grain_scale": 5.0, "bump": 0.25}
            if kind not in ("room", "space")
            else {}
        ),
        **haze,
    }
    ops: list[dict[str, Any]] = [
        {
            "op": "create_primitive",
            "id": "set_ground",
            "shape": "plane",
            "size": [400, 400, 1],
            "tags": ["set", "ground"],
        },
        {"op": "set_material", "targets": ["set_ground"], "material": ground},
    ]
    if kind not in ("room", "space"):
        ops += pebble_ops(plan, seed)
    n = int(round(28 * density))
    pieces: dict[str, list[str]] = {}

    def add(pid: str, matkey: str, op: dict[str, Any]) -> None:
        op["id"] = pid
        op.setdefault("tags", ["set"])
        ops.append(op)
        pieces.setdefault(matkey, []).append(pid)

    if kind == "junkyard":
        rust = ["#8C4A2F", "#6E6A64", "#A0522D", "#4F5B62", "#7A6A4F", "#9C7A3C"]
        for i, (x, y) in enumerate(_scatter_positions(rng, n, 3.2, 14)):
            t = rng.choice(["crate", "barrel", "tire", "slab", "pipe"])
            rot = [rng.uniform(-15, 15), rng.uniform(-15, 15), rng.uniform(0, 360)]
            c = rng.randrange(len(rust))
            if t == "crate":
                s = rng.uniform(0.35, 0.9)
                add(
                    f"set_junk_{i}",
                    f"rust{c}",
                    {
                        "op": "create_primitive",
                        "shape": "cube",
                        "size": [s, s * rng.uniform(0.7, 1.3), s * 0.8],
                        "location": [x, y, s * 0.36],
                        "rotation": [rot[0] * 0.3, rot[1] * 0.3, rot[2]],
                    },
                )
            elif t == "barrel":
                add(
                    f"set_junk_{i}",
                    f"rust{c}",
                    {
                        "op": "create_primitive",
                        "shape": "cylinder",
                        "radius": 0.28,
                        "depth": 0.85,
                        "location": [x, y, 0.42],
                        "rotation": [0, 0, rot[2]],
                        "segments": 20,
                    },
                )
            elif t == "tire":
                add(
                    f"set_junk_{i}",
                    "tire",
                    {
                        "op": "create_primitive",
                        "shape": "torus",
                        "radius": 0.34,
                        "depth": 0.13,
                        "location": [x, y, 0.12],
                        "rotation": [rng.uniform(-10, 10), rng.uniform(-10, 10), 0],
                        "segments": 24,
                    },
                )
            elif t == "slab":
                add(
                    f"set_junk_{i}",
                    f"rust{c}",
                    {
                        "op": "create_primitive",
                        "shape": "cube",
                        "size": [rng.uniform(0.8, 1.8), 0.06, rng.uniform(0.5, 1.2)],
                        "location": [x, y, 0.35],
                        "rotation": [rng.uniform(-30, 30), rng.uniform(-25, 25), rot[2]],
                    },
                )
            else:
                add(
                    f"set_junk_{i}",
                    f"rust{c}",
                    {
                        "op": "create_primitive",
                        "shape": "cylinder",
                        "radius": 0.09,
                        "depth": rng.uniform(1, 2.2),
                        "location": [x, y, 0.09],
                        "rotation": [90, 0, rot[2]],
                        "segments": 12,
                    },
                )
        for i, (x, y) in enumerate(_scatter_positions(rng, max(4, n // 4), 12, 30)):
            # distant scrap heaps: smooth, lumpy mounds (a 20-face icosahedron read as a pitched roof)
            s = rng.uniform(2.5, 5.5)
            add(
                f"set_pile_{i}",
                f"rust{rng.randrange(len(rust))}",
                {
                    "op": "create_primitive",
                    "shape": "ico_sphere",
                    "radius": s,
                    "scale": [1.3, 1, 0.7],
                    "location": [x, y, -s * 0.07],
                    "segments": 64,  # 4 subdivisions: the displaced dome no longer shows facets
                    "rotation": [0, 0, rng.uniform(0, 360)],
                    "smooth": True,
                },
            )
            # junk poking out of the heap breaks its dome silhouette (beams, panels, a drum)
            jr = random.Random(seed * 31 + i)
            k = s / 3.0
            for j, shape in enumerate(("beam", "panel", "drum", "beam", "panel")):
                # biased toward the crest, where the pieces break the dome's silhouette against the sky
                a, e = jr.uniform(0, 2 * math.pi), jr.uniform(0.75, 1.45)
                px = x + 1.3 * s * math.cos(e) * math.cos(a)
                py = y + s * math.cos(e) * math.sin(a)
                pz = -s * 0.07 + 0.7 * s * math.sin(e)
                piece: dict[str, Any] = {
                    "op": "create_primitive",
                    "shape": "cylinder" if shape == "drum" else "cube",
                    "location": [round(px, 3), round(py, 3), round(pz, 3)],
                    "rotation": [
                        round(jr.uniform(-40, 40), 1),
                        round(jr.uniform(-40, 40), 1),
                        round(math.degrees(a), 1),
                    ],
                }
                if shape == "beam":  # a girder or pipe end jutting up
                    piece["size"] = [
                        round(0.18 * k, 2),
                        round(0.18 * k, 2),
                        round(jr.uniform(1.4, 2.4) * k, 2),
                    ]
                elif shape == "panel":
                    piece["size"] = [
                        round(jr.uniform(0.9, 1.5) * k, 2),
                        round(0.07 * k, 2),
                        round(jr.uniform(0.6, 1.0) * k, 2),
                    ]
                else:
                    piece.update({"radius": round(0.3 * k, 2), "depth": round(0.8 * k, 2)})
                add(f"set_pile_{i}_junk{j}", f"rust{jr.randrange(len(rust))}", piece)
            ops.append(
                {
                    "op": "add_modifier",
                    "target": f"set_pile_{i}",
                    "type": "displace",
                    "params": {"noise_scale": 1.5, "strength": 0.8},
                }
            )
        mats = {f"rust{i}": mat(c, 0.5, 0.7) for i, c in enumerate(rust)}
        mats["tire"] = mat("#1E1E20", 0, 0.8)
        # a broken car silhouette
        add(
            "set_car",
            "rust1",
            {
                "op": "create_primitive",
                "shape": "cube",
                "size": [2.6, 1.3, 0.8],
                "location": [4.8, 4.0, 0.5],
                "rotation": [0, 6, 25],
            },
        )
        add(
            "set_car_top",
            "rust1",
            {
                "op": "create_primitive",
                "shape": "cube",
                "size": [1.4, 1.2, 0.6],
                "location": [4.6, 4.1, 1.1],
                "rotation": [0, 6, 25],
            },
        )
        ops.append(
            {
                "op": "add_modifier",
                "target": "set_car",
                "type": "bevel",
                "params": {"width": 0.15, "segments": 3},
            }
        )
        ops.append(
            {
                "op": "add_modifier",
                "target": "set_car_top",
                "type": "bevel",
                "params": {"width": 0.2, "segments": 3},
            }
        )
    elif kind in ("forest", "snow", "meadow"):
        leaf = {"forest": "#2F6B3A", "snow": "#E9F0F5", "meadow": "#4E8B3A"}[kind]
        for i, (x, y) in enumerate(_scatter_positions(rng, n if kind != "meadow" else n // 2, 4, 22)):
            h = rng.uniform(2.2, 4.5)
            add(
                f"set_trunk_{i}",
                "trunk",
                {
                    "op": "create_primitive",
                    "shape": "cylinder",
                    "radius": 0.14,
                    "depth": h * 0.4,
                    "location": [x, y, h * 0.2],
                    "segments": 10,
                },
            )
            for k in range(3):
                add(
                    f"set_leaves_{i}_{k}",
                    "leaf",
                    {
                        "op": "create_primitive",
                        "shape": "cone",
                        "radius": h * (0.38 - 0.08 * k),
                        "depth": h * 0.45,
                        "location": [x, y, h * (0.45 + 0.2 * k)],
                        "segments": 12,
                    },
                )
        for i, (x, y) in enumerate(_scatter_positions(rng, n, 2.6, 12, front_ok=True)):
            if kind == "meadow":
                add(
                    f"set_tuft_{i}",
                    "grass",
                    {
                        "op": "create_primitive",
                        "shape": "cone",
                        "radius": 0.09,
                        "depth": rng.uniform(0.18, 0.35),
                        "location": [x, y, 0.1],
                        "segments": 6,
                    },
                )
            else:
                s = rng.uniform(0.15, 0.4)
                add(
                    f"set_rock_{i}",
                    "rock",
                    {
                        "op": "create_primitive",
                        "shape": "ico_sphere",
                        "radius": s,
                        "scale": [1.2, 1, 0.6],
                        "location": [x, y, s * 0.25],
                        "segments": 16,
                    },
                )
        mats = {
            "trunk": mat("#5B3A29", 0, 0.9),
            "leaf": mat(leaf, 0, 0.8),
            "grass": mat("#5FA040", 0, 0.8),
            "rock": mat("#7D7A73", 0, 0.9),
        }
        if kind == "meadow" or "hills" in landmarks:
            for i, (x, y) in enumerate(_scatter_positions(rng, 6, 18, 40)):
                s = rng.uniform(6, 12)
                add(
                    f"set_hill_{i}",
                    "hill",
                    {
                        "op": "create_primitive",
                        "shape": "uv_sphere",
                        "radius": s,
                        "scale": [1.6, 1, 0.35],
                        "location": [x, y, -s * 0.15],
                        "smooth": True,
                    },
                )
            mats["hill"] = mat(shade(pal.ground, 0.05), 0, 0.9)
    elif kind in ("desert", "beach", "space"):
        for i, (x, y) in enumerate(_scatter_positions(rng, max(6, n // 3), 10, 35)):
            s = rng.uniform(4, 9)
            add(
                f"set_dune_{i}",
                "dune",
                {
                    "op": "create_primitive",
                    "shape": "uv_sphere",
                    "radius": s,
                    "scale": [1.8, 1, 0.3],
                    "location": [x, y, -s * 0.12],
                    "smooth": True,
                },
            )
        for i, (x, y) in enumerate(_scatter_positions(rng, n // 2, 3, 14)):
            s = rng.uniform(0.2, 0.6)
            if kind == "desert" and i % 3 == 0:
                add(
                    f"set_cactus_{i}",
                    "cactus",
                    {
                        "op": "create_primitive",
                        "shape": "cylinder",
                        "radius": 0.16,
                        "depth": s * 4,
                        "location": [x, y, s * 2],
                        "smooth": True,
                        "segments": 12,
                    },
                )
            elif kind == "space":
                add(
                    f"set_crater_{i}",
                    "rock",
                    {
                        "op": "create_primitive",
                        "shape": "torus",
                        "radius": s * 2,
                        "depth": s * 0.4,
                        "scale": [1, 1, 0.3],
                        "location": [x, y, 0.0],
                    },
                )
            else:
                add(
                    f"set_rock_{i}",
                    "rock",
                    {
                        "op": "create_primitive",
                        "shape": "ico_sphere",
                        "radius": s,
                        "scale": [1.3, 1, 0.6],
                        "location": [x, y, s * 0.2],
                        "segments": 16,
                    },
                )
        mats = {
            "dune": mat(shade(pal.ground, -0.04), 0, 0.95),
            "cactus": mat("#4C7D3A", 0, 0.7),
            "rock": mat("#8A8178", 0, 0.9),
        }
        if kind == "beach":
            add(
                "set_sea",
                "sea",
                {"op": "create_primitive", "shape": "plane", "size": [160, 60, 1], "location": [0, 36, 0.03]},
            )
            mats["sea"] = mat("#2C7DA0", 0.1, 0.08)
        if kind == "space":
            add(
                "set_planet",
                "planet",
                {
                    "op": "create_primitive",
                    "shape": "uv_sphere",
                    "radius": 9,
                    "location": [-25, 70, 22],
                    "smooth": True,
                },
            )
            mats["planet"] = mat("#C97B4A", 0, 0.6, emission="#C97B4A", strength=0.6)
    elif kind == "city":
        for i, (x, y) in enumerate(_scatter_positions(rng, n, 9, 30)):
            h = rng.uniform(4, 14)
            w = rng.uniform(2, 4)
            add(
                f"set_bldg_{i}",
                f"bldg{i % 3}",
                {"op": "create_primitive", "shape": "cube", "size": [w, w, h], "location": [x, y, h / 2]},
            )
        mats = {f"bldg{i}": mat(c, 0.1, 0.7) for i, c in enumerate(["#4A4E69", "#6C6F7D", "#3D405B"])}
        add(
            "set_lamp",
            "bldg2",
            {
                "op": "create_primitive",
                "shape": "cylinder",
                "radius": 0.05,
                "depth": 2.6,
                "location": [-2.5, 2.5, 1.3],
            },
        )
    else:  # room
        add(
            "set_wall_back",
            "wall",
            {"op": "create_primitive", "shape": "cube", "size": [16, 0.2, 6], "location": [0, 4.5, 3]},
        )
        add(
            "set_wall_side",
            "wall",
            {"op": "create_primitive", "shape": "cube", "size": [0.2, 12, 6], "location": [-7, 0, 3]},
        )
        add(
            "set_window",
            "window",
            {"op": "create_primitive", "shape": "cube", "size": [2.4, 0.05, 1.6], "location": [2, 4.38, 2.6]},
        )
        add(
            "set_shelf",
            "wood",
            {"op": "create_primitive", "shape": "cube", "size": [2.5, 0.5, 0.08], "location": [-3, 4.1, 1.8]},
        )
        for i in range(5):
            add(
                f"set_box_{i}",
                "wood",
                {
                    "op": "create_primitive",
                    "shape": "cube",
                    "size": [0.3, 0.3, 0.3 + 0.08 * i],
                    "location": [-4 + 0.5 * i, 4.1, 2.0 + 0.04 * i],
                },
            )
        mats = {
            "wall": mat("#D8CBB0", 0, 0.9),
            "window": mat("#FFE6B0", 0, 0.2, emission="#FFE6B0", strength=4),
            "wood": mat("#8B5A3C", 0, 0.7),
        }

    for key, ids in pieces.items():
        if key in mats:
            grime = (
                {}
                if mats[key].get("emission") or key in ("sea", "window")
                else {"noise": 0.6, "noise_scale": 2.2}
            )
            ops.append(
                {
                    "op": "set_material",
                    "targets": ids,
                    "material": {**mats[key], **grime, **haze, "name": f"set_{key}"},
                }
            )
    if plan.setting.time_of_day in ("sunset", "dawn") and kind not in ("room", "space"):
        ops += sun_disc_ops(plan)
    if plan.setting.time_of_day == "night" and kind != "room":
        ops += [
            {
                "op": "create_primitive",
                "id": "set_moon",
                "shape": "uv_sphere",
                "radius": 3.0,
                "location": [-30, 80, 26],
                "smooth": True,
                "tags": ["set", "sky"],
            },
            {
                "op": "set_material",
                "targets": ["set_moon"],
                "material": mat("#E8EEFF", 0, 0.5, emission="#E8EEFF", strength=6, name="set_moon"),
            },
        ]
    return ops


SUN_AZIMUTH = {"sunset": 210.0, "dawn": 150.0}


def sun_direction(tod: str, disc: bool = False) -> tuple[float, float, float]:
    """Unit vector *toward* the sun (for sunset/dawn the sun sits low behind the set).

    ``disc=True`` returns the direction for the visible sun disc, a little lower than the key light so
    it sits on the horizon line (a classic cheat)."""
    elev = math.radians((4 if disc else 12) if tod in ("sunset", "dawn") else 50 if tod == "day" else 35)
    az = math.radians(SUN_AZIMUTH.get(tod, 200.0))
    # light travels along d = (-sin az * sin a, cos az * sin a, -cos a) with a = 90 - elev; sun is at -d
    a = math.pi / 2 - elev
    d = (-math.sin(az) * math.sin(a), math.cos(az) * math.sin(a), -math.cos(a))
    return (-d[0], -d[1], -d[2])


def sun_disc_ops(plan: FilmPlan) -> list[dict[str, Any]]:
    sx, sy, sz = sun_direction(plan.setting.time_of_day, disc=True)
    dist = 90
    loc = [round(sx * dist, 2), round(sy * dist, 2), round(sz * dist, 2)]
    yaw = math.degrees(math.atan2(-sx, sy))
    return [
        {
            "op": "create_primitive",
            "id": "set_sun_disc",
            "shape": "circle",
            "radius": 5.5,
            "segments": 48,
            "location": loc,
            "rotation": [90, 0, round(yaw, 2)],
            "tags": ["set", "sky"],
        },
        {
            "op": "set_material",
            "targets": ["set_sun_disc"],
            "material": mat(
                plan.style.palette.sun, 0, 0.5, emission=plan.style.palette.sun, strength=2.2, name="set_sun"
            ),
        },
        # soft halo behind the disc (an emissive radial falloff — cheap "bloom" without compositing)
        {
            "op": "create_primitive",
            "id": "set_sun_glow",
            "shape": "circle",
            "radius": 22,
            "segments": 48,
            "location": [round(sx * (dist + 2), 2), round(sy * (dist + 2), 2), round(sz * (dist + 2), 2)],
            "rotation": [90, 0, round(yaw, 2)],
            "tags": ["set", "sky"],
        },
        {
            "op": "set_material",
            "targets": ["set_sun_glow"],
            "material": {
                **mat(
                    plan.style.palette.sun,
                    0,
                    0.5,
                    emission=plan.style.palette.sun,
                    strength=2.5,
                    name="set_sun_glow",
                ),
                "radial_glow": True,
            },
        },
    ]


@scripted("asset.params")
def _scripted_asset(payload: dict[str, Any]) -> dict[str, Any]:
    plan = payload["plan"]
    hero = plan["characters"][0]
    pal = plan["style"]["palette"]
    return {
        "character": {
            "color": hero["color"],
            "eye_color": hero.get("eye_color", pal["accent"]),
            "trim_color": pal["secondary"],
            "proportions": "chunky",
            "antenna": True,
        },
        "prop": {
            "color": plan["props"][0]["color"] if plan.get("props") else "#FF5C8A",
            "glow": 1.5 if plan["setting"]["time_of_day"] == "night" else 0.0,
        },
        "set": {
            "density": plan["setting"].get("density", 1.0),
            "seed": zlib.crc32(plan.get("prompt", "").encode()) % 10000,
            "landmarks": ["sun_disc"] if plan["setting"]["time_of_day"] in ("sunset", "dawn") else [],
        },
    }


class AssetAgent(Agent):
    role = "asset"
    task = "asset.params"
    system_prompt = SYSTEM

    def params(self, ctx: Context) -> dict[str, Any]:
        plan = ctx.plan
        p = self.ask(ctx, {"plan": plan.model_dump(mode="json")}, validate=_check_params)
        p.setdefault("character", {})
        ov = ctx.state.tuning.get("asset_overrides", {})
        for k, v in ov.items():
            p["character"][k] = v
        return p

    def run(self, ctx: Context) -> dict[str, Any]:
        plan = ctx.plan
        p = self.params(ctx)
        ch, pr, st = p["character"], p.get("prop", {}), p.get("set", {})
        density = float(st.get("density", 1.0))
        seed = int(st.get("seed", 7))
        self.submit(
            ctx,
            self.batch(
                f"Build the {plan.setting.kind} set ({plan.setting.time_of_day})",
                set_ops(plan, density, seed, list(st.get("landmarks", []))),
                verify={"preview": True, "camera": "auto", "resolution": [480, 270]},
            ),
        )
        hero = plan.hero
        recipe = CHARACTER_RECIPES[hero.kind]
        res = self.submit(
            ctx,
            self.batch(
                f"Build {hero.name} the {hero.kind} (rigged: root/body/head/eyes/mouth/arms)",
                recipe(
                    ch.get("color", hero.color),
                    ch.get("eye_color", hero.eye_color),
                    ch.get("trim_color", plan.style.palette.secondary),
                    antenna=bool(ch.get("antenna", True)),
                    scale=hero.scale,
                    species=hero.species,
                ),
            ),
        )
        prop_height = 0.0
        if plan.prop:
            ops, prop_height = prop_ops(
                plan.prop.kind,
                pr.get("color", plan.prop.color),
                plan.prop.location,
                float(pr.get("glow", 0.0)),
            )
            self.submit(ctx, self.batch(f"Build the {plan.prop.kind} prop", ops))
        ctx.state.artifacts["hero_parts"] = len(res.created)
        return {
            "prop_height": prop_height,
            "hero_height": HERO_HEIGHT[hero.kind] * hero.scale,
            "head_z": HERO_HEAD_Z[hero.kind] * hero.scale,
        }


def _check_params(d: dict[str, Any]) -> None:
    import re

    for sect in ("character", "prop"):
        for k, v in (d.get(sect) or {}).items():
            if k.endswith("color") and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(v)):
                raise ValueError(f"{sect}.{k} must be #RRGGBB")
