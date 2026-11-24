# Bibi Kobe (tortoise), design v3

Approved and locked at v3 (owner review 11-17): the skirt-like rim flare is reduced and the shell's ray marks are smooth (a denser mesh and a soft-edged ray), no more pixel steps. Expressions change the face clearly (DECISIONS #65).

| | |
|---|---|
| Rubric | **9.72** / 10, ready (re-scored with today's rubric and rig stress record; 9.53 when rendered) |
| Silhouette reads as (critic) | tortoise |
| 96 px thumbnail reads as (critic) | leopard tortoise |
| Blind read, no context (silhouette / thumbnail) | tortoise 85 (clear; turtle, armadillo next) / tortoise 93 (clear; turtle, box turtle next) |
| Appeal (critic) | 8 |
| Rig stress test | 11 / 11 checks pass |

## Files

* `sheet.jpg`: turnaround, expressions, silhouette, thumbnail, rubric panel.
* `motion.mp4`: 10 s from the rig stress take: she walks, turns about 18 degrees toward the camera (she walks 3.6 cm/s, so a full turn would take 16 s; turning on the spot isn't planned yet), bows and comes back up (she has no sit pose), turns her head, runs through every expression, then says her line — "When you walk slowly, you learn to look up."
* `runner_up_1.jpg`: head × 1.1, eye × 1.08 (10.0).
* `runner_up_2.jpg`: head × 0.94, eye × 1.12, ear × 1.1 (10.0).
* `scores.json`: every number above, the failed checks and the stress-test checks.

## Failed checks

* `shape:shell_dome`: the shell keeps its full width up to 52% of its height (max 40%): a ball or barrel; a tortoise's dome curves in just above the rim

Not scored (added to the rubric after this sheet was rendered; a re-render scores them): `face:eye_outline`, `face:brow_outline`. Not counted as passed; the eye and brow outlines were measured on later renders (DECISIONS #89, #115): open in docs/REVIEW_QUEUE.md.

## Still open

* Locked: changes now need your sign-off (design/bibi_kobe/approved.json).
* The shell still reads rounder than a dome (`shape:shell_dome`, soft, above). A proposal fixes it without touching the rest: design/proposals/bibi_kobe-v4/ (dome 0.28, blind read tortoise 90 / 92; passes every motion check). Your call: v4 or keep v3.
* Motion: she still can't turn on the spot, and has no sit pose.
* Motion clip: cut from the 11-17 take, before the feet fix (#69/#70); the rig stress record and the checks above are from the current rig, where every planted sole stays under half the foot's radius. The laptop's re-rendered take replaces the clip on the next `design_packet.py` run there.

## Runner-ups

Both runner-ups are small head and eye morphs, scored 10.0 by the loop without a species read, so they aren't comparable with the current design's score.

Approve, or reply with notes.
