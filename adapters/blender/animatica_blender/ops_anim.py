# SPDX-License-Identifier: GPL-3.0-or-later
"""Animation ops: batched keyframes (5.x layered actions), shape keys, frame range, sound strips."""

from __future__ import annotations

import math
import os

import bpy

from .common import OpError, _is_array, _iter_fcurves


class AnimOps:
    """Mixin for :class:`Executor` (expects ``self.obj``, ``self.scene``, ``self._new_object``, ``self.workdir``)."""

    def _fcurve_target(self, o, prop: str):
        """Return (id_block, data_path, is_vector, transform)."""
        if prop == "location":
            return o, "location", True, None
        if prop == "rotation":
            return o, "rotation_euler", True, math.radians
        if prop == "scale":
            return o, "scale", True, None
        if prop == "hide":
            return o, "hide_render", False, bool
        if prop.startswith("shape_key:"):
            key = prop.split(":", 1)[1]
            if (
                not o.data
                or not getattr(o.data, "shape_keys", None)
                or key not in o.data.shape_keys.key_blocks
            ):
                raise OpError(f"{o.name!r} has no shape key {key!r}")
            return o.data.shape_keys, f'key_blocks["{key}"].value', False, None
        if prop == "light.energy":
            return o.data, "energy", False, None
        if prop == "light.color":
            return o.data, "color", True, None
        if prop == "camera.lens":
            return o.data, "lens", False, None
        if prop == "material.emission_strength":
            mat = o.active_material
            if mat is None:
                raise OpError(f"{o.name!r} has no material")
            return (
                mat.node_tree,
                'nodes["Principled BSDF"].inputs["Emission Strength"].default_value',
                False,
                None,
            )
        raise OpError(f"unsupported property {prop!r}")

    EASING = {
        "EASE_IN": ("BEZIER", "EASE_IN"),
        "EASE_OUT": ("BEZIER", "EASE_OUT"),
        "EASE_IN_OUT": ("BEZIER", "EASE_IN_OUT"),
        "BACK": ("BACK", "EASE_OUT"),
        "ELASTIC": ("ELASTIC", "EASE_OUT"),
        "BOUNCE": ("BOUNCE", "EASE_OUT"),
    }

    def op_insert_keyframes(self, op: dict, res: dict) -> None:
        o = self.obj(op["target"])
        block, path, is_vec, conv = self._fcurve_target(o, op["property"])
        if block.animation_data is None:
            block.animation_data_create()
        action = block.animation_data.action
        if action is None:
            action = bpy.data.actions.new(f"{o.name}_{op['property'].replace(':', '_')}_action")
            block.animation_data.action = action
        index = op.get("index")
        if is_vec:
            n = 3
            channels = [index] if index is not None else list(range(n))
        else:
            channels = [None]
        for ch in channels:
            fc = self._ensure_fcurve(block, action, path, ch if ch is not None else 0)
            pts = op["keys"]
            start = len(fc.keyframe_points)
            fc.keyframe_points.add(len(pts))
            for j, (frame, value, interp) in enumerate(pts):
                if isinstance(value, (list, tuple)):
                    v = value[ch]
                else:
                    v = value
                if conv is not None:
                    v = conv(v)
                    v = float(v)
                kp = fc.keyframe_points[start + j]
                kp.co = (frame, v)
                ipo, ease = self.EASING.get(interp, (interp, "AUTO"))
                kp.interpolation = ipo
                kp.easing = ease
                kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
            fc.keyframe_points.sort()
            fc.update()
        res["modified"].append(op["target"])

    @staticmethod
    def _ensure_fcurve(block, action, path: str, index: int):
        # Blender 4.4+ uses layered actions; keyframe_insert creates the slot/channelbag for us.
        try:
            fc = None
            for f in _iter_fcurves(action):
                if f.data_path == path and f.array_index == index:
                    fc = f
                    break
            if fc is not None:
                return fc
        except Exception:  # noqa: BLE001
            pass
        block.keyframe_insert(data_path=path, index=index if _is_array(block, path) else -1, frame=-100000)
        for f in _iter_fcurves(block.animation_data.action):
            if f.data_path == path and (f.array_index == index or not _is_array(block, path)):
                # remove the sentinel key we just added
                for kp in list(f.keyframe_points):
                    if kp.co[0] == -100000:
                        f.keyframe_points.remove(kp)
                return f
        raise OpError(f"could not create fcurve for {path}")

    def op_clear_animation(self, op: dict, res: dict) -> None:
        for t in op["targets"]:
            o = self.obj(t)
            o.animation_data_clear()
            if op.get("shape_keys", True) and o.type == "MESH" and o.data.shape_keys:
                o.data.shape_keys.animation_data_clear()
                for kb in o.data.shape_keys.key_blocks:
                    kb.value = 0.0
            if o.type in ("LIGHT", "CAMERA") and o.data.animation_data:
                o.data.animation_data_clear()
            res["modified"].append(t)

    def op_set_frame_range(self, op: dict, res: dict) -> None:
        s = self.scene
        s.frame_start, s.frame_end = op.get("start", 1), op["end"]
        s.render.fps = op.get("fps", 24)
        s.frame_set(s.frame_start)

    def op_add_shape_keys(self, op: dict, res: dict) -> None:
        o = self.obj(op["target"])
        if o.type != "MESH":
            raise OpError(f"{op['target']!r} is not a mesh")
        n = len(o.data.vertices)
        if o.data.shape_keys is None:
            o.shape_key_add(name="Basis", from_mix=False)
        for name, positions in op["keys"].items():
            if len(positions) != n:
                raise OpError(f"shape key {name!r}: {len(positions)} positions for {n} vertices")
            kb = o.data.shape_keys.key_blocks.get(name) or o.shape_key_add(name=name, from_mix=False)
            kb.value = 0.0
            kb.slider_min, kb.slider_max = 0.0, 1.0
            for i, p in enumerate(positions):
                kb.data[i].co = p
        res["modified"].append(op["target"])

    def op_add_sound_strip(self, op: dict, res: dict) -> None:
        s = self.scene
        if not os.path.exists(op["path"]):
            raise OpError(f"file not found: {op['path']}")
        if s.sequence_editor is None:
            s.sequence_editor_create()
        se = s.sequence_editor
        strips = se.strips if hasattr(se, "strips") else se.sequences
        old = strips.get(op["id"])
        if old is not None:
            strips.remove(old)
        st = strips.new_sound(op["id"], op["path"], op.get("channel", 1), op.get("frame_start", 1))
        st.volume = op.get("volume", 1.0)
        res["created"].append(op["id"])
