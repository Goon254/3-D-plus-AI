# Design packets (DESIGN_STAGE §6): for owner approval

One folder per character: `sheet.jpg`, a 10-second `motion.mp4` with the character's line, `scores.json`, the
design loop's two runner-ups, and a one-page `README.md`. Built by `scripts/design_packet.py --all` from the
current design (`design/<char>/v*`), its rig stress report (`design/<char>/rig_stress.json`) and the loop log
(`design/<char>/loop/`); the notes are in `notes.json`. This index is written from the packets' `scores.json` and
`design/<char>/approved.json` (`design_packet.py --index` rebuilds it alone), so it can't fall behind them.

| Character | Design | Owner | Rubric | Ready | Rig stress | Asks of you |
|---|---|---|---|---|---|---|
| [Bibi Kobe](bibi_kobe/README.md) | v3 | **approved** v3 | 9.72 | yes | 11 / 11 | nothing: locked |
| [Kiki](kiki/README.md) | v6 | **approved** v6 | 10.0 | no | 13 / 13 | nothing: locked v6 (v4 body, v5 patches) per your 11-18 plan; notes still welcome |
| [Neema](neema/README.md) | v3 | **approved** v3 | 9.9 | yes | 11 / 11 | nothing: locked |
| [Tembo](tembo/README.md) | v3 | **approved** v3 | 9.89 | yes | 11 / 11 | nothing: locked |
| [Zuri](zuri/README.md) | v4 | **approved** v4 | 9.86 | no | 11 / 11 | nothing: locked v4 (brush mane) per your 11-18 plan; notes still welcome |

Read the scores this way: "ready" needs 9.0+, no hard failure, the species read and appeal 8+. The species read and
appeal come from a recorded critique (no live vision key on this machine). The runner-ups' 10.0s were scored
*without* a species read, so they don't compete with the current designs' numbers. An approved design is locked to
its species parameters (`design/<char>/approved.json`); production may not change it.
