# PROGRESS — morning report (overnight build, 2026-11-15)

## 0. Design stage — owner's top priority since 2026-11-16 23:58 (DESIGN_STAGE.md)

Film production is **paused** until the owner approves the five design packets, then the animatic.

Cloud session 11-17 06:36 UTC ([review](docs/reviews/2026-11-17T0636Z.md), DECISIONS #52): **steps 2 (sheet renderer,
rubric, critic, best-of-N loop) are built**: briefs for all five in [`design/`](design/README.md), `animatica.design`
(measure, brief, variants, rubric, image checks, critic), `scripts/design_sheet.py`, `scripts/design_loop.py`, 16 tests.
The current designs were sheeted and reviewed ([`design/baseline/`](design/README.md#baseline--the-current-designs-before-the-design-loop-cloud-review-2026-11-17-0636-utc)):
Tembo 9.6, Neema 9.8, Bibi Kobe 9.3 (appeal 6–7 blocks them), Zuri 7.3 (silhouette reads as a horse), Kiki 2.6
(reads as a weasel / prairie dog). Next: base-mesh fixes for what morphs can't change (REVIEW_QUEUE P0-DESIGN), the
rig stress test (step 3), then the loop per character and the packets.

## 0b. Savannah film (CHALLENGE-SAVANNAH.md) — production paused for the design stage

Laptop session 11-17 (owner's list): **Chatterbox (MIT) is the voice engine** on the RTX 5060 (CUDA torch 2.7.1),
steered by the approved Kokoro blends, with a Whisper check per take, Kokoro fallback and a line cache (#45);
**eyes sit in sockets** with lids and brows on the skin, and a rigid skull (#46); **coat patterns are pinned** to the
rest pose (#47); **meerkat v3** (#48); the **set pass** (clumped canopies, warm haze, denser foreground grass, #51);
SC 2 re-voiced and drafted at 960×540 on OptiX ([`sc02_draft.mp4`](examples/showcase/savannah-scenes/sc02_draft.mp4)).
New Critic checks measure eye seating, brow/lid contact and texture swim on the deformed meshes
([eye/coat sheet](examples/showcase/savannah-face-tests/eye_coat_sheet.jpg)). SC 1 final render (1280×720, OptiX) is for
the owner's review (full quality stays out of git: `output/savannah/sc01/sc01.mp4`).

Status 11-17 03:36 UTC ([review](docs/reviews/2026-11-17T0336Z.md)): **SC 2 now plays its gag in the picture**
(Tembo drinks, the trunk "hiccups" a jet of water onto Kiki, Neema ducks, heads turn to whoever speaks). Done so far:

* Species research notes (elephant, giraffe, zebra, meerkat, leopard tortoise): `src/animatica/knowledge/species/`.
* Story: premise and beats, draft 1, story-editor critique, production screenplay (10 scenes, ≈5:20): `films/savannah/`.
* Creatures: species body plans on bone rigs with IK legs and a foot-locked gait planner (0.0 mm measured stance slide),
  metaball-sculpted bodies, faces (Rhubarb-synced mouths, brows, 9 expressions):
  [`savannah-walk-tests/`](examples/showcase/savannah-walk-tests/), [`savannah-face-tests/`](examples/showcase/savannah-face-tests/).
* Set: swaying grass, acacias, termite mounds, watering hole, mountains, dawn/midday/sunset/night skies:
  [`savannah-set-tests/`](examples/showcase/savannah-set-tests/).
* Sound: a Composer with per-scene cues and six leitmotifs on real SoundFont samples
  ([`savannah-score/`](examples/showcase/savannah-score/)); six distinct cast voices, procedural ambience, species
  footsteps and SFX ([`savannah-sound/`](examples/showcase/savannah-sound/), -14.3 LUFS, dialogue +12.6 dB).
* **Scene production** (new): `films/savannah/07_scenes.json` (SC 1, SC 2) → `python scripts/savannah_scene.py sc02
  --quality preview|draft|final` → a mixed scene MP4 with lines timed from the real voices, cuts on the lines, cameras
  framed on the measured heads, and the scene's own music cue re-timed to it. First result:
  [`savannah-scenes/sc02_preview.mp4`](examples/showcase/savannah-scenes/) (Cycles CPU preview, 480×270, 12 fps).
* **Acting** (new): automatic eyelines plus spec-driven gestures (trunk drink and spray with a keyed water jet, head
  duck, ear droop, head shake, nod, look-at) layered over the gaits; cameras swing around animals standing in the
  sight line (DECISIONS #49, #50). Preview stills: `python scripts/savannah_scene.py sc02 --at 10.3,11.3`.

Scorecard (strict, 11-17 03:36): story 8 (script), character design 7, motion 7, visuals 6, voices 7, music 7, mix 7.
Next: the specs for SC 3–10, the film edit, SC 2 polish, then the full GPU render on the laptop (see [docs/REVIEW_QUEUE.md](docs/REVIEW_QUEUE.md) P1-SAVANNAH).

### Needs you

* **Design stage**: nothing to approve yet. When packets appear in `design/packets/`, review them there. An
  `ANTHROPIC_API_KEY` would let the vision critic run live instead of relying on a reviewer's recorded critique.

* **Laptop session: render SC 2 at final quality** (now with the gag, eyelines and the new eyes) on the RTX 5060 (`python scripts/savannah_scene.py sc02 --quality
  final`, OptiX, ~530 frames at 1280×720) and commit a ≤ 25 MB cut to `examples/showcase/savannah-scenes/`.
* **Listen to the score** (`examples/showcase/savannah-score/score.m4a`); the cloud reviewer has no speakers.
* **Install FluidSynth on the laptop** and put it on PATH (or place `fluidsynth.exe` in
  `%USERPROFILE%\.cache\animatica\fluidsynth\bin\`), then rerun `scripts/setup_assets.sh` from Git Bash to fetch the
  SoundFont. Without it the Composer falls back to its numpy synth.
* An `ANTHROPIC_API_KEY` would let the live Anthropic provider path run once (still never run).

## 1. Headline

**`animatica film "<prompt>"` works end to end with no human input and no API key.**

* A Director plans a 4-shot, ~21-second short. The story arc changes with the prompt: an entrance or
  a lonely opening; a settle, celebrate or exit ending.
* Art builds a procedural set with a hazy sunset look (grime, aerial perspective, glowing sun), a
  rigged robot or critter, and a prop. Everything runs in Blender (bpy 5.3) in a separate GPL process.
* Voice speaks the lines with Kokoro TTS, Rhubarb lip-syncs them onto a readable shape-key mouth, and
  a procedural music bed is high-passed and ducked under the dialogue.
* The Animator writes ~3 000 principle-driven keys: anticipation, overshoot, spring follow-through,
  jointed arms that reach, blinks and lip sync.
* Camera & Lighting stages a cut per shot, including a true head-and-shoulders dialogue close-up.
* The Critic measures every shot (frustum, framing, floor contact, face size while speaking, the
  addressed prop in frame, mouth activity, exposure) and applies fixes in a loop. On the showcase film
  it reframed the dialogue close-up to bring the flower fully into frame (before/after in the log).
* The Editor renders with Cycles and writes an **MP4 with sound, captions and a title**, plus an
  editable `scene.blend` and an `edit.mlt` timeline for Shotcut/Kdenlive.

Hand edits survive `animatica continue` / `revise`. An **MCP server** exposes the batched tools. A
**Godot games track** turns a prompt into a platformer that a bot playtests headlessly. **160 tests**
(`pytest -q`, 1 skipped without Godot) pass locally. GitHub CI runs ruff, unit, bpy adapter and offline pipeline tests; status
for the final SHA is at the bottom of this report. An hourly reviewer session scored the project, and
its queue is in [docs/REVIEW_QUEUE.md](docs/REVIEW_QUEUE.md).

## 2. Try it (fresh clone)

```bash
git clone https://github.com/Goon254/3-D-plus-AI && cd 3-D-plus-AI
python3.13 -m venv .venv && . .venv/bin/activate        # bpy 5.3 needs exactly Python 3.13
pip install -e ".[dev,tts,mcp]" bpy==5.3.0
scripts/setup_assets.sh --godot      # Kokoro model, CC0/CC-BY Piper fallback voices, Rhubarb, Godot (GitHub releases)
animatica dev doctor                 # needs ffmpeg on PATH

animatica demo --quality preview     # ~2–3 min: fast Workbench render of the north-star short
animatica demo                       # Cycles 960×540, ≈10–13 s/frame on 2 CPU cores (~90 min)
animatica film "A lonely robot sits in a junkyard at dusk until a flower blooms. It says: 'You came back.' Then it heads home." --quality preview
animatica revise output/hello-little-one "make the robot blue and slow down shot 2" --quality preview
animatica game "a 2D platformer where a robot collects flowers" && godot --path output/game-*/godot
animatica-mcp                        # MCP server (stdio) for Claude Desktop / Claude Code
pytest -q                            # 160 tests (Blender/Godot/MCP tests skip if those are missing)
```

Each film writes `output/<project>/final.mp4` (video + audio + captions), `scene.blend`, `edit.mlt`,
`scene.usda`, `final.srt`, `audio/` (with `audio_manifest.json`), and `log/index.html`. That last file
is the production log viewer: every agent decision, every batch, every critique with its preview.

## 3. Showcase

<!-- SHOWCASE_LIST -->
* **North-star short** — [`examples/showcase/hello-little-one/final.mp4`](examples/showcase/hello-little-one/final.mp4)
  (21 s, 640×360 Cycles `--quality draft`, voice + lip sync + music + captions, 1.0 MB), re-rendered 2026-11-16 on OptiX
  (88 s of rendering) with every fix to date. [Production log](examples/showcase/hello-little-one/log/index.html) shows the
  critic loop: iteration 1 flags the flower at 56 % in the close-up, iteration 2 passes after the reframe.
  [Editable `.blend`](examples/showcase/hello-little-one/scene.blend). Reproduce: `animatica demo --quality draft`.
* **HD version** — [`examples/showcase/hello-little-one-hd/final.mp4`](examples/showcase/hello-little-one-hd/final.mp4)
  (21 s, **960×540 Cycles `--quality final`**, title overlay, voice + lip sync + music + captions, 1.5 MB), re-rendered
  2026-11-16 from `a26e85d` on an **RTX 5060 with OptiX in 4 min end to end** (504 frames in 199 s, 0.40 s/frame; the
  previous CPU render took ~2 h). Includes everything to date: speaker cheats toward the lens (22° off-axis), whole flower
  in the close-up (critic iteration 1 flags it at 56 % with the new 80 % rule, iteration 2 passes), hazy ridge band on
  the horizon, junk spread around the heap crest, rolling wheels, ground grit and pebbles, Rhubarb lip sync, and the
  acting beats (cautious discovery with a lean-in and head tilt; a glance down at the flower after the line).
  [Production log](examples/showcase/hello-little-one-hd/log/index.html) ·
  [contact sheet](examples/showcase/hello-little-one-hd/contact_sheet.jpg).
* **Fox film (HD)** — [`examples/showcase/fox-lantern/final.mp4`](examples/showcase/fox-lantern/final.mp4)
  (22 s, 960×540 Cycles `--quality final`, OptiX 214 s, from `3a5ac08`, with the critter bone rig), prompt "A tiny fox finds a glowing lantern in a snowy forest at
  night. It whispers: 'Are you lost too?' Then it hops away." The species pass (snout, pointed ears, white-tipped tail,
  legs), an eye-level head-and-shoulders dialogue close-up with a readable Rhubarb-synced mouth, the acting beats,
  rock-not-puddle snow stones, and an exit that leaves frame. Critic passes every shot on iteration 1.
  [Production log](examples/showcase/fox-lantern/log/index.html) · [contact sheet](examples/showcase/fox-lantern/contact_sheet.jpg).
* **Games track** — [`examples/showcase/robot-flower-platformer/`](examples/showcase/robot-flower-platformer/)
  (generated Godot project; bot playtest 6/6).

## 4. Milestones

| # | Milestone | Status | Proof |
|---|---|---|---|
| 0 | Foundation & license audit | **done** | `pyproject.toml`, ruff, pytest, CI workflow, `docs/SETUP.md`, `docs/LICENSE_AUDIT.md`, `THIRD_PARTY.md` |
| 1 | Protocol + Blender adapter | **done** | `animatica dev run-batch examples/batches/robot.json` → `.blend` + preview; `tests/test_protocol.py`, `tests/test_blender_adapter.py` (validation, rollback, 300-op batch, sandboxed scripts, keyframes, shape keys, armature, inspect). Live add-on written but untested inside the Blender UI |
| 2 | Orchestrator, LLM layer, agents | **done** | task graph + budgets + JSONL log; Anthropic (unit-tested with a fake transport) + scripted providers; 7 agents (`docs/AGENTS.md`); knowledge base + `lookup()` |
| 3 | 🎯 Prompt → MP4 with voice, lip sync, music | **done** | `animatica demo`; `tests/test_pipeline.py` checks video + audio + subtitle streams, 15–31 s, all agents logged |
| 4 | Quality | **partial** | critic checks + fix loop (before/after in the showcase log, floor fix on the cat film); animation principles, jointed arms; shot types and moves; style bible; multi-shot cuts; varied arcs. Three prompts give coherent 4-shot films. Still below the reviewer's 9/10 bar on visuals/animation (§5) |
| 5 | Artist in the loop | **done** | `continue` / `revise` / `log`; `tests/test_continue.py` hand-edits the `.blend` by script and the edits survive both; `edit.mlt` for editors |
| 6 | MCP server | **done** | `animatica-mcp` (mcp 2.x); `tests/test_mcp.py` (in-process + stdio) |
| 7 | Games track (Godot) | **done (thin slice)** | `animatica game …` → Godot 4.5.1 project, bot playtest 6/6 with 0 script errors, xvfb screenshot, `tests/test_games.py`. One genre; no export (templates ≈1 GB) |
| 8 | Reference study | **partial** | `animatica study <local files> --license …` (palette, cuts, motion, warmth, + vision notes if the LLM can see) → `film --style`. Refuses URLs. No image-to-3D hooks |
| 9 | Polish | **partial** | README + quickstart + Makefile, CONTRIBUTING (DCO), issue templates, `docs/BLENDER_FEATURE_MAP.md`, `docs/GAMES.md`. No GIF, no web UI |

## 5. Known issues & honest quality assessment

**Update 11-16 19:00** ([review](docs/reviews/2026-11-16T1900Z.md)): the lantern now really glows (its point light was
trapped inside the opaque glass; a warm ~1 m pool on the snow and warm light on the fox's face), the critter close-up
no longer clips a sliver of the lantern (new critic `prop_sliver`, the frame tightens from the bottom), snow has a few
large rocks instead of ash-like specks, and the fur has a sheen rim. Stills in the review. **The HD fox showcase (re-rendered at `1a4066c`
with the bone rig) was built before these fixes: re-render it on the GPU.** Scores ≈8.5 (visual 8, animation 8, audio 8); gate not met.

**Update 14:15** ([review](docs/reviews/2026-11-15T1415Z.md)): exits now leave the frame (camera holds on the set),
night reads as night in previews, the ground has grit/bump/pebbles, and scrap heaps are smooth with junk on the crest. The critter
no longer sits in the floor. 71 tests pass. Scores ≈8.1 (visual 7, animation 6). Next: re-render the showcase, then bone rig + acting.
`PHASE2.md` (showcase films, site, hosted MCP) was added at 14:00 and starts after the P1 quality items.

Reviewer scores at 12:36 ([review](docs/reviews/2026-11-15T1236Z.md)): functionality 8, visual 7, animation 6,
audio 8, code 9, architecture 9, docs 9, licenses 9 (≈8.1/10). The exit-verb fix is verified. Top open items: the exit
beat doesn't carry the hero out of frame, the HD showcase is stale (floating slab), and there is no bone rig or acting beat.

* **It's a lit toy, not cinema.** Characters are bevelled primitives. They're readable and charming
  in Cycles, but there are no real textures (only procedural grime) and no volumetrics. The critter
  reads a bit like a chick.
* **Rigging:** critters (fox/cat/dog) have a bone rig for the tail (skinned, bends with follow-through) and legs
  (tuck and reach in hops); body, head and the robot stay object-level pivots (DECISIONS #36). No walk cycle: the robot
  rolls on wheels that turn by distance, critters hop.
* **Story variety is template-driven offline.** Arcs vary with the prompt, but the scripted Director is
  a keyword parser. The Anthropic path (plans, performance, camera, vision critic) is implemented and
  unit-tested but **was never run against the live API** (no key here).
* **The Critic is geometric.** It finds technical problems and fixes them. It cannot judge appeal or
  acting.
* **Render cost:** Cycles CPU ≈10–13 s/frame at 960×540 on 2 cores (~90 min per 21 s). `preview`
  (Workbench, flat colours) takes 2 minutes.
* **Music:** the short films still use the procedural numpy bed (clean but generic). The savannah score uses the new Composer (FluidSynth + GeneralUser GS, leitmotifs per character); wiring it into `film` is queued.
* **Script mode is a guard-rail, not a sandbox.** The **live add-on is untested** in the Blender UI.
* **Games:** one template genre with polygon art; no exported builds.

## 6. Decisions

All are in [docs/DECISIONS.md](docs/DECISIONS.md). These are worth a look:

1. **Licensing split:** core Apache-2.0. `adapters/blender` and `adapters/tts_worker` are
   GPL-3.0-or-later and run as separate processes. `adapters/godot` is MIT.
2. **TTS = Kokoro** (Apache weights) in a GPL worker process, following your research update. Piper
   stays as an opt-in fallback with CC0/CC-BY voices only.
3. **The critic uses low-sample Cycles for its 4 per-shot exposure previews.** Workbench can't judge
   lighting.
4. **Object-level rig instead of bones** for tonight.
5. **Godot 4.5.1** (not 4.7) and no exports yet.
6. **`ruff format` not applied yet.** The reviewer asked for it as one mechanical commit when no build
   session is active.

## 7. Next steps (priority order)

1. **Run with a real `ANTHROPIC_API_KEY`** and put the vision critic in the loop. Let Claude write
   varied story beats and review previews against the shot goals.
2. **Bone rig + walk/hop cycles** (Rigify-lite), eyelids/brows for acting. Optionally import CC0
   characters (Quaternius/Kenney) via `import_asset`.
3. **Richer look:** CC0 textures (offline Poly Haven/ambientCG cache), Geometry Nodes scatter recipes,
   volumetric haze where a GPU exists, and FluidSynth music.
4. **Speed:** render shots in parallel processes. Add a WebGPU/three.js previewer of the USD-shaped
   scene model so the critic loop no longer needs Blender (step 1 of the Blender feature-map plan).
5. **Studio UI** around `log/index.html` (prompt in, live batch stream, approve/redo per shot,
   `revise` notes), and `melt`-rendered edits. For games: export templates and a second genre.

## CI status

<!-- CI_STATUS -->
Checked 12:01 UTC via the Actions API: run #39 for `54b67d3` (Director exit verbs, the last code commit of the
night) → **success** on both jobs (`lint-and-unit`: ruff check + ruff format --check + unit tests;
`blender-and-offline-pipeline`: bpy 5.3 adapter tests + offline film smoke test). Locally on that SHA:
`pytest -q` → **65 passed** (Blender, Godot, MCP and Kokoro all present).
