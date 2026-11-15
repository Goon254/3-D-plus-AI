# SPDX-License-Identifier: GPL-3.0-or-later
"""Executes Animatica batches inside Blender (bpy).

Receives plain-JSON batches (already validated by the core, re-checked lightly here), applies all
ops as one transaction, rolls back on any error, and returns a compact result dict.

Rollback strategy: headless Blender has no reliable undo stack, so before each mutating batch we
write a snapshot .blend (``undo_token``) and restore it on failure. In the live add-on, the same
snapshot mechanism is used so behaviour is identical.
"""

from __future__ import annotations

import builtins
import math
import os
import signal
import tempfile
import time
import traceback
from typing import Any

import bpy
import mathutils

ID_PROP = "animatica_id"
TAGS_PROP = "animatica_tags"
READ_ONLY_OPS = {"query", "inspect", "render_preview", "render_final", "save"}


class OpError(Exception):
    pass


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    srgb = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    # sRGB -> linear (Blender colour properties are scene-linear)
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)  # type: ignore[return-value]


def rad(v):
    return tuple(math.radians(x) for x in v)


class Executor:
    def __init__(self, workdir: str | None = None):
        self.workdir = workdir or tempfile.mkdtemp(prefix="animatica_")
        self._undo_counter = 0
        self.ensure_scene()

    # ------------------------------------------------------------------ scene helpers
    def ensure_scene(self) -> None:
        scene = bpy.context.scene
        if "animatica_project" not in scene:
            scene["animatica_project"] = True

    @property
    def scene(self):
        return bpy.context.scene

    def obj(self, oid: str):
        o = bpy.data.objects.get(oid)
        if o is not None:
            return o
        for cand in bpy.data.objects:  # artist may have renamed it; identity lives in the custom prop
            if cand.get(ID_PROP) == oid:
                return cand
        raise OpError(f"unknown id {oid!r}")

    def ids(self) -> set[str]:
        return {o.get(ID_PROP, o.name) for o in bpy.data.objects}

    def _link(self, o, collection: str | None):
        coll = self.scene.collection
        if collection:
            coll = bpy.data.collections.get(collection)
            if coll is None:
                coll = bpy.data.collections.new(collection)
                self.scene.collection.children.link(coll)
        coll.objects.link(o)

    def _new_object(self, op: dict, data) -> Any:
        oid = op["id"]
        if bpy.data.objects.get(oid) is not None:
            raise OpError(f"duplicate id {oid!r}")
        o = bpy.data.objects.new(oid, data)
        o[ID_PROP] = oid
        if op.get("tags"):
            o[TAGS_PROP] = ",".join(op["tags"])
        self._link(o, op.get("collection"))
        if op.get("parent"):
            o.parent = self.obj(op["parent"])
        o.location = op.get("location", (0, 0, 0))
        o.rotation_euler = rad(op.get("rotation", (0, 0, 0)))
        o.scale = op.get("scale", (1, 1, 1))
        return o

    # ------------------------------------------------------------------ batch entry
    def run_batch(self, batch: dict) -> dict:
        t0 = time.time()
        res: dict[str, Any] = {
            "batch_id": batch.get("batch_id", "?"), "ok": True, "created": [], "modified": [], "deleted": [],
            "warnings": [], "errors": [], "preview": None, "undo_token": None, "data": {},
        }
        ops = batch.get("ops", [])
        mutating = batch.get("mode") == "script" or any(o.get("op") not in READ_ONLY_OPS for o in ops)
        snapshot = None
        if mutating:
            snapshot = self._snapshot()
            res["undo_token"] = snapshot
        try:
            if batch.get("mode") == "script":
                self._run_script(batch.get("script") or "", float(batch.get("script_timeout_s", 30)), res)
            for i, op in enumerate(ops):
                try:
                    handler = getattr(self, "op_" + op["op"])
                except AttributeError:
                    raise OpError(f"unsupported op {op['op']!r}") from None
                try:
                    handler(op, res)
                except OpError as e:
                    raise OpError(f"ops[{i}]({op['op']}): {e}") from None
                except Exception as e:  # noqa: BLE001
                    raise OpError(f"ops[{i}]({op['op']}): {type(e).__name__}: {e}") from None
            verify = batch.get("verify") or {}
            if verify.get("preview"):
                path = os.path.join(self.workdir, "previews", f"{res['batch_id']}.png")
                self.op_render_preview(
                    {"path": path, "camera": verify.get("camera", "auto"),
                     "resolution": verify.get("resolution", (480, 270)), "frame": verify.get("frame")}, res)
        except Exception as e:  # noqa: BLE001
            res["ok"] = False
            res["errors"].append(str(e))
            if os.environ.get("ANIMATICA_DEBUG"):
                res["errors"].append(traceback.format_exc()[-1500:])
            if snapshot:
                self._restore(snapshot)
            res["created"], res["modified"], res["deleted"] = [], [], []
        res["elapsed_ms"] = int((time.time() - t0) * 1000)
        for k in ("created", "modified", "deleted"):
            res[k] = list(dict.fromkeys(res[k]))
        return res

    def _snapshot(self) -> str:
        self._undo_counter += 1
        path = os.path.join(self.workdir, "undo", f"u-{self._undo_counter}.blend")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=False)
        return path

    def _restore(self, path: str) -> None:
        bpy.ops.wm.open_mainfile(filepath=path)

    def undo(self, token: str) -> bool:
        if token and os.path.exists(token):
            self._restore(token)
            return True
        return False

    # ------------------------------------------------------------------ script mode
    SAFE_MODULES = {"math", "random", "mathutils", "bmesh", "bpy", "itertools", "functools", "colorsys"}

    def _run_script(self, code: str, timeout: float, res: dict) -> None:
        before = self.ids()

        def safe_import(name, *args, **kwargs):
            if name.split(".")[0] not in self.SAFE_MODULES:
                raise ImportError(f"import of {name!r} not allowed in script mode")
            return builtins.__import__(name, *args, **kwargs)

        banned = {"open", "exec", "eval", "compile", "input", "breakpoint", "__import__", "exit", "quit"}
        safe_builtins = {k: getattr(builtins, k) for k in dir(builtins) if k not in banned and not k.startswith("_")}
        safe_builtins["__import__"] = safe_import
        safe_builtins["__build_class__"] = builtins.__build_class__
        ns = {"__builtins__": safe_builtins, "bpy": bpy, "mathutils": mathutils, "math": math,
              "ax": ScriptHelpers(self), "__name__": "animatica_script"}

        def on_timeout(signum, frame):
            raise TimeoutError(f"script exceeded {timeout}s")

        old = None
        if hasattr(signal, "SIGALRM"):
            try:
                old = signal.signal(signal.SIGALRM, on_timeout)
                signal.setitimer(signal.ITIMER_REAL, timeout)
            except ValueError:  # not main thread (live add-on)
                old = None
        try:
            exec(compile(code, "<animatica-script>", "exec"), ns)  # noqa: S102 - sandboxed namespace
        finally:
            if old is not None:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old)
        for o in bpy.data.objects:
            if ID_PROP not in o:
                o[ID_PROP] = o.name
        after = self.ids()
        res["created"].extend(sorted(after - before))
        res["deleted"].extend(sorted(before - after))

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
                bm.faces.new((verts[i][j], verts[(i + 1) % seg][j], verts[(i + 1) % seg][(j + 1) % ring], verts[i][(j + 1) % ring]))

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

    MOD_TYPES = {"bevel": "BEVEL", "subsurf": "SUBSURF", "array": "ARRAY", "solidify": "SOLIDIFY",
                 "displace": "DISPLACE", "mirror": "MIRROR", "smooth": "SMOOTH", "wireframe": "WIREFRAME",
                 "decimate": "DECIMATE"}

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

    def _material(self, spec: dict, name: str):
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is None:
            bsdf = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        rgb = hex_to_rgb(spec.get("base_color", "#CCCCCC"))
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        bsdf.inputs["Metallic"].default_value = spec.get("metallic", 0.0)
        bsdf.inputs["Roughness"].default_value = spec.get("roughness", 0.5)
        if spec.get("emission"):
            bsdf.inputs["Emission Color"].default_value = (*hex_to_rgb(spec["emission"]), 1.0)
            bsdf.inputs["Emission Strength"].default_value = spec.get("emission_strength", 1.0)
        alpha = spec.get("alpha", 1.0)
        bsdf.inputs["Alpha"].default_value = alpha
        mat.diffuse_color = (*rgb, alpha)  # workbench / viewport colour
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

    def op_set_camera_active(self, op: dict, res: dict) -> None:
        cam = self.obj(op["id"])
        if cam.type != "CAMERA":
            raise OpError(f"{op['id']!r} is not a camera")
        if op.get("frame") is None:
            self.scene.camera = cam
        else:
            name = f"cut_{op['id']}_{op['frame']}"
            m = self.scene.timeline_markers.get(name) or self.scene.timeline_markers.new(name, frame=op["frame"])
            m.camera = cam
            if op["frame"] <= self.scene.frame_start:
                self.scene.camera = cam

    CONSTRAINTS = {"track_to": "TRACK_TO", "damped_track": "DAMPED_TRACK", "copy_location": "COPY_LOCATION",
                   "child_of": "CHILD_OF", "limit_location": "LIMIT_LOCATION"}

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
            if not o.data or not getattr(o.data, "shape_keys", None) or key not in o.data.shape_keys.key_blocks:
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
            return mat.node_tree, 'nodes["Principled BSDF"].inputs["Emission Strength"].default_value', False, None
        raise OpError(f"unsupported property {prop!r}")

    EASING = {"EASE_IN": ("BEZIER", "EASE_IN"), "EASE_OUT": ("BEZIER", "EASE_OUT"),
              "EASE_IN_OUT": ("BEZIER", "EASE_IN_OUT"), "BACK": ("BACK", "EASE_OUT"),
              "ELASTIC": ("ELASTIC", "EASE_OUT"), "BOUNCE": ("BOUNCE", "EASE_OUT")}

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
        glow.color = (*(hex_to_rgb(op["glow"]) if op.get("glow") else [0.6 * a + 0.4 * b for a, b in zip(hz, zn)]), 1)
        bg.inputs["Strength"].default_value = op.get("strength", 1.0)
        world.color = hex_to_rgb(op.get("horizon", "#F2B880"))
        if op.get("mist"):
            s.render.use_motion_blur = False
            world.mist_settings.start, world.mist_settings.depth = 5, 60 * (1.01 - op["mist"])

    def op_set_render(self, op: dict, res: dict) -> None:
        s = self.scene
        eng = op.get("engine")
        if eng:
            s.render.engine = {"workbench": "BLENDER_WORKBENCH", "eevee": _eevee_id(), "cycles": "CYCLES"}[eng]
            if eng == "cycles":
                s.cycles.device = "CPU"
                fast_cycles(s)
                try:
                    s.cycles.use_denoising = True
                    s.cycles.denoiser = "OPENIMAGEDENOISE"
                except Exception:  # noqa: BLE001
                    res["warnings"].append("denoiser unavailable")
        if op.get("resolution"):
            s.render.resolution_x, s.render.resolution_y = op["resolution"]
            s.render.resolution_percentage = 100
        if op.get("samples"):
            s.cycles.samples = op["samples"]
            try:
                s.eevee.taa_render_samples = op["samples"]
            except Exception:  # noqa: BLE001
                pass
        if op.get("fps"):
            s.render.fps = op["fps"]
        if op.get("look"):
            try:
                s.view_settings.view_transform = "AgX"
                s.view_settings.look = op["look"]
            except TypeError:
                res["warnings"].append(f"look {op['look']!r} unavailable")
        if op.get("exposure") is not None:
            s.view_settings.exposure = op["exposure"]

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

    # ------------------------------------------------------------------ render / io
    def _auto_camera(self):
        cam = self.scene.camera
        if cam is not None:
            return cam, False
        data = bpy.data.cameras.new("__auto_cam")
        cam = bpy.data.objects.new("__auto_cam", data)
        self.scene.collection.objects.link(cam)
        pts = [o.matrix_world @ mathutils.Vector(c) for o in self.scene.objects if o.type == "MESH" for c in o.bound_box]
        center = sum(pts, mathutils.Vector()) / max(1, len(pts)) if pts else mathutils.Vector()
        radius = max(((p - center).length for p in pts), default=2.0)
        cam.location = center + mathutils.Vector((1, -1.4, 0.8)).normalized() * radius * 2.4
        self._aim(cam, center)
        return cam, True

    def op_render_preview(self, op: dict, res: dict) -> None:
        s = self.scene
        path = op.get("path") or os.path.join(self.workdir, "previews", f"{res['batch_id']}.png")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        saved = (s.render.engine, s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage,
                 s.render.filepath, s.camera, s.frame_current)
        temp_cam = False
        saved_samples = s.cycles.samples if hasattr(s, "cycles") else None
        try:
            cam_id = op.get("camera", "auto")
            if cam_id and cam_id != "auto":
                s.camera = self.obj(cam_id)
            else:
                cam, temp_cam = self._auto_camera()
                s.camera = cam
            eng = op.get("engine", "workbench")
            s.render.engine = {"workbench": "BLENDER_WORKBENCH", "eevee": _eevee_id(), "cycles": "CYCLES"}[eng]
            if eng == "cycles":
                fast_cycles(s)
                s.cycles.samples = int(op.get("samples", 12))
                s.cycles.use_denoising = True
                s.cycles.device = "CPU"
            if eng == "workbench":
                sh = s.display.shading
                sh.light, sh.color_type = "STUDIO", "MATERIAL"
                sh.show_shadows, sh.show_cavity = True, True
                s.display.shading.background_type = "WORLD" if hasattr(sh, "background_type") else None
            s.render.resolution_x, s.render.resolution_y = op.get("resolution", (480, 270))
            s.render.resolution_percentage = 100
            if op.get("frame") is not None:
                s.frame_set(op["frame"])
                if not (cam_id and cam_id != "auto"):
                    markers = [m for m in s.timeline_markers if m.camera and m.frame <= op["frame"]]
                    if markers:
                        s.camera = max(markers, key=lambda m: m.frame).camera
            s.render.filepath = path
            s.render.image_settings.file_format = "PNG"
            bpy.ops.render.render(write_still=True)
        finally:
            (s.render.engine, s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage,
             s.render.filepath, cam0, frame0) = saved
            s.camera = cam0
            s.frame_set(frame0)
            if saved_samples is not None:
                s.cycles.samples = saved_samples
            if temp_cam:
                bpy.data.objects.remove(bpy.data.objects["__auto_cam"], do_unlink=True)
        res["preview"] = path
        st = image_stats(path)
        res.setdefault("data", {})["preview_stats"] = st
        res["data"].setdefault("previews", []).append({"path": path, "stats": st})

    def op_render_final(self, op: dict, res: dict) -> None:
        s = self.scene
        out = op["output_dir"]
        os.makedirs(out, exist_ok=True)
        s.render.filepath = os.path.join(out, "frame_")
        s.render.image_settings.file_format = "PNG"
        s.render.use_file_extension = True
        fs, fe = s.frame_start, s.frame_end
        if op.get("frame_start") is not None:
            s.frame_start = op["frame_start"]
        if op.get("frame_end") is not None:
            s.frame_end = op["frame_end"]
        s.frame_step = op.get("frame_step", 1)
        t0 = time.time()
        try:
            bpy.ops.render.render(animation=True)
        finally:
            s.frame_start, s.frame_end, s.frame_step = fs, fe, 1
        res["data"]["frames_dir"] = out
        res["data"]["render_seconds"] = round(time.time() - t0, 1)

    def op_save(self, op: dict, res: dict) -> None:
        path = os.path.abspath(op["path"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
        res["data"]["saved"] = path

    # ------------------------------------------------------------------ query / inspect
    def op_query(self, op: dict, res: dict) -> None:
        fields = op.get("fields") or ["type", "transform"]
        bpy.context.view_layer.update()  # matrix_world is stale until the depsgraph updates
        out = {}
        for o in bpy.data.objects:
            oid = o.get(ID_PROP, o.name)
            if oid.startswith("__"):
                continue
            if op.get("ids") and oid not in op["ids"]:
                continue
            if op.get("types") and o.type.lower() not in [t.lower() for t in op["types"]]:
                continue
            tags = [t for t in str(o.get(TAGS_PROP, "")).split(",") if t]
            if op.get("tag") and op["tag"] not in tags:
                continue
            out[oid] = describe(o, fields, tags)
            if len(out) >= op.get("limit", 200):
                res["warnings"].append("query truncated at limit")
                break
        s = self.scene
        res["data"]["objects"] = out
        res["data"]["scene"] = {"frame_start": s.frame_start, "frame_end": s.frame_end, "fps": s.render.fps,
                                "camera": s.camera.get(ID_PROP, s.camera.name) if s.camera else None,
                                "markers": sorted([[m.frame, m.camera.name if m.camera else None] for m in s.timeline_markers])}

    def op_inspect(self, op: dict, res: dict) -> None:
        from bpy_extras.object_utils import world_to_camera_view

        s = self.scene
        report = {"frames": {}, "subjects": op["subjects"]}
        floor = op.get("floor_z", 0.0)
        bpy.context.view_layer.update()
        prev_centers: dict[str, mathutils.Vector] = {}
        motion = {sid: 0.0 for sid in op["subjects"]}
        frame0 = s.frame_current
        for f in op["frames"]:
            s.frame_set(f)
            cam = self.obj(op["camera"]) if op.get("camera") else s.camera
            markers = [m for m in s.timeline_markers if m.camera and m.frame <= f]
            if not op.get("camera") and markers:
                cam = max(markers, key=lambda m: m.frame).camera
            fr = {"camera": cam.name if cam else None, "subjects": {}}
            for sid in op["subjects"]:
                o = self.obj(sid)
                pts = hierarchy_bbox_points(o)
                if not pts:
                    continue
                zmin = min(p.z for p in pts)
                center = sum(pts, mathutils.Vector()) / len(pts)
                info = {"min_z": round(zmin - floor, 3), "center": [round(c, 3) for c in center]}
                if cam is not None:
                    ndc = [world_to_camera_view(s, cam, p) for p in pts]
                    xs, ys, zs = [n.x for n in ndc], [n.y for n in ndc], [n.z for n in ndc]
                    info["screen"] = [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]
                    info["behind_camera"] = max(zs) < 0
                    vis_x = max(0.0, min(1.0, max(xs)) - max(0.0, min(xs)))
                    vis_y = max(0.0, min(1.0, max(ys)) - max(0.0, min(ys)))
                    full = max(1e-6, (max(xs) - min(xs)) * (max(ys) - min(ys)))
                    info["visible_fraction"] = round(min(1.0, vis_x * vis_y / full), 3)
                    info["screen_height"] = round(max(ys) - min(ys), 3)
                if sid in prev_centers:
                    motion[sid] += (center - prev_centers[sid]).length
                prev_centers[sid] = center
                fr["subjects"][sid] = info
            if op.get("shape_key_target"):
                t = self.obj(op["shape_key_target"])
                if t.data and t.data.shape_keys:
                    fr["mouth"] = round(sum(kb.value for kb in t.data.shape_keys.key_blocks[1:]), 3)
            report["frames"][str(f)] = fr
        s.frame_set(frame0)
        report["motion"] = {k: round(v, 3) for k, v in motion.items()}
        res["data"]["inspect"] = report
        res["data"].setdefault("inspects", []).append(report)


class ScriptHelpers:
    """Small helper API available as ``ax`` inside script-mode batches."""

    def __init__(self, ex: Executor):
        self._ex = ex

    def obj(self, oid: str):
        return self._ex.obj(oid)

    def run_ops(self, ops: list[dict]) -> dict:
        res = {"created": [], "modified": [], "deleted": [], "warnings": [], "errors": [], "data": {}}
        for op in ops:
            getattr(self._ex, "op_" + op["op"])(op, res)
        return res


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
            pts.extend(cur.matrix_world @ mathutils.Vector(c) for c in cur.bound_box)
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
        d["bbox"] = [[round(min(p[i] for p in pts), 3) for i in range(3)], [round(max(p[i] for p in pts), 3) for i in range(3)]]
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
        return {"mean": round(mean, 3), "black": round(sum(v < 0.02 for v in lum) / len(lum), 3),
                "white": round(sum(v > 0.98 for v in lum) / len(lum), 3)}
    finally:
        bpy.data.images.remove(img)
