"""Measure a species design: proportions, silhouette features and materials (no Blender needed).

Every metric is a dimensionless ratio, so briefs can state appeal ranges independent of the animal's size:

* ``head_body``    longest head dimension / body length (torso, or the shell for a tortoise). Babies: big.
* ``eye_head``     eye diameter / head height. Kids'-film eyes are large.
* ``eye_spacing``  distance between the eye centres / head width (1.0 = eyes on the head's sides).
* ``neck_head``    neck radius where it meets the head / half the head's smaller cross-section. Below 1 the
                   neck is visibly narrower than the head (the melted-elephant failure was ~1).
* ``elongation``   body length / body depth (a meerkat at 2.8 walks like a weasel, at 2.2 like a hamster).
* ``belly_gap``    daylight under the belly / body depth (legs long enough to read).
* ``leg_thickness`` lower fore-leg radius / body width.
* ``ear_head``     ear area / head side area.
* ``neck_length``  neck chain length / body height above the ground.
* ``snout``        muzzle length / head length (0 when the species has no separate muzzle).
"""

from __future__ import annotations

import math
from typing import Any

from animatica.creatures import shell as shell_mod
from animatica.creatures.species import Species


def _hex(linear: tuple[float, float, float]) -> str:
    """Linear RGB (vertex colours) -> sRGB hex."""

    def enc(c: float) -> int:
        c = max(0.0, min(1.0, c))
        v = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(v * 255)

    return "#" + "".join(f"{enc(c):02X}" for c in linear)


def luminance(hex_color: str) -> float:
    """Relative luminance (WCAG, linear sRGB) of ``#RRGGBB``: 0 = black, 1 = white."""
    h = hex_color.lstrip("#")
    c = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours (1 = identical, 21 = black on white)."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def body_length(sp: Species) -> float:
    return max(sp.torso[1], sp.shell[0][1] if sp.shell else 0.0)


def proportions(sp: Species) -> dict[str, float]:
    hw, hl, hh = sp.head_size
    ex, _ey, _ez, er = sp.eye
    blen = body_length(sp)
    depth = sp.torso[2]
    belly = sp.body_z + sp.torso_at[2] - depth / 2
    ear_area = sp.ear[1][1] * sp.ear[1][2] if sp.ear[0] != "none" else 0.0
    neck_len = math.dist(sp.neck.base, sp.neck.tip)
    out = {
        "head_body": max(sp.head_size) / blen,
        "eye_head": 2 * er / hh,
        "eye_spacing": 2 * abs(ex) / hw,
        "neck_head": sp.neck.r1 / (min(hw, hh) / 2),
        "elongation": sp.torso[1] / depth,
        "belly_gap": belly / depth,
        "leg_thickness": sp.leg_r[1] / sp.torso[0],
        "ear_head": ear_area / (hl * hh),
        "neck_length": neck_len / sp.body_z,
        "snout": sp.muzzle[0][1] / hl if sp.muzzle else 0.0,
    }
    return {k: round(v, 4) for k, v in out.items()}


def _patterns(sp: Species) -> set[str]:
    out = set()
    for m in [sp.coat, *sp.mats.values()]:
        if m.get("pattern"):
            out.add(str(m["pattern"]))
    if sp.shell is not None and sp.mats.get("shell", {}).get("vertex_color"):
        out.add("scutes")  # the carapace mesh paints its scute marks per vertex (creatures.shell)
    return out


def features(sp: Species) -> set[str]:
    """Silhouette and marking features the design has (brief ``features`` must all be present)."""
    f: set[str] = set()
    if sp.trunk is not None:
        f.add("trunk")
    if sp.shell is not None:
        f.add("shell")
    if sp.tuft > 0:
        f.add("tail_tuft")
    if sp.eye_patch is not None:
        f.add("eye_patch")
    if sp.ear[0] != "none":
        f.add("ears")
    if sp.ear[0] != "none" and sp.ear[1][1] * sp.ear[1][2] > 0.5 * sp.head_size[1] * sp.head_size[2]:
        f.add("big_ears")
    if sp.muzzle is not None:
        f.add("muzzle")
    if sp.default_pose == "sentinel":
        f.add("sentinel")
    if sp.separate_head:
        f.add("separate_head")
    for ex in sp.extras:
        f.add(ex.id.rstrip("_LR").split("_")[0])  # ossicone_L -> ossicone, mane -> mane
    if sp.mane:  # the mane ridge mesh (creatures.parts)
        f.add("mane")
    f |= {f"pattern:{p}" for p in _patterns(sp)}
    return f


