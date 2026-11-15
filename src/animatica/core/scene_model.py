"""USD-shaped, text-based scene model.

Prims keyed by stable agent-chosen ids, with a type, parent, local transform (xformOp-like:
translate / rotateXYZ degrees / scale), material binding and animated-property names. It is kept in
sync by replaying successful batch ops, and can be diffed against a snapshot queried from the engine
(to detect artist edits) or against a declarative spec (spec mode -> minimal ops).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .protocol import Batch

_EPS = 1e-3


@dataclass
class Prim:
    id: str
    type: str  # mesh | empty | light | camera | armature | sound
    parent: str | None = None
    translate: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotate: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    material: str | None = None  # base colour hex
    animated: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


_CREATE_TYPES = {
    "create_primitive": "mesh",
    "create_mesh": "mesh",
    "create_empty": "empty",
    "add_light": "light",
    "add_camera": "camera",
    "create_armature": "armature",
    "import_asset": "empty",
}


class SceneModel:
    def __init__(self) -> None:
        self.prims: dict[str, Prim] = {}

    # --------------------------------------------------------------- replay
    def apply(self, batch: Batch) -> None:
        for op in batch.ops:
            d = op.model_dump()
            kind = d["op"]
            if kind in _CREATE_TYPES:
                self.prims[d["id"]] = Prim(
                    id=d["id"],
                    type=_CREATE_TYPES[kind],
                    parent=d.get("parent"),
                    translate=list(d.get("location", (0, 0, 0))),
                    rotate=list(d.get("rotation", (0, 0, 0))),
                    scale=list(d.get("scale", (1, 1, 1))),
                    tags=list(d.get("tags", [])),
                )
            elif kind == "delete":
                for t in d["targets"]:
                    self.prims.pop(t, None)
            elif kind == "transform" and d["target"] in self.prims:
                p = self.prims[d["target"]]
                if d.get("location") is not None:
                    p.translate = list(d["location"])
                if d.get("rotation") is not None:
                    p.rotate = list(d["rotation"])
                if d.get("scale") is not None:
                    p.scale = list(d["scale"])
            elif kind == "parent" and d["child"] in self.prims:
                self.prims[d["child"]].parent = d.get("parent")
            elif kind == "set_material":
                for t in d["targets"]:
                    if t in self.prims:
                        self.prims[t].material = d["material"]["base_color"].upper()
            elif kind == "insert_keyframes" and d["target"] in self.prims:
                p = self.prims[d["target"]]
                if d["property"] not in p.animated:
                    p.animated.append(d["property"])

    # --------------------------------------------------------------- engine snapshot diff
    def diff_snapshot(self, objects: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
        """Compare against an engine query (fields type, transform, material, parent).

        Returns {id: [changed aspects]} including "added" / "deleted". Animated transform channels are
        ignored for transform comparison (their value depends on the current frame).
        """
        changes: dict[str, list[str]] = {}
        for oid, o in objects.items():
            p = self.prims.get(oid)
            if p is None:
                changes[oid] = ["added"]
                continue
            aspects = []
            animated = set(p.animated)
            if "location" not in animated and _differs(o.get("location"), p.translate):
                aspects.append("transform")
            elif "rotation" not in animated and _differs(o.get("rotation"), p.rotate, 0.5):
                aspects.append("transform")
            elif "scale" not in animated and _differs(o.get("scale"), p.scale):
                aspects.append("transform")
            mat = (o.get("material") or {}).get("base_color")
            if mat and p.material and _hex_dist(mat, p.material) > 6:
                aspects.append("material")
            if "parent" in o and o.get("parent") != p.parent:
                aspects.append("parent")
            if aspects:
                changes[oid] = aspects
        for oid in self.prims:
            if oid not in objects and self.prims[oid].type != "sound":
                changes[oid] = ["deleted"]
        return changes

    def absorb_snapshot(self, objects: dict[str, dict[str, Any]]) -> None:
        """Make the model match the engine (after accepting artist edits as authoritative)."""
        for oid, o in objects.items():
            p = self.prims.get(oid) or Prim(id=oid, type=o.get("type", "mesh"))
            if o.get("location") is not None and "location" not in p.animated:
                p.translate = list(o["location"])
            if o.get("rotation") is not None and "rotation" not in p.animated:
                p.rotate = list(o["rotation"])
            if o.get("scale") is not None and "scale" not in p.animated:
                p.scale = list(o["scale"])
            if (o.get("material") or {}).get("base_color"):
                p.material = o["material"]["base_color"].upper()
            if "parent" in o:
                p.parent = o["parent"]
            self.prims[oid] = p
        for oid in [k for k in self.prims if k not in objects]:
            del self.prims[oid]

    # --------------------------------------------------------------- spec mode
    def spec_to_ops(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        """Declarative desired state -> minimal op list.

        spec = {"objects": {id: {"location": [...], "rotation": [...], "scale": [...], "material": {...},
                                 "create": {...create op fields...} | absent, "delete": bool}}}
        """
        ops: list[dict[str, Any]] = []
        for oid, want in (spec.get("objects") or {}).items():
            p = self.prims.get(oid)
            if want.get("delete"):
                if p is not None:
                    ops.append({"op": "delete", "targets": [oid]})
                continue
            if p is None:
                create = dict(want.get("create") or {})
                if not create:
                    raise ValueError(f"spec: {oid!r} does not exist and has no 'create'")
                create.setdefault("op", "create_primitive")
                create["id"] = oid
                for k in ("location", "rotation", "scale"):
                    if k in want:
                        create[k] = want[k]
                ops.append(create)
            else:
                tr: dict[str, Any] = {}
                if "location" in want and _differs(want["location"], p.translate):
                    tr["location"] = want["location"]
                if "rotation" in want and _differs(want["rotation"], p.rotate, 0.5):
                    tr["rotation"] = want["rotation"]
                if "scale" in want and _differs(want["scale"], p.scale):
                    tr["scale"] = want["scale"]
                if tr:
                    ops.append({"op": "transform", "target": oid, **tr})
            mat = want.get("material")
            if mat and (
                p is None or not p.material or p.material.upper() != mat.get("base_color", "").upper()
            ):
                ops.append({"op": "set_material", "targets": [oid], "material": mat})
        return ops

    # --------------------------------------------------------------- io
    def to_dict(self) -> dict[str, Any]:
        return {"prims": {k: asdict(v) for k, v in self.prims.items()}}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SceneModel:
        m = cls()
        for k, v in (d.get("prims") or {}).items():
            m.prims[k] = Prim(**v)
        return m

    def to_usda(self) -> str:
        """Minimal USDA text export (Xforms + display colour) — groundwork for OpenUSD interop."""
        lines = [
            "#usda 1.0",
            '(defaultPrim = "World" upAxis = "Z" metersPerUnit = 1)',
            "",
            'def Xform "World"',
            "{",
        ]
        children: dict[str | None, list[Prim]] = {}
        for p in self.prims.values():
            children.setdefault(p.parent if p.parent in self.prims else None, []).append(p)

        def emit(p: Prim, depth: int) -> None:
            ind = "    " * depth
            usd_type = {"mesh": "Xform", "empty": "Xform", "light": "SphereLight", "camera": "Camera"}.get(
                p.type, "Xform"
            )
            name = p.id.replace(".", "_").replace("-", "_")
            lines.append(f'{ind}def {usd_type} "{name}"')
            lines.append(f"{ind}{{")
            lines.append(f"{ind}    double3 xformOp:translate = ({', '.join(f'{v:g}' for v in p.translate)})")
            lines.append(f"{ind}    float3 xformOp:rotateXYZ = ({', '.join(f'{v:g}' for v in p.rotate)})")
            lines.append(f"{ind}    float3 xformOp:scale = ({', '.join(f'{v:g}' for v in p.scale)})")
            lines.append(
                f'{ind}    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]'
            )
            if p.material:
                r, g, b = (int(p.material[i : i + 2], 16) / 255 for i in (1, 3, 5))
                lines.append(f"{ind}    color3f[] primvars:displayColor = [({r:.3f}, {g:.3f}, {b:.3f})]")
            for c in children.get(p.id, []):
                emit(c, depth + 1)
            lines.append(f"{ind}}}")

        for p in children.get(None, []):
            emit(p, 1)
        lines.append("}")
        return "\n".join(lines) + "\n"


def _differs(a: Any, b: Any, tol: float = _EPS) -> bool:
    if a is None or b is None:
        return False
    return any(abs(float(x) - float(y)) > tol for x, y in zip(a, b))


def _hex_dist(a: str, b: str) -> int:
    return max(abs(int(a[i : i + 2], 16) - int(b[i : i + 2], 16)) for i in (1, 3, 5))
