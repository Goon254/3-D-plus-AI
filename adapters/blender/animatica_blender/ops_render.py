# SPDX-License-Identifier: GPL-3.0-or-later
"""Render & inspection ops: render settings, previews, final frames, save, query, Critic inspect."""

from __future__ import annotations

import math
import os
import time

import bpy
import mathutils

from . import devices
from .common import (
    ID_PROP,
    TAGS_PROP,
    OpError,
    _eevee_id,
    describe,
    fast_cycles,
    glow_visibility,
    hierarchy_bbox_points,
    image_stats,
    workbench_setup,
)


def facing_degrees(obj, cam) -> float:
    """Yaw (ground-plane) angle between ``obj``'s forward axis (-Y, the rig convention) and the direction
    from ``obj`` to the camera. 0 = looking straight into the lens, 90 = profile, 180 = back to camera."""
    mw = obj.matrix_world
    fwd = mw.to_3x3() @ mathutils.Vector((0.0, -1.0, 0.0))
    to_cam = cam.matrix_world.translation - mw.translation
    a = mathutils.Vector((fwd.x, fwd.y))
    b = mathutils.Vector((to_cam.x, to_cam.y))
    if a.length < 1e-6 or b.length < 1e-6:
        return 0.0
    return math.degrees(a.angle(b))