def _foot_vertices(op: dict[str, Any], sp: Species) -> list[tuple[float, float, float]]:
    """A foot's vertices in its own frame (sole at z = 0). A ``create_primitive`` cylinder is sampled as the
    puck it renders as."""
    if op["op"] == "create_mesh":
        return [tuple(v) for v in op["vertices"]]
    _shape, r, h = sp.foot
    ring = [(math.sin(2 * math.pi * k / 32) * r, -math.cos(2 * math.pi * k / 32) * r) for k in range(32)]
    return [(x, y, z) for z in (0.0, h) for x, y in ring]


def hoof_shape(sp: Species) -> dict[str, float] | None:
    """The hooves as built (``creatures.build``), measured on the mesh: ``taper`` = coronet width / sole width
    (a cylinder "puck" is 1.0), ``wall_deg`` = front wall angle from the ground (a puck stands at 90; a horse's
    hoof wall is about 50-55), ``height`` = hoof height / sole length. ``None`` when the species has no hooves.
    Zuri v2's hooves were flat cylinders the striped leg tube sat on, read as toy parts (review 11-17 15:36)."""
    if sp.foot[0] != "hoof":
        return None
    from animatica.creatures.build import build_creature  # a lazy import: build imports nothing from design

    ops = build_creature("m", sp)[0]
    feet = [o for o in ops if str(o.get("id", "")).startswith("m_foot_")]
    worst: dict[str, float] = {}
    for op in feet:
        vs = _foot_vertices(op, sp)
        z0, z1 = min(v[2] for v in vs), max(v[2] for v in vs)
        tol = 0.02 * (z1 - z0)
        sole = [v for v in vs if v[2] <= z0 + tol]  # the sole ring (and its centre)
        top = [v for v in vs if v[2] >= z1 - tol]  # the coronet ring (and the cap's centre)
        sw = max(v[0] for v in sole) - min(v[0] for v in sole)
        tw = max(v[0] for v in top) - min(v[0] for v in top)
        sl = max(v[1] for v in sole) - min(v[1] for v in sole)
        setback = min(v[1] for v in top) - min(v[1] for v in sole)  # the toe is -Y: + = the coronet sits back
        m = {
            "taper": tw / max(sw, 1e-9),
            "wall_deg": math.degrees(math.atan2(z1 - z0, max(setback, 0.0))),
            "height": (z1 - z0) / max(sl, 1e-9),
        }
        for k, v in m.items():  # the least hoof-like foot decides
            worst[k] = v if k not in worst else (min(worst[k], v) if k == "height" else max(worst[k], v))
    return {k: round(v, 3) for k, v in worst.items()} if worst else None


