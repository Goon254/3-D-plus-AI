# Savannah cast — walk tests (before the full film)

## v2: organic characters (after review)

[`walk_reel_before_after.mp4`](walk_reel_before_after.mp4): old primitive build (left) next to the new organic build (right),
same walk, all five species, 44 s. The new clips one at a time are in [`organic/`](organic/). Bodies are metaball-sculpted on the
anatomy graph with muscle masses and skinned to the same bone rig. Shading: fur on the zebra, giraffe and meerkat; wrinkled
subsurface skin on the elephant; scutes and scales on the tortoise. The meerkat stands up into its sentinel pose whenever it stops.
Measured on the rendered rig:

| species | max stance slide (mm) | max IK miss (mm) | render (s) |
|---|---|---|---|
| elephant | 0.0 | 0.07 | 58.9 |
| giraffe | 0.0 | 0.07 | 43.5 |
| zebra | 0.0 | 0.07 | 47.6 |
| meerkat | 0.41 | 30.23 | 41.3 |
| tortoise | 0.0 | 0.07 | 58.6 |

(The meerkat's 0.4 mm is the hind feet as the body pivots upright, and the front-paw IK miss happens with the paws tucked in the air. See
DECISIONS #40 for why metaballs won over Skin-modifier, CC0 base meshes and TripoSR.)

## v1: primitives (first review)

[`walk_tests_reel.mp4`](walk_tests_reel.mp4) (all five, labelled, 44 s), or one at a time:
[elephant](elephant_walk.mp4) · [giraffe](giraffe_walk.mp4) · [zebra](zebra_walk.mp4) · [meerkat](meerkat_walk.mp4) ·
[tortoise](tortoise_walk.mp4). Each clip: stand (idle: breathing, blinks, ear/tail/trunk motion) -> walk across frame
-> stop on four planted feet. Cycles on an RTX 5060 (OptiX), 960x540, 12 spp.

Made by `python scripts/creature_walk_test.py <species>`: procedural body plan on a bone rig (two-bone IK legs
with knee poles, neck/tail/trunk chains) and the foot-locked gait planner (`animatica.creatures`) using the
gait tables in `src/animatica/knowledge/species/`. The numbers below are **measured on the rendered rig**:
the world position of each foot bone tip after IK, every frame.

| species | gait | leg (m) | speed (m/s) | max stance slide (mm) | max IK miss (mm) | render (s) |
|---|---|---|---|---|---|---|
| elephant | walk | 0.587 | 0.462 | **0.0** | 0.07 | 42.2 |
| giraffe | walk | 1.616 | 1.022 | **0.0** | 0.07 | 35.0 |
| zebra | walk | 0.797 | 0.745 | **0.0** | 0.07 | 38.9 |
| meerkat | walk | 0.08 | 0.144 | **0.0** | 0.06 | 36.7 |
| tortoise | walk | 0.14 | 0.034 | **0.0** | 0.07 | 43.5 |

What to look for: feet stay put against the pebbles while planted. The elephant keeps two or more feet down
and its body rides over near-straight pillar legs. The giraffe's same-side legs move almost together
(lateral couplets). The zebra uses a four-beat LH-LF-RH-RF walk. The tortoise is slow, with a high duty
factor. Known gaps before production: no faces/mouths yet (dialogue), meerkat sentinel pose and scurry,
zebra trot/canter clips, tortoise shell scutes, grass and set dressing.
