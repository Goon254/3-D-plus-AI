# Design proposals

A proposal is a candidate **next version of a locked character**, built beside it and never over it
(DESIGN_STAGE.md §1 and §6; DECISIONS #112). Each folder holds `proposal.json` (field overrides on the locked
species, and why), the standard design sheet (`sheet.jpg`), the species-read images (`silhouette.png`,
`thumb96.png`), `score.json` (the rubric), `compare.jpg` (the locked design next to the proposal) and, once read,
`blind_read.json` (a reader with no context names the animal; DECISIONS #111).

    python scripts/design_proposal.py design/proposals/kiki-v7 --compare   # render, score, compare (~20 s on CPU)
    python scripts/design_proposal.py --list                               # every proposal, its blind read and status

A proposal is offered to the owner only if a blind reader reads it better than the locked design, or, for a design that already reads clearly, if the read stays clear (a shape fix; DECISIONS #114). Before it is
offered it runs the rig stress test as itself (`python scripts/rig_stress_test.py --proposal <folder> --no-render`,
CPU, under a minute; DECISIONS #120): the report goes to the proposal's `rig_stress.json` and is summarised in its
`score.json`. If he approves one, it is copied into `creatures/species.py` and a `design/<char>/<version>/` folder
like any approved design.

| proposal | status |
|---|---|
| [bibi_kobe-v4](bibi_kobe-v4/) | **offered.** Only the shell changes: a full round crown whose sides slope in above a level rim, a flatter plastron (`shape:shell_dome` 0.53 → 0.28, max 0.40; 0.57 × its length high, species notes 0.58). v3's scutes, marks, head and legs kept; no outward flare (the 11-17 "skirt" note). Rubric 9.7 (only the cast-wide brow note). Blind: tortoise 90 / thumbnail 92 from two fresh readers, the same as the v3 control. Rig stress test passed (all 9 checks, cloud 11-23 18:36, `rig_stress.json`). |
| [kiki-v7](kiki-v7/) | **not offered.** Head carried higher and a little bigger, body 4 % shorter, a thicker tail base, the back bands at the brief's colour; v4's legs and v5's light patches kept (the owner's 11-18 choice). Rubric 9.8, but the blind read did not improve: silhouette meerkat 45 (lizard / otter) vs v6's 70, thumbnail 60 (mongoose / weasel) as v6. Small parameter moves inside the owner's choices don't fix Kiki's read; see the 11-22 12:36 review. |
| [kiki-v8](kiki-v8/) | **shown, not offered as a replacement** (the picture for the owner's open Kiki question, DECISIONS #119). Reopens his 11-18 choices only where the 11-22 review pointed: a darker crescent mask, a straighter, taller sentinel with the nose up a little (`Species.sentinel_pose` 88° / 80° / 26°, tail 78°), a shorter tail brace, smaller hind paws. Blind: silhouette meerkat 80 / 80 from two fresh readers (v6 control 75; the lizard / otter alternatives gone), Kiki's first clear sentinel read; thumbnail on all fours 55 / 55 (control 70): the all-fours body is still the problem. Rig stress test passed (all 11 incl. `sentinel_tail` / `sentinel_paws`); by eye the 26° nose-up holds through her line, so in the close-up she talks to the sky ([stills](../../docs/reviews/assets/2026-11-23T1836Z-kiki-v8-stress-stills.jpg)). |
| [zuri-v5](zuri-v5/) | **offered.** The neck's tip runs up and back into the head so the brush mane reaches the poll (`mane_reach` 0.86 vs 0.76), a taller mane (0.15 m), a 6 % shorter barrel, a 4 % bigger head, 18 % bigger ears; v4's brush mane, chevron stripes and colours kept. Rubric 9.7 (only the cast-wide eye/brow outline notes). Blind: silhouette zebra 60 from two fresh readers (v4 control: zebra 55, horse 75; 11-22 09:36: zebra 50), thumbnail zebra 95 / 92 (v4 95). Better, still not a clear read. Rig stress test passed (all 9 checks, cloud 11-23 18:36). |
