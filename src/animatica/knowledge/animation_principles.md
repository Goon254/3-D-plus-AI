# Animation principles (applied by the Animator)

## Timing and spacing
Hold key poses long enough to read (≥ 8 frames at 24 fps for an emotion). Fast in, slow out reads as
energy; slow in, slow out (ease-in-out) reads as weight. Never move everything at once.

## Anticipation
Before a big action, move a little the opposite way: lean back before rolling forward, dip before a hop,
duck the head before a surprised look-up. 4–10 frames. Implemented: `lean` -9° before approach, `dip`.

## Overshoot and settle
Fast turns overshoot their target and settle back (BACK easing). Head snaps toward a discovery use
`ease("back")`. Stops overshoot by a few centimetres then settle.

## Follow-through and overlapping action
Loose parts (antenna, tail, ears, arms) keep moving after the body stops and lag behind when it starts.
Implemented as a damped spring driven by root acceleration: θ'' = −kθ − cθ' − g·a(t).

## Secondary motion
Small motions that support the main action: tread bob while rolling, idle breathing (≈2.6 s cycle,
0.6 cm), blinks (every 2–4 s, 5 frames, faster down than up), flower sway.

## Squash and stretch
Preserve volume: squash Z by s, widen X/Y by (1−s)/2. Use on landings, hops, and "settling in".

## Staging and silhouette
One idea per shot. Characters face the thing they react to. Keep the action readable in silhouette.

## Acting for dialogue
Head nods on stressed syllables, eyes widen at the start of a line, gestures (a reach) right after
the line, not during the first word. Lip sync: open on vowels, closed on M/B/P, round on O/U/W.
