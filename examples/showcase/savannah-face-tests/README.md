# Savannah cast — face tests (dialogue)

[`face_reel.mp4`](face_reel.mp4): each character says a line from the screenplay in a 3/4 close-up, with sound.

* **Voices**: stock Kokoro voices (no cloning), pitch and rate tuned per character: Tembo `am_puck`, Zuri `af_bella`,
  Neema `af_nicole`, Kiki `af_sky`, Bibi Kobe `bf_emma` (slower, lower). These are provisional until the audio pass.
* **Lip sync**: Rhubarb visemes drive the mouth's `open`/`wide`/`round` shape keys. The mouth is seated on the real
  surface by ray cast (`snap_to_surface`): on the muzzle (zebra, giraffe, meerkat), under the trunk with its corners
  showing (elephant), or across the beak (tortoise).
* **Acting**: an expression track per line (worried -> determined -> happy, proud -> sad, scared -> surprised ->
  happy, ...) eases the brows (lift and tilt: inner end up for sad/worried, down for determined) and the mouth's
  `smile`/`frown`. Idle layers keep breathing, blinking, and moving the ears, tail and trunk.

Made by `python scripts/creature_face_test.py <species>` (Cycles on OptiX, ~25 s per clip).

## Eyes in sockets, coats pinned to the skin (2026-11-17)

[`eye_coat_sheet.jpg`](eye_coat_sheet.jpg): each row is one character: standing, then mid-stride (the expression
track has moved into a heavy-lidded "sad"), then side-on mid-walk. The eyeballs are sunk ~65 % into the sculpted skin
with lids wrapping them, brows lie on the skin, and the meerkat is the slim v3 with painted eye patches (DECISIONS
#46–#48). [`eye_coat_report.json`](eye_coat_report.json) holds the Critic's measurements on the deformed meshes over
the walk: eye embed 64.5–65 % with no drift, brow/lid gaps, and coat-texture drift (0.0 mm on all five; it was 142 mm
on the elephant's skin before the rest-position fix). `python scripts/creature_eye_test.py`.
