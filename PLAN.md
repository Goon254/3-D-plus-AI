# PLAN.md — Animatica: The AI-Native Animation & Game Studio

> **📌 UPDATE (added 2026-11-15, 01:55 ET) — every session, read this first:**
> 1. **Read `docs/research/README.md` and the four reports in `docs/research/` before choosing any tool, library, model, asset source, or API.** They are verified, current research with ADOPT / AVOID verdicts and license traps (e.g., Blender 5.x removed `action.fcurves`; never `import bpy` in the Apache core; Piper is now GPL; use Kokoro, Rhubarb, Workbench previews). Where this plan and the research disagree on a tool, the research wins.
> 2. **Before starting each milestone, re-read `docs/REVIEW_QUEUE.md` (if it exists) and fix its open high-priority items first.** An hourly reviewer session scores the project and adds fixes there.
> 3. If you already chose a tool the research marks AVOID, replace it and log the change in `docs/DECISIONS.md`.

> **Working title:** Animatica (rename freely — search-and-replace is fine).
> **Read this entire file before writing any code.** This is your mission brief. You are working autonomously overnight. The owner will review the repository in the morning. Make it count.

---

## 0. Mission

Build the best open-source tool for artists and game developers: an **AI-native creative studio** where a person describes a short film or a game, and a **team of specialist AI agents** — each with its own tools — plans, builds, critiques, and iterates on it inside real engines (**Blender** for animation/film, **Godot** for games) until it is finished.

The output is never a black box. Every result is a **real, editable Blender or Godot project** that an artist can open, change by hand, and hand back to the agents to continue. We are building a tool that makes artists 10× faster — not one that replaces them.

### North-star demo (the thing that must exist by morning)

```bash
animatica film "A curious little robot discovers a flower growing in a junkyard at sunset. It says: 'Hello, little one.'"
```

…produces, with no human intervention:

1. A `.blend` project file with a modeled scene, a character, materials, lighting, and a camera.
2. Keyframed character animation and camera motion (15–30 seconds).
3. A voiced line of dialogue (local text-to-speech) with **lip sync** driving the character's mouth.
4. Background music / ambient sound bed (procedurally generated or CC0).
5. A final rendered **MP4 with sound** in `output/`.
6. A **production log** showing every agent decision, every batch of operations, and every critic review with its preview render.

Stylized and simple is fine. Broken is not. A clean, working, end-to-end 20-second short beats an ambitious half-built system.

---

## 1. Ground rules for you (the overnight agent)

1. **Do not stop to ask questions.** The owner is asleep. When something is ambiguous, pick the most reasonable option, record it in `docs/DECISIONS.md` (one line: decision + why), and keep going.
2. **Commit early and often.** Small, working commits with clear messages. Push to the remote after every milestone. Never leave the repo in a broken state at the end of the session.
3. **Keep `PROGRESS.md` updated** at the repo root after every milestone: what's done, what works, what's broken, what's next. This is the first file the owner reads in the morning.
4. **Working beats perfect.** Get a thin vertical slice running end-to-end first (Milestone 3), then deepen it. Do not spend hours polishing one component while the pipeline doesn't run.
5. **Test what you build.** Every module gets tests. Every milestone gets a script that proves it works. If you claim something works, there must be a command in `PROGRESS.md` that demonstrates it.
6. **Look at your own output.** Render preview frames and actually inspect them. If the robot is floating, inside the floor, off-camera, or black, fix it.
7. **Respect licenses (see §7). This is non-negotiable.** When in doubt, don't copy the code — reimplement from the idea and credit the source.
8. **You may install anything you need** — Blender, Godot, Python packages, npm packages, ffmpeg, TTS engines, lip-sync tools, open-source asset libraries. If the network blocks a download, try an alternative route (PyPI `bpy` wheel, apt, GitHub releases, conda-forge) and document what worked in `docs/SETUP.md`.

---

## 2. Core design principles

These came out of the design discussion and are the heart of the project. Do not drop them.

