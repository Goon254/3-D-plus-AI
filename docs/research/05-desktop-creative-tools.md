# 05 — Desktop creative tools: what to integrate

Date: 2026-11-15. Scope: 16 popular open-source desktop media/creative apps, evaluated for whether our agents can **use** them (run as a separate program / CLI / scripting API) to raise output quality or cut work.

## The core rule

Almost all of these are **GPL**. We may **run** GPL programs as separate processes (command line, subprocess, socket) from our Apache-2.0 core — exactly as we already run Blender. We must **not copy or link their code into the Apache core**; doing so would force the core to become GPL. Anything installed is a runtime dependency recorded in `THIRD_PARTY.md`, not vendored code. (AGPL code is avoided entirely per PLAN.md §7.)

License column: ✅ = verified from a primary or reliable source on 2026-11-15 (see Sources). ⚠️ = from general knowledge; **re-verify against the project's LICENSE file before integrating.**

## Verdicts

| # | Tool | License | How we'd use it | Verdict |
|---|---|---|---|---|
| 59 | Blender | GPL-3.0-or-later ✅ (see 01) | Core film engine | **ADOPT** (already core) |
| 64 | Godot | MIT ⚠️ (see 04) | Core game engine | **ADOPT** (already core) |
| 52/53 | **MLT framework** (engine behind Kdenlive & Shotcut) | Framework LGPL-2.1; `melt` CLI GPL-2 ✅ | Editor agent writes an MLT XML timeline (cuts, transitions, titles, audio tracks) and renders it with `melt` in a subprocess. Output the same project as a Kdenlive/Shotcut file so artists can open and fine-tune the AI's edit in a real editor. | **ADOPT** (Milestone 4–5) |
| 52 | Kdenlive | GPL ⚠️ | Not run by us; target format for artist hand-off (see MLT) | **ADOPT as hand-off target** |
| 53 | Shotcut | GPL-3.0 ⚠️ | Same as Kdenlive (also MLT XML) | **ADOPT as hand-off target** |
| 60 | Upscayl app | **AGPL-3.0** ✅ | — | **AVOID** the app/backend code |
| 60→ | **Real-ESRGAN** (the model Upscayl uses) | Code and official weights **BSD-3-Clause** ✅ | Render final frames at lower resolution, upscale 2–4× with `realesrgan-ncnn-vulkan` (needs Vulkan GPU) or ONNX Runtime on CPU. Potentially large render-time savings. Use upstream xinntao weights and the upstream ncnn-vulkan binary, **not** Upscayl's AGPL fork (`upscayl-ncnn`). | **TRIAL** (measure quality vs. native render; CPU speed may be the bottleneck) |
| 56 | **Krita** | GPL-3.0 ⚠️ | Python scripting API + animation timeline: future 2D animation track, painted textures, storyboard frames. Run headless via its Python API in a separate process. | **TRIAL** (2D track, later) |
| 57 | **Inkscape** | GPL-2.0-or-later ⚠️ | Agents write SVG (title cards, logos, UI art, 2D game sprites); `inkscape --export-type=png` renders them. Pure-Python fallback: `resvg`/CairoSVG. | **ADOPT** (cheap, high value for titles & 2D assets) |
| 65 | **MuseScore** | MuseScore 4: GPL-3.0 with font exception ✅ | Music agent writes MusicXML/MIDI; `mscore -o out.wav score.musicxml` renders with better instruments than plain FluidSynth (run headless with `QT_QPA_PLATFORM=offscreen`). MuseScore puts no license claim on exported audio ✅. | **TRIAL** (quality upgrade over FluidSynth path in 03) |
| 61 | mpv / libmpv | GPL-2.0+ (LGPL build possible) ⚠️ | Video preview/scrubbing in our future desktop or web-wrapper UI | **TRIAL** (UI phase) |
| 51 | OBS Studio | GPL-2.0 ⚠️ | Record demo videos and tutorials for launch; not part of the pipeline | **USE AROUND** the product |
| 63 | Penpot | MPL-2.0 ⚠️ | Design our app's UI; self-hostable | **USE AROUND** the product |
| 54 | HandBrake | GPL-2.0 ⚠️ | ffmpeg already covers encoding | **SKIP** |
| 55 | Audacity | GPL-3.0 ⚠️ | Scripting exists (mod-script-pipe) but needs a GUI; ffmpeg + pyloudnorm stack in 03 is better | **SKIP** |
| 58 | Darktable | GPL-3.0 ⚠️ | Photo RAW editing is outside our workflow | **SKIP** |
| 66 | LMMS | GPL-2.0 ⚠️ | Hard to automate; MIDI-in-code + MuseScore/FluidSynth is better | **SKIP** |
| 62 | yt-dlp | Unlicense ⚠️ | Code license is fine, but downloading from YouTube and similar sites breaks their terms and conflicts with PLAN.md §7 (no copyrighted reference media) | **AVOID** |

## Highest-impact integrations (in priority order)

1. **MLT / `melt` for the Editor agent** — real timeline editing (transitions, titles, multi-track audio) instead of ad-hoc ffmpeg filtergraphs, plus an artist hand-off format (open the AI's cut in Kdenlive or Shotcut). Directly serves the "artist in the loop" principle.
2. **Inkscape (or resvg) for 2D assets** — SVG is text, so it's ideal for LLM agents: titles, credits, logos, UI, sprites for the Godot track.
3. **Real-ESRGAN upscaling** — render low-res, upscale; benchmark quality (critic compares against a native render on sample frames) and CPU speed before enabling by default.
4. **MuseScore CLI** — optional higher-quality music rendering.
5. **Krita** — when the 2D animation track starts.

## Integration notes

- Each tool lives behind an adapter in its own subprocess with a timeout, and is optional: the pipeline must still work if the tool isn't installed (feature detection + fallback), and `docs/SETUP.md` lists install routes (apt package names, AppImages, release binaries).
- Record every runtime dependency in `THIRD_PARTY.md` with its license and how we invoke it.
- Never ship Upscayl's code or `upscayl-ncnn` (AGPL). Use upstream Real-ESRGAN.

## Sources

- Upscayl license (AGPL-3.0, backend uses Real-ESRGAN): https://alternativeto.net/software/upscayl/about , https://www.opensourcealternatives.to/item/upscayl , https://github.com/oyyuyu/upscayl (README mirror: CLI is real-esrgan-ncnn-vulkan; Upscayl's fork is upscayl-ncnn)
- Real-ESRGAN code and weights BSD-3-Clause: https://openmodeldb.info/models/4x-realesr-general-x4v3 , https://huggingface.co/gtomato/os-realesr-general , https://aireiter.com/blog/real-esrgan-guide-download-gui
- MLT licensing (framework LGPL-2.1, melt GPL-2): https://mltframework.org/docs/copyrightpolicy/ , https://mltframework.org/features/
- MuseScore license and CLI export formats: https://www.wikipedia.org/wiki/Musescore , https://musescore.org/pl/faq , https://dyn.manpages.debian.org/trixie/musescore/musescore.1.en.html
