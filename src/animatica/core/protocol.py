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
Interp = Literal[
    "CONSTANT", "LINEAR", "BEZIER", "EASE_IN", "EASE_OUT", "EASE_IN_OUT", "BACK", "ELASTIC", "BOUNCE"
]


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
    # False: the object casts no shadow (e.g. the emissive glass around a lantern's point light,
    # which would otherwise block the very light it is meant to throw)
    cast_shadow: bool = True

    def references(self) -> list[str]:
        return [self.parent] if self.parent else []


class Mark(BaseModel):
    """A soft painted ellipsoid in object space (rest pose on skinned meshes): an eye patch, a muzzle blush."""

    model_config = ConfigDict(extra="forbid")
    at: Vec3
    radii: Vec3
    color: str
    soft: float = Field(0.5, gt=0, le=1)  # share of the radius over which it fades out
    strength: float = Field(1.0, ge=0, le=1)


class MaterialSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    base_color: str = "#CCCCCC"
    metallic: float = Field(0.0, ge=0, le=1)
    roughness: float = Field(0.5, ge=0, le=1)
    specular: float | None = Field(
        None, ge=0, le=1
    )  # Principled "Specular IOR Level" (0.5 = Blender default)
    emission: str | None = None
    emission_strength: float = Field(0.0, ge=0, le=1000)
    alpha: float = Field(1.0, ge=0, le=1)
    noise: float = Field(0.0, ge=0, le=1)  # procedural grime/variation amount (darker patches)
    noise_scale: float = Field(2.0, gt=0, le=1000)
    fade_to: str | None = None  # aerial perspective: blend toward this colour with distance from origin
    fade_start: float = Field(15.0, ge=0)
    fade_end: float = Field(90.0, gt=0)
    # how much of the faded colour is emitted (1: distant things glow at the haze colour regardless of light;
    # under a high sun lower it, or the far ground and hills blow out to white)
    fade_glow: float = Field(1.0, ge=0, le=1)
    radial_glow: bool = False  # emission fades to transparent at the edges (sun/moon halos)
    # fine surface detail: a second, small-scale noise darkens specks (grit, gravel) and drives a bump
    grain: float = Field(0.0, ge=0, le=1)
    grain_scale: float = Field(40.0, gt=0, le=10000)
    bump: float = Field(0.0, ge=0, le=1)
    # soft velvet/fur rim (Principled sheen): grazing light catches the silhouette, so a coat stops reading as plastic
    sheen: float = Field(0.0, ge=0, le=1)
    sheen_tint: str | None = None
    # procedural coat pattern in object space (metres): zebra stripes, giraffe patches, tortoise/leopard
    # spots, meerkat back bands. pattern_color is the marking; base_color the ground colour.
    pattern: Literal["stripes", "patches", "spots", "bands", "scutes", "scales"] | None = None
    pattern_color: str | None = None
    pattern_scale: float = Field(1.0, gt=0, le=1000)  # markings per metre (roughly)
    pattern_width: float = Field(0.5, gt=0, lt=1)  # share of the pattern that is marking
    pattern_axis: Literal["x", "y", "z"] = "z"  # stripes/bands run across this axis
    pattern_distort: float = Field(2.0, ge=0, le=50)
    # stripes/bands on (axis + chevron * |x|): they wrap the body as chevrons instead of ringing every part
    # that faces along the axis (zebra chest, rump and forehead bullseyes)
    pattern_chevron: float = Field(0.0, ge=0, le=20)
    vertex_color: bool = False  # base colour from the mesh's "Col" attribute (create_mesh colors)
    pattern_tilt: float = Field(0.0, ge=-20, le=20)  # + tilt * z on the stripe coordinate (slanted stripes)
    # markings only above this object-space height (fading in over pattern_fade): a meerkat's back bands
    pattern_above: float | None = None
    pattern_fade: float = Field(0.02, gt=0, le=10)
    marks: list[Mark] = Field(default_factory=list)
    # skin and fur shading per species
    subsurface: float = Field(0.0, ge=0, le=1)  # skin: light scatters under the surface (elephant, tortoise)
    subsurface_radius: float = Field(0.02, gt=0, le=1)  # metres
    fur: float = Field(0.0, ge=0, le=1)  # short coat: fine streak bump + soft sheen rim
    fur_scale: float = Field(220.0, gt=0, le=5000)  # streaks per metre
    wrinkles: float = Field(0.0, ge=0, le=1)  # creased skin bump (elephant)
    tip_color: str | None = None  # vertical gradient: base_color at z=0 -> tip_color at tip_height (grass)
    tip_height: float = Field(0.5, gt=0, le=100)
    transmission: float = Field(0.0, ge=0, le=1)  # water / glass
    ior: float = Field(1.33, ge=1, le=3)
    wrinkle_scale: float = Field(12.0, gt=0, le=1000)

    @field_validator("base_color", "emission", "fade_to", "sheen_tint", "pattern_color", "tip_color")
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


