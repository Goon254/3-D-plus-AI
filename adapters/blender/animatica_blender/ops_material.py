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