### 2.1 Batch everything — tokens and round-trips are the enemy
Agents must **never** issue one tool call per tiny action. All engine operations go through a **batched operation protocol**:
- One call = a list of operations (could be 3 or 300), validated as a whole, executed in one round-trip, applied as **one undo step**.
- Agents may also submit **scripts** (Blender Python) for loops and procedural work — e.g., place 200 trees or set 500 keyframes in one call.
- Agents may submit a **declarative scene spec** (the desired state); the add-on computes the diff and applies only what changed. Revisions resend only deltas.

### 2.2 Small replies
Engine responses are compact: a short summary, IDs of created/changed objects, warnings, errors. Never dump the full scene graph unless explicitly requested with a filter. Visual verification uses **one low-res preview render** per batch, not data dumps.

### 2.3 Validate → execute → verify
1. **Validate** the whole batch before touching the scene (schema, names exist, values in range, coordinates sane). Reject with precise errors.
2. **Execute** as a single undoable transaction. Roll back the whole batch on any error.
3. **Verify** with a preview render reviewed by the Critic agent.

### 2.4 Parameters over strokes
Agents build with procedural shapes, modifiers, geometry nodes, materials and parameters — not brush strokes. When strokes are truly needed (sculpting), they are sent as one batched list of points with pressure.

### 2.5 Artist in the loop
Every step is visible, logged, and reversible. A human can open the `.blend` in normal Blender, change anything, save, and run `animatica continue` — agents read the current state and carry on from the human's changes rather than overwriting them.

### 2.6 Engine-agnostic core, engine-specific adapters
The orchestrator, agents, protocol and scene model don't know about Blender or Godot. Adapters translate. Long-term (see §9) we gradually replace Blender pieces with our own, without a rewrite.

### 2.7 Open scene representation
Use a clean, text-based internal scene model that agents can read and write cheaply. Design it to map onto **OpenUSD** concepts (prims, transforms, materials, time samples) so we can import/export USD later. Blender can import/export USD.

---

## 3. Architecture

```
                         ┌──────────────────────────────┐
  user prompt ──────────►│        ORCHESTRATOR          │◄──── artist edits (.blend / Godot)
                         │  task graph · shared state    │
                         │  budget · production log      │
                         └──────────────┬───────────────┘
                                        │ assigns tasks
     ┌────────────┬────────────┬────────┴───┬────────────┬────────────┬────────────┐
     ▼            ▼            ▼            ▼            ▼            ▼            ▼
  DIRECTOR    ART/ASSET    ANIMATOR     CAMERA &     VOICE &      EDITOR       CRITIC
  story, shot  modeling,   keyframes,   LIGHTING     SOUND        assembly,    renders &
  list, style  materials,  rigs, lip    framing,     TTS, lip     timing,      reviews
  bible        props       sync         lights       sync, music  final mux    every batch
     │            │            │            │            │            │            │
     └────────────┴────────────┴─────┬──────┴────────────┴────────────┴────────────┘
                                     ▼
                       ┌───────────────────────────┐
                       │  BATCHED OPERATION LAYER  │  validate → execute → verify
                       └─────────────┬─────────────┘
                     ┌───────────────┴───────────────┐
                     ▼                               ▼
            BLENDER ADAPTER (GPL)            GODOT ADAPTER (MIT)
            headless (bpy) or live add-on    headless or editor plugin
```

### 3.1 Components

| Component | Responsibility |
|---|---|
| `core/orchestrator` | Builds a task graph from the Director's plan, dispatches tasks to agents, manages retries, enforces token/time budgets, writes the production log. |
| `core/state` | Shared project state: the scene model, style bible, shot list, asset registry, decisions, and history. Persisted to disk as JSON/YAML in the project folder and versioned with git. |
| `core/protocol` | The batched operation schema (JSON Schema + Pydantic models), validator, and result format. Single source of truth for every adapter. |
| `core/llm` | Provider-agnostic LLM client. Anthropic first (`ANTHROPIC_API_KEY`), pluggable for others, **plus a deterministic offline "scripted" provider** so the full pipeline and tests run with no API key. |
| `agents/*` | One module per agent role: system prompt, allowed tools, input/output contracts. |
| `adapters/blender` | Blender add-on (GPL) + headless runner. Executes batches, renders previews, exports. Talks to the core over a local socket/JSON-RPC, or runs as `blender -b --python`. |
| `adapters/godot` | Godot plugin + headless runner for the games track (Milestone 7+). |
| `audio/` | TTS (Piper or Kokoro, local), lip-sync (Rhubarb Lip Sync → viseme keyframes), music/ambience (procedural synthesis or CC0 library), ffmpeg muxing. |
| `knowledge/` | Retrieval knowledge base: Blender Python API notes, recipes, animation principles, and the **Blender feature map** (§9). Agents look things up here instead of guessing. |
| `cli/` | `animatica film`, `animatica game`, `animatica continue`, `animatica render`, `animatica log`. |
| `mcp/` | An MCP server exposing the batched tools so Claude (or any MCP client) can drive Animatica directly. |

