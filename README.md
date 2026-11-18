# Animatica — an AI-native animation studio

> 🌱 **Early-stage and built in the open.** Animatica is a few weeks old: the results are rough in places and
> improving every day. Every bug we find becomes an automatic check, so the same mistake can't happen twice.
> **Contributors of every kind are welcome:** see [How you can help](#how-you-can-help).

Describe a short film; a **team of specialist AI agents** plans it, builds it in **Blender**, animates it,
voices it, lip-syncs it, scores it, critiques its own previews, and renders an **MP4 with sound** — and
leaves you a **normal, editable `.blend`** you can open, change by hand, and hand back to the agents.

```bash
animatica film "A curious little robot discovers a flower growing in a junkyard at sunset. It says: 'Hello, little one.'"
```

**Showcase** — made by the command above, fully offline (scripted planner, Kokoro voice, Rhubarb lip sync,
procedural music, Cycles 640×360 `--quality draft`: 2 min on an RTX 5060 with OptiX, ~21 min on 2 CPU cores), no human edits:

[![contact sheet](examples/showcase/hello-little-one/contact_sheet.jpg)](examples/showcase/hello-little-one/final.mp4)

▶ [`examples/showcase/hello-little-one/final.mp4`](examples/showcase/hello-little-one/final.mp4) (21 s, with sound and captions) ·
[production log](examples/showcase/hello-little-one/log/index.html) ·
[editable .blend](examples/showcase/hello-little-one/scene.blend) ·
**[HD 960×540 version](examples/showcase/hello-little-one-hd/final.mp4)** ·
**[fox film, HD](examples/showcase/fox-lantern/final.mp4)** ("A tiny fox finds a glowing lantern in a snowy forest at night…") ·
games track: [robot-flower-platformer](examples/showcase/robot-flower-platformer/) (screenshot below)

<img src="examples/showcase/robot-flower-platformer/screenshot.png" width="480" alt="generated Godot platformer">

### Latest: *Tembo and the Singing Spring* (animatic, 5:16)

Our first long test: a 5-minute kids' story with five savannah animals (an elephant calf, a giraffe, a zebra,
a meerkat and a leopard tortoise), 103 shots from dawn to night, with a different voice for every character
and music written for each scene. The animals walk with gait patterns taken from published locomotion
research: elephants never trot, and giraffes "pace", moving both legs on one side together.

[![animatic contact sheet](examples/showcase/savannah-animatic/contact_sheet.jpg)](examples/showcase/savannah-animatic/animatic_web.mp4)

▶ [`examples/showcase/savannah-animatic/animatic_web.mp4`](examples/showcase/savannah-animatic/animatic_web.mp4)

An **animatic** is the rough cut that studios make before the final render, to judge story, timing and
staging. Known issues we're fixing next: the lip sync drifts, some movements and sound effects are off, the
night scenes are too dark, and one zebra wanders where she shouldn't. The character designs come from the
[design stage](DESIGN_STAGE.md) (design sheets and approval packets are in [`design/`](design/)).

## Get started

### What you need

