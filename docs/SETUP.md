# Setup — what actually worked

Environment used for the overnight build: Linux x86_64 cloud sandbox, 2 vCPU, 8 GB RAM, **no GPU**,
Python 3.13.18, outbound HTTPS through an allow-listing proxy (HuggingFace was **blocked**; PyPI and
GitHub release downloads worked).

## 1. Python + Blender (as a Python module)

```bash
python3.13 -m venv venv && . venv/bin/activate
pip install bpy==5.3.0          # Blender 5.3 as a module; the wheel needs exactly Python 3.13
pip install -e ".[dev]"         # animatica core + pytest + ruff
```

* `pip install bpy` **worked first try** (≈400 MB wheel). No apt Blender or tarball needed.
* The core never imports `bpy`; it starts `python -m animatica_blender.server --stdio` in a child process
  (GPL adapter). To use a Blender binary instead set `ANIMATICA_BLENDER_BIN=/path/to/blender`.
* To use a different interpreter for the adapter set `ANIMATICA_BLENDER_PYTHON`.
* Headless rendering: Workbench ~0.1–0.2 s/frame at 480×270; Cycles CPU (16 spp, OIDN denoise,
  adaptive sampling, persistent data, reduced bounces) ≈ 9 s/frame at 960×540 on 2 vCPU.
  EEVEE works but software GL (llvmpipe) made the first frame take 75 s, so we don't use it without a GPU.
  "EGL Error 0x3009" lines in stderr are harmless.

## 2. ffmpeg

Already present (`/usr/local/bin/ffmpeg`). On Debian/Ubuntu: `sudo apt-get install ffmpeg`.

## 3. Voice, lip sync (optional — fallbacks exist)

```bash
pip install kokoro-onnx soundfile     # Kokoro TTS runtime (MIT), used by the GPL tts worker process
pip install piper-tts                  # optional fallback (GPL, subprocess only)
scripts/setup_assets.sh               # downloads models + Rhubarb into ~/.cache/animatica
```

What the script fetches (all from **GitHub releases**, since HuggingFace was blocked here):

| Asset | Source | Size |
|---|---|---|
| Kokoro-82M ONNX + voices | `thewh1teagle/kokoro-onnx` release `model-files-v1.0` | 325 MB + 28 MB |
| Piper voices `en-us-kathleen-low` (CC0 data), `en-us-libritts-high` (CC BY 4.0 data) | `rhasspy/piper` release `v0.0.2` | 58 MB, 120 MB |
| Rhubarb Lip Sync 1.14.0 Linux | `DanielSWolf/rhubarb-lip-sync` release `v1.14.0` | 87 MB |

* `voice-en-us-ljspeech-medium.tar.gz` is not in that release (404).
* `apt-get install fluidsynth` had no install candidate in this sandbox (no apt index); the music bed is
  synthesised with numpy instead (see DECISIONS).
* Without any of these, Animatica still runs: TTS falls back to espeak-ng (if installed) or a built-in
  synth "babble" voice, and lip sync falls back to an amplitude/spectral viseme estimator.

Check what was found:

```bash
animatica dev doctor
```

## 4. LLM

* `ANTHROPIC_API_KEY` set → agents use Claude (`ANIMATICA_MODEL`, default `claude-sonnet-4-5`).
* Not set → deterministic offline **scripted** provider. Everything (including CI) runs without keys.
  No key was available tonight, so every render in `examples/` used the scripted provider.

## 5. Windows + NVIDIA GPU (tested 2026-11-16)

Machine: Windows 11, Ryzen 9 9955HX (16 cores / 32 threads), 16 GB RAM, **RTX 5060 Laptop GPU (8 GB)**,
driver 591.97, Python 3.13, `bpy==5.3.0` in `.venv`, ffmpeg from winget.

```bash
py -3.13 -m venv .venv && .venv/Scripts/pip install -e ".[dev,tts,mcp]" bpy==5.3.0
bash scripts/setup_assets.sh --godot   # from Git Bash: fetches the *Windows* Rhubarb + Godot builds
.venv/Scripts/animatica dev doctor     # kokoro, rhubarb.exe, godot, and render_devices: {"auto": "OPTIX"}
```

* `animatica dev doctor` lists the GPUs Cycles can use (`render_devices`), probed in the GPL adapter process.
* **`--device auto|cpu|cuda|optix`** on `film`/`demo`/`continue`/`revise`/`render` (or `ANIMATICA_RENDER_DEVICE`).
  `auto` (default) = OptiX on RTX cards, else CUDA, else CPU. An explicit `optix`/`cuda` on a machine without
  one renders on CPU with a warning in the log; a GPU render error mid-film retries on CPU. The critic's Cycles
  previews use the same device.
* Windows fixes made while setting this up: render output paths are made absolute (Blender wrote *no*
  frames for a relative `--out output` on Windows), MLT paths are POSIX, script-mode timeouts use
  `sys.settrace` where `SIGALRM` doesn't exist (the sandbox test hung forever before), and Rhubarb/Godot
  are found as `rhubarb.exe` / `Godot_*_win64_console.exe`.

### Benchmark: one frame, CPU vs OptiX

`python scripts/bench_device.py examples/showcase/hello-little-one-hd/scene.blend --frame 300 --warm 4`
(dialogue close-up, AgX, OIDN denoise, adaptive sampling; fresh adapter process per device):

| Quality | Device | First frame (incl. kernel load + BVH) | Steady state |
|---|---|---|---|
| `final` 960×540, 16 spp | CPU (32 threads) | 1.31 s | **1.06 s/frame** |
| `final` 960×540, 16 spp | OptiX RTX 5060 | 1.19 s | **0.33 s/frame** (3.2×) |
| `high` 1280×720, 48 spp | CPU (32 threads) | 5.31 s | **5.70 s/frame** |
| `high` 1280×720, 48 spp | OptiX RTX 5060 | 2.29 s | **1.41 s/frame** (4.0×) |

A full 21 s film (504 frames) at `final` is ≈ 3 min on OptiX vs ≈ 9 min on this CPU (and ≈ 90 min on the
2-vCPU cloud sandbox in §1). OptiX output matches CPU (`tests/test_render_device.py` compares the two).

## 6. Godot (games track)

See `docs/GAMES.md` once Milestone 7 lands.
