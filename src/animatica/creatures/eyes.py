"""Eyes that sit in sockets: an eyeball sunk ~65 % into the skin, upper and lower lids that wrap it, all
riding the head bone.

The old eyes were whole spheres placed at a nominal offset on an idealised head. On the sculpted (metaball)
heads they floated half out of the skin, and the zebra's side-set eyes read as googly balls. Now:

* the eyeball's socket axis is the head's surface normal at the eye (the normal of the head ellipsoid), and
  ``snap_to_surface`` sinks the centre :data:`EMBED_DEPTH` eye radii under the real skin along that axis, so
  ~65 % of the ball is buried and the skin itself is the socket;
* the iris looks along the socket axis turned up to :data:`MAX_LOOK_DEG` toward the face's forward
  direction, so it sits on the visible cap, not at its rim;
* each lid is a thin spherical-cap shell around the eyeball (inner radius just clear of it), opening from
  the eye's up axis (upper lid) or down axis (lower). Shape keys: ``blink`` (closed), ``droop`` (heavy lid:
  sad, tired, determined) and ``wide`` (surprised, scared). The skin-coloured rim is what makes it read as an
  eye in a socket rather than a ball stuck on.

Pure geometry (root-space tuples); :mod:`animatica.creatures.build` turns it into ops.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .species import Species

V3 = tuple[float, float, float]

IRIS_AT = (
    0.78  # iris centre along the gaze, in eye radii: its front (half depth 0.24) is just proud of the ball
)
EMBED_DEPTH = 0.3  # eyeball centre this many radii under the skin: (1 + 0.3) / 2 = 65 % buried
MAX_LOOK_DEG = 42.0  # the iris turns at most this far from the socket axis toward the face's forward
LID_INNER = 1.1  # lid shell radii, in eye radii (clear of the eyeball)
LID_OUTER = 1.18
UPPER_OPEN = 54.0  # rest opening of the upper lid: polar angle of its edge from the eye's up axis (deg)
LOWER_OPEN = 32.0  # the lower lid's edge, from the down axis
UPPER_CLOSED = 146.0  # blink: the upper lid comes down past the lower lid's edge (which rises to 38)
LOWER_CLOSED = 38.0
UPPER_DROOP = 82.0  # a heavy lid, half over the iris
UPPER_WIDE = 20.0  # eyes wide open: white shows above the iris (surprise reads at sheet size)
LOWER_CHEEK = 74.0  # "smiling eyes": the cheeks push the lower lid up over the bottom of the iris (happy)


def _norm(v: V3) -> V3:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a: V3, b: V3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: V3, b: V3) -> V3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _rx(v: V3, deg: float) -> V3:
    a = math.radians(deg)
    return (v[0], v[1] * math.cos(a) - v[2] * math.sin(a), v[1] * math.sin(a) + v[2] * math.cos(a))


@dataclass(frozen=True)
class EyeFrame:
    centre: V3  # nominal centre (root space), before snapping into the skin
    socket: V3  # outward socket axis = head surface normal at the eye
    look: V3  # where the iris points
    up: V3  # the lid axis: perpendicular to ``look``, toward the top of the head
    radius: float


def eye_frame(sp: Species, sx: int) -> EyeFrame:
    """The eye on side ``sx`` (+1 left, -1 right) of ``sp``'s head."""
    ex, ey, ez, er = sp.eye
    hw, hl, hh = sp.head_size
    off = (ex * sx, ey, ez)
    centre = tuple(h + o for h, o in zip(sp.head_at, _rx(off, sp.head_pitch)))
    # the normal of the head ellipsoid (semi-axes = half the head size) at the eye, in head space, then pitched
    a, b, c = hw / 2, hl / 2, hh / 2
    socket = _norm(_rx((off[0] / a**2, off[1] / b**2, off[2] / c**2), sp.head_pitch))
    fwd = _rx((0.0, -1.0, 0.0), sp.head_pitch)
    t = (
        fwd[0] - _dot(fwd, socket) * socket[0],
        fwd[1] - _dot(fwd, socket) * socket[1],
        fwd[2] - _dot(fwd, socket) * socket[2],
    )
    ang = math.acos(max(-1.0, min(1.0, _dot(fwd, socket))))
    if math.sqrt(_dot(t, t)) < 1e-6:
        look = socket
    else:
        t = _norm(t)
        th = min(math.radians(MAX_LOOK_DEG), ang)
        look = _norm(tuple(socket[k] * math.cos(th) + t[k] * math.sin(th) for k in range(3)))  # type: ignore[arg-type]
    up0 = _rx((0.0, 0.0, 1.0), sp.head_pitch)
    up = _norm(tuple(up0[k] - _dot(up0, look) * look[k] for k in range(3)))  # type: ignore[arg-type]
    return EyeFrame(centre, socket, look, up, er)  # type: ignore[arg-type]


