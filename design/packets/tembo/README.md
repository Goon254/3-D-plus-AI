# Tembo (elephant), design v3

Approved and locked at v3 (owner review 11-17): softer resting brows (they no longer slope into a worried look; the eyes sit a little deeper and the lids rest drawn up). Expressions change the face clearly: happy = smiling eyes and a raised mouth, surprised = wide eyes, small pupils, lifted brows (DECISIONS #65).

| | |
|---|---|
| Rubric | **9.58** / 10, ready |
| Silhouette reads as | elephant calf |
| 96 px thumbnail reads as | baby elephant |
| Appeal (critic) | 8 |
| Rig stress test | 8 / 9 checks pass |

## Files

* `sheet.jpg`: turnaround, expressions, silhouette, thumbnail, rubric panel.
* `motion.mp4`: 10 s from the rig stress take: he walks, turns toward the camera, bows and comes back up (no sit pose on this rig), turns his head, runs through every expression, then says his line — "Then I'll find it. For everyone!"
* `runner_up_1.jpg`: head × 1.1, eye × 1.08 (10.0).
* `runner_up_2.jpg`: head × 0.94, eye × 1.12, ear × 1.1 (10.0).
* `scores.json`: every number above, the failed checks and the stress-test checks.

## Failed checks

* `motion:foot_plant`: a planted sole (skin) strays up to 76.7 mm within one stance (LH, frames 122-139; limit 60 mm, half the foot's radius) over 26 stance phases

## Still open

* Locked: changes now need your sign-off (design/tembo/approved.json).
* Feet: the new skin probe (DECISIONS #66) shows planted soles rocking heel-to-toe within a stance (soft `foot_plant` fails for all five). The fix is a planted-sole foot/hoof bone in the rig; not done yet.

## Runner-ups

Both runner-ups are small head and eye morphs, scored 10.0 by the loop without a species read. The current design is ready on the rubric (9.84, with the recorded critique).

Approve, or reply with notes.
