# Research index

Deep research on open-source tools for this project, done on 2026-11-15. Every build and review session should read this before choosing a tool. Each report rates tools ADOPT / TRIAL / REFERENCE-ONLY / AVOID and lists license traps.

| Report | Topic |
|---|---|
| [01-3d-assets-and-blender.md](01-3d-assets-and-blender.md) | Blender automation, headless rendering benchmarks, procedural generation, image-to-3D models, asset libraries, scene formats |
| [02-animation-rigging-motion.md](02-animation-rigging-motion.md) | Rigging, keyframing APIs, stock motion data, text-to-motion, mocap from video, lip sync |
| [03-voice-music-sound.md](03-voice-music-sound.md) | Text-to-speech, music, sound effects, mixing, the final audio/video pipeline |
| [04-agents-infra-language.md](04-agents-infra-language.md) | Language choice, agent orchestration, MCP, Godot, critic design, infrastructure |

## Key decisions at a glance

- **Language:** Python for the core and the Blender adapter (`bpy` 5.3 needs Python 3.13). GDScript for the Godot plugin. TypeScript + three.js for the web UI and log viewer. Rust later, only for an optional native scene core and viewport.
- **Never `import bpy` in the Apache-licensed core.** Blender code runs in the GPL adapter, in a separate process.
- **Blender 5.x API:** `action.fcurves` was removed in 5.0. Use the channelbag API for keyframes; common LLM-written snippets will break.
- **Rendering on CPU:** Workbench for critic previews (~0.1 s/frame), Cycles CPU with denoise for finals, EEVEE only with a GPU.
- **Rigging:** Rigify or rigid bone parenting, both built into Blender.
- **Lip sync:** Rhubarb Lip Sync (MIT) → shape-key keyframes.
- **Voice:** Kokoro-82M via kokoro-onnx as default. Piper is now GPL and many of its voices are research-only; run any TTS in its own process.
- **Music:** MIDI composed in code, rendered with FluidSynth + GeneralUser GS. No AI music weights by default.
- **Assets:** Poly Haven and ambientCG (CC0), Kenney/Quaternius CC0 packs, Blender Human Base Meshes. Sandbox may block these sites: keep an offline cache and a procedural fallback.
- **Motion data:** Quaternius animation library, Mesh2Motion (CC0), CMU mocap, 100STYLE (CC BY 4.0). Avoid Mixamo, Bandai Namco, LaFAN1.
- **Orchestration:** thin custom Python orchestrator; Pydantic AI optional; official Python `mcp` SDK.
- **Avoid (license traps):** LL3M, OpenMontage, FreeMoCap (AGPL), Wav2Lip, MusicGen, AudioLDM2, F5-TTS, XTTS-v2, Hunyuan3D, InstantMesh, text-to-motion weights trained on HumanML3D/AMASS/SMPL, nvdiffrast, PyMeshLab in the core.
