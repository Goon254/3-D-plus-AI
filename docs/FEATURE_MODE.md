# Feature mode: `animatica feature "story"`

> Stage 3 of the 2026-11-18 day plan. Goal: one command takes a story idea to a finished short film, the
> way the savannah film was made by hand: **story engine → design gate → animatic gate → production**.
> The owner approves at the two gates; everything else runs unattended and resumes where it stopped.

## Usage

```
animatica feature "a shy tortoise and a fast zebra race to the river"   # start (or resume) a film
animatica feature --film films/shy-tortoise --status                       # where is it, what's next
animatica feature --film films/shy-tortoise --approve design              # owner gate 1
animatica feature --film films/shy-tortoise --approve animatic            # owner gate 2
```

Every run looks at what already exists in the film folder, does the next stages it can do on its own,
and stops at the first gate the owner hasn't passed, printing what to look at. Nothing is redone if its
output exists (delete a file to redo that step). One heavy process at a time, as everywhere else.

## Stages

| # | Stage | Output (in `films/<slug>/`) | Done when | Who |
|---|---|---|---|---|
| 1 | **story** | `01_premise.json` (logline, theme, cast with species, want/need/flaw/gift, beats), `04_screenplay.json` (scenes: time of day, intent, lines) | both exist and validate | story engine (LLM, or the offline scripted engine) |
| 2 | **design** | `design/<char>/approved.json` per character | every character has one | design loop + packets (DESIGN_STAGE.md), **owner gate** |
| 3 | **voices** | `06_voices.json` (cast → stock voice, pitch, rate, ref text) | exists | casting step |
| 4 | **scenes** | `07_scenes.json` (layout, cast blocking, lines, shots) | exists and passes `production.continuity` | scene planner |
| 5 | **animatic** | `output/<slug>-animatic/animatic.mp4`, `animatic_approved.json` | owner approves | animatic renderer (EEVEE), **owner gate** |
| 6 | **production** | `output/<slug>/<scene>/` final renders, `output/<slug>/film.mp4` | every scene rendered, mixed to −14 LUFS | final renderer (OptiX), resumable per scene |

The machine is `animatica.feature.stages`: each stage has a `done(film)` test and, for the two gates, an
owner approval file (`approvals.json` in the film folder: stage → date, note). `status()` lists the stages
with done / gate / blocked / todo; `next_stage()` is the first not done.

## The story engine (`animatica.feature.story`)

Two LLM tasks, both with deterministic offline handlers (`core.llm.scripted`) so the whole flow runs
without a key and in CI:

* `feature.premise`: idea → logline, theme, 2–5 characters (name, species from the creature library,
  personality, want → need, flaw, gift), a three-act beat sheet. The species are limited to what the
  creature library can build (`creatures.species.SPECIES`); an idea that names other animals is mapped to
  the nearest body plan and the mapping is noted.
* `feature.screenplay`: premise → 4–8 scenes, each with a time of day, an intent, the beats it covers,
  and lines (who, text, mood). Kid-film rules from the savannah critique: every character gets a moment
  that only they can solve, the hero's flaw costs something in act 2, setups pay off, lines short.

The offline handler builds a small, complete story from the idea's words (which animals, which place,
which goal), so the later stages always have real input.

Later (not in the first pieces): a `feature.critique` pass that scores the draft against the
`03_story_critique.md` checklist and revises it once, the same loop the savannah script went through.

## Gates

* **Design**: the existing design stage (DESIGN_STAGE.md): briefs from the species knowledge, best-of-N
  design loop, rig stress test, design packets. Characters reuse approved designs from other films when
  the species and role match (the savannah five are locked).
* **Animatic**: the savannah animatic pipeline (`savannah_animatic.py`), generalised to any film folder:
  real voices, music, timing, cameras; continuity check; the strict review against the owner's notes.

## First pieces (this session)

1. `animatica.feature.stages`: the stage table, `status`, `next_stage`, approvals. Tested.
2. `animatica.feature.story`: premise and screenplay tasks with offline handlers and validation. Tested.
3. `animatica feature` CLI: runs the story stage, writes the files, prints the status and the next step.

## Next pieces

4. ~~Casting step~~ **done** (`animatica.feature.casting`): a register per character from personality, then
   species (big & young, tall & gentle, fast & bright, small & quick, old & slow), each with two tested stock
   blends; no two characters share a voice (a semitone apart if a register runs out). Runs with the story.
5. ~~Scene planner~~ **first pass done** (`animatica.feature.planner`): per scene a layout for its time of
   day, the speaking cast in a shallow arc opening toward the cameras, each line addressed to the previous
   speaker, moods as expressions with a listener reacting, a species call at the first line, and shots cut on the
   lines (establishing EWS, a close shot sized by species, a two-shot on exchanges, a closing WS). The plan is
   continuity-checked before it is written. Next: a director pass (LLM) for blocking and gestures from the beats.
6. ~~Generalise the scene scripts~~ **done**: `savannah_scene.py` and `savannah_animatic.py` take `--film <folder>`
   (default `films/savannah`), and the animatic's title comes from the film's premise. The planner also writes
   the score's `05_cue_sheet.json` (wonder at the opening, the time of day's mood after, triumph at the end).
   Not yet run end to end on a new film: that needs the GPU, which was busy with the savannah final render.
7. Production stage: the final render loop with per-scene resume, mix, web copy.