| | |
|---|---|
| **Python 3.13** | exactly 3.13: Blender's Python module (`bpy` 5.3) only supports this version |
| **Git** and **ffmpeg** | to download the project and assemble the videos |
| **Disk** | about 3 GB (Blender module ≈ 360 MB, voices, lip-sync and music tools) |
| **GPU** | optional. An NVIDIA RTX card makes renders ~3–4× faster than a strong CPU (OptiX). Other machines render on the CPU |
| **API key** | optional. Everything runs offline for free; see [Offline vs. with an API key](#offline-vs-with-an-api-key) |

### Install

<details open>
<summary><b>Windows</b> (PowerShell; tested on Windows 11 + RTX 5060)</summary>

```powershell
winget install Git.Git Python.Python.3.13 Gyan.FFmpeg
# close and reopen PowerShell so the new tools are found, then:
git clone https://github.com/Goon254/3-D-plus-AI; cd 3-D-plus-AI
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1      # if this errors: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e ".[dev,tts,mcp]" bpy==5.3.0
& "C:\Program Files\Git\bin\bash.exe" scripts/setup_assets.sh   # optional: voice model, lip sync, music samples
animatica dev doctor              # checks what was found, including your GPU
```
</details>

<details>
<summary><b>macOS</b> (Apple Silicon or Intel; renders on the CPU)</summary>

```bash
brew install python@3.13 ffmpeg git
git clone https://github.com/Goon254/3-D-plus-AI && cd 3-D-plus-AI
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,tts,mcp]" bpy==5.3.0
scripts/setup_assets.sh           # optional: voice model, lip sync, music samples
animatica dev doctor
```
</details>

<details>
<summary><b>Linux</b></summary>

```bash
# install Python 3.13 (your distro, deadsnakes, or pyenv), ffmpeg and git; fluidsynth is optional (better music)
git clone https://github.com/Goon254/3-D-plus-AI && cd 3-D-plus-AI
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,tts,mcp]" bpy==5.3.0
scripts/setup_assets.sh           # optional: voice model, lip sync, music samples
animatica dev doctor
```
</details>

The first install downloads a few hundred MB, so give it a few minutes. Every optional tool has a fallback, so
the pipeline always runs: without the voice model you get a simpler synthetic voice, and without Rhubarb you
get simpler lip sync.

### Make your first film

```bash
animatica film "A shy little fox finds a glowing mushroom in a forest at night. It whispers: 'Are you lost too?'" --quality preview
```

This takes about 2–5 minutes. If you like the preview, render the real thing:

```bash
animatica film "A shy little fox finds a glowing mushroom in a forest at night. It whispers: 'Are you lost too?'" --quality final
```

Quality levels, fastest first: `preview` (rough look, for checking timing), `draft`, `final` (960×540) and
`high` (1280×720). GPU use is automatic (`--device auto`); add `--device cpu` to force the CPU.

**What you get:** the command prints a project folder under `output/`, containing:

* `final.mp4`: the film, with voice, lip sync, music and captions
* `scene.blend`: the whole scene, which you can open and edit in [Blender](https://www.blender.org/download/)
* `edit.mlt`: the edit, which opens in Kdenlive or Shotcut
* `log/index.html`: a page showing every decision each agent made, with the critic's preview images

Changed something by hand in Blender? Run `animatica continue <project folder>`: your edits are locked in and
the agents rebuild around them. Or ask for a change in words:
`animatica revise <project folder> "make the fox orange and slow down shot 2"`.

### Offline vs. with an API key

**Offline (default, free):** a built-in planner reads your prompt for keywords. Use these words and your film
follows them:

* **Who:** a robot, or a small animal (fox, cat, bunny, dog)
* **Where:** junkyard, forest, meadow, beach, desert, snow, city, space, room
* **When:** dawn, day, sunset, night
* **What they find:** flower, lantern, ball, crystal, mushroom, star
* **What they say:** put the line in quotes

**With an Anthropic API key** (paid per use, from [console.anthropic.com](https://console.anthropic.com)),
Claude plans the film from your full prompt, chooses the acting and camera work, and reviews the previews by
looking at them:

```bash
pip install -e ".[anthropic]"
export ANTHROPIC_API_KEY=sk-...          # PowerShell: $env:ANTHROPIC_API_KEY="sk-..."
animatica film "your story" --quality final
```

### How the 5-minute savannah film was made

*Tembo and the Singing Spring* was **not** made with one command. A Claude Code session acted as the director
and screenwriter. It researched the animals, wrote and revised the screenplay, ran the
[design stage](DESIGN_STAGE.md), and produced the film scene by scene with the project's scripts
(`films/savannah/`, `scripts/savannah_*.py`), while the owner reviewed and approved each stage. Turning this
into a single `animatica feature` command is on the roadmap.

### Troubleshooting

| Problem | Fix |
|---|---|
| `No matching distribution found for bpy==5.3.0` | you're not on Python 3.13; check with `python --version` inside the venv |
| `ffmpeg not found` | install ffmpeg and reopen your terminal; `animatica dev doctor` should then list it |
| Render stops or the machine freezes (out of memory) | close browsers and other heavy apps, render one film at a time, use `--quality preview` while iterating |
| Robotic or flat voice | run `setup_assets.sh` to get the Kokoro voice model; `animatica dev doctor` shows which voice engine is active |
| Mouth barely moves | Rhubarb isn't installed; run `setup_assets.sh` |
| GPU not used | `animatica dev doctor` lists `render_devices`; update the NVIDIA driver. Mac (Metal) and AMD (HIP) GPUs aren't supported yet ([help wanted](#how-you-can-help)) |

More detail: [docs/SETUP.md](docs/SETUP.md) has exact setups that worked, including Windows + RTX benchmarks.

## How you can help

You don't need to be a programmer. Animatica needs:

| You are… | You could… |
|---|---|
| 🎨 **3D artist / character designer** | improve base meshes, sculpt species parts, design new characters, make CC0 textures |
| 🏃 **Animator** | build gait and pose libraries, acting beats, expressions, camera language |
| 🎵 **Musician / sound designer** | write character themes and scene cues, record or synthesise CC0 sound effects |
| ✍️ **Writer / storyteller** | write kids' stories and screenplays, review story structure and dialogue |
| 🧪 **Tester** | run it on your machine (Windows, macOS, Linux; NVIDIA, AMD, Apple GPUs) and report what breaks |
| 💻 **Developer** | Mac (Metal) and AMD (HIP) GPU rendering, the vision critic, the web app, Godot games, tests |

Start with an issue labelled **good first issue** or **help wanted**, or open a Discussion to say hello and
tell us what you'd like to work on. Read [CONTRIBUTING.md](CONTRIBUTING.md) first (licensing rules and a DCO
sign-off on commits). Everyone who contributes is credited in the README and in the end credits of every film
we make.


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
