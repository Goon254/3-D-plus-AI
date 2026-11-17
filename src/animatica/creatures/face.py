"""Faces for dialogue: a mouth with lip-sync and expression shape keys, and brows that act.

* Mouth: a flat ellipse on the front of the muzzle (or under the elephant's trunk, or on the tortoise's
  beak), facing along the head's pitch. Shape keys: ``open``/``wide``/``round`` (Rhubarb visemes via
  :func:`animatica.audio.lipsync.cues_to_keyframes`), plus ``smile``/``frown`` (the corners curl up or down).
* Brows: two soft capsules above the eyes, rigid on the head bone and seated in the skin: the centre sits a
  little under the surface and a shrinkwrap (keep outside, evaluated every frame on the deformed skin) lays
  the underside on it, so they never float. They rise, fall and tilt (inner end up = sad/worried, inner end
  down = determined), sliding along the brow ridge rather than lifting off it.
* Lids (built with the eyes, :mod:`animatica.creatures.eyes`): the expression sets how heavy (``droop``) or
  wide open (``wide``) the upper lids are; blinks are layered on top by the idle.
* Expressions: a track of ``(seconds, emotion)``. Each emotion sets brow height and tilt, lids, smile/frown;
  :func:`face_keys` eases between them over 0.3 s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..audio.lipsync import Cue, cues_to_keyframes
from .species import Species

V3 = tuple[float, float, float]


@dataclass(frozen=True)
class Expression:
    brow_up: float  # brow lift in eye radii
    brow_tilt: float  # degrees; + = inner end up (sad, worried), - = inner end down (determined)
    smile: float  # 0..1 (frown when negative)
    asym: float = 0.0  # extra lift of the left brow (curious: one brow up)
    lid: float = 0.0  # upper lids: + heavier (droop), - wider open


BROW_COLOR = {  # a shade darker than the coat around the eyes
    "elephant": "#5F5A55",
    "giraffe": "#7A4422",
    "zebra": "#161414",
    "meerkat": "#24180F",
    "tortoise": "#6A5840",
}

EXPRESSIONS: dict[str, Expression] = {
    "neutral": Expression(0.0, 0.0, 0.1),
    "happy": Expression(0.18, -4.0, 0.85, lid=0.12),
    "sad": Expression(0.05, 20.0, -0.6, lid=0.55),
    "surprised": Expression(0.5, 4.0, 0.0, lid=-0.85),
    "worried": Expression(0.22, 15.0, -0.3, lid=-0.2),
    "determined": Expression(-0.16, -16.0, 0.15, lid=0.4),
    "curious": Expression(0.12, 6.0, 0.25, asym=0.3, lid=-0.25),
    "scared": Expression(0.42, 18.0, -0.45, lid=-0.9),
    "proud": Expression(0.08, -8.0, 0.6, lid=0.3),
}


def _rx(v: V3, deg: float) -> V3:
    a = math.radians(deg)
    return (v[0], v[1] * math.cos(a) - v[2] * math.sin(a), v[1] * math.sin(a) + v[2] * math.cos(a))


def _add(a: V3, b: V3) -> V3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mouth_place(sp: Species) -> tuple[V3, float]:
    """(centre in root space, half width) of the mouth for ``sp``."""
    hw, hl, hh = sp.head_size

    def hp(off: V3) -> V3:
        return _add(sp.head_at, _rx(off, sp.head_pitch))

    if sp.muzzle:  # on the front of the muzzle, a little below its middle
        (mx, my, mz), moff = sp.muzzle
        return hp((moff[0], moff[1] - my * 0.46, moff[2] - mz * 0.18)), mx * 0.32
    if sp.trunk:  # an elephant's mouth sits under the base of the trunk
        # wide enough that the smile's corners show either side of the trunk (the cartoon convention)
        return hp((0.0, -hl * 0.36, -hh * 0.3)), hw * 0.21
    return hp((0.0, -hl * 0.4, -hh * 0.3)), hw * 0.34  # across the bottom of the beak (not the tip: a nose)


def mouth_mesh(half_w: float, n: int = 24) -> tuple[list, list, dict[str, list]]:
    """An ellipse fan in the XZ plane (facing -Y) with lip-sync and expression shape keys."""
    hh = half_w * 0.16

    def ring(hw: float, h: float, corner: float = 0.0, pinch: float = 0.0) -> list[list[float]]:
        pts = [[0.0, 0.0, round(corner * 0.3, 5)]]
        for i in range(n):
            a = 2 * math.pi * i / n
            x, z = hw * math.cos(a), h * math.sin(a)
            if pinch and z > 0:  # flatter top lip when open: a friendlier "D"
                z *= 1 - pinch
            z += corner * (x / hw) ** 2  # corners curl up (smile) or down (frown)
            pts.append([round(x, 5), 0.0, round(z, 5)])
        return pts

    verts = ring(half_w, hh)
    faces = [[0, 1 + i, 1 + (i + 1) % n] for i in range(n)]
    keys = {
        "open": ring(half_w * 0.98, hh * 6.5, pinch=0.3),  # keeps its width: corners stay readable
        "wide": ring(half_w * 1.3, hh * 2.0),
        "round": ring(half_w * 0.5, hh * 4.5),
        "smile": ring(half_w * 1.08, hh * 1.4, corner=half_w * 0.32),
        "frown": ring(half_w * 0.95, hh * 1.1, corner=-half_w * 0.26),
    }
    return verts, faces, keys


def _lum(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def face_ops(
    cid: str, sp: Species, root: str, rig: str, brow_color: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ops adding the mouth (with shape keys) and brows to creature ``cid``; returns (ops, face meta)."""
    centre, half_w = mouth_place(sp)
    fwd = _rx((0.0, -1.0, 0.0), sp.head_pitch)  # the way the face looks (root space)
    around = (sp.mats.get("muzzle") or sp.coat)["base_color"]
    # a dark mouth disappears on a dark muzzle (zebra): show the warm inside instead
    mouth_color = "#8A2A34" if _lum(around) < 0.15 else "#3A1418"
    surface = f"{cid}_muzzle" if sp.muzzle else (f"{cid}_head" if sp.separate_head else f"{cid}_body")
    # sit just proud of the surface, facing along the head's pitch
    out = _rx((0.0, -0.006 * max(1.0, half_w / 0.02), 0.0), sp.head_pitch)
    verts, faces, keys = mouth_mesh(half_w)
    mouth = f"{cid}_mouth"
    ops: list[dict[str, Any]] = [
        {
            "op": "create_mesh",
            "id": mouth,
            "vertices": verts,
            "faces": faces,
            "location": [round(c, 4) for c in _add(centre, out)],
            "rotation": [sp.head_pitch, 0, 0],
            "parent": root,
            "tags": ["creature", cid, "mouth"],
        },
        {"op": "add_shape_keys", "target": mouth, "keys": keys},
        # seat it on the real surface (muzzle / sculpted head / body), whatever the blend did to it
        {
            "op": "snap_to_surface",
            "target": mouth,
            "surface": surface,
            "direction": list(fwd),
            "offset": 0.003,
        },
        {"op": "bind_mesh_to_armature", "mesh": mouth, "armature": rig, "bone": "head"},
        {
            "op": "set_material",
            "targets": [mouth],
            "material": {"base_color": mouth_color, "roughness": 0.45, "name": f"{cid}_mouth"},
        },
    ]
    ex, ey, ez, er = sp.eye
    brows: dict[str, dict[str, Any]] = {}
    head = f"{cid}_head" if sp.separate_head else f"{cid}_body"
    for side, sx in (("L", 1), ("R", -1)):
        rest = _add(sp.head_at, _rx((ex * sx * 0.95, ey - er * 0.15, ez + er * 1.3), sp.head_pitch))
        bid = f"{cid}_brow_{side}"
        out_dir = _rx((0.25 * sx, -1.0, 0.55), sp.head_pitch)
        n = math.sqrt(sum(c * c for c in out_dir))
        out_dir = (out_dir[0] / n, out_dir[1] / n, out_dir[2] / n)
        ops += [
            {
                "op": "create_primitive",
                "id": bid,
                "shape": "uv_sphere",
                "size": [round(er * 1.7, 4), round(er * 0.42, 4), round(er * 0.36, 4)],
                "location": [round(c, 4) for c in rest],
                "rotation": [sp.head_pitch, 0, 0],
                "smooth": True,
                "segments": 16,
                "parent": root,
                "tags": ["creature", cid, "brow"],
            },
            {
                "op": "snap_to_surface",
                "target": bid,
                "surface": head,
                "direction": [round(c, 4) for c in out_dir],
                "offset": round(-er * 0.06, 5),  # centre just under the skin
            },
            {
                # whatever pokes inside the (deformed) skin is laid onto it: the brow sits on the skin
                "op": "add_modifier",
                "target": bid,
                "type": "shrinkwrap",
                "surface": head,
                "params": {"wrap_method": "NEAREST_SURFACEPOINT", "wrap_mode": "OUTSIDE", "offset": 0.0012},
            },
            {"op": "bind_mesh_to_armature", "mesh": bid, "armature": rig, "bone": "head"},
        ]
        brows[side] = {"id": bid, "rest": rest, "sign": sx, "out": out_dir}
    ops.append(
        {
            "op": "set_material",
            "targets": [b["id"] for b in brows.values()],
            "material": {"base_color": brow_color, "roughness": 0.8, "name": f"{cid}_brow"},
        }
    )
    lids = [f"{cid}_lid_{side}_up" for side in ("L", "R")]
    meta = {"mouth": mouth, "brows": brows, "eye_r": er, "head_pitch": sp.head_pitch, "lids": lids}
    return ops, meta