class CreateSkinMesh(_Placed):
    """Organic body from a skeleton graph: Blender's Skin modifier wraps the edges with per-vertex radii,
    then Subdivision rounds it. ``apply`` bakes both into real geometry (for skinning and texturing)."""

    op: Literal["create_skin_mesh"]
    id: str
    vertices: list[Vec3] = Field(min_length=2, max_length=5000)
    edges: list[tuple[int, int]] = Field(min_length=1, max_length=10000)
    radii: list[tuple[float, float]] = Field(min_length=2, max_length=5000)  # per vertex (x, y)
    root: int = Field(0, ge=0)
    subdivisions: int = Field(2, ge=0, le=4)
    smooth: bool = True
    apply: bool = True

    def creates(self) -> list[str]:
        return [self.id]


class MetaElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ball", "capsule", "ellipsoid"] = "ball"
    co: Vec3
    radius: float = Field(gt=0, le=MAX_COORD)
    size: Vec3 = (0.0, 0.0, 0.0)  # capsule: half-length in x; ellipsoid: x/y/z scale
    rotation: Vec3 = (0.0, 0.0, 0.0)  # Euler XYZ degrees (a capsule runs along its local X)
    stiffness: float = Field(2.0, gt=0, le=10)
    negative: bool = False  # carves instead of adds


class CreateMetaballMesh(_Placed):
    """Implicit-surface sculpting: overlapping capsules/ellipsoids melt into one smooth body (muscle masses
    blend; no hull seams), converted to a real mesh at ``resolution`` (metres)."""

    op: Literal["create_metaball_mesh"]
    id: str
    elements: list[MetaElement] = Field(min_length=1, max_length=2000)
    resolution: float = Field(0.02, gt=0.0005, le=1)
    threshold: float = Field(0.6, gt=0, le=10)
    smooth: bool = True

    def creates(self) -> list[str]:
        return [self.id]


class CreateMesh(_Placed):
    op: Literal["create_mesh"]
    id: str
    vertices: list[Vec3] = Field(min_length=1, max_length=200_000)
    faces: list[list[int]] = Field(default_factory=list)
    smooth: bool = False
    colors: list[Vec3] | None = None  # per-vertex linear RGB 0..1 (attribute "Col"), read by vertex_color

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
    type: Literal[
        "bevel",
        "subsurf",
        "array",
        "solidify",
        "displace",
        "mirror",
        "smooth",
        "wireframe",
        "decimate",
        "shrinkwrap",
    ]
    name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    # shrinkwrap: the surface to wrap onto (evaluated every frame, so it follows the deformed skin)
    surface: str | None = None

    def references(self) -> list[str]:
        return [self.target] + ([self.surface] if self.surface else [])


class SetMaterial(_Op):
    op: Literal["set_material"]
    targets: list[str] = Field(min_length=1)
    material: MaterialSpec

    def references(self) -> list[str]:
        return list(self.targets)


class MaterialRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bones: list[str] = Field(min_length=1)  # bone-name prefixes, e.g. ["leg_"]
    material: MaterialSpec


class SetMaterialByBone(_Op):
    """Regional materials on one skinned mesh: each face takes the material of the rule matching its
    dominant bone weight (legs striped across, body striped along; pale lower legs; scaly tortoise legs)."""

    op: Literal["set_material_by_bone"]
    target: str
    default: MaterialSpec
    rules: list[MaterialRule] = Field(default_factory=list)

    def references(self) -> list[str]:
        return [self.target]


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


class SnapToSurface(_Op):
    """Seat ``target`` on the surface of mesh ``surface``: cast a ray from outside along ``direction`` (parent
    space of the target) back toward the object, and place it ``offset`` metres proud of the hit. Robust face
    placement on sculpted (metaball) heads, whose blended surfaces swell unpredictably."""

    op: Literal["snap_to_surface"]
    target: str
    surface: str
    direction: Vec3 = (0.0, -1.0, 0.0)
    offset: float = Field(0.002, ge=-1, le=1)  # negative: sink into the surface (an eyeball in its socket)
    reach: float = Field(1.0, gt=0, le=100)
    carry: list[str] = Field(default_factory=list)  # move these by the same translation (iris, glint, lids)

    def references(self) -> list[str]:
        return [self.target, self.surface, *self.carry]


class Scatter(_Op):
    """Geometry-nodes instancing: ``instance`` copies scattered over mesh ``surface`` (grass, reeds, rocks),
    with random yaw/scale, an optional travelling wind sway, cleared circles (paths, water) and circles where
    the copies stay short (so feet stay visible in the action area)."""

    op: Literal["scatter"]
    id: str  # the modifier carrier: a new object holding the scattered instances
    surface: str
    instance: str
    density: float = Field(10.0, gt=0, le=5000)  # per square metre
    seed: int = 0
    scale: tuple[float, float] = (0.7, 1.3)
    clear: list[tuple[float, float, float]] = Field(default_factory=list)  # (x, y, radius): nothing grows
    short: list[tuple[float, float, float]] = Field(default_factory=list)  # (x, y, radius): kept low
    short_scale: float = Field(0.35, gt=0, le=1)
    # (x, y, radius, multiplier): denser inside, fading out to the base density at the edge. Points are scattered
    # at the highest density and thinned at random per point, so there is no grid and no rows.
    dense: list[tuple[float, float, float, float]] = Field(default_factory=list)
    wind: float = Field(0.0, ge=0, le=1)  # sway amplitude (radians-ish); gusts travel across the field
    wind_speed: float = Field(0.6, ge=0, le=20)

    def creates(self) -> list[str]:
        return [self.id]

    def references(self) -> list[str]:
        return [self.surface, self.instance]


class AddBoneConstraint(_Op):
    """A constraint on a pose bone. ``ik``: two-bone legs reach ``subject`` (a foot target), bending toward
    ``pole``; ``damped_track``: aim the bone at ``subject`` (look-at); ``copy_rotation``."""

    op: Literal["add_bone_constraint"]
    armature: str
    bone: str
    type: Literal["ik", "damped_track", "copy_rotation"]
    subject: str
    pole: str | None = None
    chain_count: int = Field(2, ge=1, le=16)
    pole_angle: float = Field(-90.0, ge=-360, le=360)  # degrees
    influence: float = Field(1.0, ge=0, le=1)

    def references(self) -> list[str]:
        return [self.armature, self.subject] + ([self.pole] if self.pole else [])


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
    ``bone:<name>.rotation`` (degrees, pose space) / ``.location`` / ``.scale`` on an armature |
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


class RigidRegion(BaseModel):
    """Inside this ellipsoid (armature space) the skin follows ``bone`` alone, blending back to the automatic
    weights over the outer ``falloff`` share: a skull does not bend with the neck, so the eyes, lids and brows
    riding the head bone stay seated in the skin."""

    model_config = ConfigDict(extra="forbid")
    bone: str
    center: Vec3
    radii: Vec3
    pitch: float = 0.0  # degrees about X (the head's pitch)
    falloff: float = Field(0.35, ge=0.0, le=1.0)