def mane_shape(sp: Species) -> dict[str, Any] | None:
    """The mane as built: ``follows_neck`` (a ridge skinned along the neck chain, not a rigid mesh carried by one
    neck bone: v2's was an ellipsoid board that ignored the neck's curve and stepped at the poll), ``stand`` =
    the tallest crest height above the neck's skin / the neck's depth there (a fin or plank stands tall), and
    ``jag`` = the biggest crest step between neighbouring stations / the tallest crest (a saw, not a brush).
    ``None`` when the species has no mane."""
    rigid = [ex for ex in sp.extras if ex.id.startswith("mane")]
    if not sp.mane and not rigid:
        return None
    if not sp.mane:  # rigid boards: their standing height from the extra's size (its vertical extent, halved)
        neck_d = sp.neck.r0 + sp.neck.r1
        stand = max(ex.size[2] / 2 + ex.loc[2] - sp.neck.r0 for ex in rigid) / neck_d
        return {"follows_neck": False, "stand": round(stand, 3), "jag": 0.0}
    from animatica.creatures.parts import mane_line, mane_ridge

    mh, mw, teeth = sp.mane
    line = mane_line(sp)
    verts = mane_ridge(line, mh, mw, teeth)[0]
    heights, stands = [], []
    for i, (p, r) in enumerate(line):
        a, b = verts[4 * i + 2], verts[4 * i + 3]  # the crest's two vertices at this station
        c = [(a[k] + b[k]) / 2 for k in range(3)]
        h = math.dist(c, p) - r
        heights.append(h)
        stands.append(h / (2 * r))
    top = max(heights) or 1e-9
    inner = heights[2:-2]  # the tapered ends are meant to step down
    jag = max((abs(x - y) for x, y in zip(inner, inner[1:], strict=False)), default=0.0) / top
    crest = [[(verts[4 * i + 2][k] + verts[4 * i + 3][k]) / 2 for k in range(3)] for i in range(len(line))]
    return {
        "follows_neck": not rigid,
        "stand": round(max(stands), 3),
        "jag": round(jag, 3),
        "reach": round(_mane_reach(sp, crest), 3),
    }


def _in_head(sp: Species, q: list[float]) -> float:
    """``q`` in the head ellipsoid's normalised coordinates (< 1 inside), with the head's pitch."""
    a = math.radians(-sp.head_pitch)
    d = [q[k] - sp.head_at[k] for k in range(3)]
    y = d[1] * math.cos(a) - d[2] * math.sin(a)
    z = d[1] * math.sin(a) + d[2] * math.cos(a)
    hx, hy, hz = (s / 2 for s in sp.head_size)
    return (d[0] / hx) ** 2 + (y / hy) ** 2 + (z / hz) ** 2


def _mane_reach(sp: Species, crest: list[list[float]]) -> float:
    """How far the mane's crest runs from the withers toward the poll: 1 - (the gap from the crest's last point
    to the back of the head) / (withers -> poll). A zebra's mane runs to the poll, between the ears; Zuri v4's
    stopped about a quarter short and ended as a square-cut slab (review 11-18 18:36)."""
    end = crest[-1]
    if _in_head(sp, end) <= 1.0:
        return 1.0
    poll, step = list(end), 0
    while _in_head(sp, poll) > 1.0 and step < 400:  # walk from the crest's end toward the head's centre
        poll = [poll[k] + (sp.head_at[k] - end[k]) / 400 for k in range(3)]
        step += 1
    gap = math.dist(end, poll)
    length = math.dist(crest[0], poll) or 1.0
    return max(0.0, 1.0 - gap / length)


def dome_shoulder(vertices: list[list[float]] | list[tuple[float, float, float]], bins: int = 40) -> float:
    """How high a shell's sides stay at full width, as a share of its height: cut the mesh into ``bins``
    horizontal slices, take each slice's outline radius (top view, width scaled to the length so an oval counts
    as round), and return the height of the highest slice still at >= 95 % of the widest. A ball is 0.65, a
    half-sphere on a flat plate 0.30 (any dome scaled taller or flatter keeps its value)."""
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    z0, z1 = min(zs), max(zs)
    length, width = max(ys) - min(ys), max(xs) - min(xs)
    k = length / max(width, 1e-9)
    ext = [0.0] * (bins + 1)
    for x, y, z in zip(xs, ys, zs, strict=True):
        b = round((z - z0) / max(z1 - z0, 1e-9) * bins)
        ext[b] = max(ext[b], math.hypot(x * k, y))
    widest = max(ext)
    return max(i for i, e in enumerate(ext) if e >= 0.95 * widest) / bins


