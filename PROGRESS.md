# PROGRESS — morning report (overnight build, 2026-11-15)

## Day session 2026-11-18 (laptop, unattended): the owner's three-stage plan

**What you approved, and when** (so the gates are written down): your message of 2026-11-18 morning set the day's
plan. Stage 1 = fix your animatic notes; **Stage 2 was pre-approved once the Stage 1 review passed** (it passed,
[review](docs/reviews/2026-11-18-animatic-v2.md)); Stage 2 item 9 told me to **lock all five designs**: Kiki v6 (v4
body, v5 patches, as you asked) and Zuri v4 (soft brush mane) are locked with Tembo, Neema and Bibi Kobe v3. Phase 2
stayed on hold.

**Links**

* Animatic v2 (Stage 1 fixes, 316.8 s, 105 shots): [`savannah-animatic/animatic_v2_web.mp4`](examples/showcase/savannah-animatic/animatic_v2_web.mp4),
  [contact sheet](examples/showcase/savannah-animatic/animatic_v2_contact.jpg), [strict review](docs/reviews/2026-11-18-animatic-v2.md).
* Final film (OptiX, 1280×720, −14 LUFS): [`savannah-film/film_web.mp4`](examples/showcase/savannah-film/film_web.mp4) ([contact sheet](examples/showcase/savannah-film/film_contact.jpg); 316.8 s, 22.8 MB web copy at 540p; measured −14.0 LUFS); full quality in `output/savannah/film.mp4` (200 MB, not committed)
* Trailer: [`savannah-trailer/trailer_web.mp4`](examples/showcase/savannah-trailer/trailer_web.mp4) (70.6 s, 15 cuts on the lines, title card and the end card "Made with Animatica · open source", 23.1 MB at 720p); full quality in `output/savannah/trailer.mp4`

