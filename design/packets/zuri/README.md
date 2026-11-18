# Zuri (zebra), design v4

v3 (owner review 11-17): a stockier zebra: deeper chest, thicker neck and legs, a bigger head, a short bristly striped mane that follows the neck from withers to poll (a lofted ridge skinned to the neck, so it bends with it), real hooves (flat sole, sloped front wall, narrower coronet). Lids drawn up at rest; expressions change the face as for all five.

| | |
|---|---|
| Rubric | **10.0** / 10, not ready |
| Silhouette reads as | — |
| 96 px thumbnail reads as | — |
| Appeal (critic) | — |
| Rig stress test | 11 / 11 checks pass |

## Files

* `sheet.jpg`: turnaround, expressions, silhouette, thumbnail, rubric panel.
* `motion.mp4`: 10 s from the rig stress take: turn, stop, head turns, every expression, then the line — "I thought fastest was best. I'm sorry."
* `runner_up_1.jpg`: head × 1.1, eye × 1.08 (10.0).
* `runner_up_2.jpg`: eye × 1.15, snout × 0.88, neck × 0.92 (10.0).
* `scores.json`: every number above, the failed checks and the stress-test checks.

## Failed checks

* none

## Still open

* Hard failure, recorded honestly: on the silhouette alone I read 'zebra, but a donkey is the nearest other read', and the rubric counts that as ambiguous with a known confusion (donkey). The thumbnail reads as a zebra. The pony read from v2 is gone.
* Appeal 7: the face is calm but not yet charming at sheet size; 'happy' changes 3.7 % of the face (a dark mouth on a dark muzzle).
* The cloud reviewer (11-18) finds the toothed mane a little 'saw-back'; it can be softened into more of a brush if you agree.
* Feet: fixed in the rig. Each foot hangs level from the ankle (DECISIONS #69) and the meerkat's hind paws pivot at the heel into the sentinel (#70), so `foot_plant` is now a hard check and passes for all five (planted soles stray 1.6-23 mm per stance, all under half the foot's radius). The motion clip here predates the fix until the laptop re-renders the stress takes.

## Runner-ups

Runner-up 1 is a bigger head and eyes; runner-up 2 has bigger eyes, a shorter snout and a thinner neck. Both scored 10.0 without a species read.

Approve, or reply with notes.
