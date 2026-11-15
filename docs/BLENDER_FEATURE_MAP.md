# Blender feature map

Groundwork for the long-term plan (PLAN §9): know what Blender does for artists, where it lives in the
source tree, how our agents reach it today, and how hard it would be to replace piece by piece.

* **Source pointers** are directories in the Blender repository (`blender/blender` on projects.blender.org).
* **Agent access**: *op* = a protocol op exists · *script* = reachable via sandboxed script mode only ·
  *—* = not exposed yet.
* **Difficulty to replace**: 1 (weekend) … 5 (multi-year, large team).
* **Priority** = how soon replacing/owning it pays off for an AI-native studio (H/M/L).

| Feature | What artists use it for | How Blender implements it (source) | Our agents today | Replace difficulty | Priority |
|---|---|---|---|---|---|
| Mesh primitives & editing | blocking, hard-surface | `source/blender/bmesh/`, `editors/mesh/`, `blenkernel/intern/mesh*.cc` | op: `create_primitive`, `create_mesh` (bmesh-built) | 2 | H — a native scene core needs it first |
| Modifiers (bevel, subsurf, array, solidify, displace, mirror…) | non-destructive modelling | `source/blender/modifiers/intern/MOD_*.cc` | op: `add_modifier` (9 types) | 3 (each modifier 1–3; subsurf/bevel are hard) | M |
| Geometry Nodes | procedural sets, scattering, instancing | `source/blender/nodes/geometry/`, `blenkernel/intern/geometry_*` | script (planned: node-graph recipes) | 5 | M — agents benefit greatly; replacing is huge |
| Sculpting | organic forms | `editors/sculpt_paint/`, `blenkernel/intern/paint*.cc`, `bmesh` dyntopo | — (strokes as batched point lists planned) | 4 | L |
| Materials / shading (Principled BSDF, node trees) | look development | `source/blender/nodes/shader/`, `gpu/` (EEVEE), `intern/cycles/scene/shader*` | op: `set_material` (compact Principled spec) | 3 (a PBR subset is 2) | H — USD Preview Surface subset |
| UV unwrapping | texturing | `editors/uvedit/`, `geometry/intern/uv_parametrizer.cc` | — | 3 | L (stylised flat shading for now) |
| Rigging / armatures | deforming characters | `blenkernel/intern/armature*.cc`, `editors/armature/`, `animrig/` | op: `create_armature`, `bind_mesh_to_armature` (rigid or auto-weights); hero uses empties | 3 | M |
| Shape keys | facial expressions, lip sync | `blenkernel/intern/key.cc` | op: `add_shape_keys`, keyframes on `shape_key:<name>` | 2 | H (lip sync core) |
| Animation: actions, F-curves, Graph Editor | keyframing, easing | `animrig/` (layered actions, channelbags in 5.x), `blenkernel/intern/fcurve.cc`, `editors/space_graph/` | op: `insert_keyframes` (batched, 9 interpolations), `clear_animation` | 2 (curves) / 4 (full editor UX) | H — we already compute curves in Python |
| NLA | layering/reusing actions | `blenkernel/intern/nla.cc`, `editors/space_nla/` | — | 3 | M (motion library reuse) |
| Constraints | tracking, IK, parenting tricks | `blenkernel/intern/constraint.cc` | op: `add_constraint` (5 types) | 3 | M |
| Drivers | procedural relationships | `blenkernel/intern/fcurve_driver.cc`, `animrig` | — | 3 | L |
| Physics: rigid body | falling junk, collisions | `blenkernel/intern/rigidbody.cc` + Bullet (`extern/bullet2`) | — | 3 (use an existing engine, e.g. Jolt/Rapier) | M |
| Physics: cloth / soft body | capes, flags | `blenkernel/intern/cloth.cc`, `softbody.cc`, `simulation/` | — | 4 | L |
| Physics: fluids (Mantaflow) | water, smoke | `intern/mantaflow/`, `blenkernel/intern/fluid.cc` | — | 5 | L |
| Particles / hair (curves) | grass, fur | `blenkernel/intern/particle*.cc`, new hair = Curves + Geometry Nodes | — (we scatter with batched ops) | 4 | L |
| Grease Pencil (v3) | 2D animation, storyboards | `blenkernel/intern/grease_pencil*.cc`, `editors/grease_pencil/` | — | 4 | M — great fit for AI storyboards |
| Workbench | fast previews | `draw/engines/workbench/` | op: `render_preview` (default critic/batch previews) | 2 (a WebGPU viewport) | **H — first subsystem to replace** (three.js/WebGPU previewer of the scene model) |
| EEVEE (Next) | real-time final look | `draw/engines/eevee/` | `set_render engine=eevee` (needs GPU) | 5 | L |
| Cycles | path-traced finals | `intern/cycles/` (standalone-capable, Apache-2.0!) | `set_render engine=cycles` (final renders) | 5 — but Cycles is Apache-2.0 and can be embedded directly | M (embed Cycles standalone rather than rewrite) |
| Compositor | grading, glare, depth of field in post | `source/blender/compositor/`, `nodes/composite/` | — (AgX look + exposure via `set_render`) | 3 | M |
| Video Sequence Editor | editing, sound placement | `source/blender/sequencer/`, `editors/space_sequencer/` | op: `add_sound_strip`; final mux by ffmpeg | 2 (ffmpeg + timeline model) | H — editing already happens in our core |
| Camera & cuts (markers) | multi-shot direction | `blenkernel/intern/camera.cc`, scene markers | op: `add_camera`, `set_camera_active(frame)` | 1 | H |
| Lights & world | lighting | `blenkernel/intern/light.cc`, world node trees | op: `add_light`, `set_world` (gradient sky) | 2 | H |
| Import/export: glTF | game/web interchange | `scripts/addons_core/io_scene_gltf2/` (Python, Apache-2.0) | op: `import_asset` | 2 | H (Godot bridge) |
| Import/export: USD | pipeline interchange | `source/blender/io/usd/` (uses OpenUSD) | op: `import_asset`; core exports `scene.usda` from the scene model | 3 | **H** — our scene model is USD-shaped by design |
| Import/export: FBX / OBJ | asset libraries | `io_scene_fbx` (Python), `source/blender/io/wavefront_obj/` | op: `import_asset` | 2 | M |
| Undo system | safety | `editors/undo/`, memfile undo | snapshot rollback per batch (`undo_token`) | 2 (scene-model diffs) | H |
| Python API (bpy/RNA) | automation | `source/blender/makesrna/`, `python/intern/` | the GPL adapter process | — | — |

## Replacement order (proposal)

1. **Viewport/preview** (WebGPU/three.js reading the USD-shaped scene model + glTF meshes) — removes Blender
   from the critic loop and enables a browser studio UI.
2. **Timeline/edit** — already in core (shot list, cuts, ffmpeg mux); add a timeline model + UI.
3. **Curves & keyframes** — the Animator already computes curves; evaluate them natively.
4. **Mesh core** (bmesh-like half-edge in Rust, PyO3) + a handful of modifiers (bevel, subsurf, array).
5. **Final rendering** — embed Cycles standalone (Apache-2.0) instead of rewriting.
Blender stays the artist-facing editor throughout (open the `.blend`, edit, `animatica continue`).