**Stage 1 (your animatic notes), all done** (DECISIONS #73–#82):

* Lip sync and acting from the dialogue: the mouth was already on the audio (median lag 0 ms); the real causes
  were a 42 ms picture delay when scenes were joined (now 0), faces too small to read (talking shots are tightened),
  and no acting. Now: head beats on stressed syllables, blinks at line starts and pauses, listeners blink and the
  addressee nods, speakers turn toward the camera.
* Continuity checker (`scripts/continuity_check.py`): who is on stage in every shot, lines, gestures, distance
  from the action, the real camera frames, and (new) nobody inside a mound or tree. 0 violations. The zebra leaves
  SC 5 and isn't in the tall-grass scene until she re-enters.
* Paths: real destinations (exit:right, landmarks) and smooth curves; no more circles.
* Opening: giraffes and zebras cross the far grass, birds, wind in the grass, a slow push-in; the white horizon
  stripe is gone.
* Sound (all synthesised, recorded in THIRD_PARTY.md): per-species footsteps placed by the camera, animal calls,
  a real log creak, the gush and the spring's song; every line at least 12 dB over the music (SC 10: 13 dB).
* Moonlit nights, the glowing spring.
* All five Kokoro fallbacks re-voiced with Chatterbox (the off-screen "Hellooo?" is now "Hello? Anybody?";
  Whisper heard the stretched spelling as a wrong word every time). The two dropped short shots are back.

**Stage 2** (DECISIONS #79, #83, #84): Kiki v6 and Zuri's brush mane (both pass every motion check; designs
locked); real baobab and log models, an irregular puddle with a mud bank, layered acacia tables; Kiki rides on
Neema in SC 10 (with a shot of it). Feet: the hard no-sliding check from #69/#70 passes for all five. The final
render and the trailer are made by `scripts/savannah_film.py` (resumes scene by scene).

**Stage 3: `animatica feature "story"`** ([plan](docs/FEATURE_MODE.md), DECISIONS #80, #85–#87): a stage machine
with your two gates (design, animatic) that resumes from the film folder; an offline story engine (premise and
screenplay, validated against what the creature library can build); casting (distinct stock voices); a rule-based
scene planner (continuity-checked) and cue sheet; the scene and animatic scripts take `--film`. Try:
`animatica feature "a little meerkat and an old turtle look for the lost rain" --llm scripted`.

**Still weak (honest)**

* Night close-ups read but are murky (the moon rims from behind); SC 8's tortoise shot is the darkest.
* Close-ups of Bibi Kobe and Kiki are often crowded by a neighbour's legs at the frame edge.
* The cloud reviewer, looking at the sheets: Kiki v6 still reads as a mongoose on all fours (6/10), and her eyes
  break the head's outline; Zuri's mane stops halfway up the neck and her body reads horse-like (7/10). Both were
  locked by your plan; they are the first candidates for a v7/v5 if you want another pass.
* Feature mode hasn't rendered a new film end to end yet (the GPU was busy with the savannah film).
* Nobody has listened to today's mix with ears.

### Needs you (day session)

* **Watch the film and the trailer**, and listen: footsteps, calls, the creak/gush/song, the voices.
* **Kiki and Zuri**: locked per your plan. Say if you want another design pass on the notes above.
* **When you apply film notes** (laptop): first `python scripts/continuity_check.py --cameras --json output/continuity_before.json`, then `--cameras --diff output/continuity_before.json` after each scene fix to see what was fixed and what is new (cloud 11-19 15:36, DECISIONS #94; 49 open findings today: 3 `dead_air` (#100), 26 `crowding` (#103)).
* An `ANTHROPIC_API_KEY` would let the story engine, the vision critic and the director pass run live.
* Nothing failed twice today without a workaround (the SC 8 tortoise close-up took two fixes and is weak, not broken).

### Cloud build 11-20 18:36 UTC

[Review](docs/reviews/2026-11-20T1836Z.md), DECISIONS #103. Still no reply from you, so nothing in the film or the designs changed. The last "known, still open" film note now has a check: **`crowding`** finds close and medium shots where a neighbour shows up only as legs or a flank, with its head out of the frame (the giraffe's legs behind Kiki at 2:30, the zebra legs at the edge of the tortoise close-ups). The film has a lot of it: 26 shots on the approximate cameras, 22 of them real when I looked; the herd stands too close in most face shots. It runs in `python scripts/continuity_check.py --cameras` and on the real cameras in every scene build; a shot can be marked `crowd_ok` when a foreground body is the point. With this, every note any review or you have made has an automatic check; the cloud sessions will only review from here until you reply.

### Cloud build 11-20 15:36 UTC

[Review](docs/reviews/2026-11-20T1536Z.md), DECISIONS #102. Still no reply from you, so nothing in the film or the designs changed. The dark tortoise close-up the reviews kept noting (SC 8, 3:48) is now measured: **`dark_faces`** finds any close or medium shot whose subject's head renders near black, by drawing the head's box through the shot's camera on the frame. On the final film it finds exactly that shot (two cuts of it, 3:50 and 3:54); every other face, dusk and night included, passes with a margin. It is in the animatic's own report (`dark_faces` in `animatic.json`) and in `python scripts/frame_check.py <film> --faces --animatic examples/showcase/savannah-animatic/animatic.json`.

### Cloud build 11-20 12:36 UTC

[Review](docs/reviews/2026-11-20T1236Z.md), DECISIONS #101. Still no reply from you, so nothing in the film or the designs changed. The dead-air check now runs where you will see it: the animatic's own report (`animatic.json`) lists every stretch over 4.5 s where nothing on screen moves but the camera, per scene, on that scene's real cameras and voice timings, and the scene build prints it with the other continuity findings. On the laptop, `python scripts/savannah_animatic.py --assemble` (no render) adds it to the current animatic.

### Cloud build 11-20 09:36 UTC

[Review](docs/reviews/2026-11-20T0936Z.md), DECISIONS #100. No reply from you yet, so no scene, design or render was touched (one annotation: the end card's shot is marked `hold`, a deliberate still; it renders the same). Your first animatic note, "the first scene has no animal movement", is now a check that runs before anything renders: **`dead_air`** in `python scripts/continuity_check.py --cameras` finds any stretch over 4.5 s, across cuts, where nothing on screen moves but the camera. The old 22 s opening fails; today's passes. On the film it finds three, which I confirmed on animatic v2: the SC 9 climax (Kiki stands still with her back to the spring for ~12 s), a silent 7.5 s Kiki close-up at the end of SC 5, and the 5 s empty sunset wide that opens SC 7. They join your parked film notes. Every catch you and the reviews have made now has an automatic check.

### Cloud build 11-20 06:36 UTC

[Review](docs/reviews/2026-11-20T0636Z.md), DECISIONS #99. No reply from you yet, so no scene or design was touched. Your "horizon stripe" note is now a check on rendered frames: `python scripts/frame_check.py <video or still>`, and the animatic measures every shot. The 11-16 still fails. **Honest finding: the film still has a toned-down version** (a pale tan band under the hills) in the SC 4–6 midday/afternoon wides (1:41–3:02); dawn, dusk and night are clean. It is parked with your other set notes until after the animatic. Left on the eye-only list: the static opening. Scores unchanged (film 7; Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9).

### Cloud build 11-20 03:36 UTC

[Review](docs/reviews/2026-11-20T0336Z.md), DECISIONS #98. No reply from you yet, so no scene or design was touched. Your "broccoli acacias" note is now a check: **every acacia crown is measured as built** (`set_canopy`, in `continuity_check.py` and every scene build): the 11-16 cushion fails (no sky through it), the 11-17 clumps fail (round florets), the 11-18 layered tables in the film pass. Left on the eye-only list: the horizon stripe and the static opening. Scores unchanged (film 7; Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9).

### Cloud build 11-20 00:36 UTC

[Review](docs/reviews/2026-11-20T0036Z.md), DECISIONS #97. No reply from you yet, so no scene or design was touched. The last eye-only design catch became a check: **ears seen edge-on as fins are now measured** (`shape:ear_edge`, hard): Tembo's old flat ears fail from 3/4 (0.19), the whole cast passes (0.34–0.53). Every known design failure is now caught by the pipeline. Scores unchanged (film 7; Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9).

### Cloud build 11-19 21:36 UTC

[Review](docs/reviews/2026-11-19T2136Z.md), DECISIONS #96. No reply from you yet, so no scene or design was touched. Another eye-only catch became a check: **bullseye stripes are now measured** (`materials:stripe_rings`, hard): Zuri's baseline chest and rump rings fail (2.6 %, 15 %), her current chevrons pass (0.7 %). Scores unchanged (film 7; Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9).

### Cloud build 11-19 18:36 UTC

[Review](docs/reviews/2026-11-19T1836Z.md), DECISIONS #95. No reply from you yet, so no scene or design was touched. One eye-only catch became a check: **Bibi Kobe's ball-like shell is now measured** (`shape:shell_dome`, soft): her shell keeps its full width up half its height (0.53; a dome is ≤ 0.40), a number for the next design pass. Scores unchanged (film 7; Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9).

### Cloud review of the final film (11-19 00:36 UTC, reviewer only)

[Review](docs/reviews/2026-11-19T0036Z.md): **7/10, not done yet**. It is a watchable five-minute film with a real
story (8), and golden hour, the opening and the sunset are the best images so far. What holds it back: Zuri stands
on Bibi Kobe's shell in the last scene (nothing checks for animals walking into each other); the climax shows Kiki
from behind in a washed-out pale-green glow with a bright white log end; the far mountains read as pillows; Kiki's
sentinel reads as a kangaroo; the web film peaks at +0.5 dBFS (loudness itself is right at −14 LUFS). Voices and
music couldn't be heard from the cloud. Scores: story 8, design 7, motion 7, visuals 7, mix 7. Fixes are queued
under P0-FILM for after you've watched it.

### Cloud build 11-19 03:36 UTC

[Review](docs/reviews/2026-11-19T0336Z.md), DECISIONS #90. Two film fixes that are pure code (no scenes touched):
**animals walking into each other are now checked** (`continuity_check.py` finds three on the film: Tembo and Zuri
in SC 3, Tembo and Kiki in SC 6, Tembo and Bibi Kobe in SC 7; the SC 10 "Zuri on the shell" is a camera angle, not
contact), and **the mix is limited and measured after encoding** (the +0.5 dBTP came from the web copy's second
AAC pass). **Needs you / the laptop**: `python scripts/savannah_film.py --assemble` and `--trailer` to re-master
the committed copies (minutes, no render); the marks move after you've given film notes.

### Cloud build 11-19 06:36 UTC

[Review](docs/reviews/2026-11-19T0636Z.md), DECISIONS #91. **Staging tangents are now checked on the cameras**:
a farther animal's feet drawn on a nearer one's back or shell (the "Zuri on the shell" at 5:06). The scene script
checks its real cameras; `python scripts/continuity_check.py --cameras` checks the whole film in seconds on
approximate cameras and finds the SC 10 case plus seven candidates (mostly Kiki or Bibi Kobe in front of a taller
animal on a low camera: SC 4–9). Nothing in the film changed. **Needs you / the laptop**: unchanged from 03:36
(watch the film and give notes; re-assemble for the true peak); the next scene build prints the tangents on the
real cameras.

### Cloud build 11-19 09:36 UTC

[Review](docs/reviews/2026-11-19T0936Z.md), DECISIONS #92. **The film's hand-off files are code now**:
`python scripts/savannah_film.py --deliver` writes CHALLENGE "Output" into `examples/showcase/savannah/`:
`final.mp4` (1280×720, ≤ 25 MB, captions as a switchable track), `poster.jpg`, `captions.srt` / `.vtt`,
`edit.mlt` (opens in Shotcut / Kdenlive) and `production_log.md`. Nothing in the film changed. **Needs you / the
laptop**: after `--assemble` and `--trailer`, run `--deliver` (minutes, no render) and commit the folder.

### Cloud build 11-19 12:36 UTC

[Review](docs/reviews/2026-11-19T1236Z.md), DECISIONS #93. **Back views in face shots are now checked**
(`staging.facing_away`): a close-up or medium shot whose subject we see from behind. On the film it finds the
climax (Kiki's back as the spring sings, SC 9) and four more (Tembo in SC 6, 8 and a close-up of the back of his
head in SC 9; Zuri in SC 8); seven of the nine are plain back views on the committed film. A shot that should be
from behind can say so (`"from_behind": true`). Nothing in the film changed; still no reply from you, so the
next runs review only unless you or the laptop push. **Needs you**: unchanged (watch the film, give notes).

## 0. Design stage — owner's top priority since 2026-11-16 23:58 (DESIGN_STAGE.md)

Film production is **paused** until the owner approves the five design packets, then the animatic.

Cloud review 11-18 21:36 UTC ([review](docs/reviews/2026-11-18T2136Z.md), DECISIONS #89): main is green again,
and your 11-18 plan is now written down: all five designs are locked (Kiki v6, Zuri v4) and the final savannah render
runs on the laptop, so the "please confirm" note from 18:36 is answered. **New automatic check**: eyes and brows are
measured against the head's outline from every sheet view. It confirms what the reviews saw by eye: in the 3/4 view
every character's far brow hangs in the air beside the head, and Zuri's and Neema's eyes bulge out of the head from
the front. These are soft checks; no locked design was changed, and the fix waits for your next design pass. Scores:
Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9.

Cloud review 11-18 18:36 UTC ([review](docs/reviews/2026-11-18T1836Z.md)): reviewer only, since the laptop was active. **Main was red for four pushes** (a formatting check, and Kiki's stress report went stale with v6); both are fixed and everything passes. Kiki v6 and Zuri's brush mane pass every motion check. Looking at the sheets: Kiki v6 still reads as a mongoose on all fours (6), and Zuri's mane stops halfway up her neck (7). Scores: Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 8. **Needs you:** the packets and this page still say Kiki and Zuri are waiting for you, while the laptop treats Stage 2 as pre-approved. Please confirm which designs and which animatic you've approved, so the gates are written down.

Cloud review 11-18 15:36 UTC ([review](docs/reviews/2026-11-18T1536Z.md), DECISIONS #72): no new notes from
you, so fixes only. **Kiki's sentinel pose is now checked automatically**: her paws must stay tucked high at the
chest (close to the body, level, well off the ground) whenever she stands up, alongside the existing tail-on-the-ground
check; a version with hanging arms fails it. All five characters pass every motion check. No designs changed. Scores:
Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9. **Still waiting on you:** Kiki (which body on all fours: v5 per
your note, or v4's) and Zuri (approve or notes). Laptop: re-render the stress takes and packets, then rescore.

Cloud review 11-18 12:36 UTC ([review](docs/reviews/2026-11-18T1236Z.md), DECISIONS #71): no new notes from
you, so fixes only. **Manes and hooves are now checked automatically**: a board or fin mane and puck hooves (both
caught only by eye on Zuri v2) fail the rubric, and a saw-tooth crest is flagged (Zuri v3's mane is one, which the
silhouette confirms; it gets fixed in her polish round after your notes). No designs changed. Scores: Tembo 9,
Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9. **Still waiting on you:** Kiki (which body on all fours: v5 per your
note, or v4's) and Zuri (approve or notes). Laptop: re-render the stress takes and packets, then rescore.

Cloud review 11-18 09:36 UTC ([review](docs/reviews/2026-11-18T0936Z.md), DECISIONS #70): no new notes from
you, so fixes only. **Kiki's feet are fixed too**: her hind paws now pivot at the heel as she rises into the
sentinel, so the soles stay flat on the ground (7.1 → 1.6 mm per stance). The foot check is now strict, and all five
characters pass it. No designs changed. Scores: Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9. **Still waiting
on you:** Kiki (which body on all fours: v5 per your note, or v4's) and Zuri (approve or notes). Laptop: re-render
the stress takes and packets so the clips show the planted feet.

Cloud review 11-18 06:36 UTC ([review](docs/reviews/2026-11-18T0636Z.md), DECISIONS #68, #69): no new notes from
you, so fixes only. **Planted feet no longer skate**: each foot now hangs level from the ankle, and four of five pass
(Tembo 77 → 21 mm, Zuri 61 → 9, Bibi 50 → 3, Neema 46 → 23); Kiki is 1 mm over on a hind paw. Stress reports are now
tied to the design they measured, so stale ones can't pass, and the packets' index
([`design/packets/README.md`](design/packets/README.md)) is generated, so it shows the current versions (it still
said Kiki v4 / Zuri v2). Scores: Tembo 9, Neema 8, Bibi 8, Kiki 6, Zuri 7, tooling 9. **Still waiting on you:** Kiki
(which body on all fours: v5 per your note, or v4's) and Zuri (approve or notes).

Cloud review 11-18 03:36 UTC ([review](docs/reviews/2026-11-18T0336Z.md), DECISIONS #66): your notes arrived, and the
laptop locked **Tembo, Neema and Bibi Kobe v3** (#65). Reviewer scores: Tembo 9, Neema 8, Bibi 8, Kiki v5 6 (reads as a
weasel on all fours: a step back from v4), Zuri v3 7, tooling 8. Foot slide is now measured on the skin, not the IK
bone: every planted foot **skates 8–77 mm within a stance**, because the rigid hooves and feet rock about the ankle.
That needs a rig fix before the animatic. The slimmer v3 brows float off the skin in motion (Neema 21 %, Zuri 13 %).
Still waiting on you: Kiki and Zuri.

Cloud review 11-18 00:36 UTC ([review](docs/reviews/2026-11-18T0036Z.md), DECISIONS #64): still waiting for your
notes on the packets in [`design/packets/`](design/packets/README.md), so fixes only. The flat-black check now also
catches near-black painted marks (not only base colours), and Kiki's paw shade is tied to her rest height. No design
changed; scores unchanged.

Cloud review 11-17 21:36 UTC ([review](docs/reviews/2026-11-17T2136Z.md), DECISIONS #63): still waiting for your
notes on the packets, so fixes only. The rig stress reports were refreshed for all five: the new `part_float` check
passes through every take (Zuri's ears stay on her head in motion), and `foot_slide` now records how many planted
feet it measured and fails on zero. Scores unchanged.

Cloud review 11-17 18:36 UTC ([review](docs/reviews/2026-11-17T1836Z.md), DECISIONS #62): **the five design packets
are ready for you in [`design/packets/`](design/packets/README.md)**. Reviewer scores: Tembo 8, Neema 7, Kiki 7, Zuri 6,
Bibi 7, tooling 8. Watching the clips showed Zuri's ears hovering 3.6 cm above her head, which no check measured.
That is now fixed in code, with a new hard check (`part_float`) for every ear, mane, ossicone, muzzle and nose, but her
packet still shows the old ears. No new features until you reply.

Laptop GPU session + cloud review 11-17 15:36 UTC ([review](docs/reviews/2026-11-17T1536Z.md), DECISIONS #55, #56):
**Kiki v4** reads as a meerkat both on all fours and in the sentinel (crisp mask, slim barrel, bent legs, paws-only
shade, tail attached in the sentinel): rubric 9.76, appeal 7 ([`design/kiki/v4/`](design/kiki/v4/)). **Zuri v2**: stripes
wrap as chevrons with no bullseyes, plus bigger ears and a softer muzzle, but the mane is a flat board, the hooves are
pucks and the silhouette reads as a pony: 7.4 ([`design/zuri/v2/`](design/zuri/v2/)). **Bibi Kobe v2**: a real carapace with leopard rays (#57),
but the rays are stair-stepped. Reviewer scores: Kiki 7, Zuri 6, Bibi 7, Tembo 7, Neema 7. Next: Zuri v3 (mane, hooves, filly proportions), then Bibi's shell and Tembo's ears.

Cloud session 11-17 12:36 UTC ([review](docs/reviews/2026-11-17T1236Z.md), DECISIONS #54): **Kiki v3**: the head
is carried forward with a nape and a throat line, the snout is one cone out of the face, and the sentinel stands with
the head level. **Happy now reads** for four of the five (smiling eyes, wider smile). `design_sheet.py --rescore`
lets a recorded critique stick to its sheet. Kiki 5.2 → 7.4: the sentinel reads as a meerkat, and the thumbnail on
all fours reads as a mongoose (next: crisper patches, a slimmer barrel, shorter legs): [`design/kiki/v3/`](design/kiki/v3/).

Cloud session 11-17 09:36 UTC ([review](docs/reviews/2026-11-17T0936Z.md), DECISIONS #53): **Kiki v2**: a new
meerkat base (shorter deeper body, bigger raised head, short tapering tail, dark ears, coat-shade legs, visible eye
patches) and an upright sentinel with paws tucked and a tripod tail, whose silhouette now reads as a meerkat. On all
fours she still reads as a puppy or mongoose (no throat line, tube snout). Score 2.6 → 5.2: [`design/kiki/v2/`](design/kiki/v2/).

Cloud session 11-17 06:36 UTC ([review](docs/reviews/2026-11-17T0636Z.md), DECISIONS #52): **steps 2 (sheet renderer,
rubric, critic, best-of-N loop) are built**: briefs for all five in [`design/`](design/README.md), `animatica.design`
(measure, brief, variants, rubric, image checks, critic), `scripts/design_sheet.py`, `scripts/design_loop.py`, 16 tests.
The current designs were sheeted and reviewed ([`design/baseline/`](design/README.md#baseline--the-current-designs-before-the-design-loop-cloud-review-2026-11-17-0636-utc)):
Tembo 9.6, Neema 9.8, Bibi Kobe 9.3 (appeal 6–7 blocks them), Zuri 7.3 (silhouette reads as a horse), Kiki 2.6
(reads as a weasel / prairie dog). Next: base-mesh fixes for what morphs can't change (REVIEW_QUEUE P0-DESIGN), the
rig stress test (step 3), then the loop per character and the packets.

## 0b. Savannah film (CHALLENGE-SAVANNAH.md) — production paused for the design stage

Laptop session 11-17 (owner's list): **Chatterbox (MIT) is the voice engine** on the RTX 5060 (CUDA torch 2.7.1),
steered by the approved Kokoro blends, with a Whisper check per take, Kokoro fallback and a line cache (#45);
**eyes sit in sockets** with lids and brows on the skin, and a rigid skull (#46); **coat patterns are pinned** to the
rest pose (#47); **meerkat v3** (#48); the **set pass** (clumped canopies, warm haze, denser foreground grass, #51);
SC 2 re-voiced and drafted at 960×540 on OptiX ([`sc02_draft.mp4`](examples/showcase/savannah-scenes/sc02_draft.mp4)).
New Critic checks measure eye seating, brow/lid contact and texture swim on the deformed meshes
([eye/coat sheet](examples/showcase/savannah-face-tests/eye_coat_sheet.jpg)). SC 1 final render (1280×720, OptiX) is for
the owner's review (full quality stays out of git: `output/savannah/sc01/sc01.mp4`).

Status 11-17 03:36 UTC ([review](docs/reviews/2026-11-17T0336Z.md)): **SC 2 now plays its gag in the picture**
(Tembo drinks, the trunk "hiccups" a jet of water onto Kiki, Neema ducks, heads turn to whoever speaks). Done so far:

* Species research notes (elephant, giraffe, zebra, meerkat, leopard tortoise): `src/animatica/knowledge/species/`.
* Story: premise and beats, draft 1, story-editor critique, production screenplay (10 scenes, ≈5:20): `films/savannah/`.
* Creatures: species body plans on bone rigs with IK legs and a foot-locked gait planner (0.0 mm measured stance slide),
  metaball-sculpted bodies, faces (Rhubarb-synced mouths, brows, 9 expressions):
  [`savannah-walk-tests/`](examples/showcase/savannah-walk-tests/), [`savannah-face-tests/`](examples/showcase/savannah-face-tests/).
* Set: swaying grass, acacias, termite mounds, watering hole, mountains, dawn/midday/sunset/night skies:
  [`savannah-set-tests/`](examples/showcase/savannah-set-tests/).
* Sound: a Composer with per-scene cues and six leitmotifs on real SoundFont samples
  ([`savannah-score/`](examples/showcase/savannah-score/)); six distinct cast voices, procedural ambience, species
  footsteps and SFX ([`savannah-sound/`](examples/showcase/savannah-sound/), -14.3 LUFS, dialogue +12.6 dB).
* **Scene production** (new): `films/savannah/07_scenes.json` (SC 1, SC 2) → `python scripts/savannah_scene.py sc02
  --quality preview|draft|final` → a mixed scene MP4 with lines timed from the real voices, cuts on the lines, cameras
  framed on the measured heads, and the scene's own music cue re-timed to it. First result:
  [`savannah-scenes/sc02_preview.mp4`](examples/showcase/savannah-scenes/) (Cycles CPU preview, 480×270, 12 fps).
* **Acting** (new): automatic eyelines plus spec-driven gestures (trunk drink and spray with a keyed water jet, head
  duck, ear droop, head shake, nod, look-at) layered over the gaits; cameras swing around animals standing in the
  sight line (DECISIONS #49, #50). Preview stills: `python scripts/savannah_scene.py sc02 --at 10.3,11.3`.

Scorecard (strict, 11-17 03:36): story 8 (script), character design 7, motion 7, visuals 6, voices 7, music 7, mix 7.
Next: the specs for SC 3–10, the film edit, SC 2 polish, then the full GPU render on the laptop (see [docs/REVIEW_QUEUE.md](docs/REVIEW_QUEUE.md) P1-SAVANNAH).

### Needs you

* **Design stage: two packets left in [`design/packets/`](design/packets/README.md)** (Tembo, Neema and Bibi Kobe
  are approved, v3): **Kiki** (which body on all fours: v5 per your note, or v4's) and **Zuri v3** (approve or
  notes). The laptop should re-render the stress takes and packets first (`rig_stress_test.py --all`, then
  `design_packet.py --all`) so the clips show the fixed feet (DECISIONS #69, #70). An
  `ANTHROPIC_API_KEY` would let the vision critic run live instead of relying on a reviewer's recorded critique.

* *(Paused with film production until the packets and the animatic are approved.)* **Laptop session: render SC 2 at final quality** (now with the gag, eyelines and the new eyes) on the RTX 5060 (`python scripts/savannah_scene.py sc02 --quality
  final`, OptiX, ~530 frames at 1280×720) and commit a ≤ 25 MB cut to `examples/showcase/savannah-scenes/`.
* **Listen to the score** (`examples/showcase/savannah-score/score.m4a`); the cloud reviewer has no speakers.
* **Install FluidSynth on the laptop** and put it on PATH (or place `fluidsynth.exe` in
  `%USERPROFILE%\.cache\animatica\fluidsynth\bin\`), then rerun `scripts/setup_assets.sh` from Git Bash to fetch the
  SoundFont. Without it the Composer falls back to its numpy synth.
* An `ANTHROPIC_API_KEY` would let the live Anthropic provider path run once (still never run).

## 1. Headline

**`animatica film "<prompt>"` works end to end with no human input and no API key.**

* A Director plans a 4-shot, ~21-second short. The story arc changes with the prompt: an entrance or
  a lonely opening; a settle, celebrate or exit ending.
* Art builds a procedural set with a hazy sunset look (grime, aerial perspective, glowing sun), a
  rigged robot or critter, and a prop. Everything runs in Blender (bpy 5.3) in a separate GPL process.
* Voice speaks the lines with Kokoro TTS, Rhubarb lip-syncs them onto a readable shape-key mouth, and
  a procedural music bed is high-passed and ducked under the dialogue.
* The Animator writes ~3 000 principle-driven keys: anticipation, overshoot, spring follow-through,
  jointed arms that reach, blinks and lip sync.
* Camera & Lighting stages a cut per shot, including a true head-and-shoulders dialogue close-up.
* The Critic measures every shot (frustum, framing, floor contact, face size while speaking, the
  addressed prop in frame, mouth activity, exposure) and applies fixes in a loop. On the showcase film
  it reframed the dialogue close-up to bring the flower fully into frame (before/after in the log).
* The Editor renders with Cycles and writes an **MP4 with sound, captions and a title**, plus an
  editable `scene.blend` and an `edit.mlt` timeline for Shotcut/Kdenlive.

Hand edits survive `animatica continue` / `revise`. An **MCP server** exposes the batched tools. A
**Godot games track** turns a prompt into a platformer that a bot playtests headlessly. **160 tests**
(`pytest -q`, 1 skipped without Godot) pass locally. GitHub CI runs ruff, unit, bpy adapter and offline pipeline tests; status
for the final SHA is at the bottom of this report. An hourly reviewer session scored the project, and
its queue is in [docs/REVIEW_QUEUE.md](docs/REVIEW_QUEUE.md).

## 2. Try it (fresh clone)

```bash
git clone https://github.com/Goon254/3-D-plus-AI && cd 3-D-plus-AI
python3.13 -m venv .venv && . .venv/bin/activate        # bpy 5.3 needs exactly Python 3.13
pip install -e ".[dev,tts,mcp]" bpy==5.3.0
scripts/setup_assets.sh --godot      # Kokoro model, CC0/CC-BY Piper fallback voices, Rhubarb, Godot (GitHub releases)
animatica dev doctor                 # needs ffmpeg on PATH

animatica demo --quality preview     # ~2–3 min: fast Workbench render of the north-star short
animatica demo                       # Cycles 960×540, ≈10–13 s/frame on 2 CPU cores (~90 min)
animatica film "A lonely robot sits in a junkyard at dusk until a flower blooms. It says: 'You came back.' Then it heads home." --quality preview
animatica revise output/hello-little-one "make the robot blue and slow down shot 2" --quality preview
animatica game "a 2D platformer where a robot collects flowers" && godot --path output/game-*/godot
animatica-mcp                        # MCP server (stdio) for Claude Desktop / Claude Code
pytest -q                            # 160 tests (Blender/Godot/MCP tests skip if those are missing)
```

Each film writes `output/<project>/final.mp4` (video + audio + captions), `scene.blend`, `edit.mlt`,
`scene.usda`, `final.srt`, `audio/` (with `audio_manifest.json`), and `log/index.html`. That last file
is the production log viewer: every agent decision, every batch, every critique with its preview.

## 3. Showcase

<!-- SHOWCASE_LIST -->
* **North-star short** — [`examples/showcase/hello-little-one/final.mp4`](examples/showcase/hello-little-one/final.mp4)
  (21 s, 640×360 Cycles `--quality draft`, voice + lip sync + music + captions, 1.0 MB), re-rendered 2026-11-16 on OptiX
  (88 s of rendering) with every fix to date. [Production log](examples/showcase/hello-little-one/log/index.html) shows the
  critic loop: iteration 1 flags the flower at 56 % in the close-up, iteration 2 passes after the reframe.
  [Editable `.blend`](examples/showcase/hello-little-one/scene.blend). Reproduce: `animatica demo --quality draft`.
* **HD version** — [`examples/showcase/hello-little-one-hd/final.mp4`](examples/showcase/hello-little-one-hd/final.mp4)
  (21 s, **960×540 Cycles `--quality final`**, title overlay, voice + lip sync + music + captions, 1.5 MB), re-rendered
  2026-11-16 from `a26e85d` on an **RTX 5060 with OptiX in 4 min end to end** (504 frames in 199 s, 0.40 s/frame; the
  previous CPU render took ~2 h). Includes everything to date: speaker cheats toward the lens (22° off-axis), whole flower
  in the close-up (critic iteration 1 flags it at 56 % with the new 80 % rule, iteration 2 passes), hazy ridge band on
  the horizon, junk spread around the heap crest, rolling wheels, ground grit and pebbles, Rhubarb lip sync, and the
  acting beats (cautious discovery with a lean-in and head tilt; a glance down at the flower after the line).
  [Production log](examples/showcase/hello-little-one-hd/log/index.html) ·
  [contact sheet](examples/showcase/hello-little-one-hd/contact_sheet.jpg).
* **Fox film (HD)** — [`examples/showcase/fox-lantern/final.mp4`](examples/showcase/fox-lantern/final.mp4)
  (22 s, 960×540 Cycles `--quality final`, OptiX 214 s, from `3a5ac08`, with the critter bone rig), prompt "A tiny fox finds a glowing lantern in a snowy forest at
  night. It whispers: 'Are you lost too?' Then it hops away." The species pass (snout, pointed ears, white-tipped tail,
  legs), an eye-level head-and-shoulders dialogue close-up with a readable Rhubarb-synced mouth, the acting beats,
  rock-not-puddle snow stones, and an exit that leaves frame. Critic passes every shot on iteration 1.
  [Production log](examples/showcase/fox-lantern/log/index.html) · [contact sheet](examples/showcase/fox-lantern/contact_sheet.jpg).
* **Games track** — [`examples/showcase/robot-flower-platformer/`](examples/showcase/robot-flower-platformer/)
  (generated Godot project; bot playtest 6/6).

## 4. Milestones

| # | Milestone | Status | Proof |
|---|---|---|---|
| 0 | Foundation & license audit | **done** | `pyproject.toml`, ruff, pytest, CI workflow, `docs/SETUP.md`, `docs/LICENSE_AUDIT.md`, `THIRD_PARTY.md` |
| 1 | Protocol + Blender adapter | **done** | `animatica dev run-batch examples/batches/robot.json` → `.blend` + preview; `tests/test_protocol.py`, `tests/test_blender_adapter.py` (validation, rollback, 300-op batch, sandboxed scripts, keyframes, shape keys, armature, inspect). Live add-on written but untested inside the Blender UI |
| 2 | Orchestrator, LLM layer, agents | **done** | task graph + budgets + JSONL log; Anthropic (unit-tested with a fake transport) + scripted providers; 7 agents (`docs/AGENTS.md`); knowledge base + `lookup()` |
| 3 | 🎯 Prompt → MP4 with voice, lip sync, music | **done** | `animatica demo`; `tests/test_pipeline.py` checks video + audio + subtitle streams, 15–31 s, all agents logged |
| 4 | Quality | **partial** | critic checks + fix loop (before/after in the showcase log, floor fix on the cat film); animation principles, jointed arms; shot types and moves; style bible; multi-shot cuts; varied arcs. Three prompts give coherent 4-shot films. Still below the reviewer's 9/10 bar on visuals/animation (§5) |
| 5 | Artist in the loop | **done** | `continue` / `revise` / `log`; `tests/test_continue.py` hand-edits the `.blend` by script and the edits survive both; `edit.mlt` for editors |
| 6 | MCP server | **done** | `animatica-mcp` (mcp 2.x); `tests/test_mcp.py` (in-process + stdio) |
| 7 | Games track (Godot) | **done (thin slice)** | `animatica game …` → Godot 4.5.1 project, bot playtest 6/6 with 0 script errors, xvfb screenshot, `tests/test_games.py`. One genre; no export (templates ≈1 GB) |
| 8 | Reference study | **partial** | `animatica study <local files> --license …` (palette, cuts, motion, warmth, + vision notes if the LLM can see) → `film --style`. Refuses URLs. No image-to-3D hooks |
| 9 | Polish | **partial** | README + quickstart + Makefile, CONTRIBUTING (DCO), issue templates, `docs/BLENDER_FEATURE_MAP.md`, `docs/GAMES.md`. No GIF, no web UI |

## 5. Known issues & honest quality assessment

**Update 11-16 19:00** ([review](docs/reviews/2026-11-16T1900Z.md)): the lantern now really glows (its point light was
trapped inside the opaque glass; a warm ~1 m pool on the snow and warm light on the fox's face), the critter close-up
no longer clips a sliver of the lantern (new critic `prop_sliver`, the frame tightens from the bottom), snow has a few
large rocks instead of ash-like specks, and the fur has a sheen rim. Stills in the review. **The HD fox showcase (re-rendered at `1a4066c`
with the bone rig) was built before these fixes: re-render it on the GPU.** Scores ≈8.5 (visual 8, animation 8, audio 8); gate not met.

**Update 14:15** ([review](docs/reviews/2026-11-15T1415Z.md)): exits now leave the frame (camera holds on the set),
night reads as night in previews, the ground has grit/bump/pebbles, and scrap heaps are smooth with junk on the crest. The critter
no longer sits in the floor. 71 tests pass. Scores ≈8.1 (visual 7, animation 6). Next: re-render the showcase, then bone rig + acting.
`PHASE2.md` (showcase films, site, hosted MCP) was added at 14:00 and starts after the P1 quality items.

Reviewer scores at 12:36 ([review](docs/reviews/2026-11-15T1236Z.md)): functionality 8, visual 7, animation 6,
audio 8, code 9, architecture 9, docs 9, licenses 9 (≈8.1/10). The exit-verb fix is verified. Top open items: the exit
beat doesn't carry the hero out of frame, the HD showcase is stale (floating slab), and there is no bone rig or acting beat.

* **It's a lit toy, not cinema.** Characters are bevelled primitives. They're readable and charming
  in Cycles, but there are no real textures (only procedural grime) and no volumetrics. The critter
  reads a bit like a chick.
* **Rigging:** critters (fox/cat/dog) have a bone rig for the tail (skinned, bends with follow-through) and legs
  (tuck and reach in hops); body, head and the robot stay object-level pivots (DECISIONS #36). No walk cycle: the robot
  rolls on wheels that turn by distance, critters hop.
* **Story variety is template-driven offline.** Arcs vary with the prompt, but the scripted Director is
  a keyword parser. The Anthropic path (plans, performance, camera, vision critic) is implemented and
  unit-tested but **was never run against the live API** (no key here).
* **The Critic is geometric.** It finds technical problems and fixes them. It cannot judge appeal or
  acting.
* **Render cost:** Cycles CPU ≈10–13 s/frame at 960×540 on 2 cores (~90 min per 21 s). `preview`
  (Workbench, flat colours) takes 2 minutes.
* **Music:** the short films still use the procedural numpy bed (clean but generic). The savannah score uses the new Composer (FluidSynth + GeneralUser GS, leitmotifs per character); wiring it into `film` is queued.
* **Script mode is a guard-rail, not a sandbox.** The **live add-on is untested** in the Blender UI.
* **Games:** one template genre with polygon art; no exported builds.

## 6. Decisions

All are in [docs/DECISIONS.md](docs/DECISIONS.md). These are worth a look:

1. **Licensing split:** core Apache-2.0. `adapters/blender` and `adapters/tts_worker` are
   GPL-3.0-or-later and run as separate processes. `adapters/godot` is MIT.
2. **TTS = Kokoro** (Apache weights) in a GPL worker process, following your research update. Piper
   stays as an opt-in fallback with CC0/CC-BY voices only.
3. **The critic uses low-sample Cycles for its 4 per-shot exposure previews.** Workbench can't judge
   lighting.
4. **Object-level rig instead of bones** for tonight.
5. **Godot 4.5.1** (not 4.7) and no exports yet.
6. **`ruff format` not applied yet.** The reviewer asked for it as one mechanical commit when no build
   session is active.

## 7. Next steps (priority order)

1. **Run with a real `ANTHROPIC_API_KEY`** and put the vision critic in the loop. Let Claude write
   varied story beats and review previews against the shot goals.
2. **Bone rig + walk/hop cycles** (Rigify-lite), eyelids/brows for acting. Optionally import CC0
   characters (Quaternius/Kenney) via `import_asset`.
3. **Richer look:** CC0 textures (offline Poly Haven/ambientCG cache), Geometry Nodes scatter recipes,
   volumetric haze where a GPU exists, and FluidSynth music.
4. **Speed:** render shots in parallel processes. Add a WebGPU/three.js previewer of the USD-shaped
   scene model so the critic loop no longer needs Blender (step 1 of the Blender feature-map plan).
5. **Studio UI** around `log/index.html` (prompt in, live batch stream, approve/redo per shot,
   `revise` notes), and `melt`-rendered edits. For games: export templates and a second genre.

## CI status

<!-- CI_STATUS -->
Checked 12:01 UTC via the Actions API: run #39 for `54b67d3` (Director exit verbs, the last code commit of the
night) → **success** on both jobs (`lint-and-unit`: ruff check + ruff format --check + unit tests;
`blender-and-offline-pipeline`: bpy 5.3 adapter tests + offline film smoke test). Locally on that SHA:
`pytest -q` → **65 passed** (Blender, Godot, MCP and Kokoro all present).