def shell_shape(sp: Species) -> dict[str, float] | None:
    """The carapace as built (``creatures.build`` -> ``creatures.shell.carapace``), measured on the mesh:
    ``shoulder`` (:func:`dome_shoulder`: a dome curves in just above its rim, a ball or barrel keeps its full
    width up its sides), ``height_length`` and ``width_length`` (the whole shell with the plastron). ``None``
    without a shell. Bibi Kobe's shell read as a ball (cloud reviews 11-17 06:36 to 11-19) while every check
    passed."""
    if sp.shell is None:
        return None
    from animatica.creatures.build import build_creature  # a lazy import: build imports nothing from design

    ops = build_creature("m", sp)[0]
    shell = next(o for o in ops if str(o.get("id", "")).endswith("_shell"))
    vs = shell["vertices"]
    length = max(v[1] for v in vs) - min(v[1] for v in vs)
    return {
        "shoulder": round(dome_shoulder(vs), 3),
        "height_length": round((max(v[2] for v in vs) - min(v[2] for v in vs)) / length, 3),
        "width_length": round((max(v[0] for v in vs) - min(v[0] for v in vs)) / length, 3),
    }


# The design sheet's cameras (``scripts/design_sheet.py`` imports these): direction from the subject to the lens,
# the animal facing -Y. ``face`` is the expression close-up's camera.
SHEET_VIEWS: dict[str, tuple[float, float, float]] = {
    "front": (0.0, -1.0, 0.12),
    "side": (1.0, 0.0, 0.08),  # from the animal's left: head on the image's left
    "three_quarter": (0.72, -0.72, 0.2),
    "back": (0.0, 1.0, 0.15),
}
FACE_DIR = (0.5, -1.0, 0.1)
# the views in which an ear must show its bowl, not its edge (from behind we see its back, which is fine edge-on)
EAR_VIEWS = ("front", "side", "three_quarter", "face")


def _uv_sphere(
    size: list[float] | tuple[float, ...], seg: int = 24
) -> tuple[list[list[float]], list[list[int]]]:
    """A UV sphere scaled to ``size`` (the adapter's ``create_primitive`` ``uv_sphere`` with ``size``)."""
    rings = seg // 2
    vs = [
        [
            math.sin(math.pi * i / rings) * math.cos(2 * math.pi * k / seg) * size[0] / 2,
            math.sin(math.pi * i / rings) * math.sin(2 * math.pi * k / seg) * size[1] / 2,
            math.cos(math.pi * i / rings) * size[2] / 2,
        ]
        for i in range(rings + 1)
        for k in range(seg)
    ]
    fs = [
        [i * seg + k, (i + 1) * seg + k, (i + 1) * seg + (k + 1) % seg, i * seg + (k + 1) % seg]
        for i in range(rings)
        for k in range(seg)
    ]
    return vs, fs


def _placed(op: dict[str, Any]) -> tuple[Any, Any]:
    """An ear op's (vertices in the creature's frame, triangles), as numpy arrays."""
    import numpy as np

    from animatica.creatures.gesture import euler_to_mat

    if op["op"] == "create_mesh":
        vs, fs = op["vertices"], op["faces"]
    else:
        vs, fs = _uv_sphere(op["size"])
    rot = np.array(euler_to_mat(op.get("rotation", (0.0, 0.0, 0.0))))
    v = np.asarray(vs, float) @ rot.T + np.asarray(op.get("location", (0.0, 0.0, 0.0)), float)
    tris = [[f[0], f[j], f[j + 1]] for f in fs for j in range(1, len(f) - 1)]
    return v, np.asarray(tris, int)


def projected_area(vertices: Any, tris: Any, direction: tuple[float, float, float], px: float) -> float:
    """Area of a mesh's outline seen along ``direction`` (orthographic), rasterised at pixel size ``px``: what
    a camera draws of it, holes and overlaps counted once."""
    import numpy as np
    from PIL import Image, ImageDraw

    d = np.asarray(direction, float)
    d /= np.linalg.norm(d)
    up = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.99 else np.array([0.0, 1.0, 0.0])
    u = np.cross(up, d)
    u /= np.linalg.norm(u)
    w = np.cross(d, u)
    p = np.stack([vertices @ u, vertices @ w], 1)
    p = (p - p.min(0)) / px + 1.0
    size = np.ceil(p.max(0)).astype(int) + 2
    img = Image.new("1", (int(size[0]), int(size[1])), 0)
    draw = ImageDraw.Draw(img)
    for t in tris:
        draw.polygon([tuple(q) for q in p[t]], fill=1)
    return float(np.count_nonzero(np.asarray(img))) * px * px


