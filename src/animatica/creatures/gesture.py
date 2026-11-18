"""Acting layers on top of locomotion: eyelines (heads turn toward whoever is speaking), and gestures the
story needs (an elephant's trunk drinking and spraying, a giraffe ducking her head, ears drooping, a
head shake, a nod).

Every layer is a rotation about an axis given in the creature's body (armature) space, e.g. "turn about
the world vertical" or "pitch nose-down". :func:`local_rotation` converts that into the bone's own rest
frame (Blender's roll-0 bone matrix), so one description works on every species' rig. The layers are
composed *outside* the locomotion keys (``posed = R_gesture * rest * R_gait``), so a turning head keeps its
walk nod and a drinking trunk keeps a little sway.

Pure Python (no Blender): unit-tested, and :func:`animatica.creatures.perform.walk_keys` bakes the result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .gait import LocoFrame

Mat = list[list[float]]
V3 = tuple[float, float, float]

IDENT: Mat = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

# How much of a head turn each part takes (the neck chain shares NECK_SHARE, the head the rest), and the
# furthest an animal turns its head before it would turn its body instead.
NECK_SHARE = 0.55
MAX_TURN = 70.0
EYELINE_TAU = 0.11  # seconds: heads settle on a new speaker with this time constant (no snaps)
SPEAKER_SHARE = 0.45  # a speaker turns this much of the way toward the addressee (cheated to the lens)

KINDS = ("look_at", "head_duck", "ears_droop", "trunk_drink", "trunk_spray", "head_shake", "nod", "talk")


def mat_mul(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def transpose(a: Mat) -> Mat:
    return [[a[j][i] for j in range(3)] for i in range(3)]


def apply(a: Mat, v: V3) -> V3:
    return (
        a[0][0] * v[0] + a[0][1] * v[1] + a[0][2] * v[2],
        a[1][0] * v[0] + a[1][1] * v[1] + a[1][2] * v[2],
        a[2][0] * v[0] + a[2][1] * v[1] + a[2][2] * v[2],
    )


def axis_angle(axis: V3, deg: float) -> Mat:
    n = math.sqrt(sum(c * c for c in axis)) or 1.0
    x, y, z = (c / n for c in axis)
    a = math.radians(deg)
    c, s, C = math.cos(a), math.sin(a), 1 - math.cos(a)
    return [
        [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ]


def euler_to_mat(e: list[float] | tuple[float, ...]) -> Mat:
    """Blender XYZ Euler (degrees): R = Rz * Ry * Rx."""
    return mat_mul(
        axis_angle((0, 0, 1), e[2]), mat_mul(axis_angle((0, 1, 0), e[1]), axis_angle((1, 0, 0), e[0]))
    )


def mat_to_euler(m: Mat) -> list[float]:
    sy = max(-1.0, min(1.0, -m[2][0]))
    y = math.asin(sy)
    if abs(sy) < 0.99999:
        x = math.atan2(m[2][1], m[2][2])
        z = math.atan2(m[1][0], m[0][0])
    else:  # gimbal lock: put everything in z
        x = 0.0
        z = math.atan2(-m[0][1], m[1][1])
    return [math.degrees(x), math.degrees(y), math.degrees(z)]


def rest_matrix(direction: V3) -> Mat:
    """A roll-0 bone's rest orientation in armature space (columns = local X, Y, Z), as Blender builds it
    (``vec_roll_to_mat3``): the shortest rotation taking +Y onto the bone direction."""
    n = math.sqrt(sum(c * c for c in direction)) or 1.0
    x, y, z = (c / n for c in direction)
    theta = 1.0 + y
    theta_alt = x * x + z * z
    if theta > 1e-5 or theta_alt > 1e-12:
        if theta <= 1e-5:
            theta = theta_alt * 0.5 + theta_alt * theta_alt * 0.125
        cx = (1 - x * x / theta, -x, -x * z / theta)
        cy = (x, y, z)
        cz = (-x * z / theta, -z, 1 - z * z / theta)
    else:
        cx, cy, cz = (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)
    return [[cx[i], cy[i], cz[i]] for i in range(3)]


def local_rotation(direction: V3, axis: V3, deg: float) -> Mat:
    """The pose rotation (bone-local) that turns a bone pointing along ``direction`` by ``deg`` about the
    armature-space ``axis``: ``B^T R B``."""
    b = rest_matrix(direction)
    return mat_mul(transpose(b), mat_mul(axis_angle(axis, deg), b))


def body_axis(world: V3, pitch: float, roll: float) -> V3:
    """A world-space axis expressed in the body frame of a root rotated by Euler (pitch, roll, yaw): the
    yaw doesn't matter for a vertical axis, the pitch does (a meerkat standing up)."""
    r = mat_mul(axis_angle((0, 1, 0), roll), axis_angle((1, 0, 0), pitch))
    return apply(transpose(r), world)


