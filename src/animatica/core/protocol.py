"""Batched operation protocol (v0).

One batch = a list of operations validated as a whole, executed in one round-trip, applied as one
undo step. This module is the single source of truth for every adapter: it defines the operation
models (Pydantic), the semantic validator, and the compact result format.

Adapters receive batches as plain JSON (``Batch.model_dump(mode="json")``) so they never need to
import this package (the Blender adapter is GPL and lives in a separate process).
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

PROTOCOL_VERSION = "0.1"
ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{0,62}$")
MAX_COORD = 10_000.0
MAX_FRAME = 100_000

Vec3 = tuple[float, float, float]
Interp = Literal["CONSTANT", "LINEAR", "BEZIER", "EASE_IN", "EASE_OUT", "EASE_IN_OUT", "BACK", "ELASTIC", "BOUNCE"]


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def creates(self) -> list[str]:
        return []

    def references(self) -> list[str]:
        return []

    def deletes(self) -> list[str]:
        return []


class _Placed(_Op):
    location: Vec3 = (0.0, 0.0, 0.0)
    rotation: Vec3 = (0.0, 0.0, 0.0)  # Euler XYZ, degrees
    scale: Vec3 = (1.0, 1.0, 1.0)
    parent: str | None = None
    collection: str | None = None
    tags: list[str] = Field(default_factory=list)

    def references(self) -> list[str]:
        return [self.parent] if self.parent else []


class MaterialSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    base_color: str = "#CCCCCC"
    metallic: float = Field(0.0, ge=0, le=1)
    roughness: float = Field(0.5, ge=0, le=1)
    emission: str | None = None
    emission_strength: float = Field(0.0, ge=0, le=1000)
    alpha: float = Field(1.0, ge=0, le=1)
    noise: float = Field(0.0, ge=0, le=1)  # procedural grime/variation amount (darker patches)
    noise_scale: float = Field(2.0, gt=0, le=1000)
    fade_to: str | None = None  # aerial perspective: blend toward this colour with distance from origin
    fade_start: float = Field(15.0, ge=0)
    fade_end: float = Field(90.0, gt=0)
    radial_glow: bool = False  # emission fades to transparent at the edges (sun/moon halos)

    @field_validator("base_color", "emission", "fade_to")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            raise ValueError(f"color must be #RRGGBB, got {v!r}")
        return v


class CreatePrimitive(_Placed):
    op: Literal["create_primitive"]
    id: str
    shape: Literal["cube", "uv_sphere", "ico_sphere", "cylinder", "cone", "torus", "plane", "circle"]
    size: Vec3 | None = None  # full dimensions (cube/plane); overrides radius/depth semantics
    radius: float | None = Field(None, gt=0, le=MAX_COORD)
    depth: float | None = Field(None, gt=0, le=MAX_COORD)
    segments: int = Field(32, ge=3, le=256)
    smooth: bool = False

    def creates(self) -> list[str]:
        return [self.id]


class CreateMesh(_Placed):
    op: Literal["create_mesh"]
    id: str
    vertices: list[Vec3] = Field(min_length=1, max_length=200_000)
    faces: list[list[int]] = Field(default_factory=list)
    smooth: bool = False

    def creates(self) -> list[str]:
        return [self.id]


class CreateEmpty(_Placed):
    op: Literal["create_empty"]
    id: str
    display: Literal["PLAIN_AXES", "ARROWS", "SPHERE", "CUBE"] = "PLAIN_AXES"
    display_size: float = Field(0.2, gt=0)

    def creates(self) -> list[str]:
        return [self.id]


class Delete(_Op):
    op: Literal["delete"]
    targets: list[str] = Field(min_length=1)

    def references(self) -> list[str]:
        return list(self.targets)

    def deletes(self) -> list[str]:
        return list(self.targets)


class Transform(_Op):
    op: Literal["transform"]
    target: str
    location: Vec3 | None = None
    rotation: Vec3 | None = None
    scale: Vec3 | None = None

    def references(self) -> list[str]:
        return [self.target]


class Parent(_Op):
    op: Literal["parent"]
    child: str
    parent: str | None  # None = clear parent
    keep_transform: bool = True

    def references(self) -> list[str]:
        return [self.child] + ([self.parent] if self.parent else [])


class AddModifier(_Op):
    op: Literal["add_modifier"]
    target: str
    type: Literal["bevel", "subsurf", "array", "solidify", "displace", "mirror", "smooth", "wireframe", "decimate"]
    name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    def references(self) -> list[str]:
        return [self.target]


class SetMaterial(_Op):
    op: Literal["set_material"]
    targets: list[str] = Field(min_length=1)
    material: MaterialSpec

    def references(self) -> list[str]:
        return list(self.targets)


class AddLight(_Placed):
    op: Literal["add_light"]
    id: str
    light_type: Literal["sun", "point", "area", "spot"] = "point"
    energy: float = Field(100.0, ge=0, le=1e7)
    color: str = "#FFFFFF"
    size: float = Field(0.25, ge=0, le=1000)
    spot_angle: float = Field(45.0, gt=0, le=180)

    def creates(self) -> list[str]:
        return [self.id]


class AddCamera(_Placed):
    op: Literal["add_camera"]
    id: str
    lens: float = Field(50.0, ge=1, le=5000)
    look_at: str | Vec3 | None = None
    dof_target: str | None = None
    fstop: float = Field(2.8, gt=0, le=128)

    def creates(self) -> list[str]:
        return [self.id]

    def references(self) -> list[str]:
        refs = super().references()
        if isinstance(self.look_at, str):
            refs.append(self.look_at)
        if self.dof_target:
            refs.append(self.dof_target)
        return refs


class SetCameraActive(_Op):
    op: Literal["set_camera_active"]
    id: str
    frame: int | None = Field(None, ge=0, le=MAX_FRAME)  # if set: camera cut marker at that frame

    def references(self) -> list[str]:
        return [self.id]


class AddConstraint(_Op):
    op: Literal["add_constraint"]
    target: str
    type: Literal["track_to", "damped_track", "copy_location", "child_of", "limit_location"]
    subject: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    def references(self) -> list[str]:
        return [self.target] + ([self.subject] if self.subject else [])


Keyframe = tuple[int, Union[float, Vec3], Interp]


class InsertKeyframes(_Op):
    """Batched keyframes: one op sets many keys on one property.

    property: ``location`` | ``rotation`` (degrees) | ``scale`` | ``shape_key:<name>`` |
    ``light.energy`` | ``light.color`` | ``camera.lens`` | ``material.emission_strength`` |
    ``hide`` (0/1)
    """

    op: Literal["insert_keyframes"]
    target: str
    property: str
    keys: list[Keyframe] = Field(min_length=1, max_length=100_000)
    index: int | None = Field(None, ge=0, le=2)  # animate a single channel with scalar values

    def references(self) -> list[str]:
        return [self.target]


class ClearAnimation(_Op):
    op: Literal["clear_animation"]
    targets: list[str] = Field(min_length=1)
    shape_keys: bool = True

    def references(self) -> list[str]:
        return list(self.targets)


class SetFrameRange(_Op):
    op: Literal["set_frame_range"]
    start: int = Field(1, ge=0, le=MAX_FRAME)
    end: int = Field(..., ge=1, le=MAX_FRAME)
    fps: int = Field(24, ge=1, le=240)


class Bone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    head: Vec3
    tail: Vec3
    parent: str | None = None


class CreateArmature(_Placed):
    op: Literal["create_armature"]
    id: str
    bones: list[Bone] = Field(min_length=1)

    def creates(self) -> list[str]:
        return [self.id]


class BindMeshToArmature(_Op):
    op: Literal["bind_mesh_to_armature"]
    mesh: str
    armature: str
    bone: str | None = None  # rigid bind to one bone; None = automatic weights

    def references(self) -> list[str]:
        return [self.mesh, self.armature]


class AddShapeKeys(_Op):
    """Add named shape keys. ``keys`` maps name -> per-vertex absolute positions (len == vert count)."""

    op: Literal["add_shape_keys"]
    target: str
    keys: dict[str, list[Vec3]] = Field(min_length=1)

    def references(self) -> list[str]:
        return [self.target]


class ImportAsset(_Placed):
    op: Literal["import_asset"]
    id: str
    path: str
    format: Literal["gltf", "glb", "obj", "fbx", "usd"] | None = None

    def creates(self) -> list[str]:
        return [self.id]


class AddSoundStrip(_Op):
    op: Literal["add_sound_strip"]
    id: str
    path: str
    frame_start: int = Field(1, ge=0, le=MAX_FRAME)
    channel: int = Field(1, ge=1, le=128)
    volume: float = Field(1.0, ge=0, le=10)


class SetWorld(_Op):
    op: Literal["set_world"]
    zenith: str = "#4A6FA5"
    horizon: str = "#F2B880"
    ground: str | None = None
    glow: str | None = None  # optional band between horizon and zenith (sunset pinks, etc.)
    strength: float = Field(1.0, ge=0, le=100)
    mist: float = Field(0.0, ge=0, le=1)


class SetRender(_Op):
    op: Literal["set_render"]
    engine: Literal["workbench", "eevee", "cycles"] | None = None
    resolution: tuple[int, int] | None = None
    samples: int | None = Field(None, ge=1, le=4096)
    fps: int | None = Field(None, ge=1, le=240)
    look: str | None = None
    exposure: float | None = Field(None, ge=-10, le=10)


class RenderPreview(_Op):
    op: Literal["render_preview"]
    path: str | None = None
    frame: int | None = Field(None, ge=0, le=MAX_FRAME)
    camera: str = "auto"
    resolution: tuple[int, int] = (480, 270)
    engine: Literal["workbench", "eevee", "cycles"] = "workbench"


class RenderFinal(_Op):
    op: Literal["render_final"]
    output_dir: str
    frame_start: int | None = None
    frame_end: int | None = None
    frame_step: int = Field(1, ge=1, le=100)


class Save(_Op):
    op: Literal["save"]
    path: str


class Query(_Op):
    op: Literal["query"]
    ids: list[str] | None = None
    types: list[str] | None = None
    tag: str | None = None
    fields: list[Literal["transform", "bbox", "material", "parent", "type", "shape_keys", "animation", "tags"]] = Field(
        default_factory=lambda: ["type", "transform"]
    )
    limit: int = Field(200, ge=1, le=10_000)


class Inspect(_Op):
    """Cheap geometric checks used by the Critic (frustum, floor contact, motion, mouth activity)."""

    op: Literal["inspect"]
    subjects: list[str] = Field(min_length=1)
    frames: list[int] = Field(min_length=1, max_length=2000)
    floor_z: float = 0.0
    camera: str | None = None
    shape_key_target: str | None = None

    def references(self) -> list[str]:
        return list(self.subjects) + ([self.camera] if self.camera else [])


class SetProperty(_Op):
    """Escape hatch for simple data paths, e.g. ``{"target": "sun", "path": "data.angle", "value": 0.1}``."""

    op: Literal["set_property"]
    target: str
    path: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_.]*$")
    value: Any

    def references(self) -> list[str]:
        return [self.target]


OP_CLASSES: tuple[type[_Op], ...] = (
    CreatePrimitive, CreateMesh, CreateEmpty, Delete, Transform, Parent, AddModifier, SetMaterial,
    AddLight, AddCamera, SetCameraActive, AddConstraint, InsertKeyframes, ClearAnimation, SetFrameRange, CreateArmature,
    BindMeshToArmature, AddShapeKeys, ImportAsset, AddSoundStrip, SetWorld, SetRender, RenderPreview,
    RenderFinal, Save, Query, Inspect, SetProperty,
)
Operation = Annotated[Union[OP_CLASSES], Field(discriminator="op")]  # type: ignore[valid-type]
OP_NAMES = sorted(c.model_fields["op"].annotation.__args__[0] for c in OP_CLASSES)  # type: ignore[union-attr]


class VerifySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview: bool = False
    camera: str = "auto"
    resolution: tuple[int, int] = (480, 270)
    frame: int | None = None


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    agent: str = "user"
    intent: str = ""
    mode: Literal["ops", "script", "spec"] = "ops"
    ops: list[Operation] = Field(default_factory=list, max_length=50_000)
    script: str | None = None
    script_timeout_s: float = Field(30.0, gt=0, le=600)
    spec: dict[str, Any] | None = None
    verify: VerifySpec = Field(default_factory=VerifySpec)
    locked: list[str] = Field(default_factory=list)  # ids an artist owns; agents may not modify them


class BatchResult(BaseModel):
    batch_id: str
    ok: bool
    created: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    preview: str | None = None
    undo_token: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)  # query/inspect payloads, kept compact
    elapsed_ms: int = 0

    def summary(self) -> str:
        status = "ok" if self.ok else "FAILED"
        parts = [f"{self.batch_id}: {status}"]
        for name in ("created", "modified", "deleted"):
            vals = getattr(self, name)
            if vals:
                parts.append(f"{name} {len(vals)}")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warnings")
        if self.errors:
            parts.append("errors: " + "; ".join(self.errors[:3]))
        return ", ".join(parts)


class BatchValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


_batch_adapter = TypeAdapter(Batch)


def _finite(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            errors.append(f"{path}: number must be finite")
        elif abs(value) > MAX_COORD * 100:
            errors.append(f"{path}: value {value} out of range")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _finite(v, f"{path}[{i}]", errors)
    elif isinstance(value, dict):
        for k, v in value.items():
            _finite(v, f"{path}.{k}", errors)


def parse_batch(data: dict[str, Any] | Batch) -> Batch:
    """Schema-validate a raw batch. Raises BatchValidationError with precise, path-qualified errors."""
    if isinstance(data, Batch):
        return data
    try:
        return _batch_adapter.validate_python(data)
    except ValidationError as exc:
        errs = []
        for e in exc.errors()[:20]:
            loc = ".".join(str(p) for p in e["loc"])
            errs.append(f"{loc}: {e['msg']}")
        raise BatchValidationError(errs) from None


def validate_batch(data: dict[str, Any] | Batch, existing_ids: set[str] | None = None) -> Batch:
    """Schema + semantic validation of a whole batch before anything touches the scene.

    Semantic checks: ids well-formed and unique, referenced ids exist (in the scene or created earlier
    in the batch), numbers finite and in range, keyframes strictly ordered, locked ids untouched,
    mode/payload consistency.
    """
    batch = parse_batch(data)
    errors: list[str] = []
    known = set(existing_ids or set())
    created_here: set[str] = set()
    locked = set(batch.locked)

    if batch.mode == "script" and not batch.script:
        errors.append("mode 'script' requires a non-empty 'script'")
    if batch.mode == "spec" and not batch.spec:
        errors.append("mode 'spec' requires 'spec'")
    if batch.mode == "ops" and batch.script:
        errors.append("'script' given but mode is 'ops'")

    frame_end: int | None = None
    for i, op in enumerate(batch.ops):
        p = f"ops[{i}]({op.op})"
        _finite(op.model_dump(), p, errors)
        for new_id in op.creates():
            if not ID_RE.match(new_id):
                errors.append(f"{p}: invalid id {new_id!r} (letters, digits, _ . - ; max 63 chars)")
            if new_id in known or new_id in created_here:
                errors.append(f"{p}: duplicate id {new_id!r}")
            created_here.add(new_id)
        for ref in op.references():
            if ref not in known and ref not in created_here:
                errors.append(f"{p}: unknown id {ref!r}")
        touched = set(op.references())
        if isinstance(op, (Transform, SetMaterial, Delete, InsertKeyframes, AddModifier, SetProperty)):
            hit = touched & locked
            if hit:
                errors.append(f"{p}: ids {sorted(hit)} are locked by the artist")
        if isinstance(op, Delete):
            for d in op.deletes():
                known.discard(d)
                created_here.discard(d)
        if isinstance(op, SetFrameRange):
            if op.end < op.start:
                errors.append(f"{p}: end {op.end} < start {op.start}")
            frame_end = op.end
        if isinstance(op, InsertKeyframes):
            frames = [k[0] for k in op.keys]
            if any(b <= a for a, b in zip(frames, frames[1:])):
                errors.append(f"{p}: keyframes must be strictly increasing by frame")
            if any(f < 0 or f > MAX_FRAME for f in frames):
                errors.append(f"{p}: frame out of range")
            if frame_end is not None and frames and frames[-1] > frame_end + 1000:
                errors.append(f"{p}: keyframe {frames[-1]} far beyond frame range end {frame_end}")
            kinds = {isinstance(k[1], (tuple, list)) for k in op.keys}
            if len(kinds) > 1:
                errors.append(f"{p}: mix of scalar and vector values")
            if op.index is not None and True in kinds:
                errors.append(f"{p}: 'index' given, values must be scalars")
            vec_props = {"location", "rotation", "scale", "light.color"}
            if op.index is None and op.property in vec_props and False in kinds:
                errors.append(f"{p}: property {op.property!r} needs vector values or an 'index'")
            if not re.fullmatch(
                r"location|rotation|scale|hide|shape_key:[\w .\-]+|light\.(energy|color)|camera\.lens|material\.emission_strength",
                op.property,
            ):
                errors.append(f"{p}: unsupported property {op.property!r}")
        if isinstance(op, AddShapeKeys):
            lengths = {len(v) for v in op.keys.values()}
            if len(lengths) > 1:
                errors.append(f"{p}: all shape keys must have the same vertex count")
        if isinstance(op, CreateMesh):
            n = len(op.vertices)
            for fi, face in enumerate(op.faces):
                if len(face) < 3:
                    errors.append(f"{p}: face {fi} has fewer than 3 vertices")
                if any(v < 0 or v >= n for v in face):
                    errors.append(f"{p}: face {fi} references a vertex out of range")
    if errors:
        raise BatchValidationError(errors[:50])
    return batch


def batch_json_schema() -> dict[str, Any]:
    return Batch.model_json_schema()
