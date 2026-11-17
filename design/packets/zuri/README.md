# Zuri (zebra), design v2

v2: the stripes wrap the body as chevrons with no bullseyes on the chest, forehead or rump; an upright brush mane stands on the neck's crest; the ears are bigger; the muzzle is smaller and charcoal-brown (DECISIONS #56).

| | |
|---|---|
| Rubric | **7.64** / 10, not ready |
| Silhouette reads as | pony with an upright mane |
| 96 px thumbnail reads as | zebra |
| Appeal (critic) | 7 |
| Rig stress test | 7 / 7 checks pass |

## Files

* `sheet.jpg`: turnaround, expressions, silhouette, thumbnail, rubric panel.
* `motion.mp4`: 10 s from the rig stress take: turn, stop, head turns, every expression, then the line — "I thought fastest was best. I'm sorry."
* `runner_up_1.jpg`: head × 1.1, eye × 1.08 (10.0).
* `runner_up_2.jpg`: eye × 1.15, snout × 0.88, neck × 0.92 (10.0).
* `scores.json`: every number above, the failed checks and the stress-test checks.

## Failed checks

* `face:happy`: happy changes 2.4% of the face close-up (min 3%): the expression doesn't read
* `read:silhouette` (hard): silhouette read as 'pony with an upright mane': misread as pony (a known confusion)
* `critic:appeal`: art-director appeal 7/10 (min 8)

## Still open

* Her ears hover about 3.6 cm above the head in this sheet's 3/4 view and in the motion test (no check measured it then). Fixed in code after the packet was built (DECISIONS #62: the ears now sit on the head, and a new hard check, `part_float`, catches any part off its base); the sheet and clip will be re-rendered with her v3 body.
* Hard failure: her silhouette alone still reads as a pony (long thin legs, horse body). The thumbnail reads as a zebra, because the stripes carry it. She needs a shorter-legged, stockier body plan, and the design loop has no 'shorter legs' morph yet.
* Not ready: please give notes on the silhouette direction (stockier foal? bigger head? shorter legs?) rather than approve.

## Runner-ups

Runner-up 1 is a bigger head and eyes; runner-up 2 has bigger eyes, a shorter snout and a shorter neck (a younger look). The loop scored both 10.0 without a species read, so neither has been checked against the pony read.

Approve, or reply with notes.
