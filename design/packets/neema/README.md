# Neema (giraffe), design v2

v2: sturdier legs and hooves, a much bigger head and eyes so her face reads at 96 px on a 3 m animal, brows resting higher so she no longer scowls (DECISIONS #59).

| | |
|---|---|
| Rubric | **9.88** / 10, ready |
| Silhouette reads as | giraffe |
| 96 px thumbnail reads as | young giraffe |
| Appeal (critic) | 8 |
| Rig stress test | 7 / 7 checks pass |

## Files

* `sheet.jpg`: turnaround, expressions, silhouette, thumbnail, rubric panel.
* `motion.mp4`: 10 s from the rig stress take: she walks, turns toward the camera, bows and comes back up (no sit pose on this rig), turns her head, runs through every expression, then says her line — "There! I see her stripes!"
* `runner_up_1.jpg`: head × 0.94, eye × 1.12, ear × 1.1 (9.96).
* `runner_up_2.jpg`: head × 1.06, ear × 0.9, leg × 1.12, lift_dark × 0.6 (9.91).
* `scores.json`: every number above, the failed checks and the stress-test checks.

## Failed checks

* none

## Still open

* The rig stress test caught her brows floating 16 % of their size off the skin on 'surprised'; the lift is now capped (`brow_max` 0.7, 8 %). The motion clip has the fix; the sheet's surprised panel was rendered before it and still shows the higher brows. A fresh sheet needs a new critique, so it waits for your notes.
* No sit pose on the rig yet: the take bows and rises instead.

## Runner-ups

Runner-up 1 is a smaller head with bigger eyes and ears; runner-up 2 is a slightly bigger head, smaller ears, longer legs and a lighter coat. The loop scored them 9.96 and 9.91 without a species read.

Approve, or reply with notes.
