# Review queue

Prioritised fixes from the hourly reviews (highest impact first). Builders: work this list **before**
starting new milestones. Reviewers tick an item only after verifying the fix. Each item links the review
that raised it.

## P0 — broken / blocking

- [x] Pipeline test red on CI run #7 (`tests/test_pipeline.py:26`, film 13.67 s < 15 s). *Verified fixed
  at `268b6bf` (58/58 pass locally).* — [review 07:46](reviews/2026-11-15T0746Z.md)

## P1 — high impact on quality (blocks "done": visual/animation/audio must reach 9/10)

- [ ] **Commit the showcase** (small compressed MP4 + contact sheet + log link) to `examples/showcase/`
  and fill the `<!-- SHOWCASE -->` / `<!-- SHOWCASE_LIST -->` placeholders in README and PROGRESS.
- [ ] **Lip sync legibility:** make the mouth on the robot's screen-face ~2–3× larger, and make the
  "closeup" shot an actual close-up (head + shoulders, face ≥ 25 % of frame height). Currently f300 is a
  medium shot and the mouth is ~20 px tall at 960×540. (`agents/asset.py`, `agents/camera.py`)
- [ ] **Set dressing & look:** textures or procedural noise on ground and junk (rust, dirt, grime via
  shader nodes), a ground that doesn't end in a hard edge at the horizon (larger plane or curved
  backdrop/fog), volumetric haze or mist for depth, and a sun with glow (compositor glare/bloom or an
  emissive gradient). (`agents/asset.py`, `agents/camera.py` lighting)
- [ ] **Preview preset looks bad:** Workbench output (dark brown ground, flat sky, translucent sun) is
  what new users see first. Use studio lighting + scene-world colour + object colours from materials, or
  make `draft` (Cycles 640×360) the documented quick path with a frame-step option.
- [ ] **Music mix balance:** high-pass/shelve the bed below ~120 Hz and reduce the bass voice; target
  the bed ≈ −20 LUFS short-term under dialogue sections, ≈ −16 LUFS elsewhere. Add a test that measures
  low-band energy ratio. (`audio/music.py`)
- [ ] **Animation depth:** bone rig (Rigify-lite or simple armature) with arms/head that gesture during
  the line; hero should *react* (lean in, head tilt) on the discovery beat rather than glide. Vary the
  story arc beyond the fixed 4 beats in the scripted Director.
- [ ] **Critic must earn its loop:** in the demo every shot passed on iteration 1, so the loop proves
  nothing. Add checks that would have caught the items above (mouth on-screen size during dialogue,
  shot-type fill vs. intent, empty-frame ratio, horizon edge visible) and show a before/after in the log.

## P2 — correctness / docs / hygiene

- [ ] `cli/main.py:151,161`: add `kokoro` to `--tts` choices.
- [ ] `THIRD_PARTY.md`: add Godot 4.5.1 (MIT), `mcp` SDK (MIT), `anthropic` SDK (MIT), xvfb (X11/MIT).
- [ ] `pyproject.toml`: the `tts` extra should be `kokoro-onnx` + `soundfile`; keep `piper-tts` as an
  opt-in `tts-piper` extra (GPL, worker only).
- [ ] PROGRESS: only state "CI green" after checking the latest run for the pushed SHA.
- [ ] Split `adapters/blender/animatica_blender/executor.py` (1 038 lines) by op family.
- [ ] Run the Anthropic provider path once against the live API (when a key is available) and record
  the result.
- [ ] Games track: second genre and a visual pass (the platformer is flat rectangles on a flat sky).