def ear_views(sp: Species, res: int = 160) -> dict[str, dict[str, float]] | None:
    """For each ear as built (``creatures.build``, rest pose), the area the sheet's cameras draw of it as a
    share of its face-on area (seen along its thinnest principal axis): 1 = we see the whole bowl, ~ thickness /
    width = a fin edge-on. ``None`` without ears. Tembo's baseline disc ears (a flattened sphere) stood edge-on
    as a fin from the 3/4 and face cameras (cloud review 11-17 06:36) while every check passed."""
    import numpy as np

    if sp.ear[0] == "none":
        return None
    from animatica.creatures.build import build_creature  # a lazy import: build imports nothing from design

    ops = build_creature("m", sp, yaw=0.0)[0]
    dirs = {k: SHEET_VIEWS[k] for k in EAR_VIEWS if k in SHEET_VIEWS} | {"face": FACE_DIR}
    out: dict[str, dict[str, float]] = {}
    for op in ops:
        oid = str(op.get("id", ""))
        if "_ear_" not in oid or op["op"] not in ("create_mesh", "create_primitive"):
            continue
        v, tris = _placed(op)
        px = float((v.max(0) - v.min(0)).max()) / res
        # face-on: along the axis of least spread (the ear's thickness, through its bowl)
        _, _, vt = np.linalg.svd(v - v.mean(0), full_matrices=False)
        full = projected_area(v, tris, tuple(vt[2]), px)
        out[oid.split("_ear_")[1]] = {
            k: round(projected_area(v, tris, d, px) / full, 3) for k, d in dirs.items() if k in EAR_VIEWS
        }
    return out


def ear_edge(sp: Species) -> dict[str, Any] | None:
    """The thinnest any ear is drawn in a view that should show its bowl (:func:`ear_views`): ``share``, and
    which ``ear`` and ``view``."""
    ev = ear_views(sp)
    if not ev:
        return None
    share, ear, view = min((s, e, k) for e, views in ev.items() for k, s in views.items())
    return {"share": share, "ear": ear, "view": view, "views": ev}


def materials(sp: Species) -> dict[str, Any]:
    """Coat/part luminances, pattern contrast, and dark parts that may read as flat black blocks.

    ``dark_regions`` lists body-mesh regions (bone prefixes -> material) whose colour is near-black
    (luminance < 0.02), or that carries a near-black ``marks`` entry: a whole leg segment painted that dark
    reads as a black stick at thumbnail size.
    Small accents (nose, tail tip, nails) are not regions of the body mesh and are not listed.
    """
    coat = str(sp.coat["base_color"])
    lum = {"coat": round(luminance(coat), 4)}
    for k, m in sp.mats.items():
        if "base_color" in m:
            lum[k] = round(luminance(str(m["base_color"])), 4)
    contrast = {}
    for k, m in {"coat": sp.coat, **sp.mats}.items():
        if m.get("pattern_color"):
            contrast[k] = round(contrast_ratio(str(m["base_color"]), str(m["pattern_color"])), 2)
        elif m.get("vertex_color") and k == "shell":  # painted marks: the ochre ground against the dark rays
            contrast[k] = round(contrast_ratio(_hex(shell_mod.GROUND), _hex(shell_mod.RAY)), 2)
    dark = []
    for bones, key in sp.regions:
        m = sp.mats.get(key, {})
        if "base_color" in m and luminance(str(m["base_color"])) < 0.02:
            dark.append({"material": key, "bones": list(bones)})
            continue
        # a near-black mark painted over the region (the meerkat's paw shade) is a black block too
        marks = [i for i, mk in enumerate(m.get("marks") or []) if luminance(str(mk["color"])) < 0.02]
        if marks:
            dark.append({"material": key, "bones": list(bones), "marks": marks})
    return {"luminance": lum, "pattern_contrast": contrast, "dark_regions": dark}


def describe(sp: Species) -> dict[str, Any]:
    return {
        "species": sp.name,
        "proportions": proportions(sp),
        "features": sorted(features(sp)),
        "materials": materials(sp),
    }
