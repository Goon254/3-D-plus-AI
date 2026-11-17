# SPDX-License-Identifier: GPL-3.0-or-later
"""Material op: compact Principled spec -> node tree (grime noise, aerial fade, radial glow)."""

from __future__ import annotations

import bpy

from .common import OpError, apply_viewport_tint, hex_to_rgb


class MaterialOps:
    """Mixin for :class:`Executor` (expects ``self.obj``, ``self.scene``, ``self._new_object``, ``self.workdir``)."""

    def _material(self, spec: dict, name: str, rest: bool = False):
        """``rest``: the material goes on a mesh that deforms (armature): its procedural textures sample the
        mesh's rest pose (``rest_position``), so stripes, patches and scales stay pinned to the skin instead of
        sliding through it as the rig bends (Object coordinates are the deformed positions)."""
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        rest = rest or self._is_rest(mat)  # shared by name with a deforming mesh: stay pinned
        mat.use_nodes = True
        # rebuild the node tree from the spec every time (idempotent re-application, no node pile-up)
        mat.node_tree.nodes.clear()
        bsdf = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.name = "Principled BSDF"
        out_node = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        mat.node_tree.links.new(bsdf.outputs[0], out_node.inputs["Surface"])
        rgb = hex_to_rgb(spec.get("base_color", "#CCCCCC"))
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        bsdf.inputs["Metallic"].default_value = spec.get("metallic", 0.0)
        bsdf.inputs["Roughness"].default_value = spec.get("roughness", 0.5)
        if spec.get("specular") is not None:
            bsdf.inputs["Specular IOR Level"].default_value = spec["specular"]
        if spec.get("sheen") and "Sheen Weight" in bsdf.inputs:
            bsdf.inputs["Sheen Weight"].default_value = spec["sheen"]
            bsdf.inputs["Sheen Roughness"].default_value = 0.35
            tint = hex_to_rgb(spec.get("sheen_tint") or "#FFFFFF")
            bsdf.inputs["Sheen Tint"].default_value = (*tint, 1.0)
        if spec.get("emission"):
            bsdf.inputs["Emission Color"].default_value = (*hex_to_rgb(spec["emission"]), 1.0)
            bsdf.inputs["Emission Strength"].default_value = spec.get("emission_strength", 1.0)
        alpha = spec.get("alpha", 1.0)
        bsdf.inputs["Alpha"].default_value = alpha
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        co = self._coords(nodes, rest)  # object-space texture coordinates (rest pose on deforming meshes)
        color_out = None
        if spec.get("noise"):
            noise = nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = spec.get("noise_scale", 2.0)
            noise.inputs["Detail"].default_value = 6.0
            ramp = nodes.new("ShaderNodeValToRGB")
            ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[1].position = 0.42, 0.62
            dark = [c * (1 - spec["noise"]) for c in rgb]
            ramp.color_ramp.elements[0].color = (*dark, 1)
            ramp.color_ramp.elements[1].color = (*rgb, 1)
            links.new(co, noise.inputs["Vector"])
            links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
            color_out = ramp.outputs["Color"]
        normal_out = None
        if spec.get("tip_color"):
            # vertical gradient in object space: darker at the root, sun-bleached at the tip (grass blades)
            sxyz = nodes.new("ShaderNodeSeparateXYZ")
            links.new(co, sxyz.inputs[0])
            mr = nodes.new("ShaderNodeMapRange")
            mr.inputs["From Max"].default_value = spec.get("tip_height", 0.5)
            links.new(sxyz.outputs["Z"], mr.inputs["Value"])
            g = nodes.new("ShaderNodeMix")
            g.data_type = "RGBA"
            links.new(mr.outputs["Result"], g.inputs["Factor"])
            if color_out is not None:
                links.new(color_out, g.inputs["A"])
            else:
                g.inputs["A"].default_value = (*rgb, 1)
            g.inputs["B"].default_value = (*hex_to_rgb(spec["tip_color"]), 1)
            color_out = g.outputs["Result"]
        if spec.get("transmission") and "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = spec["transmission"]
            bsdf.inputs["IOR"].default_value = spec.get("ior", 1.33)
        if spec.get("pattern"):
            color_out, pat_height = self._pattern(nodes, links, spec, rgb, color_out, co)
            if pat_height is not None:  # scute seams / scale crevices are carved, not just painted
                normal_out = self._bump(nodes, links, pat_height, 0.6, 0.004, normal_out)
        for mk in spec.get("marks") or []:
            # a soft ellipsoid painted on the skin: |(co - at) / radii| < 1, fading over the outer `soft`
            sub = nodes.new("ShaderNodeVectorMath")
            sub.operation = "SUBTRACT"
            links.new(co, sub.inputs[0])
            sub.inputs[1].default_value = mk["at"]
            div = nodes.new("ShaderNodeVectorMath")
            div.operation = "DIVIDE"
            links.new(sub.outputs["Vector"], div.inputs[0])
            div.inputs[1].default_value = [max(1e-5, r) for r in mk["radii"]]
            ln = nodes.new("ShaderNodeVectorMath")
            ln.operation = "LENGTH"
            links.new(div.outputs["Vector"], ln.inputs[0])
            mr = nodes.new("ShaderNodeMapRange")
            mr.interpolation_type = "SMOOTHSTEP"
            mr.inputs["From Min"].default_value = 1.0
            mr.inputs["From Max"].default_value = 1.0 - mk.get("soft", 0.5)
            mr.inputs["To Max"].default_value = mk.get("strength", 1.0)
            links.new(ln.outputs["Value"], mr.inputs["Value"])
            mx = nodes.new("ShaderNodeMix")
            mx.data_type = "RGBA"
            links.new(mr.outputs["Result"], mx.inputs["Factor"])
            if color_out is not None:
                links.new(color_out, mx.inputs["A"])
            else:
                mx.inputs["A"].default_value = (*rgb, 1)
            mx.inputs["B"].default_value = (*hex_to_rgb(mk["color"]), 1)
            color_out = mx.outputs["Result"]
        if spec.get("wrinkles"):
            # creased skin: distorted wave bands (horizontal folds) plus a finer crackle
            wave = nodes.new("ShaderNodeTexWave")
            wave.wave_type, wave.bands_direction = "BANDS", "Z"
            wave.inputs["Scale"].default_value = spec.get("wrinkle_scale", 12.0)
            wave.inputs["Distortion"].default_value = 6.0
            wave.inputs["Detail"].default_value = 4.0
            links.new(co, wave.inputs["Vector"])
            normal_out = self._bump(
                nodes, links, wave.outputs["Fac"], spec["wrinkles"] * 0.5, 0.006, normal_out
            )
            crack = nodes.new("ShaderNodeTexVoronoi")
            crack.feature = "DISTANCE_TO_EDGE"
            crack.inputs["Scale"].default_value = spec.get("wrinkle_scale", 12.0) * 4
            links.new(co, crack.inputs["Vector"])
            normal_out = self._bump(
                nodes, links, crack.outputs["Distance"], spec["wrinkles"] * 0.35, 0.003, normal_out
            )
        if spec.get("fur"):
            # short coat: streaky fine noise (stretched along Z) drives a soft bump; sheen catches the rim
            mp = nodes.new("ShaderNodeMapping")
            sc = spec.get("fur_scale", 220.0)
            mp.inputs["Scale"].default_value = (sc, sc, sc * 0.18)
            nz = nodes.new("ShaderNodeTexNoise")
            nz.inputs["Scale"].default_value = 1.0
            nz.inputs["Detail"].default_value = 3.0
            links.new(co, mp.inputs["Vector"])
            links.new(mp.outputs["Vector"], nz.inputs["Vector"])
            normal_out = self._bump(nodes, links, nz.outputs["Fac"], spec["fur"] * 0.35, 0.002, normal_out)
            if "Sheen Weight" in bsdf.inputs:
                bsdf.inputs["Sheen Weight"].default_value = max(spec.get("sheen", 0.0), 0.6 * spec["fur"])
                bsdf.inputs["Sheen Roughness"].default_value = 0.4
        if spec.get("subsurface") and "Subsurface Weight" in bsdf.inputs:
            bsdf.inputs["Subsurface Weight"].default_value = spec["subsurface"]
            bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.45, 0.3)
            bsdf.inputs["Subsurface Scale"].default_value = spec.get("subsurface_radius", 0.02)
        if spec.get("grain") or spec.get("bump"):
            # fine grit: small-scale noise multiplies the colour (dark specks) and drives a bump map, so a
            # ground plane reads as a surface up close instead of a smooth gradient
            fine = nodes.new("ShaderNodeTexNoise")
            fine.inputs["Scale"].default_value = spec.get("grain_scale", 40.0)
            fine.inputs["Detail"].default_value = 8.0
            fine.inputs["Roughness"].default_value = 0.65
            links.new(co, fine.inputs["Vector"])
            if spec.get("grain"):
                gr = nodes.new("ShaderNodeValToRGB")
                gr.color_ramp.elements[0].position, gr.color_ramp.elements[1].position = 0.35, 0.6
                g = 1 - spec["grain"]
                gr.color_ramp.elements[0].color = (g, g, g, 1)
                gr.color_ramp.elements[1].color = (1, 1, 1, 1)
                links.new(fine.outputs["Fac"], gr.inputs["Fac"])
                mul = nodes.new("ShaderNodeMix")
                mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
                mul.inputs["Factor"].default_value = 1.0
                if color_out is not None:
                    links.new(color_out, mul.inputs["A"])
                else:
                    mul.inputs["A"].default_value = (*rgb, 1)
                links.new(gr.outputs["Color"], mul.inputs["B"])
                color_out = mul.outputs["Result"]
            if spec.get("bump"):
                normal_out = self._bump(nodes, links, fine.outputs["Fac"], spec["bump"], 0.02, normal_out)
        if spec.get("fade_to"):
            geo = nodes.new("ShaderNodeNewGeometry")
            length = nodes.new("ShaderNodeVectorMath")
            length.operation = "LENGTH"
            mr = nodes.new("ShaderNodeMapRange")
            mr.inputs["From Min"].default_value = spec.get("fade_start", 15.0)
            mr.inputs["From Max"].default_value = spec.get("fade_end", 90.0)
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            links.new(geo.outputs["Position"], length.inputs[0])
            links.new(length.outputs["Value"], mr.inputs["Value"])
            links.new(mr.outputs["Result"], mix.inputs["Factor"])
            if color_out is not None:
                links.new(color_out, mix.inputs["A"])
            else:
                mix.inputs["A"].default_value = (*rgb, 1)
            mix.inputs["B"].default_value = (*hex_to_rgb(spec["fade_to"]), 1)
            color_out = mix.outputs["Result"]
            # distant surfaces also stop reflecting light differently from the sky: add matching emission
            em = nodes.new("ShaderNodeMix")
            em.data_type = "RGBA"
            links.new(mr.outputs["Result"], em.inputs["Factor"])
            em.inputs["A"].default_value = (0, 0, 0, 1)
            em.inputs["B"].default_value = (*hex_to_rgb(spec["fade_to"]), 1)
            links.new(em.outputs["Result"], bsdf.inputs["Emission Color"])
            links.new(mr.outputs["Result"], bsdf.inputs["Emission Strength"])
        if color_out is not None:
            links.new(color_out, bsdf.inputs["Base Color"])
        if normal_out is not None:
            links.new(normal_out, bsdf.inputs["Normal"])
        if spec.get("radial_glow") and spec.get("emission"):
            out = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
            tc = nodes.new("ShaderNodeTexCoord")
            mp = nodes.new("ShaderNodeMapping")
            mp.inputs["Location"].default_value = (-1.0, -1.0, -0.5)  # flat mesh: generated z is 0.5
            mp.inputs["Scale"].default_value = (2.0, 2.0, 1.0)
            grad = nodes.new("ShaderNodeTexGradient")
            grad.gradient_type = "SPHERICAL"
            pw = nodes.new("ShaderNodeMath")
            pw.operation = "POWER"
            pw.inputs[1].default_value = 2.2
            emit = nodes.new("ShaderNodeEmission")
            emit.inputs["Color"].default_value = (*hex_to_rgb(spec["emission"]), 1)
            emit.inputs["Strength"].default_value = spec.get("emission_strength", 1.0)
            transp = nodes.new("ShaderNodeBsdfTransparent")
            mixs = nodes.new("ShaderNodeMixShader")
            links.new(tc.outputs["Generated"], mp.inputs["Vector"])
            links.new(mp.outputs["Vector"], grad.inputs["Vector"])
            links.new(grad.outputs["Fac"], pw.inputs[0])
            links.new(pw.outputs[0], mixs.inputs["Fac"])
            links.new(transp.outputs[0], mixs.inputs[1])
            links.new(emit.outputs[0], mixs.inputs[2])
            links.new(mixs.outputs[0], out.inputs["Surface"])
            mat["animatica_radial_glow"] = True
            try:
                mat.surface_render_method = "BLENDED"
            except Exception:  # noqa: BLE001
                pass
        mat.diffuse_color = (*rgb, alpha)  # workbench / viewport colour
        if "animatica_wb_base" in mat:
            del mat["animatica_wb_base"]
        if spec.get("emission") and spec.get("emission_strength", 1.0) >= 1.0:
            mat["animatica_emissive"] = list(hex_to_rgb(spec["emission"]))
        elif "animatica_emissive" in mat:
            del mat["animatica_emissive"]
        apply_viewport_tint(self.scene, [mat])
        mat.metallic = spec.get("metallic", 0.0)
        mat.roughness = spec.get("roughness", 0.5)
        mat["animatica_spec"] = str(spec)
        return mat

    @staticmethod
    def _coords(nodes, rest: bool):
        if rest:
            at = nodes.new("ShaderNodeAttribute")
            at.attribute_type, at.attribute_name = "GEOMETRY", "rest_position"
            at.name = "animatica_rest_coords"
            return at.outputs["Vector"]
        return nodes.new("ShaderNodeTexCoord").outputs["Object"]

    @staticmethod
    def _is_rest(mat) -> bool:
        return bool(
            mat and mat.use_nodes and mat.node_tree and "animatica_rest_coords" in mat.node_tree.nodes
        )

    @staticmethod
    def _deforms(o) -> bool:
        """True for a mesh skinned to an armature (modifier), which is where textures would swim; turns on
        its ``rest_position`` attribute so the shader can read the rest pose."""
        if o.type != "MESH" or not any(m.type == "ARMATURE" for m in o.modifiers):
            return False
        o.add_rest_position_attribute = True
        return True

    @staticmethod
    def _bump(nodes, links, height_socket, strength: float, distance: float, normal_in=None):
        """Chain a bump node (details stack: grain, wrinkles, fur, scute seams)."""
        b = nodes.new("ShaderNodeBump")
        b.inputs["Strength"].default_value = strength
        b.inputs["Distance"].default_value = distance
        links.new(height_socket, b.inputs["Height"])
        if normal_in is not None:
            links.new(normal_in, b.inputs["Normal"])
        return b.outputs["Normal"]

    @staticmethod
    def _pattern(nodes, links, spec: dict, rgb, base_out, co):
        """Coat markings in object space (metres): a hard-edged ramp between ground and marking colour.

        stripes: distorted wave bands across ``pattern_axis`` (zebra). bands: the same, sparse and thin
        (meerkat back). patches: Voronoi cells, pale lines between them (giraffe). spots: Voronoi dots
        (tortoise shell, leopard).
        """
        kind = spec["pattern"]
        height = None
        pat = None  # the marking layer, when it is not simply the ramp
        mark = (*hex_to_rgb(spec.get("pattern_color") or "#111111"), 1)
        ground = (*rgb, 1)
        width = spec.get("pattern_width", 0.5)
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.interpolation = "EASE"
        lo, hi = ramp.color_ramp.elements[0], ramp.color_ramp.elements[1]
        if kind in ("stripes", "bands"):
            wave = nodes.new("ShaderNodeTexWave")
            wave.wave_type = "BANDS"
            wave.bands_direction = spec.get("pattern_axis", "z").upper()
            wave.inputs["Scale"].default_value = spec.get("pattern_scale", 1.0)
            wave.inputs["Distortion"].default_value = spec.get("pattern_distort", 2.0)
            wave.inputs["Detail"].default_value = 1.5
            links.new(co, wave.inputs["Vector"])
            links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
            w = width if kind == "stripes" else min(width, 0.25)
            # Fac is a 0..1 sine: the bottom `w` share of it is the marking
            lo.position, hi.position = max(0.0, w - 0.04), min(1.0, w + 0.04)
            lo.color, hi.color = mark, ground
            if spec.get("pattern_above") is not None:  # markings on the back only, fading in with height
                sep = nodes.new("ShaderNodeSeparateXYZ")
                links.new(co, sep.inputs[0])
                band = nodes.new("ShaderNodeMapRange")
                f = spec.get("pattern_fade", 0.02)
                band.inputs["From Min"].default_value = spec["pattern_above"] - f
                band.inputs["From Max"].default_value = spec["pattern_above"] + f
                links.new(sep.outputs["Z"], band.inputs["Value"])
                gate = nodes.new("ShaderNodeMix")
                gate.data_type = "RGBA"
                links.new(band.outputs["Result"], gate.inputs["Factor"])
                gate.inputs["A"].default_value = ground
                links.new(ramp.outputs["Color"], gate.inputs["B"])
                pat = gate.outputs["Result"]
        else:
            vor = nodes.new("ShaderNodeTexVoronoi")
            vor.inputs["Scale"].default_value = spec.get("pattern_scale", 1.0)
            vor.inputs["Randomness"].default_value = 0.85
            links.new(co, vor.inputs["Vector"])
            if kind == "patches":
                vor.feature = "DISTANCE_TO_EDGE"
                links.new(vor.outputs["Distance"], ramp.inputs["Fac"])
                line = 0.12 * (1 - width) + 0.02  # wider pale lines when markings are smaller
                lo.position, hi.position = line, line + 0.03
                lo.color, hi.color = ground, mark
            elif kind == "spots":
                vor.feature = "F1"
                links.new(vor.outputs["Distance"], ramp.inputs["Fac"])
                r = 0.25 + 0.35 * width
                lo.position, hi.position = r, r + 0.05
                lo.color, hi.color = mark, ground
            elif kind == "scales":  # reptile skin: small plates with dark crevices (carved by the bump too)
                vor.feature = "DISTANCE_TO_EDGE"
                vor.inputs["Randomness"].default_value = 0.6
                links.new(vor.outputs["Distance"], ramp.inputs["Fac"])
                lo.position, hi.position = 0.02, 0.12
                lo.color, hi.color = mark, ground
                height = vor.outputs["Distance"]
            else:  # scutes: near-hexagonal shell plates, dark seams, growth rings, a dark heart per plate
                vor.feature = "DISTANCE_TO_EDGE"
                vor.inputs["Randomness"].default_value = 0.5
                f1 = nodes.new("ShaderNodeTexVoronoi")
                f1.feature = "F1"
                f1.inputs["Scale"].default_value = spec.get("pattern_scale", 1.0)
                f1.inputs["Randomness"].default_value = 0.5
                links.new(co, f1.inputs["Vector"])
                rings = nodes.new("ShaderNodeMath")  # growth rings parallel to the seams
                rings.operation = "PINGPONG"
                rings.inputs[1].default_value = 0.07
                links.new(vor.outputs["Distance"], rings.inputs[0])
                ring_ramp = nodes.new("ShaderNodeValToRGB")
                ring_ramp.color_ramp.elements[0].position = 0.0
                ring_ramp.color_ramp.elements[1].position = 0.05
                dark = (0.8 * ground[0], 0.8 * ground[1], 0.8 * ground[2], 1)
                ring_ramp.color_ramp.elements[0].color, ring_ramp.color_ramp.elements[1].color = dark, ground
                links.new(rings.outputs[0], ring_ramp.inputs["Fac"])
                heart = nodes.new("ShaderNodeValToRGB")  # the leopard tortoise's dark blotch per plate
                r = 0.18 + 0.3 * width
                heart.color_ramp.elements[0].position, heart.color_ramp.elements[1].position = r, r + 0.06
                heart.color_ramp.elements[0].color, heart.color_ramp.elements[1].color = mark, (1, 1, 1, 1)
                # blotchy, not a bullseye: noise breaks up the heart's outline
                hn = nodes.new("ShaderNodeTexNoise")
                hn.inputs["Scale"].default_value = spec.get("pattern_scale", 1.0) * 5
                links.new(co, hn.inputs["Vector"])
                wob = nodes.new("ShaderNodeMath")
                wob.operation = "MULTIPLY_ADD"
                wob.inputs[1].default_value = 0.22
                links.new(hn.outputs["Fac"], wob.inputs[0])
                links.new(f1.outputs["Distance"], wob.inputs[2])
                links.new(wob.outputs[0], heart.inputs["Fac"])
                m1 = nodes.new("ShaderNodeMix")
                m1.data_type, m1.blend_type = "RGBA", "MULTIPLY"
                m1.inputs["Factor"].default_value = 1.0
                links.new(ring_ramp.outputs["Color"], m1.inputs["A"])
                links.new(heart.outputs["Color"], m1.inputs["B"])
                links.new(vor.outputs["Distance"], ramp.inputs["Fac"])
                lo.position, hi.position = 0.015, 0.04  # dark seam between plates
                lo.color, hi.color = mark, (1, 1, 1, 1)
                m2 = nodes.new("ShaderNodeMix")
                m2.data_type, m2.blend_type = "RGBA", "MULTIPLY"
                m2.inputs["Factor"].default_value = 1.0
                links.new(m1.outputs["Result"], m2.inputs["A"])
                links.new(ramp.outputs["Color"], m2.inputs["B"])
                return m2.outputs["Result"], vor.outputs["Distance"]
        pat = pat if pat is not None else ramp.outputs["Color"]
        if base_out is None:
            return pat, height
        # keep any grime variation: multiply the marking layer over the noisy base
        mul = nodes.new("ShaderNodeMix")
        mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        links.new(base_out, mul.inputs["A"])
        div = nodes.new("ShaderNodeMix")  # ramp / ground: 1 on ground, marking/ground on marks
        div.data_type, div.blend_type = "RGBA", "DIVIDE"
        div.inputs["Factor"].default_value = 1.0
        links.new(pat, div.inputs["A"])
        div.inputs["B"].default_value = (max(rgb[0], 1e-3), max(rgb[1], 1e-3), max(rgb[2], 1e-3), 1)
        links.new(div.outputs["Result"], mul.inputs["B"])
        return mul.outputs["Result"], height

    def op_set_material_by_bone(self, op: dict, res: dict) -> None:
        o = self.obj(op["target"])
        if o.type != "MESH":
            raise OpError(f"{op['target']!r} is not a mesh")
        base = o.get("animatica_id", o.name)
        specs = [op["default"]] + [r["material"] for r in op.get("rules", [])]
        rest = self._deforms(o)
        mats = [
            self._material(sp, sp.get("name") or f"{base}_region{i}", rest=rest) for i, sp in enumerate(specs)
        ]
        if any(self._is_rest(m) for m in mats) and o.type == "MESH":
            o.add_rest_position_attribute = True
        o.data.materials.clear()
        for m in mats:
            o.data.materials.append(m)
        names = {vg.index: vg.name for vg in o.vertex_groups}

        def region(group: str) -> int:
            for i, r in enumerate(op.get("rules", [])):
                if any(group.startswith(p) for p in r["bones"]):
                    return i + 1
            return 0

        verts = o.data.vertices
        for poly in o.data.polygons:
            score: dict[int, float] = {}
            for vi in poly.vertices:
                for g in verts[vi].groups:
                    reg = region(names.get(g.group, ""))
                    score[reg] = score.get(reg, 0.0) + g.weight
            poly.material_index = max(score, key=score.get) if score else 0
        res["modified"].append(op["target"])

    def op_set_material(self, op: dict, res: dict) -> None:
        spec = op["material"]
        name = spec.get("name") or f"mat_{op['targets'][0]}"
        rest = any([self._deforms(self.obj(t)) for t in op["targets"]])  # list: mark every deforming target
        mat = self._material(spec, name, rest=rest)
        for t in op["targets"]:
            o = self.obj(t)
            if self._is_rest(mat) and o.type == "MESH":
                o.add_rest_position_attribute = True  # a rigid part reads its own rest = Object coordinates
            if not hasattr(o.data, "materials"):
                raise OpError(f"{t!r} cannot have materials")
            o.data.materials.clear()
            o.data.materials.append(mat)
            res["modified"].append(t)
