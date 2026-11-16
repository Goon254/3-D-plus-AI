# CHALLENGE-SAVANNAH.md — a 5-minute kids' film with an ensemble cast

> Owner's top priority (2026-11-16). Push the system past its current limits: a real story, multiple characters with believable anatomy and motion, distinct voices, varied music. Quality over speed. All PLAN.md rules still apply (licensing §7, forbidden list §10, batching, critic loop, artist-in-the-loop). PHASE2.md stays on hold.

## The target

`animatica film` (or a new `animatica feature` mode) produces a **~5-minute animated short for kids (ages 4–9)** set on the **African savannah**, with:

- **A genuinely good story**: clear hero, want, obstacle, turning point, emotional payoff, and a gentle lesson (friendship, courage, sharing, being different). Three acts, 8–14 scenes, a narrator plus character dialogue. Kid-appropriate: no peril beyond mild suspense, no violence (predators can be characters, not hunters). Humor that lands for kids and parents.
- **An ensemble of 4–6 animal characters** (e.g., a young elephant, a meerkat, a giraffe, a zebra, a lion cub, a tortoise, a hornbill) — each with a distinct silhouette, personality, voice and musical theme.
- **Real anatomy and real motion**: species-correct proportions and quadruped/biped/bird **gaits on bone rigs** — elephant walk (lateral sequence, heavy weight shift, ear flap), giraffe pace (both legs on one side together, neck counter-swing), zebra walk/trot/canter, lion-cub stalk and pounce-play, meerkat upright sentinel pose and scurry, tortoise slow plod, bird hop and flight. No more hopping or gliding as a substitute for walking. Feet plant and don't slide (foot-lock / IK). Idle behaviour per species (tail swish, ear flicks, breathing, blinking, head turns).
- **Look**: stylized feature-animation look (appealing, rounded shapes, big expressive eyes) built on correct anatomy — not photoreal. Textured fur/skin patterns per species (zebra stripes, giraffe patches, lion mane shapes via procedural or CC0 textures), golden-hour savannah lighting, acacia trees, tall grass that moves in wind, termite mounds, a watering hole, dust, distant mountains, sky that changes across the day (dawn → midday → sunset → stars).
- **Cinematic camera**: establishing wides, character close-ups for emotion, over-the-shoulder dialogue, tracking shots for journeys, a satisfying final wide.
- **Audio**:
  - Narrator voice + a **different Kokoro voice per character** (pitch/speed tuned per character; check each voice's license per docs/research/03).
  - **Different music per scene**, scored to the emotion: a main theme + a short leitmotif per character, varied tempo/key/instrumentation per mood (adventure, suspense, comedy, tender, triumphant). Use real instrument samples (FluidSynth + GeneralUser GS, MuseScore CLI optional). Draw respectfully on East/Southern African musical colour (marimba, kalimba/mbira, shakers, hand drums, choral pads) without imitating any specific copyrighted song.
  - **Ambience and SFX** per location (wind in grass, birds, insects at night, water) and per action (footsteps per species, splashes).
  - Clean mix: dialogue always clear, music ducks, −14 LUFS.
- Output: `examples/showcase/savannah/final.mp4` at 1280×720 (or 1920×1080 if render time allows), ≤ 25 MB per committed file (commit a compressed showcase cut plus poster and contact sheet; keep the full-quality render out of git and describe it in PROGRESS.md), captions, `edit.mlt`, production log.

## How to get there

1. **Research first (web access).** Use web search/fetch to study references for each species: proportions, skeleton, gait patterns, behaviour, how they move their ears/tails/necks. Legal sources only: Wikimedia Commons (check each file's license), public-domain studies (e.g., Eadweard Muybridge's *Animal Locomotion* plates), scientific/educational pages, CC-BY/CC0 photos. **Study and take notes; do not copy images into the repo** unless they are CC0/PD and attributed in THIRD_PARTY.md. **Never download YouTube or other sites' videos.** Write findings to `knowledge/species/<animal>.md` (proportions as ratios, gait phase tables, key poses, behaviour beats) so agents reuse them.
2. **Story engine.** Upgrade the Director into a real storyteller: premise → logline → beat sheet (3 acts) → scene list → screenplay with narration, dialogue, action lines and emotional intent per beat → shot list. Add a Story Critic pass (structure, character arcs, kid-appropriateness, pacing, jokes, payoff) and revise before production. When an LLM is needed, the Claude Code session running this work may act as the writer directly (write the screenplay and plan files itself), or use the Anthropic provider if `ANTHROPIC_API_KEY` is set. The offline scripted provider is not good enough for this film.
3. **Character system.** Parameterised species builder (proportions from the knowledge notes) + **armature per body plan** (quadruped, long-neck quadruped, upright small mammal, bird, tortoise) with IK legs, foot-lock, spine/neck/tail chains, face rig (blink, brows, mouth shapes for Rhubarb visemes, ear controls). Option to use **CC0 rigged animal models** (e.g., Quaternius animal packs, check license per pack) as a base where they beat procedural results — record in THIRD_PARTY.md.
4. **Locomotion system.** Gait library driven by the species notes (phase offsets, stride length, duty factor, body bob and roll), path-following with foot planting on terrain, transitions between idle/walk/trot/run, plus acting layers (look-at, emotion poses, gestures).
5. **Music system rewrite.** A Composer agent that writes per-scene cues from the screenplay's emotional intent: tempo, key, mode, instrumentation, leitmotifs, transitions on scene cuts. No two scenes reuse the same cue unless it's a deliberate theme reprise.
6. **Long-form production.** Scene-by-scene production with caching (re-render only changed scenes), per-scene critic loops, continuity checks (time of day, character positions, props), and a final edit with transitions and title/end cards.
7. **Render on the owner's RTX 5060** with `--device optix`; budget RAM (16 GB) — render scenes one at a time.

## Definition of done

The hourly reviewer watches the full film (sampling frames from every scene and listening to the audio) and scores it ≥ 9/10 on: **story** (would a parent happily show it to their kid?), **character design**, **animation/motion** (species-correct gaits, no foot sliding), **visuals**, **voices**, **music variety and fit**, **mix**. Re-render scenes until it gets there. Record the scorecard in `docs/reviews/` and the film in PROGRESS.md.
