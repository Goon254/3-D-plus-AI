# Architecture

```
 prompt ─► Studio.film()                                              artist edits .blend ─► animatica continue
            │                                                                                     │
            ▼                                                                                     ▼
   ┌──────────────── ORCHESTRATOR (core/orchestrator.py) ───────────────────────────────────────────────┐
   │ TaskGraph: director → voice ┐                                                                       │
   │                    → asset ─┴→ animator → camera → review (critic loop ≤ N) → edit                  │
   │ Context: ProjectState (plan, scene model, locks, tuning) · Budget · ProductionLog (JSONL+previews)  │
   └────────────────────────────────────────────────────────────────────────────────────────────────────┘
            │ agents ask the LLM for parameters (Anthropic or offline Scripted provider)
            │ agents submit batches ───────────────────────────────────────────┐
            ▼                                                                   ▼
   core/protocol.py  validate (schema + semantics, locked ids)        audio/ (Apache)
            │ JSON lines over stdio / TCP                              tts.py ──JSON──► adapters/tts_worker (GPL): Kokoro / Piper
            ▼                                                          lipsync.py ─► Rhubarb (MIT binary) | amplitude fallback
   adapters/blender (GPL, separate process: bpy 5.3)                   music.py (numpy pads/arp/bass/wind, ducking mix)
     server.py (stdio/TCP) · live.py (add-on, main-thread timer)       mux.py ─► ffmpeg (MP4 H.264+AAC, contact sheet)
     executor.py: ops → bpy, snapshot rollback, previews, inspect
```

## Data on disk (`output/<project>/`)

| Path | What |
|---|---|
| `project.json` | prompt, plan, USD-shaped scene model, history, locks, critic tuning, artifact paths |
| `scene.blend` | the editable Blender project (cameras cut by markers, soundtrack on the VSE) |
| `scene.usda` | minimal USDA export of the scene model (OpenUSD groundwork) |
| `audio/` | `line*.wav`, `music_bed.wav`, `mix.wav` |
| `final.mp4` | the short |
| `log/production.jsonl` | every agent decision, batch, critique (with preview path), render |
| `log/previews/` | per-batch and per-shot critic previews |
| `log/index.html` | `animatica log` viewer |

## Engine-agnostic core

The orchestrator, agents, protocol and scene model don't know about Blender. The adapter boundary is the
JSON protocol; a Godot adapter (games track) or a future native viewport implements the same ops.
The scene model (`core/scene_model.py`) is USD-shaped — prims with ids, parents, `xformOp`-style
translate/rotateXYZ/scale, a material binding and animated-property names — and exports USDA.

## Artist in the loop

`animatica continue <project>` opens the saved `.blend`, queries it, diffs it against the stored scene
model, marks every changed aspect (`transform`, `material`, `parent`, deletions) as **locked**, and re-runs
the agents; `Context.filter_locked` drops any op that would overwrite a locked aspect. `animatica revise`
turns an instruction into plan/tuning deltas and spec-mode edits.