def refresh_rest(face: dict[str, Any], objects: dict[str, dict[str, Any]]) -> None:
    """Use the brows' real rest positions (after snap_to_surface) from an engine ``query``."""
    for b in face["brows"].values():
        loc = objects.get(b["id"], {}).get("location")
        if loc:
            b["rest"] = tuple(loc)


def _smooth(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def expression_at(track: list[tuple[float, str]], t: float, blend: float = 0.3) -> Expression:
    """The expression at time t: each track entry eases in over ``blend`` seconds from the previous one."""
    if not track:
        return EXPRESSIONS["neutral"]
    track = sorted(track)
    cur = EXPRESSIONS["neutral"]
    for t0, name in track:
        if t < t0:
            break
        nxt = EXPRESSIONS.get(name, EXPRESSIONS["neutral"])
        u = _smooth((t - t0) / blend)
        cur = Expression(
            *(
                a + (b - a) * u
                for a, b in zip(
                    (cur.brow_up, cur.brow_tilt, cur.smile, cur.asym, cur.lid),
                    (nxt.brow_up, nxt.brow_tilt, nxt.smile, nxt.asym, nxt.lid),
                )
            )
        )
    return cur


def face_keys(
    face: dict[str, Any],
    track: list[tuple[float, str]],
    cues: list[Cue] | None,
    fps: int,
    frame0: int,
    frames: int,
    line_start: float = 0.0,
) -> list[dict[str, Any]]:
    """Keys for brows (location + tilt), smile/frown and lip-sync visemes over ``frames`` frames."""
    ops: list[dict[str, Any]] = []
    er, pitch = face["eye_r"], face["head_pitch"]
    ts = [i / fps for i in range(frames)]
    for side, b in face["brows"].items():
        rest, sx = b["rest"], b["sign"]
        loc_keys, rot_keys = [], []
        for i, t in enumerate(ts):
            e = expression_at(track, t)
            lift = er * (e.brow_up + (e.asym if side == "L" else 0.0))
            up = _rx((0.0, 0.0, lift), pitch)
            # follow the brow ridge as it curves back: a raised brow also sinks a little, so it slides on
            # the skin (the shrinkwrap keeps it on the surface) instead of lifting off into the air
            sink = b.get("out", (0.0, 0.0, 0.0))
            mv = [up[k] - sink[k] * 0.35 * abs(lift) for k in range(3)]
            loc_keys.append([frame0 + i, [round(rest[k] + mv[k], 5) for k in range(3)], "LINEAR"])
            # rotating about the head's forward axis: + lowers the +X (outer) end of the left brow, i.e. the
            # inner end goes up; mirrored on the right
            rot_keys.append([frame0 + i, [round(pitch, 2), round(e.brow_tilt * sx, 2), 0.0], "LINEAR"])
        ops += [
            {"op": "insert_keyframes", "target": b["id"], "property": "location", "keys": loc_keys},
            {"op": "insert_keyframes", "target": b["id"], "property": "rotation", "keys": rot_keys},
        ]
    smile = [
        [frame0 + i, round(max(0.0, expression_at(track, t).smile), 3), "LINEAR"] for i, t in enumerate(ts)
    ]
    frown = [
        [frame0 + i, round(max(0.0, -expression_at(track, t).smile), 3), "LINEAR"] for i, t in enumerate(ts)
    ]
    for lid in face.get("lids", []):
        es = [expression_at(track, t).lid for t in ts]
        ops += [
            {
                "op": "insert_keyframes",
                "target": lid,
                "property": "shape_key:droop",
                "keys": [[frame0 + i, round(max(0.0, v), 3), "LINEAR"] for i, v in enumerate(es)],
            },
            {
                "op": "insert_keyframes",
                "target": lid,
                "property": "shape_key:wide",
                "keys": [[frame0 + i, round(max(0.0, -v), 3), "LINEAR"] for i, v in enumerate(es)],
            },
        ]
    ops += [
        {"op": "insert_keyframes", "target": face["mouth"], "property": "shape_key:smile", "keys": smile},
        {"op": "insert_keyframes", "target": face["mouth"], "property": "shape_key:frown", "keys": frown},
    ]
    if cues:
        for key, kf in cues_to_keyframes(cues, fps, frame0 + int(round(line_start * fps))).items():
            if kf:
                ops.append(
                    {
                        "op": "insert_keyframes",
                        "target": face["mouth"],
                        "property": f"shape_key:{key}",
                        "keys": kf,
                    }
                )
    return ops
