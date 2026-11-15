# Decision log

One line per decision: what + why. Newest at the bottom.

1. **Core license Apache-2.0** (the repo already had an Apache LICENSE); Blender adapter and TTS worker GPL-3.0-or-later in their own folders with their own LICENSE files.
2. **Blender via the PyPI `bpy` 5.3 wheel** in a child process speaking newline-delimited JSON over stdio — installs with pip, no apt/tarball, keeps GPL code out of the core process.
3. **Rollback = snapshot .blend before each mutating batch** (`undo_token` is its path) because Blender's undo stack is unreliable in background mode; identical behaviour headless and live.
4. **Stable ids = object names + `animatica_id` custom property**, so identity survives artist renames.
5. **Rotations in degrees, colours as `#RRGGBB` sRGB** in the protocol — what LLMs and artists write naturally; the adapter converts to radians / linear.
6. **Object-level rig (empties + parenting) instead of an armature for the hero** tonight: robust, readable in the outliner, animatable with batched keys; `create_armature` + `bind_mesh_to_armature` exist in the protocol for later.
7. **Mouth = small mesh with three shape keys (open / wide / round)**; Rhubarb's 9 visemes map to weights of those three. Cheap, readable, stylised.
8. **Parameters over strokes for the LLM**: agents ask the model for plan/performance/camera *parameters*; procedural recipes turn them into ops. LLM output is validated; unusable answers fall back to the scripted answer and the fallback is logged.
9. **Scripted offline provider = keyword parser + recipes**, deterministic per prompt (crc32 seeds, no Python `hash`).
10. **Animator samples composite curves every 2 frames** (pose curves with easing + spring follow-through + bob/breathing layers) into one batched keyframe op per channel; lip-sync keys are exact.
11. **Multi-shot = one camera per shot + timeline markers bound to cameras**, so a single render pass produces the cut and an artist sees the cuts in Blender's timeline.
12. **Critic previews: Workbench for per-batch verify, Cycles 12 spp for the per-shot exposure check.** Research recommends Workbench previews; we follow that for batch verification, but Workbench can't judge lighting/exposure, so the critic's 4 per-shot frames use low-sample Cycles (~2.5 s each). Switch with `--preview-engine workbench`.
13. **Final render: Cycles CPU 16 spp + OIDN + adaptive sampling + persistent data, 960×540.** EEVEE needs a GPU (software GL took 75 s for one frame).
14. **TTS: Kokoro-82M (kokoro-onnx) default, Piper fallback, both in a separate GPL worker process** (research report 03: Piper is GPL since 2025 and espeak-ng sits under Kokoro's phonemizer). Replaced the first implementation, which called Piper directly — logged per PLAN update rule 3.
15. **Piper voices restricted to CC0 (kathleen) / CC BY 4.0 (LibriTTS) datasets**; lessac (research-only) and ryan (CC BY-NC-SA) were downloaded, rejected, and deleted.
16. **Music: numpy procedural pads/arp/bass + wind ambience** (research: ADOPT for ambient beds and the offline path). FluidSynth + GeneralUser GS is the planned upgrade; apt had no fluidsynth candidate here.
17. **Dialogue ducking done in numpy** (-9 dB envelope with 150 ms smoothing) and final mux in ffmpeg; the mix is also placed on the .blend's VSE so artists hear it.
18. **Two-shot close-up for dialogue**: the "speak" close-up frames the hero's face *and* the prop it addresses (no rule-of-thirds offset), because the emotional beat is the relationship.
19. **Sun disc sits lower (4°) than the key light (12°)** — classic cheat so the sun reads on the horizon while the light still rakes the set.
20. **Quality presets**: `ci` (Workbench 192×108), `preview` (Workbench 480×270), `draft` (Cycles 640×360 8 spp), `final` (Cycles 960×540 16 spp), `high` (Cycles 1280×720 48 spp).
