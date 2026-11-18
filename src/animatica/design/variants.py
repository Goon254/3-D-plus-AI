"""Parametric morphs of a species: the N design candidates (DESIGN_STAGE.md §3).

A :class:`Morph` is a handful of multipliers applied to a :class:`Species` without touching its skeleton
layout, so every candidate keeps the validated rig, gait scaling and face placement:

* ``head``  scales the head (size, eyes, ears, muzzle and head-carried extras) about its centre; the trunk
  moves with the front of the face.
* ``eye``   eye radius, ``ear`` ear size, ``snout`` muzzle length (its back edge stays put).
* ``leg``   leg and foot radius, ``neck`` neck radius.
* ``lift_dark`` mixes near-black body regions toward the coat (0 = unchanged, 1 = coat colour), except the
  brief's intended dark accents.

Morphs are deterministic: :func:`candidates` returns the base design plus a fixed spread around it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from animatica.creatures.species import Chain, Species
from animatica.design.measure import luminance

V3 = tuple[float, float, float]


@dataclass(frozen=True)
class Morph:
    head: float = 1.0
    eye: float = 1.0
    ear: float = 1.0
    snout: float = 1.0
    leg: float = 1.0
    neck: float = 1.0
    lift_dark: float = 0.0

    def combine(self, other: Morph) -> Morph:
        return Morph(
            head=self.head * other.head,
            eye=self.eye * other.eye,
            ear=self.ear * other.ear,
            snout=self.snout * other.snout,
            leg=self.leg * other.leg,
            neck=self.neck * other.neck,
            lift_dark=min(1.0, max(self.lift_dark, other.lift_dark)),
        )

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 4) for k, v in asdict(self).items()}

    @property
    def is_identity(self) -> bool:
        return self == Morph()


def _s(v: V3, k: float) -> V3:
    return (v[0] * k, v[1] * k, v[2] * k)


def _r4(v: V3) -> V3:
    return (round(v[0], 5), round(v[1], 5), round(v[2], 5))


def _mix(a: str, b: str, u: float) -> str:
    ca = [int(a.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * u):02X}" for x, y in zip(ca, cb))


def _darken(hex_color: str, k: float) -> str:
    return _mix(hex_color, "#000000", k)


def apply_morph(sp: Species, m: Morph, dark_ok: tuple[str, ...] = ()) -> Species:
    if m.is_identity:
        return sp
    k = m.head
    hw, hl, hh = sp.head_size
    ex, ey, ez, er = sp.eye
    ear_shape, ear_size, ear_off, ear_rot = sp.ear
    muzzle = sp.muzzle
    if muzzle is not None:
        msize, moff = _s(muzzle[0], k), _s(muzzle[1], k)
        grow = msize[1] * (m.snout - 1.0)
        muzzle = (_r4((msize[0], msize[1] * m.snout, msize[2])), _r4((moff[0], moff[1] - grow / 2, moff[2])))
    snout_tip = sp.snout_tip
    if snout_tip is not None:  # the cone follows the head; ``snout`` lengthens it
        (tx, ty, tz), tr = snout_tip
        snout_tip = (_r4((tx * k, ty * k * m.snout, tz * k)), round(tr * k, 5))
    extras = tuple(
        replace(e, size=_r4(_s(e.size, k)), loc=_r4(_s(e.loc, k))) if e.bone == "head" else e
        for e in sp.extras
    )
    trunk = sp.trunk
    if trunk is not None:  # the trunk hangs from the front of the face: follow it as the head grows
        dy = -(hl * k - hl) / 2
        dz = -(hh * k - hh) * 0.15
        trunk = Chain(
            _r4((trunk.base[0], trunk.base[1] + dy, trunk.base[2] + dz)),
            _r4((trunk.tip[0], trunk.tip[1] + dy, trunk.tip[2] + dz)),
            trunk.bones,
            round(trunk.r0 * k, 5),
            round(trunk.r1 * k, 5),
        )
    neck = Chain(
        sp.neck.base, sp.neck.tip, sp.neck.bones, round(sp.neck.r0 * m.neck, 5), round(sp.neck.r1 * m.neck, 5)
    )
    leg_r = tuple(round(r * m.leg, 5) for r in sp.leg_r)
    foot = (sp.foot[0], round(sp.foot[1] * m.leg, 5), sp.foot[2])
    mats = dict(sp.mats)
    if m.lift_dark > 0:
        coat = str(sp.coat["base_color"])
        for _bones, key in sp.regions:
            mat = mats.get(key)
            if key in dark_ok or not mat or "base_color" not in mat:
                continue
            shade = _darken(coat, 0.45)
            if luminance(str(mat["base_color"])) < 0.02:  # a black block: a darker shade of the coat instead
                mat = {**mat, "base_color": _mix(str(mat["base_color"]), shade, m.lift_dark)}
            if any(luminance(str(mk["color"])) < 0.02 for mk in mat.get("marks") or []):
                mat = {
                    **mat,
                    "marks": [
                        {**mk, "color": _mix(str(mk["color"]), shade, m.lift_dark)}
                        if luminance(str(mk["color"])) < 0.02
                        else mk
                        for mk in mat["marks"]
                    ],
                }
            mats[key] = mat
    return replace(
        sp,
        head_size=_r4(_s(sp.head_size, k)),
        eye=(round(ex * k, 5), round(ey * k, 5), round(ez * k, 5), round(er * k * m.eye, 5)),
        ear=(ear_shape, _r4(_s(ear_size, k * m.ear)), _r4(_s(ear_off, k)), ear_rot),
        muzzle=muzzle,
        snout_tip=snout_tip,
        extras=extras,
        trunk=trunk,
        neck=neck,
        leg_r=leg_r,  # type: ignore[arg-type]
        foot=foot,
        mats=mats,
    )


# A fixed spread around the base: bigger/smaller head, eyes, ears, snout, legs; one "kids' film" push.
SPREAD: tuple[Morph, ...] = (
    Morph(),
    Morph(head=1.1, eye=1.08),
    Morph(head=0.94, eye=1.12, ear=1.1),
    Morph(eye=1.15, snout=0.88, neck=0.92),
    Morph(head=1.06, ear=0.9, leg=1.12, lift_dark=0.6),
    Morph(head=1.14, eye=1.1, snout=0.92, leg=1.06, neck=0.9, lift_dark=0.8),
)


def candidates(
    sp: Species, n: int = 6, start: Morph | None = None, dark_ok: tuple[str, ...] = ()
) -> list[tuple[Morph, Species]]:
    """The base (``start``) plus ``n - 1`` spread morphs composed on top of it."""
    base = start or Morph()
    out = []
    for m in SPREAD[: max(1, min(n, len(SPREAD)))]:
        mm = base.combine(m)
        out.append((mm, apply_morph(sp, mm, dark_ok)))
    return out


def morph_from_dict(d: dict[str, Any]) -> Morph:
    return Morph(**{k: float(v) for k, v in d.items() if k in Morph.__dataclass_fields__})


__all__ = ["Morph", "apply_morph", "candidates", "morph_from_dict", "SPREAD"]
