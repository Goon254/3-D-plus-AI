# Kiki (meerkat), design v6

v5 (owner review 11-17): soft, lighter brown eye patches instead of raccoon rings; faint darker back bands; on all fours a lower, longer body with hunched shoulders (Species.hunch). Expressions now change the face: happy has smiling (lower-lid) eyes and a raised mouth, surprised has wide eyes, shrunk pupils and lifted brows.

| | |
|---|---|
| Rubric | **10.0** / 10, not ready |
| Silhouette reads as | — |
| 96 px thumbnail reads as | — |
| Appeal (critic) | — |
| Rig stress test | 13 / 13 checks pass |

## Files

* `sheet.jpg`: turnaround, expressions, silhouette, thumbnail, rubric panel.
* `motion.mp4`: 10 s from the rig stress take: she walks on all fours, turns toward the camera, rises back into the sentinel (her sit/stand), turns her head left and right, runs through every expression, then says her line — "Danger! Oh. It's a rock."
* `runner_up_1.jpg`: head × 1.1, eye × 1.08 (10.0).
* `runner_up_2.jpg`: head × 0.94, eye × 1.12, ear × 1.1 (10.0).
* `scores.json`: every number above, the failed checks and the stress-test checks.

## Failed checks

* none

## Still open

* Your call needed: the cloud reviewer (11-18) reads the lower, longer, hunched body on all fours as a weasel/mongoose from the side and prefers v4's shorter, higher-shouldered body. v5 follows your note; say which way.
* Appeal 7: the critic still wants more charm in the face before 'ready'.
* The patches are deliberately soft; at 96 px they read as shading round the eyes rather than a mask.
* Feet: fixed in the rig. Each foot hangs level from the ankle (DECISIONS #69) and the meerkat's hind paws pivot at the heel into the sentinel (#70), so `foot_plant` is now a hard check and passes for all five (planted soles stray 1.6-23 mm per stance, all under half the foot's radius). The motion clip here predates the fix until the laptop re-renders the stress takes.

## Runner-ups

Both runner-ups are small head/eye/ear morphs from the re-run loop, scored 10.0 without a species read, so they aren't comparable with the current design's score.

Approve, or reply with notes.