def look_rotation(look: V3) -> list[float]:
    """Euler XYZ (degrees) turning local -Y (a primitive's front) onto ``look``."""
    p = -math.asin(max(-1.0, min(1.0, look[2])))
    yaw = math.atan2(look[0], -look[1])
    return [round(math.degrees(p), 3), 0.0, round(math.degrees(yaw), 3)]


def _cap(er: float, axis: V3, side: V3, edge_deg: float, rows: int, seg: int) -> list[list[float]]:
    """Vertices of a lid shell: polar rows from the ``axis`` pole to ``edge_deg``, outer then inner layer."""
    w = _cross(axis, side)
    out: list[list[float]] = []
    for rad in (LID_OUTER * er, LID_INNER * er):
        out.append([round(axis[k] * rad, 6) for k in range(3)])
        for i in range(1, rows + 1):
            ph = math.radians(edge_deg) * i / rows
            for j in range(seg):
                ps = 2 * math.pi * j / seg
                d = [
                    axis[k] * math.cos(ph) + math.sin(ph) * (side[k] * math.cos(ps) + w[k] * math.sin(ps))
                    for k in range(3)
                ]
                out.append([round(d[k] * rad, 6) for k in range(3)])
    return out


def lid_mesh(
    er: float, frame: EyeFrame, upper: bool, rows: int = 6, seg: int = 28
) -> tuple[list[list[float]], list[list[int]], dict[str, list[list[float]]]]:
    """(verts, faces, shape keys) of one lid, in root-space axes about the eyeball centre."""
    axis = frame.up if upper else tuple(-c for c in frame.up)
    side = frame.look  # the azimuth origin: the front of the eye
    rest = UPPER_OPEN if upper else LOWER_OPEN
    verts = _cap(er, axis, side, rest, rows, seg)  # type: ignore[arg-type]
    n_layer = 1 + rows * seg
    faces: list[list[int]] = []
    for base, flip in ((0, False), (n_layer, True)):
        for j in range(seg):
            j2 = (j + 1) % seg
            f = [base, base + 1 + j, base + 1 + j2]
            faces.append(f[::-1] if flip else f)
        for i in range(rows - 1):
            a, b = base + 1 + i * seg, base + 1 + (i + 1) * seg
            for j in range(seg):
                j2 = (j + 1) % seg
                f = [a + j, b + j, b + j2, a + j2]
                faces.append(f[::-1] if flip else f)
    oa, ia = 1 + (rows - 1) * seg, n_layer + 1 + (rows - 1) * seg  # the rim joins the two layers
    for j in range(seg):
        j2 = (j + 1) % seg
        faces.append([oa + j, ia + j, ia + j2, oa + j2])
    keys = {"blink": _cap(er, axis, side, UPPER_CLOSED if upper else LOWER_CLOSED, rows, seg)}  # type: ignore[arg-type]
    if upper:
        keys["droop"] = _cap(er, axis, side, UPPER_DROOP, rows, seg)  # type: ignore[arg-type]
        keys["wide"] = _cap(er, axis, side, UPPER_WIDE, rows, seg)  # type: ignore[arg-type]
    else:
        keys["cheek"] = _cap(er, axis, side, LOWER_CHEEK, rows, seg)  # type: ignore[arg-type]
    return verts, faces, keys