class BindMeshToArmature(_Op):
    op: Literal["bind_mesh_to_armature"]
    mesh: str
    armature: str
    bone: str | None = None  # rigid bind to one bone; None = automatic weights
    # smooth bind to these bones with distance-falloff weights (deterministic; no bone-heat failures on
    # primitives). The mesh keeps its local transform; the armature should share the mesh's parent.
    bones: list[str] | None = None
    # automatic (bone-heat) weights over the whole armature, keeping the local transform; falls back to
    # distance weights if heat weighting fails
    auto: bool = False
    exclude: list[str] = Field(default_factory=list)  # bone-name prefixes that must not deform this mesh
    rigid: list[RigidRegion] = Field(default_factory=list)  # auto bind: regions that follow one bone rigidly

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
    # Workbench/viewport-only colour grade (multiplies every non-emissive material's viewport colour;
    # Cycles/EEVEE are unaffected). Night scenes use it so the flat-colour preview reads as night.
    viewport_tint: str | None = None
    stars: float = Field(0.0, ge=0, le=1)  # a procedural starfield above the horizon (night)
    clouds: float = Field(0.0, ge=0, le=1)  # soft cumulus wisps in the sky
    cloud_color: str = "#FFFFFF"


RenderDevice = Literal["auto", "cpu", "cuda", "optix"]


class SetRender(_Op):
    op: Literal["set_render"]
    engine: Literal["workbench", "eevee", "cycles"] | None = None
    resolution: tuple[int, int] | None = None
    samples: int | None = Field(None, ge=1, le=4096)
    fps: int | None = Field(None, ge=1, le=240)
    look: str | None = None
    exposure: float | None = Field(None, ge=-10, le=10)
    # Cycles compute device. auto = OptiX > CUDA > CPU; an unavailable GPU falls back to CPU with a warning.
    device: RenderDevice | None = None
    # RGBA frames with a transparent world (design-sheet silhouettes are cut from the alpha)
    transparent: bool | None = None


class RenderPreview(_Op):
    op: Literal["render_preview"]
    path: str | None = None
    frame: int | None = Field(None, ge=0, le=MAX_FRAME)
    camera: str = "auto"
    resolution: tuple[int, int] = (480, 270)
    engine: Literal["workbench", "eevee", "cycles"] = "workbench"
    device: RenderDevice | None = None
    samples: int = Field(12, ge=1, le=4096)  # Cycles previews


class RenderFinal(_Op):
    op: Literal["render_final"]
    output_dir: str
    frame_start: int | None = None
    frame_end: int | None = None
    frame_step: int = Field(1, ge=1, le=100)
    device: RenderDevice | None = None


class Save(_Op):
    op: Literal["save"]
    path: str


class Query(_Op):
    op: Literal["query"]
    ids: list[str] | None = None
    types: list[str] | None = None
    tag: str | None = None
    fields: list[
        Literal["transform", "bbox", "material", "parent", "type", "shape_keys", "animation", "tags"]
    ] = Field(default_factory=lambda: ["type", "transform"])
    limit: int = Field(200, ge=1, le=10_000)


class SeatPair(BaseModel):
    """``target`` should sit in ``surface``: an ``eye`` reports how deep its centre is under the deformed skin
    (embed share of its diameter); ``skin`` (brows, lids) reports the gap between its closest point and the skin."""

    model_config = ConfigDict(extra="forbid")
    target: str
    surface: str
    kind: Literal["eye", "skin"] = "eye"