def _smooth(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def envelope(t: float, start: float, dur: float, ein: float = 0.3, eout: float = 0.35) -> float:
    """0 -> 1 over ``ein`` from ``start``, hold, 1 -> 0 over the last ``eout`` of ``dur``."""
    if t < start or t > start + dur:
        return 0.0
    return min(_smooth((t - start) / max(ein, 1e-3)), _smooth((start + dur - t) / max(eout, 1e-3)))


def wrap(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def heading_to(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """The yaw that faces from ``a`` toward ``b`` (rest faces -Y; 90 = toward +X)."""
    return math.degrees(math.atan2(b[0] - a[0], -(b[1] - a[1])))


@dataclass
class Gesture:
    who: str
    kind: str
    start: float
    dur: float = 1.5
    target: str = ""  # look_at / trunk_spray: another cast member
    amount: float = 1.0  # scales the gesture's angles
    # talk: (seconds, strength) syllable accents of the line (production.acting.speech_accents)
    accents: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class Rig:
    """What the acting layers need to know about one creature (from ``CreatureMeta``)."""

    species: str
    bone_dirs: dict[str, V3]
    neck: list[str]
    trunk: list[str] = field(default_factory=list)
    ears: list[str] = field(default_factory=list)  # L then R


def _add(layers: dict[str, list[Mat]], bone: str, k: int, m: Mat) -> None:
    layers[bone][k] = mat_mul(m, layers[bone][k])


def gaze_track(
    me: str,
    plans: dict[str, list[LocoFrame]],
    lines: list,
    gestures: list[Gesture],
    fps: int,
    speaker_targets: bool = True,
) -> list[float]:
    """Per frame: how far (degrees, + = to the animal's left/counter-clockwise) ``me`` turns its head.

    Listeners look at whoever is speaking (from just before the first word to half a second after the
    last), a speaker turns part of the way toward the line's addressee (``line.to``), and explicit
    ``look_at`` gestures override both. The target angle and its on/off weight are both low-passed, so
    heads glide between speakers instead of snapping.
    """
    plan = plans[me]
    n = len(plan)
    looks = [g for g in gestures if g.who == me and g.kind == "look_at" and g.target in plans]
    out: list[float] = []
    ang = w = w1 = 0.0
    alpha = 1 - math.exp(-1.0 / (fps * EYELINE_TAU))
    for k in range(n):
        t = k / fps
        tgt, share = None, 1.0
        for ln in lines:
            if ln.start - 0.15 <= t <= ln.end + 0.5:
                if ln.who != me and ln.who in plans:
                    tgt, share = ln.who, 1.0
                elif ln.who == me and speaker_targets and getattr(ln, "to", "") in plans:
                    tgt, share = ln.to, SPEAKER_SHARE
        for g in looks:
            if g.start <= t <= g.start + g.dur:
                tgt, share = g.target, g.amount
        want_w = 0.0
        if tgt is not None and tgt != me:
            p, q = plan[k], plans[tgt][min(k, len(plans[tgt]) - 1)]
            d = wrap(heading_to(p.root, q.root) - p.yaw)
            d = max(-MAX_TURN, min(MAX_TURN, d)) * share
            ang += alpha * (d - ang) if w > 0.02 else (d - ang)  # first look: aim, then fade the weight in
            want_w = 1.0
        # two cascaded low-passes: the turn eases in and out instead of starting at full speed
        w1 += alpha * (want_w - w1)
        w += alpha * (w1 - w)
        out.append(ang * w)
    return out


def acting_layers(
    rig: Rig,
    plan: list[LocoFrame],
    gaze: list[float] | None,
    gestures: list[Gesture],
    fps: int,
    targets: dict[str, list[LocoFrame]] | None = None,
) -> dict[str, list[Mat]]:
    """Bone -> per-frame bone-local rotation to compose over the locomotion keys."""
    n = len(plan)
    bones = set(rig.neck) | {"head"} | set(rig.trunk) | set(rig.ears)
    layers: dict[str, list[Mat]] = {b: [IDENT] * n for b in bones}
    d = rig.bone_dirs
    neck = rig.neck
    for k, p in enumerate(plan):
        t = k / fps
        up = body_axis((0.0, 0.0, 1.0), p.pitch, p.roll)
        side = (1.0, 0.0, 0.0)  # body X: + tips forward-pointing bones down (nose down)

        def turn(deg: float, axis: V3, head_share: float = 1 - NECK_SHARE, k: int = k) -> None:
            if abs(deg) < 1e-4:
                return
            for b in neck:
                _add(layers, b, k, local_rotation(d[b], axis, deg * (1 - head_share) / len(neck)))
            _add(layers, "head", k, local_rotation(d["head"], axis, deg * head_share))

        if gaze is not None:
            turn(gaze[k], up)
        for g in gestures:
            e = envelope(t, g.start, g.dur)
            if e <= 0:
                continue
            u = (t - g.start) / g.dur
            a = g.amount
            if g.kind == "talk":
                # the head beats on the stressed syllables (a quick dip and a small rebound), over a slow tilt
                # and sway across the phrase, so a speaking head is never a statue
                beat = 0.0
                for ta, w in g.accents:
                    du = t - ta
                    if -0.2 < du < 0.45:
                        beat += w * (
                            math.exp(-(((du - 0.03) / 0.07) ** 2))
                            - 0.35 * math.exp(-(((du - 0.17) / 0.09) ** 2))
                        )
                turn(5.5 * a * beat * e, side, head_share=0.85)
                turn(2.5 * a * math.sin(2 * math.pi * (t - g.start) / 2.6) * e, up, head_share=0.7)
                turn(
                    3.0 * a * math.sin(2 * math.pi * (t - g.start) / 3.4 + 1.0) * e,
                    (0.0, 1.0, 0.0),
                    head_share=0.9,
                )
            elif g.kind == "head_duck":
                # an embarrassed duck: the neck bows forward, the head tucks to keep the eyes looking ahead
                turn(60 * a * e, side, head_share=-0.35)
            elif g.kind == "nod":
                turn(14 * a * math.sin(2 * math.pi * min(u * 2, 2.0)) ** 2 * e, side, head_share=0.8)
            elif g.kind == "head_shake":
                # a wet-dog shake: fast side-to-side, decaying
                turn(24 * a * math.sin(2 * math.pi * 4.2 * (t - g.start)) * (1 - u) * e, up, head_share=0.6)
            elif g.kind == "ears_droop":
                for s, b in zip((1, -1), rig.ears):
                    if rig.species == "elephant":
                        # the big ears go limp: pressed back against the head and hanging lower
                        m = mat_mul(
                            local_rotation(d[b], (0, 0, 1), -s * 22 * a * e),
                            local_rotation(d[b], (0, 1, 0), -s * 10 * a * e),
                        )
                    else:  # upright ears fold out and down
                        m = mat_mul(
                            local_rotation(d[b], (0, 1, 0), s * 55 * a * e),
                            local_rotation(d[b], side, -20 * a * e),
                        )
                    _add(layers, b, k, m)
            elif g.kind == "trunk_drink" and rig.trunk:
                # dip (0-0.3) -> suck with a wobble (0.3-0.75) -> lift and curl toward the mouth (0.75-1)
                dip = _smooth(u / 0.3) * (1 - _smooth((u - 0.75) / 0.2))
                lift = _smooth((u - 0.75) / 0.2) * e
                turn((40 * dip) * a * e, side, head_share=0.75)
                nb = len(rig.trunk)
                for i, b in enumerate(rig.trunk):
                    w = (i + 1) / nb
                    wob = 6 * math.sin(2 * math.pi * 3.0 * t + i) * (0.3 < u < 0.78) * w
                    m = local_rotation(d[b], side, (12 * dip * (1 - w) - 30 * lift * w) * a * e)
                    _add(layers, b, k, mat_mul(local_rotation(d[b], up, wob * e), m))
            elif g.kind == "trunk_spray" and rig.trunk:
                # wind-up (0-0.3): trunk rises and aims; fire (0.3-0.65): a recoil jolt; relax
                aim = 0.0
                if targets and g.target in targets:
                    q = targets[g.target][min(k, len(targets[g.target]) - 1)]
                    aim = max(-MAX_TURN, min(MAX_TURN, wrap(heading_to(p.root, q.root) - p.yaw)))
                rise = _smooth(u / 0.3)
                jolt = math.exp(-(((u - 0.34) / 0.05) ** 2))
                turn((aim * 0.8 * rise) * e, up, head_share=0.5)
                turn((-14 * rise - 6 * jolt) * a * e, side, head_share=0.9)
                nb = len(rig.trunk)
                for i, b in enumerate(rig.trunk):
                    w = (i + 1) / nb
                    m = mat_mul(
                        local_rotation(d[b], up, aim * 0.2 * rise * e / nb),
                        local_rotation(d[b], side, (-34 * rise * (0.5 + w) + 8 * jolt * w) * a * e),
                    )
                    _add(layers, b, k, m)
    return layers


def spray_droplets(
    cid: str,
    tips: dict[int, V3],
    target_head: V3,
    fps: int,
    n_frames: int,
    count: int = 110,
    seed: int = 3,
    flight: float = 0.45,
) -> list[dict]:
    """A jet of water from the trunk tip (``tips``: frame -> world position over the firing window) on
    ballistic arcs that land on ``target_head``, then splatter and drip to the ground.

    Drops are small ellipsoids stretched along their velocity (a cheap motion streak) and keyed per frame;
    each is scaled to 0 before launch and when it reaches the ground. The jet is tight (a few cm of
    spread) so it reads as one stream, not a cloud of bubbles.
    """
    import random

    rng = random.Random(seed)
    frames = sorted(tips)
    g = -9.81
    sizes = [rng.uniform(0.01, 0.022) for _ in range(count)]
    ops: list[dict] = [
        {
            "op": "create_primitive",
            "id": f"{cid}_drop_{i:02d}",
            "shape": "uv_sphere",
            "size": [s, s, s],
            "location": list(tips[frames[0]]),
            "segments": 8,
            "tags": ["fx", "spray"],
        }
        for i, s in enumerate(sizes)
    ]
    ops.append(
        {
            "op": "set_material",
            "targets": [f"{cid}_drop_{i:02d}" for i in range(count)],
            "material": {
                "name": "spray_water",
                "base_color": "#B9D9E8",
                "roughness": 0.05,
                "specular": 1.0,
                "emission": "#DDEFFF",
                "emission_strength": 0.12,
                "alpha": 0.85,
            },
        }
    )

    def orient(v: V3) -> list[float]:
        # Euler XYZ (degrees) that turns local +X onto v: Ry tilts X down, Rz swings it around
        b = -math.degrees(math.atan2(v[2], math.hypot(v[0], v[1])))
        c = math.degrees(math.atan2(v[1], v[0]))
        return [0.0, round(b, 2), round(c, 2)]

    for i in range(count):
        f_launch = frames[min(len(frames) - 1, int(i / count * len(frames)))]
        p0 = tips[f_launch]
        T = flight * rng.uniform(0.92, 1.08)
        aim = (
            target_head[0] + rng.gauss(0, 0.05),
            target_head[1] + rng.gauss(0, 0.05),
            target_head[2] + rng.gauss(0.0, 0.05),
        )
        v = ((aim[0] - p0[0]) / T, (aim[1] - p0[1]) / T, (aim[2] - p0[2] - 0.5 * g * T * T) / T)
        loc_keys, rot_keys, stretch = [], [], []
        f_end = n_frames
        land_v = None
        f = f_launch
        while f <= n_frames:
            tau = (f - f_launch) / fps
            if tau <= T:
                pos = (p0[0] + v[0] * tau, p0[1] + v[1] * tau, p0[2] + v[2] * tau + 0.5 * g * tau * tau)
                vel = (v[0], v[1], v[2] + g * tau)
                st = 3.2
            else:  # hit: splatter outward a little and drip down the target
                if land_v is None:
                    land_v = (v[0] * 0.1 + rng.gauss(0, 0.35), v[1] * 0.1 + rng.gauss(0, 0.35), 0.5)
                dt = tau - T
                pos = (
                    aim[0] + land_v[0] * dt,
                    aim[1] + land_v[1] * dt,
                    aim[2] + land_v[2] * dt + 0.5 * g * dt * dt,
                )
                vel = (land_v[0], land_v[1], land_v[2] + g * dt)
                st = 1.0 + min(1.5, 0.25 * math.sqrt(sum(c * c for c in vel)))
            if pos[2] < 0.0:
                f_end = f
                break
            loc_keys.append([f, [round(c, 4) for c in pos], "LINEAR"])
            rot_keys.append([f, orient(vel), "LINEAR"])
            stretch.append((f, st))
            f += 1
        did = f"{cid}_drop_{i:02d}"
        scale_keys: list[list] = [[1, [0.0, 0.0, 0.0], "CONSTANT"]]
        if f_launch > 1:
            scale_keys.append([f_launch - 1, [0.0, 0.0, 0.0], "CONSTANT"])
        scale_keys += [[f, [round(st, 2), 1.0, 1.0], "CONSTANT"] for f, st in stretch]
        scale_keys.append([f_end, [0.0, 0.0, 0.0], "CONSTANT"])
        if loc_keys:
            ops.append({"op": "insert_keyframes", "target": did, "property": "location", "keys": loc_keys})
            ops.append({"op": "insert_keyframes", "target": did, "property": "rotation", "keys": rot_keys})
        ops.append({"op": "insert_keyframes", "target": did, "property": "scale", "keys": scale_keys})
    return ops
