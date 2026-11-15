# PROGRESS — overnight build (in progress)

> Draft written mid-session; the final morning report replaces this section at the end of the night.

## Status right now

* `animatica film "<prompt>"` runs end-to-end offline (no API key): Director → Voice (Kokoro TTS + Rhubarb
  lip sync + procedural music) → Asset (set, rigged robot/critter, prop) → Animator (~3 000 keys) →
  Camera & Lighting (4 shots with cuts) → Critic loop → Editor (Cycles render → MP4 with sound).
* `animatica continue` / `animatica revise` preserve artist edits (tested).
* MCP server (`animatica-mcp`) with batched tools (tested in-process and over stdio).
* The north-star showcase is rendering at 960×540 (Cycles, ~9 s/frame, ~75 min).

## Milestones

| # | Milestone | Status |
|---|---|---|
| 0 | Foundation & license audit | done |
| 1 | Protocol + Blender adapter | done |
| 2 | Orchestrator, LLM layer, agents (offline first) | done |
| 3 | Prompt → MP4 with sound | done (showcase rendering) |
| 4 | Quality | partial |
| 5 | Artist in the loop | done |
| 6 | MCP server | done |
| 7 | Godot games track | not started |
| 8 | Reference study | not started |
| 9 | Polish | partial |
