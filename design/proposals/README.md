# Design proposals

A proposal is a candidate **next version of a locked character**, built beside it and never over it
(DESIGN_STAGE.md §1 and §6; DECISIONS #112). Each folder holds `proposal.json` (field overrides on the locked
species, and why), the standard design sheet (`sheet.jpg`), the species-read images (`silhouette.png`,
`thumb96.png`), `score.json` (the rubric), `compare.jpg` (the locked design next to the proposal) and, once read,
`blind_read.json` (a reader with no context names the animal; DECISIONS #111).

    python scripts/design_proposal.py design/proposals/kiki-v7 --compare   # render, score, compare (~20 s on CPU)
    python scripts/design_proposal.py --list                               # every proposal, its blind read and status

A proposal is offered to the owner only if a blind reader reads it better than the locked design. If he approves
one, it is copied into `creatures/species.py`, gets a rig stress test (`scripts/rig_stress_test.py`) and a
`design/<char>/<version>/` folder like any approved design.

| proposal | status |
|---|---|
| [kiki-v7](kiki-v7/) | **not offered.** Head carried higher and a little bigger, body 4 % shorter, a thicker tail base, the back bands at the brief's colour; v4's legs and v5's light patches kept (the owner's 11-18 choice). Rubric 9.8, but the blind read did not improve: silhouette meerkat 45 (lizard / otter) vs v6's 70, thumbnail 60 (mongoose / weasel) as v6. Small parameter moves inside the owner's choices don't fix Kiki's read; see the 11-22 12:36 review. |
| [zuri-v5](zuri-v5/) | **offered.** The neck's tip runs up and back into the head so the brush mane reaches the poll (`mane_reach` 0.86 vs 0.76), a taller mane (0.15 m), a 6 % shorter barrel, a 4 % bigger head, 18 % bigger ears; v4's brush mane, chevron stripes and colours kept. Rubric 9.7 (only the cast-wide eye/brow outline notes). Blind: silhouette zebra 60 from two fresh readers (v4 control: zebra 55, horse 75; 11-22 09:36: zebra 50), thumbnail zebra 95 / 92 (v4 95). Better, still not a clear read. Not stress-tested yet (laptop: `rig_stress_test.py` after approval). |
