# Bibi Kobe (tortoise), design v3

Approved and locked at v3 (owner review 11-17): the skirt-like rim flare is reduced and the shell's ray marks are smooth (a denser mesh and a soft-edged ray), no more pixel steps. Expressions change the face clearly (DECISIONS #65).

| | |
|---|---|
| Rubric | **9.53** / 10, ready |
| Silhouette reads as | tortoise |
| 96 px thumbnail reads as | leopard tortoise |
| Appeal (critic) | 8 |
| Rig stress test | 8 / 9 checks pass |

## Files

* `sheet.jpg`: turnaround, expressions, silhouette, thumbnail, rubric panel.
* `motion.mp4`: 10 s from the rig stress take: she walks, turns about 18 degrees toward the camera (she walks 3.6 cm/s, so a full turn would take 16 s; turning on the spot isn't planned yet), bows and comes back up (she has no sit pose), turns her head, runs through every expression, then says her line — "When you walk slowly, you learn to look up."
* `runner_up_1.jpg`: head × 1.1, eye × 1.08 (10.0).
* `runner_up_2.jpg`: head × 0.94, eye × 1.12, ear × 1.1 (10.0).
* `scores.json`: every number above, the failed checks and the stress-test checks.

## Failed checks

* `motion:foot_plant`: a planted sole (skin) strays up to 49.7 mm within one stance (LH, frames 113-383; limit 25 mm, half the foot's radius) over 12 stance phases

## Still open

* Locked: changes now need your sign-off (design/bibi_kobe/approved.json).
* Motion: she still can't turn on the spot, and has no sit pose.
* Feet: the new skin probe (DECISIONS #66) shows planted soles rocking heel-to-toe within a stance (soft `foot_plant` fails for all five). The fix is a planted-sole foot/hoof bone in the rig; not done yet.

## Runner-ups

Both runner-ups are small head and eye morphs, scored 10.0 by the loop without a species read, so they aren't comparable with the current design's score.

Approve, or reply with notes.
