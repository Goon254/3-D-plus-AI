# Blender 5.x Python API notes (things LLM-written snippets get wrong)

## Animation (5.0+ layered actions)
`action.fcurves` was removed. Keyframes live in layers → strips → channelbags:
`for bag in action.layers[0].strips[0].channelbags: bag.fcurves`. Easiest robust path:
`id.keyframe_insert(data_path, index, frame)` creates the slot/channelbag, then edit
`fcurve.keyframe_points` (add N, set `.co`, `.interpolation`, `.easing`, call `fc.update()`).
Shape key animation lives on the **Key** datablock: `mesh.shape_keys.animation_data`.

## Sequencer
`scene.sequence_editor.sequences` was renamed to `.strips` (4.4+): `se.strips.new_sound(name, path, channel, frame_start)`.
Careful: an empty collection is falsy — use `hasattr(se, "strips")`, not `getattr(...) or ...`.

## Render engines
`BLENDER_WORKBENCH`, `BLENDER_EEVEE` (EEVEE Next; `BLENDER_EEVEE_NEXT` in some 4.x builds), `CYCLES`.
Headless Cycles CPU: `scene.cycles.device = "CPU"`, `use_denoising = True`, `denoiser = "OPENIMAGEDENOISE"`,
`use_adaptive_sampling = True`, `render.use_persistent_data = True`.

## World sky gradient
Texture Coordinate → Generated → Separate XYZ → Z (range −1..1) → Math multiply-add (×0.5 + 0.5) →
Color Ramp (horizon at 0.5) → Background.

## Markers as camera cuts
`m = scene.timeline_markers.new(name, frame=f); m.camera = cam_obj` — the active camera switches at
render time, so one render pass produces an edited sequence.

## Headless gotchas
`bpy.ops.wm.read_factory_settings(use_empty=True)` for a clean scene. Undo is unreliable in background
mode: snapshot with `save_as_mainfile(copy=True)` and reopen to roll back. "EGL Error 0x3009" is harmless.
Colours on properties are scene-linear: convert sRGB hex with the sRGB EOTF.