### 3.2 Agent roles (film track)

| Agent | Input | Output | Tools |
|---|---|---|---|
| **Director** | User prompt | Style bible (palette, mood, shape language), story beats, shot list with durations, asset list, dialogue | knowledge lookup |
| **Art / Asset** | Asset list + style bible | Models, materials, set dressing — as batches/scripts | batch ops, scripts, asset library search, knowledge |
| **Animator** | Shot list + rigged assets | Keyframes, rig setup (simple armature or object-level), follow-through, anticipation, easing | batch ops, scripts, knowledge (12 principles of animation) |
| **Camera & Lighting** | Shot list + scene | Cameras per shot, camera moves, lighting setup per mood | batch ops |
| **Voice & Sound** | Dialogue + timing | WAV per line, viseme track, music/ambience bed | TTS, lip sync, audio synth |
| **Editor** | Rendered shots + audio | Final timeline (Blender VSE or ffmpeg), final MP4 | VSE batch ops, ffmpeg |
| **Critic** | Preview render(s) + the task's goal | Pass / fail + specific fix list (e.g., "character clips floor by ~0.1 m at frame 40", "subject is off-frame in shot 2") | render preview, vision model, scene query |

The Critic loop: **plan → batch → preview → critique → fix**, capped at N iterations per task (configurable, default 3) to bound cost. Every critique and its preview image are saved to the production log.

---

## 4. Repository layout

```
animatica/
├── PLAN.md                 # this file
├── PROGRESS.md             # updated after every milestone (morning report)
├── README.md               # what it is, quickstart, demo GIF/video, architecture diagram
├── LICENSE                 # see §7
├── THIRD_PARTY.md          # every external project used: name, URL, license, what we took
├── pyproject.toml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PROTOCOL.md         # batched operation spec with examples
│   ├── AGENTS.md           # each agent's contract
│   ├── SETUP.md            # install steps that actually worked in this environment
│   ├── DECISIONS.md        # one-line decision log
│   ├── LICENSE_AUDIT.md    # results of the repo audit (§6, Milestone 0)
│   └── BLENDER_FEATURE_MAP.md
├── src/animatica/
│   ├── core/ (orchestrator, state, protocol, llm, budget, log)
│   ├── agents/ (director, asset, animator, camera, voice, editor, critic)
│   ├── audio/ (tts, lipsync, music, mux)
│   ├── knowledge/
│   ├── cli/
│   └── mcp/
├── adapters/
│   ├── blender/            # GPL-licensed add-on + headless runner (separate LICENSE file)
│   └── godot/              # MIT plugin + runner
├── third_party/            # vendored code ONLY if license allows; each with its own LICENSE
├── examples/               # example prompts + their outputs (small)
├── tests/
└── output/                 # gitignored, except a few small showcase renders
```

---

## 5. The batched operation protocol (v0 spec — implement and document in `docs/PROTOCOL.md`)

```json
{
  "batch_id": "b-0042",
  "agent": "asset",
  "intent": "Build the robot's body and head",
  "mode": "ops",
  "ops": [
    {"op": "create_primitive", "id": "robot_body", "shape": "cube", "size": [0.6, 0.4, 0.8], "location": [0, 0, 0.4]},
    {"op": "create_primitive", "id": "robot_head", "shape": "uv_sphere", "radius": 0.25, "location": [0, 0, 1.05], "parent": "robot_body"},
    {"op": "add_modifier", "target": "robot_body", "type": "bevel", "params": {"width": 0.05, "segments": 3}},
    {"op": "set_material", "targets": ["robot_body", "robot_head"], "material": {"base_color": "#D9822B", "metallic": 0.6, "roughness": 0.35}}
  ],
  "verify": {"preview": true, "camera": "auto", "resolution": [480, 270]}
}
```

