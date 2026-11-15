# Review queue

Prioritised fixes from the hourly reviews (highest impact first). Builders: work this list **before**
starting new milestones. Reviewers tick an item only after verifying the fix. Each item links the review
that raised it.

## P0 — broken / blocking

- [x] Pipeline test red on CI run #7 (`tests/test_pipeline.py:26`, film 13.67 s < 15 s). *Verified fixed
  at `268b6bf` (58/58 pass locally).* — [review 07:46](reviews/2026-11-15T0746Z.md)

## P1 — high impact on quality (blocks "done": visual/animation/audio must reach 9/10)

- [x] **Re-render and recommit the showcase** (the 08:42 copy predates every quality fix — [review 09:40](reviews/2026-11-15T0940Z.md)); then (small compressed MP4 + contact sheet + log link) to `examples/showcase/`
  and fill the `<!-- SHOWCASE -->` / `<!-- SHOWCASE_LIST -->` placeholders in README and PROGRESS.
  *Partial (08:45): `examples/showcase/hello-little-one/` committed at `8f67618` (1.2 MB MP4, contact
  sheet, log, .blend); README showcase section is filled; PROGRESS `SHOWCASE_LIST` filled by reviewer 09:40. Remaining: refresh the stale render (draft/final quality, < 3 MB).* *Done 11:18 (session 10:36): re-rendered `--quality draft` (Cycles 640×360) from `6a10f8a`, 1.0 MB MP4, contact sheet checked frame by frame, log with iter1→iter2 critic previews; README + PROGRESS showcase updated. A `final` (960×540) re-render is a nice-to-have.*
- [x] **Lip sync legibility:** make the mouth on the robot's screen-face ~2–3× larger, and make the
  "closeup" shot an actual close-up (head + shoulders, face ≥ 25 % of frame height). Currently f300 is a
  medium shot and the mouth is ~20 px tall at 960×540. (`agents/asset.py`, `agents/camera.py`)
  *Builder 09:00 (`c1d167d`): mouth ~1.5× wider / 5× open on a bigger face screen; dialogue shot reframed as head-and-shoulders (face ≈30 % of frame height). Needs reviewer verification.* *Verified 09:40: face ≈ 30 % of frame height at t=12.5 s, mouth "O" clearly visible in Cycles f290.*
- [ ] **Set dressing & look:** textures or procedural noise on ground and junk (rust, dirt, grime via
  shader nodes), a ground that doesn't end in a hard edge at the horizon (larger plane or curved
  backdrop/fog), volumetric haze or mist for depth, and a sun with glow (compositor glare/bloom or an
  emissive gradient). (`agents/asset.py`, `agents/camera.py` lighting)
  *Builder 09:00 (`c1d167d`): noise grime on ground/junk, aerial-perspective fade to the horizon colour on all set materials, 400 m ground, radial-glow sun halo. No volumetrics (CPU cost).* *Reviewer 09:40: aerial fade + soft horizon verified; still open — sun glow is `hide_render` in the saved .blend (`common.py:38` `glow_visibility` never restored after Workbench), grime too faint to read, junk needs 2–3 material variants.* *Reviewer 10:36: sun glow saved visible ✔, junk grime now reads ✔; still open — featureless ground, and the distant flattened junk piles read as a floating pitched "roof" (f60/f200) — [review 10:36](reviews/2026-11-15T1036Z.md).*
- [x] **Preview preset looks bad:** Workbench output (dark brown ground, flat sky, translucent sun) is
  what new users see first. Use studio lighting + scene-world colour + object colours from materials, or
  make `draft` (Cycles 640×360) the documented quick path with a frame-step option.
  *Builder 09:05: Workbench now FLAT material colours + soft shadows + cavity; transparent halos hidden in Workbench.* *Verified 09:40 (contact sheet readable).*
- [x] **Music mix balance:** high-pass/shelve the bed below ~120 Hz and reduce the bass voice; target
  the bed ≈ −20 LUFS short-term under dialogue sections, ≈ −16 LUFS elsewhere. Add a test that measures
  low-band energy ratio. (`audio/music.py`)
  *Builder 09:00 (`c1d167d`): FFT high-pass 120 Hz, lighter bass, pads moved above the voice range, airy wind, −12 dB duck; `test_music_bed_is_not_muddy`.* *Verified 09:40: bed energy < 120 Hz ≈ 0 %, < 250 Hz 4 %; mix −15.4 LUFS.*
- [ ] **Animation depth:** bone rig (Rigify-lite or simple armature) with arms/head that gesture during
  the line; hero should *react* (lean in, head tilt) on the discovery beat rather than glide. Vary the
  story arc beyond the fixed 4 beats in the scripted Director.
  *Builder 09:10 (`172ff47`, earlier arcs commit): jointed arms (elbows) with overlapping lag, camera-side arm reaches during the line; arcs vary (idle/lonely opening, exit ending, prop blooms). Still no bone rig.* *Builder 10:45 (`5f068e4`): robot wheels roll by distance travelled (spoke + bolt, anti-strobe cap) — no more skating. Still open: bone rig, critter locomotion, acting beats.*
