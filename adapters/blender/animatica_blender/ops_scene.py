# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene-building ops: primitives, meshes, empties, lights, cameras, rigs, imports, edits, constraints, world."""

from __future__ import annotations

import math
import os

import bpy
import mathutils

from .common import ID_PROP, OpError, hex_to_rgb, rad


class SceneOps:
    """Mixin for :class:`Executor` (expects ``self.obj``, ``self.scene``, ``self._new_object``, ``self.workdir``)."""

    # ------------------------------------------------------------------ creation ops
    def op_create_primitive(self, op: dict, res: dict) -> None:
        import bmesh

        shape = op["shape"]
        mesh = bpy.data.meshes.new(op["id"] + "_mesh")
        bm = bmesh.new()
        seg = int(op.get("segments", 32))
        r = op.get("radius") or 0.5
        d = op.get("depth") or 1.0
        size = op.get("size")
        if shape == "cube":
            bmesh.ops.create_cube(bm, size=1.0)
            dims = size if size else ((2 * r,) * 3 if op.get("radius") else (1, 1, 1))
            bmesh.ops.scale(bm, vec=dims, verts=bm.verts)
        elif shape == "plane":
            bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
            dims = size or (2 * r, 2 * r, 1)
            bmesh.ops.scale(bm, vec=(dims[0], dims[1], 1), verts=bm.verts)
        elif shape == "uv_sphere":
            bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(seg // 2, 3), radius=r)
        elif shape == "ico_sphere":
            bmesh.ops.create_icosphere(bm, subdivisions=max(1, min(5, seg // 16)), radius=r)
        elif shape in ("cylinder", "cone"):
            r2 = r if shape == "cylinder" else 0.0
            bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r2, depth=d)
        elif shape == "torus":
            major, minor = r, op.get("depth") or r * 0.3
            self._torus(bm, major, minor, seg)
        elif shape == "circle":
            bmesh.ops.create_circle(bm, cap_ends=True, segments=seg, radius=r)
        else:
            raise OpError(f"unknown shape {shape}")
        if size and shape not in ("cube", "plane"):
            bm.verts.ensure_lookup_table()
            xs = [v.co for v in bm.verts]
            ext = [max(c[i] for c in xs) - min(c[i] for c in xs) or 1.0 for i in range(3)]
            bmesh.ops.scale(bm, vec=[size[i] / ext[i] for i in range(3)], verts=bm.verts)
        bm.to_mesh(mesh)
        bm.free()
        if op.get("smooth"):
            for p in mesh.polygons:
                p.use_smooth = True
        o = self._new_object(op, mesh)
        res["created"].append(o.name)

    @staticmethod
    def _torus(bm, major: float, minor: float, seg: int) -> None:
        ring = max(8, seg // 2)
        verts = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            row = []
            for j in range(ring):
                b = 2 * math.pi * j / ring
                x = (major + minor * math.cos(b)) * math.cos(a)
                y = (major + minor * math.cos(b)) * math.sin(a)
                z = minor * math.sin(b)
                row.append(bm.verts.new((x, y, z)))
            verts.append(row)
        for i in range(seg):
            for j in range(ring):
                bm.faces.new(
                    (
                        verts[i][j],
                        verts[(i + 1) % seg][j],
                        verts[(i + 1) % seg][(j + 1) % ring],
                        verts[i][(j + 1) % ring],
                    )
                )

    def op_create_mesh(self, op: dict, res: dict) -> None:
        mesh = bpy.data.meshes.new(op["id"] + "_mesh")
        mesh.from_pydata([tuple(v) for v in op["vertices"]], [], [list(f) for f in op.get("faces", [])])
        mesh.update()
        if op.get("smooth"):
            for p in mesh.polygons:
                p.use_smooth = True
        o = self._new_object(op, mesh)
        res["created"].append(o.name)

    def op_create_empty(self, op: dict, res: dict) -> None:
        o = self._new_object(op, None)
        o.empty_display_type = op.get("display", "PLAIN_AXES")
        o.empty_display_size = op.get("display_size", 0.2)
        res["created"].append(o.name)

    def op_add_light(self, op: dict, res: dict) -> None:
        lt = op.get("light_type", "point").upper()
        light = bpy.data.lights.new(op["id"] + "_light", type=lt)
        light.energy = op.get("energy", 100.0)
        light.color = hex_to_rgb(op.get("color", "#FFFFFF"))
        if lt == "SUN":
            light.angle = math.radians(max(0.1, op.get("size", 0.25) * 10))
        elif lt == "AREA":
            light.size = op.get("size", 0.25)
        else:
            light.shadow_soft_size = op.get("size", 0.25)
        if lt == "SPOT":
            light.spot_size = math.radians(op.get("spot_angle", 45.0))
        o = self._new_object(op, light)
        res["created"].append(o.name)

    def op_add_camera(self, op: dict, res: dict) -> None:
        cam = bpy.data.cameras.new(op["id"] + "_cam")
        cam.lens = op.get("lens", 50.0)
        cam.clip_end = 500
        o = self._new_object(op, cam)
        look = op.get("look_at")
        if isinstance(look, str):
            c = o.constraints.new("TRACK_TO")
            c.target = self.obj(look)
            c.track_axis, c.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
        elif look is not None:
            self._aim(o, mathutils.Vector(look))
        if op.get("dof_target"):
            cam.dof.use_dof = True
            cam.dof.focus_object = self.obj(op["dof_target"])
            cam.dof.aperture_fstop = op.get("fstop", 2.8)
        if self.scene.camera is None:
            self.scene.camera = o
        res["created"].append(o.name)

    @staticmethod
    def _aim(o, target):
        direction = target - o.location
        o.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    def op_create_armature(self, op: dict, res: dict) -> None:
        arm = bpy.data.armatures.new(op["id"] + "_arm")
        o = self._new_object(op, arm)
        bpy.context.view_layer.objects.active = o
        for ob in bpy.context.selected_objects:
            ob.select_set(False)
        o.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            made = {}
            for b in op["bones"]:
                eb = arm.edit_bones.new(b["name"])
                eb.head, eb.tail = b["head"], b["tail"]
                if b.get("parent"):
                    if b["parent"] not in made:
                        raise OpError(f"bone parent {b['parent']!r} must be defined before {b['name']!r}")
                    eb.parent = made[b["parent"]]
                made[b["name"]] = eb
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
        res["created"].append(o.name)

    def op_bind_mesh_to_armature(self, op: dict, res: dict) -> None:
        mesh, arm = self.obj(op["mesh"]), self.obj(op["armature"])
        if arm.type != "ARMATURE":
            raise OpError(f"{op['armature']!r} is not an armature")
        if op.get("bone"):
            if op["bone"] not in arm.data.bones:
                raise OpError(f"no bone {op['bone']!r}")
            mw = mesh.matrix_world.copy()
            mesh.parent = arm
            mesh.parent_type = "BONE"
            mesh.parent_bone = op["bone"]
            bpy.context.view_layer.update()
            mesh.matrix_world = mw
        else:
            for ob in bpy.context.selected_objects:
                ob.select_set(False)
            mesh.select_set(True)
            arm.select_set(True)
            bpy.context.view_layer.objects.active = arm
            bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        res["modified"].append(mesh.name)

    def op_import_asset(self, op: dict, res: dict) -> None:
        path = op["path"]
        if not os.path.exists(path):
            raise OpError(f"file not found: {path}")
        fmt = (op.get("format") or os.path.splitext(path)[1].lstrip(".")).lower()
        before = set(bpy.data.objects)
        if fmt in ("gltf", "glb"):
            bpy.ops.import_scene.gltf(filepath=path)
        elif fmt == "obj":
            bpy.ops.wm.obj_import(filepath=path)
        elif fmt == "fbx":
            bpy.ops.import_scene.fbx(filepath=path)
        elif fmt in ("usd", "usda", "usdc", "usdz"):
            bpy.ops.wm.usd_import(filepath=path)
        else:
            raise OpError(f"unsupported format {fmt}")
        new = [o for o in bpy.data.objects if o not in before]
        root = bpy.data.objects.new(op["id"], None)
        root[ID_PROP] = op["id"]
        self._link(root, op.get("collection"))
        for o in new:
            if o.parent is None:
                o.parent = root
            o[ID_PROP] = f"{op['id']}/{o.name}"
        root.location = op.get("location", (0, 0, 0))
        root.rotation_euler = rad(op.get("rotation", (0, 0, 0)))
        root.scale = op.get("scale", (1, 1, 1))
        if op.get("parent"):
            root.parent = self.obj(op["parent"])
        res["created"].append(op["id"])

    # ------------------------------------------------------------------ edit ops
    def op_delete(self, op: dict, res: dict) -> None:
        for t in op["targets"]:
            o = self.obj(t)
            bpy.data.objects.remove(o, do_unlink=True)
            res["deleted"].append(t)

    def op_transform(self, op: dict, res: dict) -> None:
        o = self.obj(op["target"])
        if op.get("location") is not None:
            o.location = op["location"]
        if op.get("rotation") is not None:
            o.rotation_euler = rad(op["rotation"])
        if op.get("scale") is not None:
            o.scale = op["scale"]
        res["modified"].append(op["target"])

    def op_parent(self, op: dict, res: dict) -> None:
        child = self.obj(op["child"])
        mw = child.matrix_world.copy()
        child.parent = self.obj(op["parent"]) if op.get("parent") else None
        if op.get("keep_transform", True):
            bpy.context.view_layer.update()
            child.matrix_world = mw
        res["modified"].append(op["child"])

    MOD_TYPES = {
        "bevel": "BEVEL",
        "subsurf": "SUBSURF",
        "array": "ARRAY",
        "solidify": "SOLIDIFY",
        "displace": "DISPLACE",
        "mirror": "MIRROR",
        "smooth": "SMOOTH",
        "wireframe": "WIREFRAME",
        "decimate": "DECIMATE",
    }

    def op_add_modifier(self, op: dict, res: dict) -> None:
        o = self.obj(op["target"])
        if o.type != "MESH":
            raise OpError(f"{op['target']!r} is not a mesh")
        m = o.modifiers.new(op.get("name") or op["type"], self.MOD_TYPES[op["type"]])
        params = dict(op.get("params", {}))
        if op["type"] == "displace":
            tex = bpy.data.textures.new(o.name + "_disp", type="CLOUDS")
            tex.noise_scale = float(params.pop("noise_scale", 1.0))
            m.texture = tex
            m.texture_coords = "GLOBAL"
        if op["type"] == "bevel":
            params.setdefault("limit_method", "ANGLE")
        if op["type"] == "subsurf":
            params.setdefault("render_levels", params.get("levels", 1))
        for k, v in params.items():
            if not hasattr(m, k):
                res["warnings"].append(f"modifier {op['type']} has no param {k!r}")
                continue
            setattr(m, k, v)
        res["modified"].append(op["target"])

    def op_set_camera_active(self, op: dict, res: dict) -> None:
        cam = self.obj(op["id"])
        if cam.type != "CAMERA":
            raise OpError(f"{op['id']!r} is not a camera")
        if op.get("frame") is None:
            self.scene.camera = cam
        else:
            name = f"cut_{op['id']}_{op['frame']}"
            m = self.scene.timeline_markers.get(name) or self.scene.timeline_markers.new(
                name, frame=op["frame"]
            )
            m.camera = cam
            if op["frame"] <= self.scene.frame_start:
                self.scene.camera = cam

    CONSTRAINTS = {
        "track_to": "TRACK_TO",
        "damped_track": "DAMPED_TRACK",
        "copy_location": "COPY_LOCATION",
        "child_of": "CHILD_OF",
        "limit_location": "LIMIT_LOCATION",
    }

    def op_add_constraint(self, op: dict, res: dict) -> None:
        o = self.obj(op["target"])
        c = o.constraints.new(self.CONSTRAINTS[op["type"]])
        if op.get("subject"):
            c.target = self.obj(op["subject"])
        if op["type"] == "track_to":
            c.track_axis, c.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
        for k, v in op.get("params", {}).items():
            if hasattr(c, k):
                setattr(c, k, v)
            else:
                res["warnings"].append(f"constraint has no param {k!r}")
        res["modified"].append(op["target"])

    def op_set_world(self, op: dict, res: dict) -> None:
        s = self.scene
        world = s.world or bpy.data.worlds.new("World")
        s.world = world
        world.use_nodes = True
        nt = world.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputWorld")
        bg = nt.nodes.new("ShaderNodeBackground")
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        nt.links.new(tc.outputs["Generated"], sep.inputs[0])
        remap = nt.nodes.new("ShaderNodeMath")  # direction z in [-1, 1] -> [0, 1]
        remap.operation = "MULTIPLY_ADD"
        remap.inputs[1].default_value = 0.5
        remap.inputs[2].default_value = 0.5
        nt.links.new(sep.outputs["Z"], remap.inputs[0])
        nt.links.new(remap.outputs[0], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
        nt.links.new(bg.outputs[0], out.inputs[0])
        el = ramp.color_ramp.elements
        ground = op.get("ground") or op.get("horizon", "#F2B880")
        # after the remap 0.5 is the horizon, 1.0 straight up
        el[0].position, el[0].color = 0.42, (*hex_to_rgb(ground), 1)
        el[1].position, el[1].color = 0.72, (*hex_to_rgb(op.get("zenith", "#4A6FA5")), 1)
        mid = el.new(0.5)
        mid.color = (*hex_to_rgb(op.get("horizon", "#F2B880")), 1)
        glow = el.new(0.545)
        hz, zn = hex_to_rgb(op.get("horizon", "#F2B880")), hex_to_rgb(op.get("zenith", "#4A6FA5"))
        glow.color = (
            *(hex_to_rgb(op["glow"]) if op.get("glow") else [0.6 * a + 0.4 * b for a, b in zip(hz, zn)]),
            1,
        )
        bg.inputs["Strength"].default_value = op.get("strength", 1.0)
        world.color = hex_to_rgb(op.get("horizon", "#F2B880"))
        if op.get("mist"):
            s.render.use_motion_blur = False
            world.mist_settings.start, world.mist_settings.depth = 5, 60 * (1.01 - op["mist"])

    def op_set_property(self, op: dict, res: dict) -> None:
        o = self.obj(op["target"])
        parts = op["path"].split(".")
        cur = o
        for p in parts[:-1]:
            cur = getattr(cur, p)
        if not hasattr(cur, parts[-1]):
            raise OpError(f"no property {op['path']!r}")
        setattr(cur, parts[-1], op["value"])
        res["modified"].append(op["target"])
