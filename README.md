# Animatica — an AI-native animation studio

Describe a short film; a **team of specialist AI agents** plans it, builds it in **Blender**, animates it,
voices it, lip-syncs it, scores it, critiques its own previews, and renders an **MP4 with sound** — and
leaves you a **normal, editable `.blend`** you can open, change by hand, and hand back to the agents.

```bash
animatica film "A curious little robot discovers a flower growing in a junkyard at sunset. It says: 'Hello, little one.'"
```

**Showcase** — made by the command above, fully offline (scripted planner, Kokoro voice, Rhubarb lip sync,
procedural music, Cycles 640×360 `--quality draft`, ~21 min on 2 CPU cores), no human edits:

[![contact sheet](examples/showcase/hello-little-one/contact_sheet.jpg)](examples/showcase/hello-little-one/final.mp4)

▶ [`examples/showcase/hello-little-one/final.mp4`](examples/showcase/hello-little-one/final.mp4) (21 s, with sound and captions) ·
[production log](examples/showcase/hello-little-one/log/index.html) ·
[editable .blend](examples/showcase/hello-little-one/scene.blend) ·
games track: [robot-flower-platformer](examples/showcase/robot-flower-platformer/) (screenshot below)

<img src="examples/showcase/robot-flower-platformer/screenshot.png" width="480" alt="generated Godot platformer">

## Quickstart (fresh clone, Linux/macOS, Python 3.13)

```bash
git clone https://github.com/Goon254/3-D-plus-AI && cd 3-D-plus-AI
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]" bpy==5.3.0 kokoro-onnx soundfile mcp   # Blender as a Python module + voice + MCP
scripts/setup_assets.sh            # optional: Kokoro voice model, Piper fallback voices, Rhubarb lip sync
animatica dev doctor               # shows what was found (ffmpeg must be on PATH)
animatica demo --quality preview   # ~2–3 min: fast Workbench render of the north-star short
animatica demo --quality final     # Cycles 960×540 (≈9 s/frame on 2 CPU cores)
```

No API key needed: without `ANTHROPIC_API_KEY` the agents use a deterministic offline "scripted" provider.
With a key, Claude plans the film, chooses performance/camera parameters and reviews previews visually.

Outputs land in `output/<project>/`: `final.mp4`, `scene.blend`, `scene.usda`, `audio/`, and
`log/index.html` — a production log with every agent decision, every batch, and every critic review
with its preview.

## Commands

| Command | What it does |
|---|---|
| `animatica film "<prompt>" [--quality ci/preview/draft/final/high]` | prompt → short film + editable project |
| `animatica demo` | the north-star film |
| `animatica continue <project>` | after you edit `scene.blend` in Blender: your changes are locked and kept; agents redo the rest |
| `animatica revise <project> "make the robot blue and slow down shot 2"` | targeted changes |
| `animatica render <project>` | re-render from the `.blend` |
| `animatica log <project>` | regenerate the HTML production log |
| `animatica dev run-batch examples/batches/robot.json` | execute one protocol batch → `.blend` + preview PNG |
| `animatica dev schema` / `animatica dev doctor` | protocol JSON Schema / environment check |
| `animatica-mcp` | MCP server so Claude (or any MCP client) can drive Animatica directly |

## How it works

```
prompt ─► Director ─► Voice & Sound ─┐
                 └──► Art/Asset ─────┴► Animator ─► Camera & Lighting ─► Critic ⟲ (fix → re-layout) ─► Editor ─► MP4
                       every engine change = one validated batch ──► Blender adapter (separate GPL process)
```

* **Batched operation protocol** — agents never make one tool call per tiny action. A batch of 3 or 3 000
  ops is validated as a whole, executed in one round-trip, and applied as one undo step (rolled back on
  any error). See [docs/PROTOCOL.md](docs/PROTOCOL.md).
* **Parameters over strokes** — the LLM picks style, staging, performance and camera *parameters*;
  procedural recipes turn them into geometry, ~3 000 keyframes, lights and camera moves.
* **Animation principles built in** — anticipation, overshoot, follow-through (spring-simulated
  antenna), secondary motion, squash & stretch, blinks, and Rhubarb lip sync on a shape-key mouth.
* **A Critic that checks real things** — subject in frame (camera-frustum projection), framing size per
  shot type, floor contact, mouth moving during dialogue, exposure — each issue comes with a fix the
  orchestrator applies before re-rendering previews.
* **Artist in the loop** — `continue` diffs your saved `.blend` against the scene model and treats your
  edits as authoritative.
* **Engine-agnostic, USD-shaped core** — the orchestrator and agents don't know Blender; adapters do.

Docs: [Architecture](docs/ARCHITECTURE.md) · [Protocol](docs/PROTOCOL.md) · [Agents](docs/AGENTS.md) ·
[Setup that worked](docs/SETUP.md) · [Decisions](docs/DECISIONS.md) · [License audit](docs/LICENSE_AUDIT.md) ·
[Research](docs/research/README.md) · [Progress](PROGRESS.md)

## Licensing

Core (`src/animatica`): **Apache-2.0**. Blender adapter (`adapters/blender`) and TTS worker
(`adapters/tts_worker`): **GPL-3.0-or-later**, run as separate processes. See [THIRD_PARTY.md](THIRD_PARTY.md).
Contributions need a DCO sign-off — see [CONTRIBUTING.md](CONTRIBUTING.md).
