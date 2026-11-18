# Neema (giraffe), design v3

Approved and locked at v3 (owner review 11-17): friendlier brows (smaller, tilted up at the inner end), a smaller, less pouty muzzle, lids drawn up at rest. Expressions change the face clearly (DECISIONS #65).

| | |
|---|---|
| Rubric | **9.61** / 10, ready |
| Silhouette reads as | giraffe |
| 96 px thumbnail reads as | giraffe |
| Appeal (critic) | 8 |
| Rig stress test | 8 / 9 checks pass |

## Files

* `sheet.jpg`: turnaround, expressions, silhouette, thumbnail, rubric panel.
* `motion.mp4`: 10 s from the rig stress take: she walks, turns toward the camera, bows and comes back up (no sit pose on this rig), turns her head, runs through every expression, then says her line — "There! I see her stripes!"
* `runner_up_1.jpg`: head × 0.94, eye × 1.12, ear × 1.1 (9.96).
* `runner_up_2.jpg`: head × 1.06, ear × 0.9, leg × 1.12, lift_dark × 0.6 (9.91).
* `scores.json`: every number above, the failed checks and the stress-test checks.

## Failed checks

* `motion:foot_plant`: a planted sole (skin) strays up to 46.2 mm within one stance (LH, frames 76-92; limit 38 mm, half the foot's radius) over 19 stance phases

## Still open

* Locked: changes now need your sign-off (design/neema/approved.json).
* Re-sheeted 11-18 with the hoof mesh every hoofed species now gets (the locked parameters are unchanged). Still open from the cloud review: pole legs with no knee.
* Feet: fixed in the rig. Each foot hangs level from the ankle (DECISIONS #69) and the meerkat's hind paws pivot at the heel into the sentinel (#70), so `foot_plant` is now a hard check and passes for all five (planted soles stray 1.6-23 mm per stance, all under half the foot's radius). The motion clip here predates the fix until the laptop re-renders the stress takes.

## Runner-ups

Runner-up 1 is a smaller head with bigger eyes and ears; runner-up 2 is a slightly bigger head, smaller ears, longer legs and a lighter coat. The loop scored them 9.96 and 9.91 without a species read.

Approve, or reply with notes.