- `mode`: `"ops"` (list of operations), `"script"` (sandboxed Blender Python string), or `"spec"` (declarative desired state → diff).
- Stable, agent-chosen `id`s for everything (never rely on Blender's auto-names like `Cube.001`).
- **Result** (compact):
```json
{"batch_id": "b-0042", "ok": true, "created": ["robot_body", "robot_head"], "modified": [], "warnings": [], "errors": [], "preview": "log/previews/b-0042.png", "undo_token": "u-17"}
```
- Minimum v0 op set: create_primitive, delete, transform, parent, add_modifier, set_material, add_light, add_camera, set_camera_active, insert_keyframes (batched: target, property, list of [frame, value, interpolation]), set_frame_range, create_armature (simple), bind_mesh_to_armature, import_asset (glTF/OBJ/FBX/USD), add_sound_strip, render_preview, render_final, query (filtered, compact).
- Validation: JSON Schema + semantic checks (ids exist, no duplicate ids, numbers finite, keyframes ordered, frames in range).
- Script mode runs with a restricted namespace and a timeout; prefer ops when possible.

---

## 6. Milestones (do them in order; each ends with a commit, a push, and a `PROGRESS.md` update)

### Milestone 0 — Foundation & license audit (keep this fast)
- [ ] Repo scaffold per §4, `pyproject.toml`, linting (ruff), tests (pytest), CI workflow (GitHub Actions: lint + unit tests + offline pipeline smoke test).
- [ ] Install Blender headless (try in order: `pip install bpy` matching a supported Python, apt `blender`, official tarball). Install ffmpeg. Record what worked in `docs/SETUP.md`.
- [ ] Audit the candidate projects below. For each: license, activity, code quality, what to reuse vs. reimplement. Write `docs/LICENSE_AUDIT.md` and start `THIRD_PARTY.md`.
  - BlenderMCP (ahujasid/blender-mcp) — MIT, reuse/adapt the Blender socket bridge pattern.
  - CommonSenseMachines/blender-mcp — check license.
  - LL3M (threedle/ll3m) — **academic/evaluation license; reference the paper's ideas only, do not copy code.**
  - Coding-Solo/godot-mcp, Open-Godot-MCP — MIT, candidates for the games track.
  - OpenMontage — **AGPL; ideas only, do not copy code.**
  - FilmAgent, ViMax — check licenses; ideas for Director/Cinematographer roles.
  - Rhubarb Lip Sync, Piper / Kokoro TTS, Blender Studio open-movie assets (CC-BY) — verify licenses.
- **Done when:** `pytest` passes, Blender runs a trivial headless script, audit doc exists.

### Milestone 1 — Protocol + Blender adapter
- [ ] Protocol models, schema, validator, compact results (§5).
- [ ] Blender adapter: headless runner executing batches in one transaction with rollback, plus preview rendering (EEVEE or Workbench for speed; Cycles only for final if time allows).
- [ ] Live add-on mode (socket server inside a running Blender) — same protocol.
- [ ] Tests: valid batches, invalid batches rejected with clear errors, rollback on failure, 300-op batch executes in one round-trip.
- **Done when:** `animatica dev run-batch examples/batches/robot.json` produces a `.blend` and a preview PNG.

### Milestone 2 — Orchestrator, LLM layer, agents (offline first)
- [ ] Provider-agnostic LLM client; Anthropic provider; **scripted offline provider** returning canned, valid plans/batches so everything runs without an API key.
- [ ] Orchestrator: task graph, dispatch, retries, budgets (max tokens, max critic iterations, max wall time), production log (JSONL + previews).
- [ ] Director, Asset, Animator, Camera & Lighting, Critic agents with clear contracts in `docs/AGENTS.md`.
- [ ] Knowledge base v0: Blender API recipes the agents actually need, animation principles, lighting recipes.
- **Done when:** the offline pipeline produces a scene with a character, camera, and lights from a prompt, with critic reviews logged.

### Milestone 3 — 🎯 First vertical slice: prompt → MP4 with sound (TOP PRIORITY)
- [ ] Voice: local TTS (Piper or Kokoro) → WAV per line.
- [ ] Lip sync: Rhubarb (or a simple amplitude/phoneme fallback) → viseme timings → mouth shape keyframes / shape keys on the character.
- [ ] Music/ambience: procedural synth bed (e.g., simple pads via numpy) or a CC0 track; mixed under dialogue.
- [ ] Editor agent: assemble shots + audio (Blender VSE or ffmpeg) → `output/<project>/final.mp4`.
- [ ] `animatica film "<prompt>"` runs end-to-end, offline provider and Anthropic provider.
- **Done when:** the north-star demo (§0) produces a watchable 15–30 s MP4 with voice, lip sync and music. Commit one showcase render (small, compressed) to `examples/showcase/` and reference it in the README.

### Milestone 4 — Quality: make it actually good
- [ ] Critic gets sharper: checks for floor intersection, off-frame subjects, blown-out or black renders, static shots, jittery motion, mouth not moving during dialogue. Combine vision review with cheap geometric checks (bounding boxes vs. camera frustum, floor plane).
- [ ] Animator applies animation principles: anticipation, ease-in/out, overlap, follow-through, secondary motion, idle breathing.
- [ ] Camera agent: shot types (wide, medium, close-up), simple moves (dolly, pan, orbit), rule-of-thirds framing.
- [ ] Style bible enforced across all agents (palette, shape language, lighting mood).
- [ ] Multi-shot films (2–4 shots) with cuts.
- **Done when:** three different prompts each produce a coherent multi-shot short; previews and critic logs prove iteration improved them.

### Milestone 5 — Artist-in-the-loop
- [ ] `animatica continue <project>`: load the current `.blend`, diff it against the stored scene model, treat human changes as locked/authoritative, and continue from there.
- [ ] `animatica revise <project> "make the robot blue and slow down shot 2"` — targeted delta edits via spec mode.
- [ ] Production log viewer: `animatica log <project>` → a static HTML page showing each step, agent, batch, preview, and critique.
- **Done when:** a test edits a `.blend` by hand (scripted), runs `continue`, and the human change is preserved.

### Milestone 6 — MCP server
- [ ] Expose the batched tools (run_batch, render_preview, query_scene, start_film, continue, revise) as an MCP server so Claude and other MCP clients can drive Animatica directly.
- **Done when:** the MCP server starts and its tools pass an integration test.

### Milestone 7 — Games track (Godot) — stretch for tonight
- [ ] Godot headless install; Godot adapter speaking the same batched protocol (scene tree ops, GDScript files, input map, run & capture screenshot/logs).
- [ ] Game agents: Game Designer (GDD + mechanics), Level Builder, Gameplay Programmer, Playtester (runs the game headless with scripted inputs, reads errors, checks win/lose conditions), Critic.
- [ ] `animatica game "a 2D platformer where a robot collects flowers"` → a runnable Godot project + an exported web or Linux build if possible.
- [ ] Shared assets: models/characters made in Blender export to Godot via glTF.
- **Done when:** a playable small game is generated and the Playtester confirms it runs without errors.

### Milestone 8 — Reference study & knowledge (stretch)
- [ ] Reference ingestion from **legally usable sources only**: Blender Studio open movies (CC-BY), user-supplied clips/images, CC0/CC-BY images. Extract frames with ffmpeg, have a vision model write notes on timing, poses, camera language, color — store as reusable style notes in `knowledge/`.
- [ ] Asset creation upgrades: optional hooks for open-source image-to-3D models (check each model's license), auto-cleanup in Blender.

### Milestone 9 — Polish for launch
- [ ] README with demo video/GIF, architecture diagram, quickstart that works from a fresh clone, contribution guide, issue templates, roadmap.
- [ ] `docs/BLENDER_FEATURE_MAP.md` filled in (§9).

---

## 7. Licensing rules (non-negotiable)

- **Our core** (`src/animatica`, CLI, orchestrator, agents, protocol, MCP server): **Apache-2.0** (or MIT — pick one, log it in DECISIONS.md).
- **Blender adapter / add-on** (`adapters/blender/`): **GPL-3.0-or-later**, with its own LICENSE file. It runs inside Blender; the core talks to it over a socket or subprocess, keeping the core separately licensed.
- **Godot adapter**: MIT or Apache-2.0.
- **Copying third-party code** into `third_party/` is allowed **only** if its license permits it and is compatible with the destination. Keep the original LICENSE file next to it, record it in `THIRD_PARTY.md`.
- Prefer **dependencies** (pip/npm/apt, git submodules) over vendoring when practical.
- **Never copy code from** AGPL projects (e.g., OpenMontage), academic/evaluation-only or non-commercial projects (e.g., LL3M), or code with no license. Reading them for ideas and citing them is fine.
- **Assets**: CC0, CC-BY (with attribution in `THIRD_PARTY.md`), or generated by us. No ripped assets.
- **Reference media**: **never download from YouTube or other sites in violation of their terms, and never ingest copyrighted films.** Use Blender Studio open movies (CC-BY), CC0/CC-BY media, or user-supplied files.
- **Voice**: only stock/open TTS voices. Any future voice-cloning feature must require explicit consent from the voice owner — design the hook with a consent field, don't ship cloning tonight.
- Add a `CONTRIBUTING.md` noting a DCO sign-off (`Signed-off-by`) for contributions.

---

## 8. Quality bar & testing

- Every module has unit tests; protocol validation has exhaustive tests.
- The **offline provider** makes the entire pipeline testable in CI without API keys or GPUs (render at tiny resolution with Workbench/EEVEE).
- A `make demo` (or `animatica demo`) target reproduces the showcase from a clean clone.
- Type hints throughout; ruff clean.
- Logs are human-readable: an artist should understand what each agent did and why.
- Performance targets for the slice: preview render < 10 s at 480×270; full 20 s short at 960×540 renders in reasonable time on CPU (use EEVEE/Workbench; Cycles optional).

---

## 9. Long-term vision: replace Blender piece by piece

We use Blender as the engine today, but we are building the **AI-native layer** that could eventually stand on its own. Start the groundwork now:

- **`docs/BLENDER_FEATURE_MAP.md`**: a table of Blender's major features — modeling, modifiers, geometry nodes, sculpting, materials/shading, UV, rigging/armatures, shape keys, animation/graph editor/NLA, physics (rigid body, cloth, fluids, particles), grease pencil (2D), rendering (EEVEE, Cycles, Workbench), compositor, video sequence editor, import/export (USD, glTF, FBX).
  For each: what artists use it for · how Blender implements it (pointers into the Blender source tree) · how our agents currently access it · difficulty to replace (1–5) · priority.
- Keep our internal scene model USD-shaped so a future native previewer/renderer (e.g., a fast WebGPU/three.js viewport) can replace Blender subsystems one at a time.

---

## 10. Forbidden / out of scope tonight

- No downloading copyrighted films or YouTube videos.
- No copying code from AGPL, non-commercial, academic-only, or unlicensed projects.
- No voice cloning of real people.
- No committing secrets/API keys. Use env vars; add `.env.example`.
- No committing large binaries (> 10 MB). Showcase videos must be compressed and small; use git LFS only if already configured.
- Do not rewrite Blender. Do not fork Blender tonight.

---

## 11. Morning report (final step of the session)

Before you finish, make sure `PROGRESS.md` contains:

1. **Headline:** what works end-to-end right now, in one paragraph.
2. **Try it:** the exact commands to run the demo from a fresh clone.
3. **Showcase:** links to the rendered example(s) and their production logs.
4. **Milestone checklist** with status (done / partial / not started).
5. **Known issues** and the honest quality assessment (what looks bad and why).
6. **Decisions made** (link to `docs/DECISIONS.md`) and anything the owner should weigh in on.
7. **Next steps:** the top 5 things to build next, in priority order.

The goal is that the owner wakes up, runs one command, watches a little AI-made animated short with sound, and immediately understands what was built and where it's going.

**Now go build it.**
