# Batched operation protocol (v0.1)

Source of truth: `src/animatica/core/protocol.py` (Pydantic models + semantic validator). JSON Schema:
`animatica dev schema`. Adapters receive plain JSON and never import the core.

## Principles

* **One call = one batch** of 1…50 000 ops, validated as a whole, executed in one round-trip, applied as
  **one undo step**. If any op fails, the whole batch is rolled back.
* **Small replies**: ids created/modified/deleted, warnings, errors, optional preview path, compact
  `data` for query/inspect. Never a scene dump unless asked (with filters).
* **Stable, agent-chosen ids** (`^[A-Za-z_][A-Za-z0-9_.-]{0,62}$`). Identity is stored on the Blender
  object (`animatica_id`) so artist renames don't break agents.
* Units: metres, **degrees**, frames; colours `#RRGGBB` (sRGB). Z is up; characters face −Y at rest.

## Batch

```json
{
  "batch_id": "b-0042",
  "agent": "asset",
  "intent": "Build the robot's body and head",
  "mode": "ops",
  "ops": [
    {"op": "create_primitive", "id": "robot_body", "shape": "cube", "size": [0.6, 0.4, 0.8], "location": [0, 0, 0.4]},
    {"op": "create_primitive", "id": "robot_head", "shape": "uv_sphere", "radius": 0.25, "location": [0, 0, 0.65], "parent": "robot_body"},
    {"op": "add_modifier", "target": "robot_body", "type": "bevel", "params": {"width": 0.05, "segments": 3}},
    {"op": "set_material", "targets": ["robot_body", "robot_head"], "material": {"base_color": "#D9822B", "metallic": 0.6, "roughness": 0.35}}
  ],
  "verify": {"preview": true, "camera": "auto", "resolution": [480, 270]},
  "locked": []
}
```

* `mode`: `ops` (default) · `script` (sandboxed Blender Python, see below) · `spec` (declarative desired
  state; the core diffs it against the scene model and sends only the delta ops — `SceneModel.spec_to_ops`).
* `verify.preview`: render one low-res Workbench preview after the batch (path in the result).
* `locked`: ids an artist owns; ops that would modify them are rejected by validation (the orchestrator
  also filters them out before sending — see `Context.filter_locked`).

## Result

```json
{"batch_id": "b-0042", "ok": true, "created": ["robot_body", "robot_head"], "modified": [], "deleted": [],
 "warnings": [], "errors": [], "preview": "log/previews/b-0042.png", "undo_token": "…/undo/u-17.blend",
 "data": {"preview_stats": {"mean": 0.31, "black": 0.0, "white": 0.0}}, "elapsed_ms": 412}
```

## Operations

| op | purpose | key fields |
|---|---|---|
| `create_primitive` | cube, uv_sphere, ico_sphere, cylinder, cone, torus, plane, circle | `id, shape, size? radius? depth? segments, smooth, location, rotation, scale, parent, tags` |
| `create_mesh` | raw mesh | `id, vertices[[x,y,z]], faces[[i…]]` |
| `create_empty` | pivots / rig controls / aim targets | `id, display` |
| `delete` | remove objects | `targets[]` |
| `transform` | set location/rotation/scale | `target, location?, rotation?, scale?` |
| `parent` | (re)parent, keep world transform | `child, parent|null` |
| `add_modifier` | bevel, subsurf, array, solidify, displace, mirror, smooth, wireframe, decimate | `target, type, params{}` |
| `set_material` | Principled BSDF from a compact spec | `targets[], material{base_color, metallic, roughness, specular?, emission, emission_strength, alpha, noise, noise_scale, fade_to, fade_start, fade_end, radial_glow, name}` |
| `add_light` | sun/point/area/spot | `id, light_type, energy, color, size, spot_angle` |
| `add_camera` | camera with optional track-to and DOF | `id, lens, look_at (id or point), dof_target, fstop` |
| `set_camera_active` | active camera, or a **cut** at `frame` (timeline marker bound to the camera) | `id, frame?` |
| `add_constraint` | track_to, damped_track, copy_location, child_of, limit_location | `target, type, subject` |
| `insert_keyframes` | many keys on one property in one op | `target, property, keys[[frame, value, interp]], index?` |
| `clear_animation` | remove animation (incl. shape keys) | `targets[]` |
| `set_frame_range` | start/end/fps | |
| `create_armature` / `bind_mesh_to_armature` | simple bone chains; rigid (bone) or automatic-weights bind | |
| `add_shape_keys` | named shape keys from absolute vertex positions | `target, keys{name: [[x,y,z]…]}` |
| `import_asset` | glTF/GLB/OBJ/FBX/USD under a root empty with `id` | `id, path, format?` |
| `add_sound_strip` | audio on the VSE (artists hear the soundtrack in Blender) | `id, path, frame_start, channel, volume` |
| `set_world` | sky gradient (zenith/glow/horizon/ground) + strength; optional `viewport_tint` grades Workbench/viewport colours only (night previews) | |
| `set_render` | engine (workbench/eevee/cycles), resolution, samples, fps, look, exposure | |
| `set_property` | escape hatch for a simple data path | `target, path, value` |
| `render_preview` | one still | `camera ("auto" frames everything), frame, resolution, engine` |
| `render_final` | PNG sequence of the frame range | `output_dir, frame_start?, frame_end?` |
| `save` | write .blend | `path` |
| `query` | filtered, compact scene info | `ids?, types?, tag?, fields[type, transform, bbox, material, parent, shape_keys, animation, tags], limit` |
| `inspect` | Critic checks per frame: screen bbox & visible fraction in a camera, height above floor, motion, mouth activity | `subjects[], frames[], camera?, floor_z, shape_key_target?` |

**Keyframe properties**: `location`, `rotation` (degrees), `scale` (vectors, or scalar with `index`),
`hide`, `shape_key:<name>`, `light.energy`, `light.color`, `camera.lens`, `material.emission_strength`.
**Interpolations**: `CONSTANT, LINEAR, BEZIER, EASE_IN, EASE_OUT, EASE_IN_OUT, BACK, ELASTIC, BOUNCE`.

## Validation (before anything touches the scene)

Schema (types, enums, ranges, `#RRGGBB`), then semantics: ids well-formed and unique; references exist
(in the scene or earlier in the batch, deletions tracked); all numbers finite and in range; keyframes
strictly increasing, scalar/vector consistent, property supported; mesh faces index valid vertices;
shape keys equal length; locked ids untouched; mode/payload consistent. Errors are path-qualified,
e.g. `ops[3](insert_keyframes): keyframes must be strictly increasing by frame`.

## Script mode

`{"mode": "script", "script": "...", "script_timeout_s": 30}` runs Blender Python with a restricted
namespace: imports limited to `math, random, mathutils, bmesh, bpy, itertools, functools, colorsys`;
no `open/exec/eval/compile`; a wall-clock timeout (SIGALRM). Helper `ax.run_ops([...])` executes protocol
ops from inside a loop (e.g. place 200 trees). New objects get ids automatically. Prefer ops; scripts
are for procedural loops. **This is a guard-rail, not a security boundary** — don't expose script mode
to untrusted users.

## Transports

* Headless: `python -m animatica_blender.server --stdio` — `{"id", "method", "params"}` lines in, `{"id", "result"|"error"}` out.
  Methods: `ping, new_scene, open, run_batch, undo, ids, shutdown`.
* Live add-on: install `adapters/blender/animatica_blender` as a Blender add-on; it listens on
  `127.0.0.1:9876` with the same messages; batches run on Blender's main thread (timer) so an artist can
  watch. Core side: `LiveBlenderSession`.
