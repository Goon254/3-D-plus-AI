"""Species body plan -> batched ops: meshes, armature (spine, IK legs, neck/tail/trunk chains, head,
ears), foot IK targets with knee poles, coat materials.

Every part is created in root space as a child of ``<cid>_root``, then bound to its bone. The binds keep
local transforms, so the scene model stays exact. Foot targets are world-space empties: the locomotion
planner keys them, and the leg IK reaches them, so a planted foot is exactly where the planner put it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from .eyes import EMBED_DEPTH, IRIS_AT, eye_frame, lid_mesh, look_rotation
from .gait import FootSpot
from .organic import body_graph, head_elements, metaball_elements, tail_points
from .species import EYE_WHITE, GLINT, IRIS, Chain, Species

V3 = tuple[float, float, float]
LEG_KEYS = ("LF", "RF", "LH", "RH")


def _add(a: V3, b: V3) -> V3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: V3, b: V3) -> V3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a: V3, k: float) -> V3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _len(a: V3) -> float:
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def _rx(v: V3, deg: float) -> V3:
    """Rotate about +X (positive tips -Y forward vectors downward: a nose-down head pitch)."""
    a = math.radians(deg)
    return (v[0], v[1] * math.cos(a) - v[2] * math.sin(a), v[1] * math.sin(a) + v[2] * math.cos(a))


def _r(v: V3, n: int = 4) -> list[float]:
    return [round(c, n) for c in v]


def align_z(direction: V3) -> list[float]:
    """Euler XYZ (degrees) turning local +Z onto ``direction``: Ry(phi) Rx(theta) z = d."""
    d = _scale(direction, 1 / max(_len(direction), 1e-9))
    theta = math.asin(max(-1.0, min(1.0, -d[1])))
    phi = math.atan2(d[0], d[2])
    return [round(math.degrees(theta), 3), round(math.degrees(phi), 3), 0.0]


def capsule(r0: float, r1: float, length: float, seg: int = 20, cap: int = 5, body: int = 6):
    """Tapered capsule along local +Z from 0 to ``length`` (rounded ends). Returns (verts, faces)."""
    prof: list[tuple[float, float]] = []
    for i in range(1, cap + 1):
        a = -math.pi / 2 + math.pi / 2 * i / cap
        prof.append((r0 * math.sin(a), r0 * math.cos(a)))
    for j in range(1, body):
        u = j / body
        prof.append((length * u, r0 + (r1 - r0) * u))
    for i in range(0, cap):
        a = math.pi / 2 * i / cap
        prof.append((length + r1 * math.sin(a), r1 * math.cos(a)))
    verts: list[list[float]] = [[0.0, 0.0, -r0]]
    for z, rr in prof:
        for k in range(seg):
            t = 2 * math.pi * k / seg
            verts.append([round(rr * math.cos(t), 5), round(rr * math.sin(t), 5), round(z, 5)])
    verts.append([0.0, 0.0, length + r1])
    faces: list[list[int]] = []
    nr = len(prof)
    for k in range(seg):
        faces.append([0, 1 + (k + 1) % seg, 1 + k])
    for i in range(nr - 1):
        a, b = 1 + i * seg, 1 + (i + 1) * seg
        for k in range(seg):
            k2 = (k + 1) % seg
            faces.append([a + k, a + k2, b + k2, b + k])
    top = len(verts) - 1
    last = 1 + (nr - 1) * seg
    for k in range(seg):
        faces.append([last + k, last + (k + 1) % seg, top])
    return verts, faces


@dataclass
class CreatureMeta:
    cid: str
    species: str
    root: str
    rig: str
    body_z: float
    foot_z: float
    leg: float  # fore-leg chain length (gait scaling)
    feet: dict[str, FootSpot]
    ik_targets: dict[str, str]
    neck_bones: list[str]
    tail_bones: list[str]
    trunk_bones: list[str] = field(default_factory=list)
    ear_bones: list[str] = field(default_factory=list)
    eyes: list[str] = field(default_factory=list)
    lids: list[str] = field(default_factory=list)  # <cid>_lid_<L|R>_<up|lo>: shape keys blink/droop/wide
    head_surface: str = ""  # the mesh the eyes are socketed in (and the brows sit on)
    head_height: float = 0.0  # world height of the head centre at rest (camera framing)
    reach_slack: float = 0.0  # how far the shortest-reaching leg can swing horizontally from rest height
    joints: dict[str, tuple[float, float, float, float]] = field(
        default_factory=dict
    )  # leg -> x, y, z, chain
    length: float = 0.0  # nose-to-tail length (camera framing)


LID_COLOR = {  # the skin around the eye: a touch darker than the coat (the zebra's and meerkat's are dark)
    "elephant": "#6E6862",
    "giraffe": "#7E5432",
    "zebra": "#4A4440",
    "meerkat": "#4A3624",
    "tortoise": "#6F604A",
}


def lid_material(sp: Species) -> dict[str, Any]:
    color = LID_COLOR.get(sp.name) or sp.coat.get("base_color", "#777777")
    return {"base_color": color, "roughness": 0.7, "sheen": 0.15}


def eye_patch_marks(sp: Species) -> dict[str, Any]:
    """``marks`` for the coat: a soft teardrop round each eye, reaching back and a little down (meerkat)."""
    if not sp.eye_patch:
        return {}
    color, strength = sp.eye_patch
    marks = []
    for sx in (1, -1):
        fr = eye_frame(sp, sx)
        er = fr.radius
        back = _rx((0.0, 0.35 * er, -0.15 * er), sp.head_pitch)
        marks.append(
            {
                "at": _r(_add(fr.centre, back), 5),
                "radii": _r((er * 1.35, er * 1.75, er * 1.25), 5),
                "color": color,
                "soft": 0.55,
                "strength": strength,
            }
        )
    return {"marks": marks}


def build_creature(
    cid: str,
    sp: Species,
    at: tuple[float, float] = (0.0, 0.0),
    yaw: float = 90.0,
    organic: bool = True,
    body_style: str = "metaball",
):
    """Ops that build creature ``cid`` of species ``sp`` standing at ``at`` heading ``yaw`` degrees."""
    root, rig = f"{cid}_root", f"{cid}_rig"
    ops: list[dict[str, Any]] = [
        {
            "op": "create_empty",
            "id": root,
            "location": [at[0], at[1], sp.body_z],
            "rotation": [0, 0, yaw],
            "tags": ["creature", cid],
        }
    ]
    L = sp.torso[1]
    bones: list[dict[str, Any]] = [
        {"name": "hips", "head": [0, L * 0.3, 0], "tail": [0, 0, 0]},
        {"name": "chest", "head": [0, 0, 0], "tail": [0, -L * 0.3, 0], "parent": "hips"},
    ]
    meshes: list[tuple[dict[str, Any], str, str | list[str]]] = []  # (create op, material key, bone(s))
    foot_h = sp.foot[2]
    foot_z_root = -sp.body_z + foot_h
    feet: dict[str, FootSpot] = {}
    poles: list[tuple[str, V3]] = []
    leg_len = 0.0
    slack = 1e9
    leg_pts: dict[str, tuple[V3, V3, V3]] = {}
    joints: dict[str, tuple[float, float, float, float]] = {}
    for key in LEG_KEYS:
        side = 1 if key[0] == "L" else -1
        fore = key[1] == "F"
        jx, jy, jz = sp.shoulder if fore else sp.hip
        fx, fy = sp.fore_foot if fore else sp.hind_foot
        J: V3 = (jx * side, jy, jz)
        F: V3 = (fx * side, fy, foot_z_root)
        d = _len(_sub(F, J))
        bend = sp.knee_bend * d
        # fore: the carpus protrudes forward when the leg folds; hind: the hock points backward
        mid = _add(J, _scale(_sub(F, J), 0.5))
        K: V3 = _add(mid, (0.0, -bend if fore else bend, 0.0))
        if abs(F[0] - J[0]) > 0.02:  # splayed (tortoise forelegs): the elbow also goes outward
            K = _add(K, (0.35 * bend * side, 0.0, 0.0))
        up, lo = f"leg_{key}_up", f"leg_{key}_lo"
        bones += [
            {"name": up, "head": _r(J), "tail": _r(K), "parent": "chest" if fore else "hips"},
            {"name": lo, "head": _r(K), "tail": _r(F), "parent": up},
        ]
        chain_len = _len(_sub(K, J)) + _len(_sub(F, K))
        joints[key] = (J[0], J[1], J[2], chain_len)
        if fore:
            leg_len = chain_len
        # horizontal reach left at rest height, keeping 5 % of the chain bent (IK never locks straight) and
        # budgeting for the hip rising with pitch/roll/breathing (2 % of the leg)
        h = (J[2] - F[2]) + 0.02 * chain_len
        slack = min(slack, math.sqrt(max((0.95 * chain_len) ** 2 - h**2, 1e-6)))
        feet[key] = FootSpot(F[0], F[1])
        ru, rl = (sp.leg_r[0], sp.leg_r[1]) if fore else (sp.leg_r[2], sp.leg_r[3])
        leg_pts[key] = (J, K, F)
        for part, a, b, r0, r1, bone in (
            ()
            if organic
            else (
                ("up", J, K, ru, (ru + rl) / 2, up),
                ("lo", K, F, rl, rl * 0.85, lo),
            )
        ):
            v, f = capsule(r0, r1, _len(_sub(b, a)))
            meshes.append(
                (
                    {
                        "op": "create_mesh",
                        "id": f"{cid}_leg_{key}_{part}",
                        "vertices": v,
                        "faces": f,
                        "location": _r(a),
                        "rotation": align_z(_sub(b, a)),
                        "smooth": True,
                    },
                    "leg",
                    bone,
                )
            )
        shape, fr, fh = sp.foot
        if organic and shape != "hoof":
            # skin-grown foot; elephants and tortoises get toenails/claws on the front of it
            for t in range(sp.nails):
                u = (t - (sp.nails - 1) / 2) / max(1, sp.nails - 1)
                ang = u * 1.1
                nail_c = (
                    F[0] + math.sin(ang) * fr * 0.85,
                    F[1] - math.cos(ang) * fr * 0.85,
                    F[2] - fh * 0.55,
                )
                meshes.append(
                    (
                        {
                            "op": "create_primitive",
                            "id": f"{cid}_nail_{key}_{t}",
                            "shape": "uv_sphere",
                            "size": [fr * 0.42, fr * 0.26, fh * 0.55],
                            "location": _r(nail_c),
                            "rotation": [0, 0, round(-math.degrees(ang) * side, 2)],
                            "smooth": True,
                            "segments": 16,
                        },
                        "nail",
                        lo,
                    )
                )
            poles.append((key, _add(K, (0.0, -d if fore else d, 0.0))))
            continue
        foot_op: dict[str, Any] = {
            "op": "create_primitive",
            "id": f"{cid}_foot_{key}",
            "shape": "cylinder" if shape != "paw" else "uv_sphere",
            "location": _r(_add(F, (0.0, -fr * 0.15, -fh / 2))),
            "smooth": True,
            "segments": 24,
        }
        foot_op["size"] = [fr * 2, fr * 2.1, fh] if shape != "paw" else [fr * 2, fr * 3, fh * 1.6]
        meshes.append((foot_op, "foot", lo))
        poles.append((key, _add(K, (0.0, -d if fore else d, 0.0))))

    def chain(prefix: str, ch: Chain, parent: str) -> list[str]:
        names = []
        step = _scale(_sub(ch.tip, ch.base), 1 / ch.bones)
        for i in range(ch.bones):
            a = _add(ch.base, _scale(step, i))
            names.append(f"{prefix}_{i}")
            bones.append(
                {
                    "name": names[-1],
                    "head": _r(a),
                    "tail": _r(_add(a, step)),
                    "parent": names[-2] if i else parent,
                }
            )
        return names

    neck_bones = chain("neck", sp.neck, "chest")
    # the head bone runs from the top of the neck through the head centre
    head_dir = _sub(sp.head_at, sp.neck.tip)
    if _len(head_dir) < 0.02:
        head_dir = (0.0, -0.05, 0.0)
    bones.append(
        {
            "name": "head",
            "head": _r(sp.neck.tip),
            "tail": _r(_add(sp.head_at, _scale(head_dir, 0.3))),
            "parent": neck_bones[-1],
        }
    )
    if organic:
        # the organic rump is fuller than the old primitive: start the tail on its surface, not inside it
        W, L, D = sp.torso
        rump_y = sp.torso_at[1] + 0.45 * L + max(W / 2 * 0.62, D / 2 * 0.66) * (0.35 if sp.shell else 0.85)
        dy = max(0.0, rump_y - sp.tail.base[1])
        if dy:
            sp = replace(
                sp,
                tail=Chain(
                    _add(sp.tail.base, (0.0, dy, 0.0)),
                    _add(sp.tail.tip, (0.0, dy, 0.0)),
                    sp.tail.bones,
                    sp.tail.r0,
                    sp.tail.r1,
                ),
            )
    tail_bones = chain("tail", sp.tail, "hips")
    trunk_bones = chain("trunk", sp.trunk, "head") if sp.trunk else []

    def head_pt(off: V3) -> V3:
        return _add(sp.head_at, _rx(off, sp.head_pitch))

    ear_bones: list[str] = []
    eyes: list[str] = []
    all_lids: list[str] = []
    sockets: list[dict[str, Any]] = []  # eyes sink into the real skin once it exists (after the meshes)
    head_surface = f"{cid}_head" if (sp.separate_head or not organic) else f"{cid}_body"
    for side, sx in (("L", 1), ("R", -1)):
        fr = eye_frame(sp, sx)
        er = fr.radius
        eye_c = fr.centre
        iris_c = _add(eye_c, _scale(fr.look, er * IRIS_AT))
        glint_c = _add(_add(eye_c, _scale(fr.look, er * 0.93)), _scale(fr.up, 0.3 * er))
        rot = look_rotation(fr.look)
        for pid, c, size, mkey in (
            (f"{cid}_eye_{side}", eye_c, (er * 2, er * 2, er * 2), "eye_white"),
            (f"{cid}_iris_{side}", iris_c, (er * 1.2, er * 0.48, er * 1.25), "iris"),
            (f"{cid}_glint_{side}", glint_c, (er * 0.3, er * 0.16, er * 0.3), "glint"),
        ):
            meshes.append(
                (
                    {
                        "op": "create_primitive",
                        "id": pid,
                        "shape": "uv_sphere",
                        "size": _r(size, 5),
                        "location": _r(c, 5),
                        "rotation": rot,
                        "smooth": True,
                        "segments": 24,
                    },
                    mkey,
                    "head",
                )
            )
        lids = []
        for part, upper in (("up", True), ("lo", False)):
            lv, lf, lk = lid_mesh(er, fr, upper)
            lid = f"{cid}_lid_{side}_{part}"
            meshes.append(
                (
                    {
                        "op": "create_mesh",
                        "id": lid,
                        "vertices": lv,
                        "faces": lf,
                        "location": _r(eye_c, 5),
                        "smooth": True,
                        "shape_keys": lk,
                    },
                    "lid",
                    "head",
                )
            )
            lids.append(lid)
        all_lids += lids
        sockets.append(
            {
                "op": "snap_to_surface",
                "target": f"{cid}_eye_{side}",
                "surface": head_surface,
                "direction": _r(fr.socket, 5),
                "offset": round(-EMBED_DEPTH * er, 5),
                "reach": round(max(6 * er, 0.05), 4),
                "carry": [f"{cid}_iris_{side}", f"{cid}_glint_{side}", *lids],
            }
        )
        eyes.append(f"{cid}_eye_{side}")
        shape, esize, eoff, erot = sp.ear
        if shape != "none":
            base = head_pt((eoff[0] * sx, eoff[1], eoff[2]))
            name = f"ear_{side}"
            bones.append(
                {
                    "name": name,
                    "head": _r(base),
                    "tail": _r(_add(base, (0.0, 0.0, max(esize) * 0.6))),
                    "parent": "head",
                }
            )
            ear_bones.append(name)
            center = _add(base, (sx * esize[0] * 0.3, esize[1] * 0.25, esize[2] * 0.35))
            meshes.append(
                (
                    {
                        "op": "create_primitive",
                        "id": f"{cid}_ear_{side}",
                        "shape": "uv_sphere",
                        "size": list(esize),
                        "location": _r(center),
                        "rotation": [erot[0], erot[1] * sx, erot[2] * sx],
                        "smooth": True,
                        "segments": 24,
                    },
                    "coat",
                    name,
                )
            )

    # body, neck, head
    meshes_before = len(meshes)
    meshes.append(
        (
            {
                "op": "create_primitive",
                "id": f"{cid}_torso",
                "shape": "uv_sphere",
                "size": list(sp.torso),
                "location": list(sp.torso_at),
                "rotation": [-sp.torso_rot, 0, 0],
                "smooth": True,
                "segments": 48,
            },
            "torso",
            ["hips", "chest"],
        )
    )
    v, f = capsule(sp.neck.r0, sp.neck.r1, _len(_sub(sp.neck.tip, sp.neck.base)))
    meshes.append(
        (
            {
                "op": "create_mesh",
                "id": f"{cid}_neck",
                "vertices": v,
                "faces": f,
                "location": list(sp.neck.base),
                "rotation": align_z(_sub(sp.neck.tip, sp.neck.base)),
                "smooth": True,
            },
            "neck",
            neck_bones if len(neck_bones) > 1 else neck_bones[0],
        )
    )
    meshes.append(
        (
            {
                "op": "create_primitive",
                "id": f"{cid}_head",
                "shape": "uv_sphere",
                "size": list(sp.head_size),
                "location": list(sp.head_at),
                "rotation": [sp.head_pitch, 0, 0],
                "smooth": True,
                "segments": 40,
            },
            "head",
            "head",
        )
    )
    if organic:  # the skin-modifier body replaces the torso/neck/head primitives
        del meshes[meshes_before:]
    if sp.muzzle:
        msize, moff = sp.muzzle
        meshes.append(
            (
                {
                    "op": "create_primitive",
                    "id": f"{cid}_muzzle",
                    "shape": "uv_sphere",
                    "size": list(msize),
                    "location": _r(head_pt(moff)),
                    "rotation": [sp.head_pitch, 0, 0],
                    "smooth": True,
                    "segments": 32,
                },
                "muzzle" if "muzzle" in sp.mats else "coat",
                "head",
            )
        )
    v, f = capsule(sp.tail.r0, sp.tail.r1, _len(_sub(sp.tail.tip, sp.tail.base)), seg=12)
    tail_at = len(meshes)
    meshes.append(
        (
            {
                "op": "create_mesh",
                "id": f"{cid}_tail",
                "vertices": v,
                "faces": f,
                "location": list(sp.tail.base),
                "rotation": align_z(_sub(sp.tail.tip, sp.tail.base)),
                "smooth": True,
            },
            "tail",
            tail_bones if len(tail_bones) > 1 else tail_bones[0],
        )
    )
    if organic:
        del meshes[tail_at:]
    if sp.tuft:
        meshes.append(
            (
                {
                    "op": "create_primitive",
                    "id": f"{cid}_tuft",
                    "shape": "uv_sphere",
                    "size": [sp.tuft * 1.6, sp.tuft * 1.6, sp.tuft * 2.6],
                    "location": _r(sp.tail.tip),
                    "rotation": align_z(_sub(sp.tail.tip, sp.tail.base)),
                    "smooth": True,
                    "segments": 16,
                },
                "tuft",
                tail_bones[-1],
            )
        )
    if sp.trunk and not organic:
        v, f = capsule(sp.trunk.r0, sp.trunk.r1, _len(_sub(sp.trunk.tip, sp.trunk.base)), seg=18, body=10)
        meshes.append(
            (
                {
                    "op": "create_mesh",
                    "id": f"{cid}_trunk",
                    "vertices": v,
                    "faces": f,
                    "location": list(sp.trunk.base),
                    "rotation": align_z(_sub(sp.trunk.tip, sp.trunk.base)),
                    "smooth": True,
                },
                "coat",
                trunk_bones,
            )
        )
    bone_heads = {b["name"]: tuple(b["head"]) for b in bones}
    for ex in sp.extras:
        base = sp.head_at if ex.bone == "head" else bone_heads[ex.bone]
        off = _rx(ex.loc, sp.head_pitch) if ex.bone == "head" else ex.loc
        rot = [ex.rot[0] + (sp.head_pitch if ex.bone == "head" else 0), ex.rot[1], ex.rot[2]]
        op = {
            "op": "create_primitive",
            "id": f"{cid}_{ex.id}",
            "shape": ex.shape,
            "size": list(ex.size),
            "location": _r(_add(base, off)),
            "rotation": rot,
            "smooth": True,
            "segments": 24,
        }
        meshes.append((op, ex.mat, ex.bone))

    ops.append(
        {"op": "create_armature", "id": rig, "parent": root, "bones": bones, "tags": ["creature", cid, "rig"]}
    )
    if organic:
        body = f"{cid}_body"
        if body_style == "metaball":
            g = body_graph(sp, leg_pts, shell=sp.shell is not None, include_tail=False)
            els, res_m = metaball_elements(g)
            ops.append(
                {
                    "op": "create_metaball_mesh",
                    "id": body,
                    "elements": els,
                    "resolution": res_m,
                    "parent": root,
                    "tags": ["creature", cid],
                }
            )
            if sp.separate_head:
                # the head is its own sculpted mass on the head bone; the trunk its own tube on the trunk chain
                hels, hres = head_elements(sp)
                trunk_pts = (
                    [
                        (
                            _add(sp.trunk.base, _scale(_sub(sp.trunk.tip, sp.trunk.base), u)),
                            sp.trunk.r0 + (sp.trunk.r1 - sp.trunk.r0) * u,
                        )
                        for u in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
                    ]
                    if sp.trunk
                    else []
                )
                ops += [
                    {
                        "op": "create_metaball_mesh",
                        "id": f"{cid}_head",
                        "elements": hels,
                        "resolution": hres,
                        "parent": root,
                        "tags": ["creature", cid],
                    },
                    {"op": "bind_mesh_to_armature", "mesh": f"{cid}_head", "armature": rig, "bone": "head"},
                    {
                        "op": "set_material",
                        "targets": [f"{cid}_head"],
                        "material": {**sp.coat, **eye_patch_marks(sp), "name": f"{cid}_coat_head"},
                    },
                ]
                if trunk_pts:
                    ops += [
                        {
                            "op": "create_skin_mesh",
                            "id": f"{cid}_trunk",
                            "vertices": [list(p) for p, _ in trunk_pts],
                            "edges": [[i, i + 1] for i in range(len(trunk_pts) - 1)],
                            "radii": [[r, r] for _, r in trunk_pts],
                            "subdivisions": 2,
                            "parent": root,
                            "tags": ["creature", cid],
                        },
                        {
                            "op": "bind_mesh_to_armature",
                            "mesh": f"{cid}_trunk",
                            "armature": rig,
                            "bones": trunk_bones,
                        },
                        {
                            "op": "set_material",
                            "targets": [f"{cid}_trunk"],
                            "material": {**sp.coat, "name": f"{cid}_coat_trunk"},
                        },
                    ]
            # the thin tail is a skin-modifier tube on its own chain (too thin for the body's resolution)
            tp = tail_points(sp)
            ops += [
                {
                    "op": "create_skin_mesh",
                    "id": f"{cid}_tail",
                    "vertices": [list(p) for p, _ in tp],
                    "edges": [[i, i + 1] for i in range(len(tp) - 1)],
                    "radii": [[r, r] for _, r in tp],
                    "subdivisions": 2,
                    "parent": root,
                    "tags": ["creature", cid],
                },
                {
                    "op": "bind_mesh_to_armature",
                    "mesh": f"{cid}_tail",
                    "armature": rig,
                    **({"bones": tail_bones} if len(tail_bones) > 1 else {"bone": tail_bones[0]}),
                },
                {
                    "op": "set_material",
                    "targets": [f"{cid}_tail"],
                    "material": {
                        **sp.mats.get(sp.part_mats.get("tail", "tail"), sp.coat),
                        "name": f"{cid}_tailskin",
                    },
                },
            ]
        else:
            g = body_graph(sp, leg_pts, shell=sp.shell is not None)
            ops.append(
                {
                    "op": "create_skin_mesh",
                    "id": body,
                    "vertices": g.verts,
                    "edges": g.edges,
                    "radii": g.radii,
                    "subdivisions": 2,
                    "parent": root,
                    "tags": ["creature", cid],
                }
            )
        ops += [
            {
                "op": "bind_mesh_to_armature",
                "mesh": body,
                "armature": rig,
                "auto": True,
                # separate meshes ride these: they must not tear the body (a swishing tail ripped the rump)
                "exclude": ["ear_"]
                + (["tail_"] if body_style == "metaball" else [])
                + (["head", "trunk_"] if sp.separate_head else []),
                # the skull is rigid: the head's skin follows the head bone alone (blending into the neck
                # over the outer shell), so the eyes, lids and brows on that bone stay in their sockets
                "rigid": []
                if sp.separate_head
                else [
                    {
                        "bone": "head",
                        "center": _r(sp.head_at),
                        "radii": _r(_scale(sp.head_size, 0.62)),
                        "pitch": sp.head_pitch,
                        "falloff": 0.4,
                    }
                ],
            },
            {
                "op": "set_material_by_bone",
                "target": body,
                "default": {**sp.coat, "name": f"{cid}_coat", **eye_patch_marks(sp)},
                "rules": [
                    {"bones": list(prefixes), "material": {**sp.mats[key], "name": f"{cid}_{key}"}}
                    for prefixes, key in sp.regions
                ],
            },
        ]
        if sp.shell is not None:
            ssize, sat = sp.shell
            meshes.append(
                (
                    {
                        "op": "create_primitive",
                        "id": f"{cid}_shell",
                        "shape": "uv_sphere",
                        "size": list(ssize),
                        "location": list(sat),
                        "smooth": True,
                        "segments": 64,
                    },
                    "shell",
                    "chest",
                )
            )
    # meshes, parented to the root (root space), then bound to their bones
    mat_groups: dict[str, list[str]] = {}
    for op, mkey, bone in meshes:
        op["parent"] = root
        op.setdefault("tags", ["creature", cid])
        keys = op.pop("shape_keys", None)
        ops.append(op)
        if keys:
            ops.append({"op": "add_shape_keys", "target": op["id"], "keys": keys})
        bind: dict[str, Any] = {"op": "bind_mesh_to_armature", "mesh": op["id"], "armature": rig}
        if isinstance(bone, list):
            bind["bones"] = bone
        else:
            bind["bone"] = bone
        ops.append(bind)
        mat_groups.setdefault(mkey, []).append(op["id"])
    for mkey, ids in mat_groups.items():
        key = sp.part_mats.get(mkey, mkey)
        if key in ("eye_white", "iris", "glint"):
            spec = {"eye_white": EYE_WHITE, "iris": IRIS, "glint": GLINT}[key]
        elif key == "lid":
            spec = lid_material(sp)
        elif key in sp.mats:
            spec = sp.mats[key]
        else:
            spec = {**sp.coat, **eye_patch_marks(sp)}  # same spec as the body: they share a name
        ops.append({"op": "set_material", "targets": ids, "material": {**spec, "name": f"{cid}_{key}"}})
    ops += sockets

    # leg IK: world-space foot targets (keyed by the locomotion planner) and knee poles that ride the body
    ik_targets: dict[str, str] = {}
    a = math.radians(yaw)

    def world(p: V3) -> list[float]:
        x, y = p[0] * math.cos(a) - p[1] * math.sin(a), p[0] * math.sin(a) + p[1] * math.cos(a)
        return _r((at[0] + x, at[1] + y, sp.body_z + p[2]))

    for key, pole_at in poles:
        tgt, pole = f"{cid}_ik_{key}", f"{cid}_pole_{key}"
        F = (feet[key].x, feet[key].y, foot_z_root)
        ops += [
            {"op": "create_empty", "id": tgt, "location": world(F), "tags": ["creature", cid, "ik"]},
            {
                "op": "create_empty",
                "id": pole,
                "location": _r(pole_at),
                "parent": root,
                "tags": ["creature", cid],
            },
            {
                "op": "add_bone_constraint",
                "armature": rig,
                "bone": f"leg_{key}_lo",
                "type": "ik",
                "subject": tgt,
                "pole": pole,
                # twist-free: a pole in front needs -90 deg, a pole behind needs +90 (measured); the wrong
                # sign spins the leg 180 deg about its own axis and drags the skinned rump with it
                "pole_angle": -90.0 if key[1] == "F" else 90.0,
            },
        ]
        ik_targets[key] = tgt
    nose = min(sp.head_at[1] - sp.head_size[1] / 2, (sp.trunk.tip[1] if sp.trunk else 0.0))
    meta = CreatureMeta(
        cid=cid,
        species=sp.name,
        root=root,
        rig=rig,
        body_z=sp.body_z,
        foot_z=foot_h,
        leg=leg_len,
        feet=feet,
        ik_targets=ik_targets,
        neck_bones=neck_bones,
        tail_bones=tail_bones,
        trunk_bones=trunk_bones,
        ear_bones=ear_bones,
        eyes=eyes,
        lids=all_lids,
        head_surface=head_surface,
        head_height=sp.body_z + sp.head_at[2],
        reach_slack=slack,
        joints=joints,
        length=max(sp.tail.tip[1], sp.torso[1] / 2) - nose,
    )
    return ops, meta
