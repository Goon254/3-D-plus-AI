# DESIGN_STAGE.md — near-best character models on the first prompt

> Owner decision (2026-11-16): before more film production, restructure the pipeline as **design → animatic → production**, with owner approval gates. This file specifies the design stage. Lessons it encodes come from the savannah iterations: clay-toy bodies, an elephant head that melted into its body, googly eyes, sliding textures, a meerkat that read as a rat / hamster / weasel, broccoli acacias, and a static 22-second opening — every one of them caught by a human, not by the pipeline.

## Goal

From a single prompt ("a young elephant calf, kids' film, warm and curious"), produce a character the owner would approve **on the first review** in most cases — or at worst need one round of notes — and catch every known failure class automatically before a human sees it.

## 1. Start from proven bases, not from scratch (raises the quality ceiling permanently)

- Build a **base-mesh library** once, at high quality, per body plan: quadruped (hoofed, padded, pillar-legged), long-neck quadruped, upright small mammal, bird, reptile/shelled, biped. Clean deformation-friendly topology, proper UVs, sculpted muscle masses, appealing default proportions, eye sockets with lids, mouth with lips/corners, rig + weights already validated.
- Species = **parametric morphs** (shape keys / proportion parameters) on a base, plus species parts (trunk, ossicones, mane, shell, beak) authored once as attachable modules. Never regenerate a body from primitives per film.
- Sources for bases: careful in-house authoring (the hand-built elephant/meerkat proved direct authoring with look-and-adjust beats generic generation), CC0/CC-BY rigged meshes when they're better (license recorded in THIRD_PARTY.md), optional image-to-3D (MIT/Apache models only, per docs/research) as rough starting forms that are then retopologised onto the base.
- Approved characters are saved as **versioned assets** (`assets/characters/<name>/v3/`) and reused across films; production may not alter an approved design.

## 2. Turn research into a measurable design brief

For each character, the research step outputs `design/<name>/brief.json`:
- real anatomy ratios (from knowledge/species/), then **stylisation rules for appeal**: head-to-body ratio by age (calves/cubs: big head), eye size relative to head, eye spacing, silhouette features that must read (trunk, ears, neck, shell dome, tail tip), colour palette and pattern (with contrast targets), personality → shape language (round = friendly, angular = sly, etc.);
- 3–6 legal reference images (Wikimedia Commons with license checked, public domain) used only for the critic's comparison, never copied into the repo unless CC0/PD and attributed.

## 3. Generate several candidates, not one

- From the brief, generate **N = 6 variants** (proportions, head shape, eye size, ear shape, colouring) in parallel.
- Render each as a **standard design sheet** with fixed lighting and cameras: front, side, 3/4, back, a black silhouette, a thumbnail at 96 px, and a face close-up with 3 expressions. GPU EEVEE/Workbench: seconds per sheet.

## 4. Judge like an art director (automatic, before a human sees anything)

Score every candidate on a written rubric with hard checks plus a vision-model review:
- **Species read**: the silhouette and the 96 px thumbnail are each identified as the intended species by the vision model, unprompted. (This alone would have caught the rat-meerkat.)
- **Appeal**: proportions inside the brief's ranges; eyes large enough, visibly set in sockets (60–70% embedded), with lids; readable face at thumbnail size; clear separation of head from body (neck/forehead visible — the melted-elephant failure).
- **Reference match**: the vision model compares the sheet with the reference images and lists mismatches (eye patches, shell scutes, leg thickness…).
- **Materials**: no flat black blocks; patterns contrast as specified; photo-based CC0 textures (ambientCG / Poly Haven) for skin, mud, bark instead of plain noise where it helps.
- **Consistency with the cast**: same style family (line weight, eye style, shading) as the other approved characters.
Pick the best candidate, apply the critique as parameter edits, re-render, repeat until it clears the threshold (max ~5 rounds).

## 5. Stress-test motion before approval

Every winning design runs a **rig stress test** before it reaches the owner: walk cycle, turn, sit/stand, head turns, blinks, all expressions, lip-sync line. Automatic checks: eyes stay seated, brows/lids don't float, **no texture swimming** (pattern fixed to rest pose), no intersections, feet planted. Any failure goes back to step 4.

## 6. Owner approval gate

Send the owner one **design packet** per character: the design sheet, a 10-second motion test with a voice line, the scores, and the top 2 runner-ups. Owner approves or gives notes. Only approved designs enter the library.

## 7. Then the animatic gate (before any expensive render)

Storyboard-style animatic for the whole film: grey-box or Workbench renders, final voices and music, real timing and camera moves. Checks: no static shot longer than ~4 s without motion or a story reason, every story beat readable, pacing for ages 4–9. Owner approves the animatic; only then does final production render scenes.

## 8. Learn from every human catch

Every issue the owner spots becomes (a) a rubric line or automated check, (b) a regression test, and (c) a note in `docs/LESSONS.md`, so the same class of mistake can't reach the owner twice.

## Order of work

1. Base-mesh library for the five savannah body plans, starting from the best existing versions (tortoise, zebra, giraffe are approved) and the hand-built elephant/meerkat proportions.
2. Design-sheet renderer + rubric + vision critic + best-of-N loop.
3. Rig stress test.
4. Re-run the five savannah characters through the new stage and send design packets.
5. Animatic for the savannah film.
6. Resume production.