class SkinFoot(BaseModel):
    """A foot measured on the deformed skin, not on its bone: at ``ref_frame`` (else the first inspected frame)
    ``k`` vertices of ``meshes`` within ``radius`` of the tip of ``bone`` (``"armature:bone"``) are chosen
    (``sole``: the lowest, the contact patch; ``near``: the nearest), and every frame reports their world
    centroid and lowest point. An IK-pinned bone tail proves only that the IK reached its
    target; the skin shows whether the weights let the foot slide."""

    model_config = ConfigDict(extra="forbid")
    id: str
    bone: str = Field(pattern=r"^[^:]+:.+$")
    meshes: list[str] = Field(min_length=1)
    k: int = Field(default=24, ge=1, le=500)
    radius: float = Field(default=1.0, gt=0)
    pick: Literal["sole", "near"] = "sole"
    # the frame at which the vertices are chosen (e.g. the foot's first planted frame); default: the first frame
    ref_frame: int | None = None


class Inspect(_Op):
    """Cheap geometric checks used by the Critic (frustum, floor contact, motion, mouth activity, eyes seated
    in their sockets, textures pinned to the skin)."""

    op: Literal["inspect"]
    subjects: list[str] = Field(min_length=1)
    frames: list[int] = Field(min_length=1, max_length=2000)
    floor_z: float = 0.0
    camera: str | None = None
    shape_key_target: str | None = None
    # report per frame the world position of these bone tips ("armature:bone"): foot-slide measurement
    bone_tails: list[str] = Field(default_factory=list)
    # report per frame how far (degrees of yaw) this object's forward axis (-Y) is turned away from the lens
    facing_target: str | None = None
    # report per frame how each target sits in its surface (deformed): eye embed, brow/lid gap
    seating: list[SeatPair] = Field(default_factory=list)
    # report per frame how far the texture coordinates of these deforming meshes drift from the first frame
    # (rest_position when the material reads it, else Object coordinates = the deformed position)
    swim: list[str] = Field(default_factory=list)
    # report per frame the centroid and lowest point of each foot's skin vertices (foot slide on the skin)
    skin_feet: list[SkinFoot] = Field(default_factory=list)

    def references(self) -> list[str]:
        refs = list(self.subjects) + ([self.camera] if self.camera else [])
        refs += [x for sp in self.seating for x in (sp.target, sp.surface)] + list(self.swim)
        refs += [m for sf in self.skin_feet for m in sf.meshes] + [
            sf.bone.split(":", 1)[0] for sf in self.skin_feet
        ]
        return refs + ([self.facing_target] if self.facing_target else [])


class SetProperty(_Op):
    """Escape hatch for simple data paths, e.g. ``{"target": "sun", "path": "data.angle", "value": 0.1}``."""

    op: Literal["set_property"]
    target: str
    path: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_.]*$")
    value: Any

    def references(self) -> list[str]:
        return [self.target]


OP_CLASSES: tuple[type[_Op], ...] = (
    CreatePrimitive,
    CreateMesh,
    CreateSkinMesh,
    CreateMetaballMesh,
    CreateEmpty,
    Delete,
    Transform,
    Parent,
    AddModifier,
    SetMaterial,
    AddLight,
    AddCamera,
    SetCameraActive,
    AddConstraint,
    AddBoneConstraint,
    SetMaterialByBone,
    SnapToSurface,
    Scatter,
    InsertKeyframes,
    ClearAnimation,
    SetFrameRange,
    CreateArmature,
    BindMeshToArmature,
    AddShapeKeys,
    ImportAsset,
    AddSoundStrip,
    SetWorld,
    SetRender,
    RenderPreview,
    RenderFinal,
    Save,
    Query,
    Inspect,
    SetProperty,
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
            is_vec = op.property in vec_props or re.fullmatch(
                r"bone:.+\.(rotation|location|scale)", op.property
            )
            if op.index is None and is_vec and False in kinds:
                errors.append(f"{p}: property {op.property!r} needs vector values or an 'index'")
            if not re.fullmatch(
                r"location|rotation|scale|hide|shape_key:[\w .\-]+|bone:[\w.\-]+\.(rotation|location|scale)"
                r"|light\.(energy|color)|camera\.lens|material\.emission_strength",
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
