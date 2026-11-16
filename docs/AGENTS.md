# Agents and their contracts

Every agent: a role, a system prompt, a task name, structured JSON in/out, and the batches it may
submit. The LLM chooses **parameters**; agent code turns them into validated batches. If the model's
answer fails validation, the agent falls back to the deterministic scripted answer and logs it.

| Agent | Task | Input | LLM returns | Emits (batches) |
|---|---|---|---|---|
| **Director** (`agents/director.py`) | `director.plan` | prompt | `FilmPlan`: title, style bible (palette, mood, shape language, lighting), setting, one character (+voice), props, 3–4 shots (type, beat, duration, camera move, subject), dialogue with timing | none — plan is normalised (15–30 s, quotes become dialogue, shots long enough for their lines) |
| **Art/Asset** (`agents/asset.py`) | `asset.params` | plan | colours, proportions, antenna, prop glow, set density/seed/landmarks | set (ground, scatter, landmarks, sun/moon), character rig (`hero_*`), prop (`prop*`) |
| **Voice & Sound** (`agents/voice.py`) | — | dialogue, voice choice | — | WAV per line (TTS worker), Rhubarb cues → mouth keys, music bed, ducked mix |
| **Animator** (`agents/animator.py`) | `animator.performance` | plan, rig, line timings | per shot: energy, speed, head tilt, reach, bounce, look-around | one batch with ~3 000 keys: root path, lean, bob, breathing, head, eyes/blinks, arms, antenna spring, prop sway, lip sync |
| **Camera & Lighting** (`agents/camera.py`) | `camera.plan` | plan, hero path, asset sizes | per shot: azimuth, height, lens, fill, move; lighting energies, world strength, exposure | world + 3-light rig; one camera + aim empty per shot, cut markers, camera moves, sun dimming |
| **Critic** (`agents/critic.py`) | `critic.review` (vision, optional) | camera cuts, previews, line timings | issues with fixes | `inspect` + `render_preview` batches (read-only) |
| **Editor** (`agents/editor.py`) | — | quality preset, mix | — | render settings, soundtrack strip on VSE, save .blend, render frames → ffmpeg MP4 + contact sheet |

## Critic checks (each issue carries a machine-applicable fix)

| Check | Rule | Fix |
|---|---|---|
| off_frame | main subject < 85 % inside frame on any sampled frame | camera `fill_mul 0.85` |
| too_tight / too_small | subject screen height outside the shot-type range (wide 14–62 %, medium 30–92 %, close-up 20–90 %) | camera `fill_mul` toward range |
| behind_camera | subject behind the camera | camera `azimuth_add 15` |
| floor_intersection / floating | hero lowest point < −3 cm or > 8 cm (outside hops) | animator `floor_offset` |
| prop_off_frame | the prop leaves frame in shots about it | camera `fill_mul 0.85` |
| prop_sliver | in a dialogue single, the prop is 0–25 % in frame (a stray-looking edge sliver) | camera `lift_frac` (raise the bottom edge) |
| mouth_static | mouth shape keys ~0 during a dialogue line | redo voice + animation |
| too_dark / blown_out | preview mean luminance < 0.07 or > 0.82, or clipping | lighting `exposure ±` |
| static_shot | nothing moves and the camera is static | (minor note) |
| vision (if the provider can see) | model reads the 4 previews against shot goals | as returned |

Loop: plan → batches → previews → critique → fixes → re-layout, capped by `--critic-iterations` (default 3).
Everything is logged to `log/production.jsonl` and rendered by `animatica log`.

## Rig interface (shared by all character recipes)

`hero_root` (floor, path & yaw) → `hero_body` (lean, bob, squash) → `hero_head_pivot` (turn/nod/tilt) →
`hero_eye_L/R` (blink = scale Z), `hero_mouth` (shape keys `open/wide/round`), `hero_antenna_pivot`
(spring follow-through; a tail on the critter) · `hero_arm_pivot_L/R` (reach = negative X rotation).
