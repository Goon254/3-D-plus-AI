# design/ — the design stage (DESIGN_STAGE.md)

Per character, `<character>/brief.json` is the measurable design brief (§2): appeal ranges for the proportion
ratios in `animatica.design.measure`, required silhouette/marking features, palette and pattern-contrast
minimums, intended dark accents, silhouette thresholds, and the names a viewer must say unprompted (plus known
confusions). `animatica.design.brief` validates it; `tests/test_design.py` checks all five.

| character | species | brief |
|---|---|---|
| Tembo | elephant calf | [tembo/brief.json](tembo/brief.json) |
| Zuri | zebra | [zuri/brief.json](zuri/brief.json) |
| Kiki | meerkat | [kiki/brief.json](kiki/brief.json) |
| Neema | giraffe | [neema/brief.json](neema/brief.json) |
| Bibi Kobe | leopard tortoise | [bibi_kobe/brief.json](bibi_kobe/brief.json) |

## Tools

```bash
python scripts/design_sheet.py --all                 # sheet + score for each current design -> output/design/
python scripts/design_sheet.py kiki --morph '{"head": 1.1, "lift_dark": 0.7}'
python scripts/design_loop.py kiki                    # best-of-6, up to 5 rounds -> output/design-loop/kiki/
```

A sheet has front, side (facing left), 3/4 and back views, the signature pose when the species has one (Kiki's
sentinel), a black silhouette, a 96 px thumbnail and three expressions, plus the rubric panel. Cycles at 16 spp:
about a minute per character on 2 CPU cores, seconds on the laptop GPU.

**Species read.** With `ANTHROPIC_API_KEY` set, a vision model names the animal from the silhouette alone and the
thumbnail alone. Without a key, a person or reviewer agent records `critique.json` next to the sheet
(`animatica.design.critic.record`). The record carries the SHA-256 of the sheet it judged, so it never applies
to a re-render. Until one of these has run, nothing is `ready`.

## baseline/ — the current designs, before the design loop (cloud review 2026-11-17 06:36 UTC)

384–512 px Cycles sheets of the designs on `main` at `248d21c`, each with the reviewer's recorded critique and
the rubric score. The sheet images were drawn before the critique was recorded, so their panels still say
"pending: species read". The real scores are in `*_score.json`:

| character | score | blocking |
|---|---|---|
| Tembo | 9.6 | appeal 7: fin-like disc ears edge-on, sleepy neutral lids, weak expressions |
| Zuri | 7.3 | silhouette alone reads as a horse; bullseye stripe rings on chest, face and rump; clown-nose muzzle |
| Kiki | 2.6 | reads weasel (thumbnail) and prairie dog/otter (sentinel silhouette); black "boot" legs; ears invisible |
| Neema | 9.8 | appeal 7: very thin legs, small head and eyes at thumbnail size |
| Bibi Kobe | 9.3 | appeal 6: ball-like shell with panel lines, hole-like spots, pale plastron disc |

Next: the base-mesh fixes the morphs can't make (listed in docs/REVIEW_QUEUE.md), then `design_loop.py`
for each character, then design packets in `design/packets/` for the owner.

## kiki/v2/ — Kiki's rebuilt base (cloud 2026-11-17 09:36, DECISIONS #53)

A 512 px sheet with a recorded critique and score: 5.2, not ready. The sentinel silhouette reads as a meerkat. On
all fours the thumbnail reads as a puppy or mongoose, there is no throat line (neck notch 0.114) and the snout is a
tube. See [review 09:36](../docs/reviews/2026-11-17T0936Z.md).

## kiki/v3/ — head forward, cone snout, smiling eyes (cloud 2026-11-17 12:36, DECISIONS #54)

512 px sheet with a recorded critique: **7.4**, not ready. The sentinel reads as a meerkat with the head level. On
all fours the head is carried forward with a nape and a throat line (neck notch 0.27), and the snout is one cone.
The thumbnail now reads as a **mongoose**: the right family, still a misread. Open: a bulky, lumpy barrel; stilt legs
with dark socks; eye patches too soft at 96 px. Re-score without re-rendering: `python scripts/design_sheet.py kiki
--tag v3 --out <dir> --rescore`. See [review 12:36](../docs/reviews/2026-11-17T1236Z.md).


## kiki/v4/ — crisp mask, slim barrel, dark paws only, a sentinel tail that stays on (laptop GPU 2026-11-17, DECISIONS #55)

512 px sheet (OptiX, ~10 s) with a recorded critique: **9.76**, not ready (appeal 7). The silhouette reads as a
meerkat in sentinel, and the 96 px thumbnail on all fours now reads as a **meerkat**. The rump end is weighted to the
hips, so the sentinel tail no longer floats below the body; that was a v2–v3 bug no review caught, and the
floating-part check now runs on the pose silhouette too. Open: the rump is round from the back, and the legs are
still a touch long.

## zuri/v2/ — chevron stripes, upright mane (laptop GPU 2026-11-17, DECISIONS #56)

Recorded critique: **7.4**, not ready. The thumbnail reads as a zebra and the bullseyes are gone (`pattern_chevron`,
`pattern_tilt`), but the silhouette alone still reads as a pony.

## bibi_kobe/v2/ — a domed carapace with raised scutes (laptop GPU 2026-11-17, DECISIONS #57)

Recorded critique: **9.81**, not ready (appeal 7). The silhouette reads as a tortoise and the thumbnail as a leopard
tortoise. The shell is its own mesh (`creatures/shell.py`) with per-vertex leopard marks; no ball, no holes, no pale plastron.
