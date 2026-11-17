# Savannah film — produced scenes

The first scenes made by the scene production pipeline (`films/savannah/07_scenes.json` →
`python scripts/savannah_scene.py <scene>`; DECISIONS #43).

* [`sc02_preview.mp4`](sc02_preview.mp4): **SC 2 (cloud CPU preview) "The puddle"** (22.5 s), Cycles on 2 CPU cores at preview quality
  (480×270, 8 samples, 12 fps held to 24; 19 min), re-rendered 11-17 04:27 UTC with the acting layers (DECISIONS #49,
  #50) and the laptop's eyes in sockets. Tembo hurries round the back of the puddle; in profile his trunk dips, sucks
  and wobbles, lifts and "hiccups" a jet of water that splashes Kiki (cut on the hit); she answers with dignity; Zuri
  laughs and teases Neema, who walks in ducking her head and ducks lower; Tembo's CU ends sad. Listeners turn their
  heads to whoever speaks. Cameras swing around animals in the sight line (MS +15°, CU +30°). Voices in the cloud are
  the Kokoro blends (Chatterbox runs on the laptop GPU). -14.7 LUFS (scene loudnorm), dialogue +13.5 dB.
  [Contact sheet](sc02_contact_sheet.jpg) (1 fps) · [report](sc02_report.json) (line timing, shots, swings, cue).
* [`sc01_stills.jpg`](sc01_stills.jpg): **SC 1** framing check (`--stills`): the dawn establishing wide and the shrinking
  puddle.

Still to polish (queue): the profile medium crops Tembo's head when the trunk rises, the trunk tip stops just above
the water, the ear droop is subtle at this resolution. Final quality (1280×720, 24 fps, OptiX) is for the laptop: `--quality final`.

**SC 2 draft, 2026-11-17** ([`sc02_draft.mp4`](sc02_draft.mp4), [contact sheet](sc02_draft_contact_sheet.jpg), 1 fps):
960×540, 16 samples, OptiX on the RTX 5060. The dialogue is regenerated with **Chatterbox** steered by the approved
Kokoro blends (all four lines pass the Whisper check; DECISIONS #45). In picture: Tembo's trunk dips to the puddle,
drinks, curls and sprays Kiki; Neema walks in ducking and goes lower after "lamp-post"; listeners turn to whoever
speaks; Tembo ends on a sad close-up with drooping ears. Eyes in sockets with lids, and coats pinned to the skin.
