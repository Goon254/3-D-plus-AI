# License audit (Milestone 0)

Rule of the house (PLAN §7): copy code only when its license allows it and is compatible with the
destination; never copy from AGPL, academic/evaluation-only, non-commercial or unlicensed projects.
**Tonight no third-party source code was copied into this repository.** Everything below is either a
runtime dependency (installed separately, invoked as a library or subprocess) or ideas-only.

Verification level: licenses marked *verified* were read from the shipped LICENSE / MODEL_CARD files
in this sandbox. Others are from the research reports in `docs/research/` (dated 2026-11-15) or from
memory and should be re-checked before any code is copied — we treat them as ideas-only until then.

| Project | License | Verified? | Activity / quality notes | Decision |
|---|---|---|---|---|
| **Blender / `bpy` 5.3** | GPL-3.0-or-later | yes (Blender) | very active | Runtime only, in the GPL adapter process (`adapters/blender/`). |
| **ahujasid/blender-mcp** | MIT | research report 01 | popular; socket bridge executing arbitrary Python per call | Reimplemented the *pattern* (JSON over a local socket inside Blender, main-thread execution via timers) with our batched protocol. No code copied. |
| **CommonSenseMachines/blender-mcp** | not verified tonight (web search did not surface it) | no | fork-style bridge plus CSM's hosted 3D generation | Ideas only. |
| **LL3M (threedle/ll3m)** | academic / evaluation license | research report 01 + PLAN | multi-agent LLM→Blender code with critic & retrieval | **Ideas only** (writer/critic loop, API retrieval). No code. |
| **Coding-Solo/godot-mcp** | MIT | research report 04 | launches Godot, runs projects, captures output | Candidate dependency/pattern for the games track; no code copied. |
| **Open-Godot-MCP** | MIT (per PLAN) | no | editor plugin bridge | Pattern only. |
| **OpenMontage** | AGPL-3.0 | PLAN + research | agentic video editing | **Ideas only. No code.** |
| **FilmAgent (HITsz-TMG)** | not verified tonight | no | multi-agent film crew in Unity (director, screenwriter, actors, cinematographer) with critique-correct loops | Ideas only: role split and "critique → revise" debate informed our Director/Camera/Critic split. |
| **ViMax (HKUDS)** | not verified tonight | no | agentic video generation: director/writer/producer | Ideas only. |
| **Rhubarb Lip Sync 1.14.0** | MIT (bundled deps Boost/BSD/MIT) | **yes** (LICENSE.md in release zip) | stable, standard in animation pipelines | Runtime binary, downloaded by `scripts/setup_assets.sh`, called as a subprocess. |
| **Kokoro-82M weights** | Apache-2.0 | research report 03 | best permissive CPU TTS | Default TTS, downloaded at setup, run in the GPL TTS worker. |
| **kokoro-onnx** | MIT (pulls espeak-ng, GPL) | research report 03 | maintained | pip dependency of the **TTS worker** only. |
| **Piper (`piper-tts` ≥1.3)** | GPL-3.0-or-later | research report 03 | maintained (OHF-Voice) | Optional fallback, subprocess only. |
| Piper voice `en-us-kathleen-low` | dataset **CC0** | **yes** (MODEL_CARD) | — | Allowed. |
| Piper voice `en-us-libritts-high` | dataset **CC BY 4.0** (LibriTTS) | **yes** (MODEL_CARD) | — | Allowed with attribution (THIRD_PARTY.md). |
| Piper voice `en-us-lessac-medium` | Blizzard 2013 Lessac license (research-only) | **yes** (MODEL_CARD) | — | **Rejected and deleted.** |
| Piper voice `en-us-ryan-medium` | dataset CC BY-NC-SA 4.0 | **yes** (MODEL_CARD) | — | **Rejected and deleted** (non-commercial). |
| **Blender Studio open movies** | CC-BY | not used tonight | — | Allowed for reference ingestion (Milestone 8) with attribution. |
| ffmpeg | LGPL/GPL depending on build | — | — | External program only. |
| numpy, pydantic, pillow | BSD / MIT / HPND | — | — | pip dependencies of the core. |

## Licensing layout of this repo

* `src/animatica/**` — Apache-2.0 (root `LICENSE`).
* `adapters/blender/**` — GPL-3.0-or-later (`adapters/blender/LICENSE`); runs inside Blender's process.
* `adapters/tts_worker/**` — GPL-3.0-or-later (`adapters/tts_worker/LICENSE`); loads GPL TTS code.
* `adapters/godot/**` — MIT (games track).
* The core talks to the GPL parts only through JSON over pipes/sockets (separate programs).
