# SPDX-License-Identifier: GPL-3.0-or-later
"""Material op: compact Principled spec -> node tree (grime noise, aerial fade, radial glow)."""

from __future__ import annotations

import bpy

from .common import OpError, apply_viewport_tint, hex_to_rgb


class MaterialOps:
    """Mixin for :class:`Executor` (expects ``self.obj``, ``self.scene``, ``self._new_object``, ``self.workdir``)."""

    def _material(self, spec: dict, name: str):
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
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
        color_out = None
        if spec.get("noise"):
            tc = nodes.new("ShaderNodeTexCoord")
            noise = nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = spec.get("noise_scale", 2.0)
            noise.inputs["Detail"].default_value = 6.0
            ramp = nodes.new("ShaderNodeValToRGB")
            ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[1].position = 0.42, 0.62
            dark = [c * (1 - spec["noise"]) for c in rgb]
            ramp.color_ramp.elements[0].color = (*dark, 1)
            ramp.color_ramp.elements[1].color = (*rgb, 1)
            links.new(tc.outputs["Object"], noise.inputs["Vector"])
            links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
            color_out = ramp.outputs["Color"]
        if spec.get("pattern"):
            color_out = self._pattern(nodes, links, spec, rgb, color_out)
        if spec.get("grain") or spec.get("bump"):
            # fine grit: small-scale noise multiplies the colour (dark specks) and drives a bump map, so a
            # ground plane reads as a surface up close instead of a smooth gradient
            tc2 = nodes.new("ShaderNodeTexCoord")
            fine = nodes.new("ShaderNodeTexNoise")
            fine.inputs["Scale"].default_value = spec.get("grain_scale", 40.0)
            fine.inputs["Detail"].default_value = 8.0
            fine.inputs["Roughness"].default_value = 0.65
            links.new(tc2.outputs["Object"], fine.inputs["Vector"])
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
                bump = nodes.new("ShaderNodeBump")
                bump.inputs["Strength"].default_value = spec["bump"]
                bump.inputs["Distance"].default_value = 0.02
                links.new(fine.outputs["Fac"], bump.inputs["Height"])
                links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
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
    def _pattern(nodes, links, spec: dict, rgb, base_out):
        """Coat markings in object space (metres): a hard-edged ramp between ground and marking colour.

        stripes: distorted wave bands across ``pattern_axis`` (zebra). bands: the same, sparse and thin
        (meerkat back). patches: Voronoi cells, pale lines between them (giraffe). spots: Voronoi dots
        (tortoise shell, leopard).
        """
        kind = spec["pattern"]
        mark = (*hex_to_rgb(spec.get("pattern_color") or "#111111"), 1)
        ground = (*rgb, 1)
        width = spec.get("pattern_width", 0.5)
        tc = nodes.new("ShaderNodeTexCoord")
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
            links.new(tc.outputs["Object"], wave.inputs["Vector"])
            links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
            w = width if kind == "stripes" else min(width, 0.25)
            # Fac is a 0..1 sine: the bottom `w` share of it is the marking
            lo.position, hi.position = max(0.0, w - 0.04), min(1.0, w + 0.04)
            lo.color, hi.color = mark, ground
        else:
            vor = nodes.new("ShaderNodeTexVoronoi")
            vor.inputs["Scale"].default_value = spec.get("pattern_scale", 1.0)
            vor.inputs["Randomness"].default_value = 0.85
            links.new(tc.outputs["Object"], vor.inputs["Vector"])
            if kind == "patches":
                vor.feature = "DISTANCE_TO_EDGE"
                links.new(vor.outputs["Distance"], ramp.inputs["Fac"])
                line = 0.12 * (1 - width) + 0.02  # wider pale lines when markings are smaller
                lo.position, hi.position = line, line + 0.03
                lo.color, hi.color = ground, mark
            else:  # spots
                vor.feature = "F1"
                links.new(vor.outputs["Distance"], ramp.inputs["Fac"])
                r = 0.25 + 0.35 * width
                lo.position, hi.position = r, r + 0.05
                lo.color, hi.color = mark, ground
        if base_out is None:
            return ramp.outputs["Color"]
        # keep any grime variation: multiply the marking layer over the noisy base
        mul = nodes.new("ShaderNodeMix")
        mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        links.new(base_out, mul.inputs["A"])
        div = nodes.new("ShaderNodeMix")  # ramp / ground: 1 on ground, marking/ground on marks
        div.data_type, div.blend_type = "RGBA", "DIVIDE"
        div.inputs["Factor"].default_value = 1.0
        links.new(ramp.outputs["Color"], div.inputs["A"])
        div.inputs["B"].default_value = (max(rgb[0], 1e-3), max(rgb[1], 1e-3), max(rgb[2], 1e-3), 1)
        links.new(div.outputs["Result"], mul.inputs["B"])
        return mul.outputs["Result"]

    def op_set_material(self, op: dict, res: dict) -> None:
        spec = op["material"]
        name = spec.get("name") or f"mat_{op['targets'][0]}"
        mat = self._material(spec, name)
        for t in op["targets"]:
            o = self.obj(t)
            if not hasattr(o.data, "materials"):
                raise OpError(f"{t!r} cannot have materials")
            o.data.materials.clear()
            o.data.materials.append(mat)
            res["modified"].append(t)