- [x] **Critic must earn its loop:** in the demo every shot passed on iteration 1, so the loop proves
  nothing. Add checks that would have caught the items above (mouth on-screen size during dialogue,
  shot-type fill vs. intent, empty-frame ratio, horizon edge visible) and show a before/after in the log.
  *Builder 09:00: added `face_too_small` / `face_cut` (lip-sync readability) checks. Before/after evidence so far is on the cat film (floor contact) — see PROGRESS showcase.* *Reviewer 09:40: still PASS ×4 at iteration 1 on the demo; the new face checks have no tests. Add tests that trigger them, and an addressee-prop-in-frame check (flower is cut by the bottom edge in the close-up).* *Verified 10:36: demo iteration 1 flags the flower at 55 % in frame, the fix (`fill_mul 0.92`) is applied and iteration 2 passes; dialogue checks unit-tested.*

## P1.5 — research 05 integrations (after the P1 quality items) — [review 08:45](reviews/2026-11-15T0845Z.md)

- [x] **Editor → MLT timeline** (`melt` subprocess, LGPL/GPL, separate process): write an MLT XML edit
  (cuts, crossfades, title card, dialogue/music/ambience tracks) and also save it as a Kdenlive/Shotcut
  project in `output/<project>/edit/` so artists can re-cut the AI's edit. Keep the ffmpeg path as fallback.
  *Builder 09:05 (`1f2ad8b`): `edit.mlt` written by the Editor (per-shot clips, dialogue + music tracks); no `melt` render / Kdenlive-specific project yet.* *Reviewer 09:40: `root` is an absolute path (not portable) and V1 cuts from `final.mp4`, which already has the title and mixed audio baked in — point V1 at per-shot or picture-only renders.* *Verified 10:36: relative resources, V1 = `edit/picture.mp4`. (`melt` render / Kdenlive project remain nice-to-haves.)*
- [ ] **Title & credit cards via SVG** (Inkscape CLI, or resvg/CairoSVG fallback): Director-chosen title,
  rendered in the film's palette, added to the edit. Also usable for Godot sprites (fixes the flat-rectangle look).
- [ ] TRIAL **Real-ESRGAN** upscaling (upstream xinntao BSD-3 code/weights only — never Upscayl or
  `upscayl-ncnn`, AGPL): benchmark 480×270→960×540 vs native Cycles on 4 frames (quality + CPU time).
- [ ] TRIAL **MuseScore CLI** music render (headless, `QT_QPA_PLATFORM=offscreen`) as an optional upgrade
  over the numpy bed; record in THIRD_PARTY when added.

## P2 — correctness / docs / hygiene

- [x] Title overlay subtitle ("an Animatica short · Pip") is low-contrast on the sky — add a soft shadow or drop it. *Verified 10:36.* — [review 09:40](reviews/2026-11-15T0940Z.md)

- [x] `cli/main.py:151,161`: add `kokoro` to `--tts` choices. *(builder: done)*
- [x] `THIRD_PARTY.md`: add Godot 4.5.1 (MIT), `mcp` SDK (MIT), `anthropic` SDK (MIT), xvfb (X11/MIT).
  *Done by reviewer 08:45 (+ ONNX Runtime, soundfile).* — [review 08:45](reviews/2026-11-15T0845Z.md)
- [x] `pyproject.toml`: the `tts` extra should be `kokoro-onnx` + `soundfile`; keep `piper-tts` as an
  opt-in `tts-piper` extra (GPL, worker only). *Done by reviewer 08:45, DECISIONS #25.*
- [x] Apply `ruff format` repo-wide in one mechanical commit (44 files differ at 09:40, growing) and add
  `ruff format --check` to CI — only when no build session is active, to avoid conflicts.
- [ ] PROGRESS: only state "CI green" after checking the latest run for the pushed SHA. Fill the empty `<!-- SHOWCASE_LIST -->` / `<!-- CI_STATUS -->` placeholders (empty on main at 10:36).
- [x] Split `adapters/blender/animatica_blender/executor.py` (1 038 lines) by op family.
  *Builder 09:14 (`b50f7fb`): split into executor + ops_scene/material/anim/render + common.* *Verified 09:40 (largest module now 361 lines; CI run #21 was red on lint, fixed by `74209ea`).*
- [ ] Run the Anthropic provider path once against the live API (when a key is available) and record
  the result.
- [ ] Games track: second genre and a visual pass (the platformer is flat rectangles on a flat sky).