class RenderOps:
    """Mixin for :class:`Executor` (expects ``self.obj``, ``self.scene``, ``self._new_object``, ``self.workdir``)."""

    _device_request: str | None = None  # last ``set_render.device``; None = $ANIMATICA_RENDER_DEVICE / auto

    def _use_device(self, op: dict, res: dict) -> None:
        """Select the Cycles device for the coming render (op ``device`` > session > env > auto)."""
        label, warnings = devices.configure(self.scene, op.get("device") or self._device_request)
        for w in warnings:
            if w not in res["warnings"]:
                res["warnings"].append(w)
        res.setdefault("data", {})["device"] = label

    def op_set_render(self, op: dict, res: dict) -> None:
        s = self.scene
        eng = op.get("engine")
        if eng:
            s.render.engine = {"workbench": "BLENDER_WORKBENCH", "eevee": _eevee_id(), "cycles": "CYCLES"}[
                eng
            ]
            if eng == "cycles":
                fast_cycles(s)
                try:
                    s.cycles.use_denoising = True
                    s.cycles.denoiser = "OPENIMAGEDENOISE"
                except Exception:  # noqa: BLE001
                    res["warnings"].append("denoiser unavailable")
        if eng:
            workbench_setup(s)
            glow_visibility(s, eng != "workbench")
        if op.get("device"):
            self._device_request = devices.requested_device(op["device"])
        if s.render.engine == "CYCLES" and (eng or op.get("device")):
            self._use_device(op, res)
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

    # ------------------------------------------------------------------ render / io
    def _auto_camera(self):
        cam = self.scene.camera
        if cam is not None:
            return cam, False
        data = bpy.data.cameras.new("__auto_cam")
        cam = bpy.data.objects.new("__auto_cam", data)
        self.scene.collection.objects.link(cam)
        pts = [
            o.matrix_world @ mathutils.Vector(c)
            for o in self.scene.objects
            if o.type == "MESH"
            for c in o.bound_box
        ]
        center = sum(pts, mathutils.Vector()) / max(1, len(pts)) if pts else mathutils.Vector()
        radius = max(((p - center).length for p in pts), default=2.0)
        cam.location = center + mathutils.Vector((1, -1.4, 0.8)).normalized() * radius * 2.4
        self._aim(cam, center)
        return cam, True

    def op_render_preview(self, op: dict, res: dict) -> None:
        s = self.scene
        path = os.path.abspath(
            op.get("path") or os.path.join(self.workdir, "previews", f"{res['batch_id']}.png")
        )
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        saved = (
            s.render.engine,
            s.render.resolution_x,
            s.render.resolution_y,
            s.render.resolution_percentage,
            s.render.filepath,
            s.camera,
            s.frame_current,
        )
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
            s.render.engine = {"workbench": "BLENDER_WORKBENCH", "eevee": _eevee_id(), "cycles": "CYCLES"}[
                eng
            ]
            if eng == "cycles":
                fast_cycles(s)
                s.cycles.samples = int(op.get("samples", 12))
                s.cycles.use_denoising = True
                self._use_device(op, res)
            glow_visibility(s, eng != "workbench")
            if eng == "workbench":
                workbench_setup(s)
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
            (
                s.render.engine,
                s.render.resolution_x,
                s.render.resolution_y,
                s.render.resolution_percentage,
                s.render.filepath,
                cam0,
                frame0,
            ) = saved
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
        # absolute: Blender does not resolve a bare relative render path against the cwd (Windows: no frames)
        out = os.path.abspath(op["output_dir"])
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
        if s.render.engine == "CYCLES":
            self._use_device(op, res)
        t0 = time.time()
        try:
            try:
                bpy.ops.render.render(animation=True)
            except RuntimeError as e:
                if s.render.engine != "CYCLES" or s.cycles.device != "GPU":
                    raise
                # GPU out of memory / kernel failure: finish the film on the CPU rather than fail it
                res["warnings"].append(f"GPU render failed ({str(e)[:160]}); retrying on CPU")
                devices.force_cpu(s)
                res["data"]["device"] = "CPU"
                bpy.ops.render.render(animation=True)
        finally:
            s.frame_start, s.frame_end, s.frame_step = fs, fe, 1
        res["data"]["frames_dir"] = out
        res["data"]["render_seconds"] = round(time.time() - t0, 1)

    def op_save(self, op: dict, res: dict) -> None:
        path = os.path.abspath(op["path"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # artists get the full look: halos hidden for a Workbench render are visible in the saved file
        glow_visibility(self.scene, True)
        bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
        glow_visibility(self.scene, self.scene.render.engine != "BLENDER_WORKBENCH")
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
        res["data"]["scene"] = {
            "frame_start": s.frame_start,
            "frame_end": s.frame_end,
            "fps": s.render.fps,
            "camera": s.camera.get(ID_PROP, s.camera.name) if s.camera else None,
            "markers": sorted([[m.frame, m.camera.name if m.camera else None] for m in s.timeline_markers]),
        }

    @staticmethod
    def _surface_tree(surf, dg):
        from mathutils.bvhtree import BVHTree

        return BVHTree.FromObject(surf.evaluated_get(dg), dg)

    def _seating(self, pairs: list[dict]) -> dict:
        """Per pair, on the deformed (evaluated) meshes: ``eye``: the centre's depth under the skin and the
        share of the diameter that is buried (``embed``; 0.5 = half in); ``skin``: the signed gap from the
        target's closest vertex to the skin (``gap`` <= 0: touching or sunk in) and its size."""
        dg = bpy.context.evaluated_depsgraph_get()
        trees: dict = {}
        out = {}
        for pr in pairs:
            o, surf = self.obj(pr["target"]), self.obj(pr["surface"])
            if surf.name not in trees:
                trees[surf.name] = self._surface_tree(surf, dg)
            tree = trees[surf.name]
            to_s = surf.evaluated_get(dg).matrix_world.inverted()
            oe = o.evaluated_get(dg)
            if pr.get("kind", "eye") == "eye":
                c = to_s @ oe.matrix_world.translation
                loc, nrm, _i, dist = tree.find_nearest(c)
                if loc is None:
                    continue
                depth = dist if (c - loc).dot(nrm) < 0 else -dist  # + = centre under the skin
                r = sum(oe.dimensions) / 6
                out[pr["target"]] = {
                    "depth": round(depth, 5),
                    "radius": round(r, 5),
                    "embed": round(max(0.0, min(1.0, (r + depth) / (2 * r))), 3),
                }
            else:
                me = oe.to_mesh()
                mw = to_s @ oe.matrix_world
                best = None
                step = max(1, len(me.vertices) // 300)
                for v in me.vertices[::step]:
                    p = mw @ v.co
                    loc, nrm, _i, _d = tree.find_nearest(p)
                    if loc is None:
                        continue
                    sd = (p - loc).dot(nrm)
                    best = sd if best is None else min(best, sd)
                size = max(oe.dimensions)
                oe.to_mesh_clear()
                if best is not None:
                    out[pr["target"]] = {"gap": round(best, 5), "size": round(size, 5)}
        return out

    def _swim(self, ids: list[str], ref: dict) -> dict:
        """How far each mesh's texture coordinates moved since the first inspected frame (metres in object
        space; p95 and max over a fixed vertex sample). A material that reads ``rest_position`` is pinned to
        the rest pose; Object coordinates follow the deformed surface and slide through the pattern."""
        dg = bpy.context.evaluated_depsgraph_get()
        out = {}
        for oid in ids:
            o = self.obj(oid)
            oe = o.evaluated_get(dg)
            me = oe.to_mesh()
            mats = [m for m in o.data.materials if m is not None]
            rest = bool(mats) and all(
                m.node_tree is not None and "animatica_rest_coords" in m.node_tree.nodes for m in mats
            )
            att = me.attributes.get("rest_position") if rest else None
            n = len(me.vertices)
            idx = range(0, n, max(1, n // 400))
            if att is not None:
                co = [att.data[i].vector.copy() for i in idx]
            else:
                co = [me.vertices[i].co.copy() for i in idx]
            oe.to_mesh_clear()
            if oid not in ref:
                ref[oid] = co
            d = sorted((a - b).length for a, b in zip(co, ref[oid]))
            if d:
                out[oid] = {
                    "p95": round(d[int(0.95 * (len(d) - 1))], 5),
                    "max": round(d[-1], 5),
                    "rest": att is not None,
                }
        return out

    def op_inspect(self, op: dict, res: dict) -> None:
        from bpy_extras.object_utils import world_to_camera_view

        s = self.scene
        report = {"frames": {}, "subjects": op["subjects"]}
        floor = op.get("floor_z", 0.0)
        bpy.context.view_layer.update()
        prev_centers: dict[str, mathutils.Vector] = {}
        motion = {sid: 0.0 for sid in op["subjects"]}
        swim_ref: dict = {}  # texture coordinates at the first inspected frame, per mesh
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
                    info["screen"] = [
                        round(min(xs), 3),
                        round(min(ys), 3),
                        round(max(xs), 3),
                        round(max(ys), 3),
                    ]
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
            if op.get("bone_tails"):
                tails = {}
                for ref in op["bone_tails"]:
                    aid, _, bname = ref.partition(":")
                    arm = self.obj(aid)
                    pb = arm.pose.bones.get(bname)
                    if pb is None:
                        raise OpError(f"{aid!r} has no bone {bname!r}")
                    tails[ref] = [round(v, 4) for v in (arm.matrix_world @ pb.tail)]
                fr["bone_tails"] = tails
            if op.get("facing_target") and cam is not None:
                fr["facing_deg"] = round(facing_degrees(self.obj(op["facing_target"]), cam), 1)
            if op.get("seating"):
                fr["seating"] = self._seating(op["seating"])
            if op.get("swim"):
                fr["swim"] = self._swim(op["swim"], swim_ref)
            if op.get("shape_key_target"):
                t = self.obj(op["shape_key_target"])
                if t.data and t.data.shape_keys:
                    fr["mouth"] = round(sum(kb.value for kb in t.data.shape_keys.key_blocks[1:]), 3)
            report["frames"][str(f)] = fr
        s.frame_set(frame0)
        report["motion"] = {k: round(v, 3) for k, v in motion.items()}
        res["data"]["inspect"] = report
        res["data"].setdefault("inspects", []).append(report)
