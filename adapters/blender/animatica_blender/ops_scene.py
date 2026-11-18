# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene-building ops: primitives, meshes, empties, lights, cameras, rigs, imports, edits, constraints, world."""

from __future__ import annotations

import math
import os

import bpy
import mathutils

from .common import ID_PROP, OpError, apply_viewport_tint, hex_to_rgb, rad


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
        if op.get("colors"):  # per-vertex colour (linear RGB) a material reads with vertex_color
            if len(op["colors"]) != len(op["vertices"]):
                raise OpError("create_mesh: one colour per vertex")
            ca = mesh.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
            ca.data.foreach_set("color", [c for rgb in op["colors"] for c in (*rgb, 1.0)])
        if op.get("smooth"):
            for p in mesh.polygons:
                p.use_smooth = True
        o = self._new_object(op, mesh)
        res["created"].append(o.name)

    def op_create_skin_mesh(self, op: dict, res: dict) -> None:
        verts, edges, radii = op["vertices"], op["edges"], op["radii"]
        if len(radii) != len(verts):
            raise OpError("create_skin_mesh: one radius pair per vertex")
        mesh = bpy.data.meshes.new(op["id"] + "_mesh")
        mesh.from_pydata([tuple(v) for v in verts], [tuple(e) for e in edges], [])
        mesh.update()
        o = self._new_object(op, mesh)
        skin = o.modifiers.new("skin", "SKIN")
        skin.use_smooth_shade = True
        sv = mesh.skin_vertices[0].data
        for i, (rx, ry) in enumerate(radii):
            sv[i].radius = (rx, ry)
            sv[i].use_root = i == op.get("root", 0)
        if op.get("subdivisions", 2):
            sub = o.modifiers.new("subsurf", "SUBSURF")
            sub.levels = sub.render_levels = op.get("subdivisions", 2)
        if op.get("apply", True):
            # bake the modifiers into real geometry: bone-heat skinning and object-space textures need it
            dg = bpy.context.evaluated_depsgraph_get()
            baked = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
            o.modifiers.clear()
            old = o.data
            o.data = baked
            baked.name = op["id"] + "_mesh"
            bpy.data.meshes.remove(old)
            if op.get("smooth", True):
                for p in baked.polygons:
                    p.use_smooth = True
        res["created"].append(o.name)
        res.setdefault("data", {}).setdefault("vertex_counts", {})[op["id"]] = len(o.data.vertices)

    def op_create_metaball_mesh(self, op: dict, res: dict) -> None:
        mb = bpy.data.metaballs.new(op["id"] + "_mb")
        mb.resolution = mb.render_resolution = op.get("resolution", 0.02)
        mb.threshold = op.get("threshold", 0.6)
        for el in op["elements"]:
            e = mb.elements.new(type=el.get("type", "ball").upper())
            e.co = el["co"]
            e.radius = el["radius"]
            e.stiffness = el.get("stiffness", 2.0)
            e.use_negative = el.get("negative", False)
            size = el.get("size") or (0.0, 0.0, 0.0)
            if e.type == "CAPSULE":
                e.size_x = max(size[0], 1e-4)
            elif e.type == "ELLIPSOID":
                e.size_x, e.size_y, e.size_z = (max(v, 1e-4) for v in size)
            rot = el.get("rotation") or (0.0, 0.0, 0.0)
            e.rotation = mathutils.Euler([math.radians(a) for a in rot], "XYZ").to_quaternion()
        tmp = bpy.data.objects.new(op["id"] + "_mbtmp", mb)
        self.scene.collection.objects.link(tmp)
        try:
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()
            mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
        finally:
            bpy.data.objects.remove(tmp, do_unlink=True)
            bpy.data.metaballs.remove(mb)
        if len(mesh.vertices) == 0:
            raise OpError(f"metaball {op['id']!r} produced no surface (radii too small for the threshold?)")
        mesh.name = op["id"] + "_mesh"
        if op.get("smooth", True):
            for p in mesh.polygons:
                p.use_smooth = True
        o = self._new_object(op, mesh)
        res["created"].append(o.name)
        res.setdefault("data", {}).setdefault("vertex_counts", {})[op["id"]] = len(mesh.vertices)

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
                eb.use_inherit_rotation = bool(b.get("inherit_rotation", True))
                made[b["name"]] = eb
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
        res["created"].append(o.name)

    def op_bind_mesh_to_armature(self, op: dict, res: dict) -> None:
        mesh, arm = self.obj(op["mesh"]), self.obj(op["armature"])
        if arm.type != "ARMATURE":
            raise OpError(f"{op['armature']!r} is not an armature")
        if op.get("auto"):
            self._auto_bind(mesh, arm, res, op.get("exclude", []))
            for reg in op.get("rigid", []):
                self._rigid_region(mesh, arm, reg)
        elif op.get("bones"):
            self._smooth_bind(mesh, arm, op["bones"])
        elif op.get("bone"):
            self._rigid_bind(mesh, arm, op["bone"])
        else:
            for ob in bpy.context.selected_objects:
                ob.select_set(False)
            mesh.select_set(True)
            arm.select_set(True)
            bpy.context.view_layer.objects.active = arm
            bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        res["modified"].append(mesh.name)

    def _auto_bind(self, mesh, arm, res: dict, exclude: list[str] | None = None) -> None:
        """Bone-heat weights over the whole armature, keeping the mesh's local transform (the parent inverse
        absorbs the re-parenting). If heat weighting fails (no weights), fall back to distance weights."""
        bpy.context.view_layer.update()
        mw = mesh.matrix_world.copy()
        for ob in bpy.context.selected_objects:
            ob.select_set(False)
        mesh.select_set(True)
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        # bones that drive other meshes (a separate tail, ears) must not pull this one's surface
        muted = [
            b for b in arm.data.bones if b.use_deform and any(b.name.startswith(p) for p in exclude or [])
        ]
        for b in muted:
            b.use_deform = False
        try:
            bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        finally:
            for b in muted:
                b.use_deform = True
            for vg in [g for g in mesh.vertex_groups if any(g.name.startswith(p) for p in exclude or [])]:
                mesh.vertex_groups.remove(vg)
        mesh.select_set(False)
        arm.select_set(False)
        weighted = any(len(v.groups) for v in mesh.data.vertices)
        if not weighted:
            res["warnings"].append(f"bone heat failed on {mesh.name!r}; using distance weights")
            for vg in list(mesh.vertex_groups):
                mesh.vertex_groups.remove(vg)
            for m in [m for m in mesh.modifiers if m.type == "ARMATURE"]:
                mesh.modifiers.remove(m)
            self._smooth_bind(mesh, arm, [b.name for b in arm.data.bones if b.use_deform])
            return
        mesh.matrix_parent_inverse = arm.matrix_world.inverted() @ mw @ mesh.matrix_basis.inverted()

    def _rigid_region(self, mesh, arm, reg: dict) -> None:
        """Weights inside an ellipsoid (armature space) go to one bone, blending out over the falloff shell."""
        bone = reg["bone"]
        if bone not in arm.data.bones:
            raise OpError(f"no bone {bone!r}")
        bpy.context.view_layer.update()
        to_arm = arm.matrix_world.inverted() @ mesh.matrix_world
        c = mathutils.Vector(reg["center"])
        rx, ry, rz = (max(1e-4, r) for r in reg["radii"])
        unpitch = mathutils.Matrix.Rotation(-math.radians(reg.get("pitch", 0.0)), 3, "X")
        fall = reg.get("falloff", 0.35)
        target = mesh.vertex_groups.get(bone) or mesh.vertex_groups.new(name=bone)
        names = {g.index: g for g in mesh.vertex_groups}
        for v in mesh.data.vertices:
            q = unpitch @ (to_arm @ v.co - c)
            e = math.sqrt((q.x / rx) ** 2 + (q.y / ry) ** 2 + (q.z / rz) ** 2)
            if e >= 1.0:
                continue
            u = 1.0 if fall <= 0 or e <= 1.0 - fall else (1.0 - e) / fall
            s = u * u * (3 - 2 * u)
            old = {g.group: g.weight for g in v.groups}
            tot = sum(old.values()) or 1.0
            new = {gi: (1 - s) * w / tot for gi, w in old.items()}
            new[target.index] = new.get(target.index, 0.0) + s
            for gi, w in new.items():
                if w < 1e-4:
                    names[gi].remove([v.index])
                else:
                    names[gi].add([v.index], w, "REPLACE")

    def _rigid_bind(self, mesh, arm, bone: str) -> None:
        if bone not in arm.data.bones:
            raise OpError(f"no bone {bone!r}")
        bpy.context.view_layer.update()
        mw = mesh.matrix_world.copy()
        b = arm.data.bones[bone]
        # a BONE parent sits at the bone's tail
        tail = arm.matrix_world @ b.matrix_local @ mathutils.Matrix.Translation((0, b.length, 0))
        mesh.parent, mesh.parent_type, mesh.parent_bone = arm, "BONE", bone
        mesh.matrix_parent_inverse = tail.inverted() @ mw @ mesh.matrix_basis.inverted()

    def _smooth_bind(self, mesh, arm, bones: list[str]) -> None:
        if mesh.type != "MESH":
            raise OpError(f"{mesh.name!r} is not a mesh")
        for b in bones:
            if b not in arm.data.bones:
                raise OpError(f"no bone {b!r}")
        bpy.context.view_layer.update()
        mw = mesh.matrix_world.copy()
        to_arm = arm.matrix_world.inverted() @ mw
        segs = [(b, arm.data.bones[b].head_local, arm.data.bones[b].tail_local) for b in bones]
        groups = {b: mesh.vertex_groups.get(b) or mesh.vertex_groups.new(name=b) for b in bones}
        for v in mesh.data.vertices:
            p = to_arm @ v.co
            ws = []
            for b, h, t in segs:
                ht = t - h
                u = max(0.0, min(1.0, (p - h).dot(ht) / max(ht.length_squared, 1e-9)))
                d = (p - (h + ht * u)).length
                ws.append((b, 1.0 / (d + 0.02) ** 4))
            total = sum(w for _, w in ws)
            for b, w in ws:
                if w / total > 0.01:
                    groups[b].add([v.index], w / total, "REPLACE")
        mesh.parent, mesh.parent_type = arm, "OBJECT"
        mesh.matrix_parent_inverse = arm.matrix_world.inverted() @ mw @ mesh.matrix_basis.inverted()
        mod = mesh.modifiers.get("animatica_armature") or mesh.modifiers.new("animatica_armature", "ARMATURE")
        mod.object = arm
        mod.use_vertex_groups = True

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
        "shrinkwrap": "SHRINKWRAP",
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
        if op["type"] == "shrinkwrap":
            if not op.get("surface"):
                raise OpError("shrinkwrap needs a surface")
            m.target = self.obj(op["surface"])
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

    def op_scatter(self, op: dict, res: dict) -> None:
        surf, inst = self.obj(op["surface"]), self.obj(op["instance"])
        mesh = bpy.data.meshes.new(op["id"] + "_mesh")  # an empty carrier: the modifier reads the surface
        o = self._new_object({"id": op["id"]}, mesh)
        ng = bpy.data.node_groups.new(op["id"] + "_scatter", "GeometryNodeTree")
        ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        n, ln = ng.nodes, ng.links
        n.new("NodeGroupInput")
        gout = n.new("NodeGroupOutput")
        sinfo = n.new("GeometryNodeObjectInfo")
        sinfo.inputs["Object"].default_value = surf
        sinfo.transform_space = "RELATIVE"
        dist = n.new("GeometryNodeDistributePointsOnFaces")
        dist.distribute_method = "RANDOM"
        dense = op.get("dense", [])
        top = max([1.0] + [float(c[3]) for c in dense])
        dist.inputs["Density"].default_value = op.get("density", 10.0) * top
        dist.inputs["Seed"].default_value = op.get("seed", 0)
        ln.new(sinfo.outputs["Geometry"], dist.inputs["Mesh"])
        pos = n.new("GeometryNodeInputPosition")
        points = dist.outputs["Points"]
        if dense:
            # keep each point with probability mult(pos) / top, mult = 1 outside the circles, rising smoothly
            # to the circle's multiplier toward its centre (max over circles)
            mult = None
            for cx, cy, r, m in dense:
                flat = n.new("ShaderNodeVectorMath")
                flat.operation = "MULTIPLY"
                flat.inputs[1].default_value = (1.0, 1.0, 0.0)
                ln.new(pos.outputs["Position"], flat.inputs[0])
                d = n.new("ShaderNodeVectorMath")
                d.operation = "DISTANCE"
                ln.new(flat.outputs["Vector"], d.inputs[0])
                d.inputs[1].default_value = (cx, cy, 0.0)
                mr = n.new("ShaderNodeMapRange")
                mr.interpolation_type = "SMOOTHSTEP"
                mr.inputs["From Min"].default_value = r
                mr.inputs["From Max"].default_value = r * 0.4
                mr.inputs["To Min"].default_value = 1.0
                mr.inputs["To Max"].default_value = m
                ln.new(d.outputs["Value"], mr.inputs["Value"])
                if mult is None:
                    mult = mr.outputs["Result"]
                else:
                    mx = n.new("ShaderNodeMath")
                    mx.operation = "MAXIMUM"
                    ln.new(mult, mx.inputs[0])
                    ln.new(mr.outputs["Result"], mx.inputs[1])
                    mult = mx.outputs[0]
            keep = n.new("ShaderNodeMath")
            keep.operation = "DIVIDE"
            ln.new(mult, keep.inputs[0])
            keep.inputs[1].default_value = top
            rnd_k = n.new("FunctionNodeRandomValue")
            rnd_k.data_type = "FLOAT"
            rnd_k.inputs["Seed"].default_value = op.get("seed", 0) + 29
            drop = n.new("FunctionNodeCompare")
            drop.data_type, drop.operation = "FLOAT", "GREATER_THAN"
            ln.new(rnd_k.outputs["Value"], drop.inputs["A"])
            ln.new(keep.outputs[0], drop.inputs["B"])
            thin = n.new("GeometryNodeDeleteGeometry")
            thin.domain = "POINT"
            ln.new(points, thin.inputs["Geometry"])
            ln.new(drop.outputs["Result"], thin.inputs["Selection"])
            points = thin.outputs["Geometry"]
        # cleared circles: delete points within (x, y, r)
        for cx, cy, r in op.get("clear", []):
            d = n.new("ShaderNodeVectorMath")
            d.operation = "DISTANCE"
            sep_c = n.new("ShaderNodeVectorMath")
            sep_c.operation = "MULTIPLY"
            sep_c.inputs[1].default_value = (1.0, 1.0, 0.0)  # distance on the ground plane
            ln.new(pos.outputs["Position"], sep_c.inputs[0])
            ln.new(sep_c.outputs["Vector"], d.inputs[0])
            d.inputs[1].default_value = (cx, cy, 0.0)
            lt = n.new("FunctionNodeCompare")
            lt.data_type, lt.operation = "FLOAT", "LESS_THAN"
            ln.new(d.outputs["Value"], lt.inputs["A"])
            lt.inputs["B"].default_value = r
            delete = n.new("GeometryNodeDeleteGeometry")
            delete.domain = "POINT"
            ln.new(points, delete.inputs["Geometry"])
            ln.new(lt.outputs["Result"], delete.inputs["Selection"])
            points = delete.outputs["Geometry"]
        # scale: random, shrunk inside the "short" circles (smoothly, from the edge inward)
        rnd_s = n.new("FunctionNodeRandomValue")
        rnd_s.data_type = "FLOAT"
        lo, hi = op.get("scale", (0.7, 1.3))
        rnd_s.inputs["Min"].default_value, rnd_s.inputs["Max"].default_value = lo, hi
        rnd_s.inputs["Seed"].default_value = op.get("seed", 0) + 7
        scale = rnd_s.outputs["Value"]
        for cx, cy, r in op.get("short", []):
            flat = n.new("ShaderNodeVectorMath")
            flat.operation = "MULTIPLY"
            flat.inputs[1].default_value = (1.0, 1.0, 0.0)
            ln.new(pos.outputs["Position"], flat.inputs[0])
            d = n.new("ShaderNodeVectorMath")
            d.operation = "DISTANCE"
            ln.new(flat.outputs["Vector"], d.inputs[0])
            d.inputs[1].default_value = (cx, cy, 0.0)
            mr = n.new("ShaderNodeMapRange")
            mr.inputs["From Min"].default_value = r * 0.6
            mr.inputs["From Max"].default_value = r
            mr.inputs["To Min"].default_value = op.get("short_scale", 0.35)
            mr.inputs["To Max"].default_value = 1.0
            ln.new(d.outputs["Value"], mr.inputs["Value"])
            mul = n.new("ShaderNodeMath")
            mul.operation = "MULTIPLY"
            ln.new(scale, mul.inputs[0])
            ln.new(mr.outputs["Result"], mul.inputs[1])
            scale = mul.outputs[0]
        # rotation: random yaw, plus a wind lean that travels across the field (noise of position + time)
        rnd_r = n.new("FunctionNodeRandomValue")
        rnd_r.data_type = "FLOAT"
        rnd_r.inputs["Min"].default_value, rnd_r.inputs["Max"].default_value = 0.0, 6.2832
        rnd_r.inputs["Seed"].default_value = op.get("seed", 0) + 13
        rot = n.new("ShaderNodeCombineXYZ")
        ln.new(rnd_r.outputs["Value"], rot.inputs["Z"])
        if op.get("wind"):
            t = n.new("GeometryNodeInputSceneTime")
            off = n.new("ShaderNodeVectorMath")
            off.operation = "SCALE"
            ln.new(pos.outputs["Position"], off.inputs[0])
            off.inputs["Scale"].default_value = 0.35
            drift = n.new("ShaderNodeCombineXYZ")
            sp_t = n.new("ShaderNodeMath")
            sp_t.operation = "MULTIPLY"
            sp_t.inputs[1].default_value = op.get("wind_speed", 0.6)
            ln.new(t.outputs["Seconds"], sp_t.inputs[0])
            ln.new(sp_t.outputs[0], drift.inputs["X"])
            ln.new(sp_t.outputs[0], drift.inputs["Y"])
            v = n.new("ShaderNodeVectorMath")
            v.operation = "ADD"
            ln.new(off.outputs["Vector"], v.inputs[0])
            ln.new(drift.outputs["Vector"], v.inputs[1])
            nz = n.new("ShaderNodeTexNoise")
            nz.noise_dimensions = "3D"
            nz.inputs["Scale"].default_value = 1.0
            ln.new(v.outputs["Vector"], nz.inputs["Vector"])
            lean = n.new("ShaderNodeMath")
            lean.operation = "MULTIPLY_ADD"
            lean.inputs[1].default_value = op["wind"] * 2.0
            lean.inputs[2].default_value = -op["wind"] * 0.8
            ln.new(nz.outputs["Fac"], lean.inputs[0])
            ln.new(lean.outputs[0], rot.inputs["X"])
        iinfo = n.new("GeometryNodeObjectInfo")
        iinfo.inputs["Object"].default_value = inst
        iinfo.inputs["As Instance"].default_value = True
        iop = n.new("GeometryNodeInstanceOnPoints")
        ln.new(points, iop.inputs["Points"])
        ln.new(iinfo.outputs["Geometry"], iop.inputs["Instance"])
        ln.new(rot.outputs["Vector"], iop.inputs["Rotation"])
        ln.new(scale, iop.inputs["Scale"])
        ln.new(iop.outputs["Instances"], gout.inputs["Geometry"])
        mod = o.modifiers.new("scatter", "NODES")
        mod.node_group = ng
        # (templates stay renderable: an object disabled for render may not be evaluated for the instancer;
        # callers park them out of sight, e.g. below the ground)
        bpy.context.view_layer.update()
        res["created"].append(o.name)

    def op_snap_to_surface(self, op: dict, res: dict) -> None:
        o, surf = self.obj(op["target"]), self.obj(op["surface"])
        if surf.type != "MESH":
            raise OpError(f"{op['surface']!r} is not a mesh")
        bpy.context.view_layer.update()
        d = mathutils.Vector(op.get("direction", (0.0, -1.0, 0.0)))
        if o.parent is not None:
            d = o.parent.matrix_world.to_3x3() @ d
        d.normalize()
        here = o.matrix_world.translation.copy()
        origin = here + d * op.get("reach", 1.0)
        inv = surf.matrix_world.inverted()
        lo, ld = inv @ origin, (inv.to_3x3() @ -d).normalized()
        hit, loc, _normal, _i = surf.ray_cast(lo, ld)
        if not hit:
            res["warnings"].append(f"snap_to_surface: no hit on {op['surface']!r} for {op['target']!r}")
            return
        world = surf.matrix_world @ loc + d * op.get("offset", 0.002)
        delta = world - here
        for ob in [o] + [self.obj(c) for c in op.get("carry", [])]:
            mw = ob.matrix_world.copy()
            mw.translation = mw.translation + delta
            ob.matrix_world = mw
            res["modified"].append(ob.get("animatica_id", ob.name))

    def op_add_bone_constraint(self, op: dict, res: dict) -> None:
        arm = self.obj(op["armature"])
        if arm.type != "ARMATURE" or op["bone"] not in arm.pose.bones:
            raise OpError(f"{op['armature']!r} has no bone {op['bone']!r}")
        pb = arm.pose.bones[op["bone"]]
        kind = {"ik": "IK", "damped_track": "DAMPED_TRACK", "copy_rotation": "COPY_ROTATION"}[op["type"]]
        c = pb.constraints.new(kind)
        c.target = self.obj(op["subject"])
        if op["type"] == "ik":
            c.chain_count = op.get("chain_count", 2)
            c.use_tail = True
            c.use_stretch = False
            if op.get("pole"):
                c.pole_target = self.obj(op["pole"])
                c.pole_angle = math.radians(op.get("pole_angle", -90.0))
        c.influence = op.get("influence", 1.0)
        res["modified"].append(op["armature"])

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
        sky = ramp.outputs["Color"]
        if op.get("clouds"):
            # soft wisps: stretched noise on the sky dome, faded out toward the horizon and the zenith
            mp = nt.nodes.new("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = (1.0, 1.0, 3.5)
            nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
            cn = nt.nodes.new("ShaderNodeTexNoise")
            cn.inputs["Scale"].default_value = 2.2
            cn.inputs["Detail"].default_value = 6.0
            cn.inputs["Roughness"].default_value = 0.55
            nt.links.new(mp.outputs["Vector"], cn.inputs["Vector"])
            cr = nt.nodes.new("ShaderNodeMapRange")
            cr.inputs["From Min"].default_value = 0.62 - 0.12 * op["clouds"]
            cr.inputs["From Max"].default_value = 0.78
            nt.links.new(cn.outputs["Fac"], cr.inputs["Value"])
            band = nt.nodes.new("ShaderNodeMapRange")  # only between ~5 and ~50 degrees above the horizon
            band.inputs["From Min"].default_value = 0.02
            band.inputs["From Max"].default_value = 0.12
            nt.links.new(sep.outputs["Z"], band.inputs["Value"])
            mul = nt.nodes.new("ShaderNodeMath")
            mul.operation = "MULTIPLY"
            nt.links.new(cr.outputs["Result"], mul.inputs[0])
            nt.links.new(band.outputs["Result"], mul.inputs[1])
            cmix = nt.nodes.new("ShaderNodeMix")
            cmix.data_type = "RGBA"
            nt.links.new(mul.outputs[0], cmix.inputs["Factor"])
            nt.links.new(sky, cmix.inputs["A"])
            cmix.inputs["B"].default_value = (*hex_to_rgb(op.get("cloud_color", "#FFFFFF")), 1)
            sky = cmix.outputs["Result"]
        if op.get("stars"):
            # point stars: tiny Voronoi cells lit where the distance is smallest, twinkle-free, above the horizon
            vor = nt.nodes.new("ShaderNodeTexVoronoi")
            vor.inputs["Scale"].default_value = 420.0
            vor.inputs["Randomness"].default_value = 1.0
            nt.links.new(tc.outputs["Generated"], vor.inputs["Vector"])
            pts = nt.nodes.new("ShaderNodeMapRange")
            pts.inputs["From Min"].default_value = 0.09
            pts.inputs["From Max"].default_value = 0.0
            nt.links.new(vor.outputs["Distance"], pts.inputs["Value"])
            thin = nt.nodes.new("ShaderNodeMath")  # most cells are dark: keep ~1 in 4 as stars
            thin.operation = "GREATER_THAN"
            thin.inputs[1].default_value = 1.0 - 0.3 * op["stars"]
            nt.links.new(vor.outputs["Color"], thin.inputs[0])
            above = nt.nodes.new("ShaderNodeMapRange")
            above.inputs["From Min"].default_value = 0.03
            above.inputs["From Max"].default_value = 0.2
            nt.links.new(sep.outputs["Z"], above.inputs["Value"])
            m1 = nt.nodes.new("ShaderNodeMath")
            m1.operation = "MULTIPLY"
            nt.links.new(pts.outputs["Result"], m1.inputs[0])
            nt.links.new(thin.outputs[0], m1.inputs[1])
            m2 = nt.nodes.new("ShaderNodeMath")
            m2.operation = "MULTIPLY"
            nt.links.new(m1.outputs[0], m2.inputs[0])
            nt.links.new(above.outputs["Result"], m2.inputs[1])
            m3 = nt.nodes.new("ShaderNodeMath")
            m3.operation = "MULTIPLY"
            m3.inputs[1].default_value = 6.0 * op["stars"]
            nt.links.new(m2.outputs[0], m3.inputs[0])
            add = nt.nodes.new("ShaderNodeMix")
            add.data_type, add.blend_type = "RGBA", "ADD"
            add.inputs["Factor"].default_value = 1.0
            nt.links.new(sky, add.inputs["A"])
            starcol = nt.nodes.new("ShaderNodeCombineColor")
            for c in ("Red", "Green", "Blue"):
                nt.links.new(m3.outputs[0], starcol.inputs[c])
            nt.links.new(starcol.outputs["Color"], add.inputs["B"])
            sky = add.outputs["Result"]
        nt.links.new(sky, bg.inputs["Color"])
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
        if op.get("viewport_tint"):
            s["animatica_viewport_tint"] = list(hex_to_rgb(op["viewport_tint"]))
        elif "animatica_viewport_tint" in s:
            del s["animatica_viewport_tint"]
        apply_viewport_tint(s)
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
