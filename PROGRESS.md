# PROGRESS — morning report (overnight build, 2026-11-15)

## 1. Headline

**`animatica film "<prompt>"` works end to end with no human input and no API key.** A Director plans a
3–4-shot, ~21-second short. Asset builds a procedural set, a rigged character and a prop in Blender
(bpy 5.3, separate GPL process). Voice speaks the dialogue with Kokoro TTS, Rhubarb lip-syncs it, and a
procedural music bed is mixed under it. The Animator writes ~3 000 principle-driven keyframes
(anticipation, overshoot, spring follow-through, blinks, lip sync). Camera & Lighting stages one camera
per shot with cuts and moves. A Critic checks every shot (frustum, framing, floor contact, mouth
activity, exposure) and applies fixes in a loop. The Editor renders with Cycles and muxes an
**MP4 with sound and captions**, and you also get an editable `scene.blend`.

Hand edits survive `animatica continue` and `animatica revise`. An **MCP server** exposes the batched
tools. A **Godot games track** turns a prompt into a playable platformer, which a bot playtests
headlessly. **61 tests** (60 pass + 1 Godot test that skips without Godot) and CI on GitHub (lint, unit, bpy adapter, offline pipeline) is green for `f0aa66d` (run #24, checked 09:40 UTC).

## 2. Try it (fresh clone)

```bash
git clone https://github.com/Goon254/3-D-plus-AI && cd 3-D-plus-AI
python3.13 -m venv .venv && . .venv/bin/activate        # bpy 5.3 needs exactly Python 3.13
pip install -e ".[dev]" bpy==5.3.0 kokoro-onnx soundfile mcp
scripts/setup_assets.sh --godot      # Kokoro model, Piper fallback voices, Rhubarb, Godot (all GitHub releases)
animatica dev doctor                 # needs ffmpeg on PATH

animatica demo --quality preview     # ~2–3 min: Workbench render of the north-star short
animatica demo                       # Cycles 960×540, ≈9 s/frame on 2 CPU cores (~75 min)
animatica film "A sleepy blue cat finds a glowing crystal in a snowy forest at night." --quality draft
animatica revise output/hello-little-one "make the robot blue and slow down shot 2" --quality preview
animatica game "a 2D platformer where a robot collects flowers" && godot --path output/game-*/godot
pytest -q                            # 61 tests (Blender/Godot tests skip if missing)
```

Each film writes `output/<project>/final.mp4`, `scene.blend`, `scene.usda`, `final.srt`, `audio/`, and
`log/index.html` (the production log viewer: every decision, batch, critique and preview).

## 3. Showcase

<!-- SHOWCASE_LIST -->
* **Film:** [`examples/showcase/hello-little-one/final.mp4`](examples/showcase/hello-little-one/final.mp4) ·
  [contact sheet](examples/showcase/hello-little-one/contact_sheet.jpg) ·
  [production log](examples/showcase/hello-little-one/log/index.html) ·
  [editable .blend](examples/showcase/hello-little-one/scene.blend). *Note: rendered 08:42, before the
  09:00–09:16 look/audio/lip-sync fixes — a refresh is the top item in `docs/REVIEW_QUEUE.md`.*
* **Game:** [`examples/showcase/robot-flower-platformer/`](examples/showcase/robot-flower-platformer/) (GDD, playtest report, screenshot).
* **Reviews:** hourly scores in [`docs/reviews/`](docs/reviews/) — latest [09:40](docs/reviews/2026-11-15T0940Z.md), overall ≈ 7.75/10.

## 4. Milestones

| # | Milestone | Status | Proof |
|---|---|---|---|
| 0 | Foundation & license audit | **done** | `pyproject.toml`, ruff, pytest, `.github/workflows/ci.yml`, `docs/SETUP.md`, `docs/LICENSE_AUDIT.md`, `THIRD_PARTY.md` |
| 1 | Protocol + Blender adapter | **done** | `animatica dev run-batch examples/batches/robot.json` → `.blend` + preview; `tests/test_protocol.py`, `tests/test_blender_adapter.py` (rollback, 300-op batch, sandboxed scripts, keyframes, shape keys, armature, inspect) |
| 2 | Orchestrator, LLM layer, agents (offline first) | **done** | task graph + budgets + JSONL log; Anthropic + scripted providers; 7 agents; knowledge base with `lookup()` |
| 3 | 🎯 Prompt → MP4 with voice, lip sync, music | **done** | `animatica demo`; `tests/test_pipeline.py` asserts video + audio + subtitle streams, 15–31 s, every agent logged |
| 4 | Quality | **partial** | Critic geometric checks + fix loop; animation principles; shot types/moves; style bible; multi-shot cuts. Three prompts produce coherent 4-shot films. Critic logs show real fixes (floor contact for the cat, close-up framing). No vision critic without an API key. |
| 5 | Artist in the loop | **done** | `animatica continue` / `revise` / `log`; `tests/test_continue.py` edits the `.blend` by script, and the edits survive both |
| 6 | MCP server | **done** | `animatica-mcp` (mcp 2.x); `tests/test_mcp.py` (in-process + stdio) |
| 7 | Games track (Godot) | **done (thin slice)** | `animatica game …` → Godot 4.5.1 project; bot playtest wins 6/6 with 0 script errors; `tests/test_games.py`; xvfb screenshot. No web/Linux export (templates are ~1 GB) |
| 8 | Reference study | **partial** | `animatica study <local files> --license …` (palette, cuts, motion, warmth; vision notes if an LLM can see) → `--style` for the Director. Refuses URLs. No image-to-3D hooks. |
| 9 | Polish | **partial** | README, quickstart, Makefile, CONTRIBUTING (DCO), issue templates, `docs/BLENDER_FEATURE_MAP.md`. No demo GIF, no web UI. |

## 5. Known issues & honest quality assessment

* **It's cute, not cinema.** Characters are built from primitives (bevelled boxes, spheres). They read
  clearly but look like a well-lit toy, not a feature film. The cat looks a bit like a chick (cone ears).
* **Acting is generic.** The offline Director always uses the same arc: enter → discover → (speak) →
  settle/celebrate. Different prompts change the setting, character, colours, prop, music mood and
  lines, but not the story structure. A real LLM key gives better plans; that path is implemented and
  unit-tested, but **it was never run against the live API tonight** (no key in the sandbox).
* **Animation is object-level.** The rig is empties and parenting, not bones: no arm bending, no
  walk cycle (the robot rolls on treads; the critter glides with a hop-bob). Lip sync is a 3-shape-key
  mouth driven by Rhubarb. It's convincing on the robot's screen-face and only OK on the critter.
* **Sets are sparse.** Scattered junk, trees or dunes with no textures and no fog. The sunset sky is a
  gradient; the sun disc looks like a flat sticker in some angles.
* **Render cost.** Cycles CPU at 960×540 takes ≈9 s/frame on 2 cores (~75 min per 21 s film). The
  `preview` preset (Workbench) takes ~2 minutes but looks like a viewport.
* **The Critic is geometric.** It can't judge appeal, staging or acting. It caught real bugs tonight
  (lip-sync check sampling, floor contact, rotated-bbox measurement), but "PASS" means "technically
  sound", not "good".
* **Music is procedural numpy pads, arpeggio, bass and wind:** pleasant but generic. The
  FluidSynth + GeneralUser GS path recommended by the research isn't wired yet (no apt candidate here).
* **The live Blender add-on (`adapters/blender/animatica_blender/live.py`) is untested inside the
  Blender UI.** It uses the same handler as the tested headless server.
* **Script mode is a guard-rail, not a security sandbox.**
* **The games track is a template-driven platformer** with polygon art. One genre only.

## 6. Decisions

All 24 are in [docs/DECISIONS.md](docs/DECISIONS.md). These ones you may want to weigh in on:

1. **Licensing split:** core Apache-2.0; `adapters/blender` and `adapters/tts_worker` GPL-3.0-or-later
   (separate processes); `adapters/godot` MIT.
2. **TTS moved from Piper to Kokoro** mid-night, after your research update (Piper is GPL; the old
   voices' licenses vary). Piper remains a fallback with CC0 and CC BY voices only.
3. **The critic uses low-sample Cycles for its 4 per-shot exposure previews** instead of Workbench
   (Workbench can't judge lighting). This costs ~10 s per critic pass.
4. **The hero uses an object-level rig, not an armature.** Moving to Rigify or a bone rig is the
   biggest visible upgrade available.
5. **Godot 4.5.1** (not 4.7) and no exports yet.

## 7. Next steps (priority order)

1. **Run with a real `ANTHROPIC_API_KEY` and add the vision critic to the loop.** Let Claude write
   varied story beats and review previews against shot goals. Watch token use: the budgets are in place.
2. **Better characters:** a bone rig (Rigify-lite) with arm bends and a walk/hop cycle. Optionally
   import CC0 characters (Quaternius/Kenney) through `import_asset` and retarget them. Add eyelids and
   eyebrows for acting.
3. **Richer sets and look:** Geometry Nodes scattering recipes, CC0 textures (Poly Haven/ambientCG
   cache), volumetric haze, and a compositor glow pass. Music via FluidSynth + GeneralUser GS.
4. **Speed:** render shots in parallel processes and use adaptive resolution for previews. Add a
   three.js/WebGPU previewer of the USD-shaped scene model so the critic loop doesn't need Blender
   (the first step of the Blender replacement plan).
5. **Studio UI:** a web page around `log/index.html` with prompt in, live batch stream, per-shot
   approve/redo buttons and `revise` notes. The games track should get export templates and a
   second genre (top-down).
