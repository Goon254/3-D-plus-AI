# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers for the Blender adapter (colour conversion, render setup, scene measurement)."""

from __future__ import annotations

import math
from typing import Any

import bpy
import mathutils

ID_PROP = "animatica_id"
TAGS_PROP = "animatica_tags"


class OpError(Exception):
    pass


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    srgb = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    # sRGB -> linear (Blender colour properties are scene-linear)
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)  # type: ignore[return-value]


def rad(v):
    return tuple(math.radians(x) for x in v)


def workbench_setup(s) -> None:
    """Readable Workbench look: flat material colours + soft shadows + cavity (studio light reads too dark)."""
    sh = s.display.shading
    sh.light, sh.color_type = "FLAT", "MATERIAL"
    sh.show_shadows, sh.shadow_intensity = True, 0.4
    sh.show_cavity = True


def apply_viewport_tint(s, mats=None) -> None:
    """Grade the Workbench/viewport colours (``Material.diffuse_color``) by the scene's viewport tint.

    Only the viewport colour changes, so Cycles/EEVEE renders are untouched. Emissive materials show their
    emission colour instead (a lantern glows in the flat preview). Idempotent: the ungraded colour is kept.
    """
    tint = s.get("animatica_viewport_tint")
    for m in mats if mats is not None else bpy.data.materials:
        if "animatica_wb_base" not in m:
            m["animatica_wb_base"] = list(m.diffuse_color)
        base = list(m["animatica_wb_base"])
        if m.get("animatica_emissive"):
            m.diffuse_color = (*m["animatica_emissive"], base[3]) if tint else tuple(base)
        elif tint:
            m.diffuse_color = (base[0] * tint[0], base[1] * tint[1], base[2] * tint[2], base[3])
        else:
            m.diffuse_color = tuple(base)


def glow_visibility(s, visible: bool) -> None:
    """Workbench can't render transparent halos: hide radial-glow objects there, show them otherwise."""
    for o in s.objects:
        m = getattr(o, "active_material", None)
        if m is not None and m.get("animatica_radial_glow"):
            o.hide_render = not visible


def fast_cycles(s) -> None:
    """Production-friendly Cycles defaults for stylized scenes on CPU."""
    c = s.cycles
    c.max_bounces, c.diffuse_bounces, c.glossy_bounces = 4, 2, 2
    c.transmission_bounces, c.transparent_max_bounces, c.volume_bounces = 2, 4, 0
    c.caustics_reflective = c.caustics_refractive = False
    c.use_adaptive_sampling, c.adaptive_threshold = True, 0.04
    c.light_sampling_threshold = 0.05
    s.render.use_persistent_data = True
    try:
        c.denoising_prefilter = "FAST"
    except Exception:  # noqa: BLE001
        pass


def _iter_fcurves(action):
    if hasattr(action, "fcurves") and not hasattr(action, "layers"):
        yield from action.fcurves
        return
    # layered actions (Blender 4.4+)
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                yield from bag.fcurves
    if hasattr(action, "fcurves"):
        try:
            yield from action.fcurves
        except Exception:  # noqa: BLE001
            return


def _is_array(block, path: str) -> bool:
    try:
        val = block.path_resolve(path)
    except ValueError:
        return False
    return hasattr(val, "__len__") and not isinstance(val, str)


def _eevee_id() -> str:
    items = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys()
    return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in items else "BLENDER_EEVEE"


def hierarchy_bbox_points(o) -> list:
    pts = []
    stack = [o]
    while stack:
        cur = stack.pop()
        if cur.type == "MESH" and not cur.hide_render:
            mw = cur.matrix_world
            verts = cur.data.vertices
            if len(verts) <= 4000:  # exact extents (a rotated bbox overestimates round shapes)
                step = max(1, len(verts) // 400)
                pts.extend(mw @ verts[i].co for i in range(0, len(verts), step))
            else:
                pts.extend(mw @ mathutils.Vector(c) for c in cur.bound_box)
        stack.extend(cur.children)
    return pts


def describe(o, fields: list[str], tags: list[str]) -> dict:
    d: dict[str, Any] = {}
    if "type" in fields:
        d["type"] = o.type.lower()
    if "transform" in fields:
        d["location"] = [round(v, 4) for v in o.location]
        d["rotation"] = [round(math.degrees(v), 3) for v in o.rotation_euler]
        d["scale"] = [round(v, 4) for v in o.scale]
    if "parent" in fields:
        d["parent"] = o.parent.get(ID_PROP, o.parent.name) if o.parent else None
    if "bbox" in fields and o.type == "MESH":
        pts = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
        d["bbox"] = [
            [round(min(p[i] for p in pts), 3) for i in range(3)],
            [round(max(p[i] for p in pts), 3) for i in range(3)],
        ]
    if "material" in fields and getattr(o, "active_material", None):
        m = o.active_material
        c = m.diffuse_color[:3]
        bsdf = m.node_tree.nodes.get("Principled BSDF") if m.use_nodes and m.node_tree else None
        if bsdf is not None and not bsdf.inputs["Base Color"].is_linked:
            c = bsdf.inputs["Base Color"].default_value[:3]  # what an artist edits in the UI
        d["material"] = {"name": m.name, "base_color": rgb_to_hex(c)}
    if "shape_keys" in fields and o.type == "MESH" and o.data.shape_keys:
        d["shape_keys"] = [kb.name for kb in o.data.shape_keys.key_blocks]
    if "animation" in fields:
        ad = o.animation_data
        d["animated"] = bool(ad and ad.action)
    if "tags" in fields:
        d["tags"] = tags
    return d


def rgb_to_hex(lin) -> str:
    out = []
    for c in lin:
        c = max(0.0, min(1.0, c))
        s = c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        out.append(round(s * 255))
    return "#{:02X}{:02X}{:02X}".format(*out)


def image_stats(path: str) -> dict:
    """Mean luminance and clipping fractions of a rendered image (cheap Critic signal)."""
    img = bpy.data.images.load(path, check_existing=False)
    try:
        px = list(img.pixels)
        n = len(px) // 4
        step = max(1, n // 4000)
        lum = []
        for i in range(0, n, step):
            r, g, b = px[4 * i], px[4 * i + 1], px[4 * i + 2]
            lum.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
        mean = sum(lum) / len(lum)
        return {
            "mean": round(mean, 3),
            "black": round(sum(v < 0.02 for v in lum) / len(lum), 3),
            "white": round(sum(v > 0.98 for v in lum) / len(lum), 3),
        }
    finally:
        bpy.data.images.remove(img)
