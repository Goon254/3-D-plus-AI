# Design packets (DESIGN_STAGE §6): for owner approval

One folder per character: `sheet.jpg`, a 10-second `motion.mp4` with the character's line, `scores.json`, the
design loop's two runner-ups, and a one-page `README.md`. Built by `scripts/design_packet.py --all` from the
current design (`design/<char>/v*`), its rig stress report (`design/<char>/rig_stress.json`) and the loop log
(`design/<char>/loop/`); the notes are in `notes.json`. This index is written from the packets' `scores.json` and
`design/<char>/approved.json`, and "Waiting on you" from the proposals in `design/proposals/` and the open
questions in `notes.json` (`design_packet.py --index` rebuilds it alone), so it can't fall behind them.

## Waiting on you

* **Bibi Kobe v4** ([proposal](../proposals/bibi_kobe-v4/)): offered as the next version; rubric 9.7; blind read tortoise 90 / tortoise 92 (silhouette / thumbnail); rig stress 9 / 9 passed.
* **Kiki v8** ([proposal](../proposals/kiki-v8/)): shown for your yes / no; rubric 9.77; blind read meerkat 80 / meerkat 55 (silhouette / thumbnail); rig stress 11 / 11 passed.
* **Zuri v5** ([proposal](../proposals/zuri-v5/)): offered as the next version; rubric 9.72; blind read zebra 60 / zebra 95 (silhouette / thumbnail); rig stress 9 / 9 passed.
* **Neema's and Zuri's resting brows** (all five fail the soft `face:brow_outline`: the far brow is drawn against the backdrop in 3/4): lowering the resting brows fixes it at face size (Neema `brow_bias` 0.3 → 0.0: face view 0.53 → 0.10; Zuri −0.2: 0.38 → 0.25) but undoes your 11-17 "friendlier brows" lift. Lower them, or keep them? ([board](../../docs/reviews/assets/2026-11-23T0036Z-eye-brow-sweep.jpg), DECISIONS #116)
* **Should the full-body 3/4 view count in the brow check?** There the head is ~45 px tall and a brow ~5 px long, so 25 % is 1–2 px; no design change moved it (DECISIONS #116).

| Character | Design | Owner | Rubric | Ready | Blind read (silhouette / thumbnail) | Rig stress | Asks of you |
|---|---|---|---|---|---|---|---|
| [Bibi Kobe](bibi_kobe/README.md) | v3 | **approved** v3 | 9.72 | yes | tortoise 85 (clear) / tortoise 93 (clear) | 11 / 11 | **your call**: [v4](../proposals/bibi_kobe-v4/) or keep v3? |
| [Kiki](kiki/README.md) | v6 | **approved** v6 | 10.0 | no: species read pending | meerkat 70 (weak) / meerkat 60 (weak) | 13 / 13 | **your yes / no**: [v8](../proposals/kiki-v8/) shows a fix on v6 (not a replacement) |
| [Neema](neema/README.md) | v3 | **approved** v3 | 9.9 | yes | giraffe 92 (clear) / giraffe 95 (clear) | 11 / 11 | locked v3; the resting-brow question under Waiting on you |
| [Tembo](tembo/README.md) | v3 | **approved** v3 | 9.89 | yes | elephant 85 (clear) / elephant 90 (clear) | 11 / 11 | nothing: locked |
| [Zuri](zuri/README.md) | v4 | **approved** v4 | 9.86 | no: species read pending | zebra 50 (weak) / zebra 95 (clear) | 11 / 11 | **your call**: [v5](../proposals/zuri-v5/) or keep v4? |

Read the scores this way: "ready" needs 9.0+, no hard failure, the species read and appeal 8+. The species read and
appeal come from a recorded critique (no live vision key on this machine), whose reader knew the brief. The blind
read is a separate reader who saw only the silhouette, then the 96 px thumbnail, and named the animal with a
first-instinct confidence: "clear" is 75+, "weak" is named but unsure (DECISIONS #111); it does not change the
score. The runner-ups' 10.0s were scored *without* a species read, so they don't compete with the current designs'
numbers. An approved design is locked to its species parameters (`design/<char>/approved.json`); production may
not change it.
