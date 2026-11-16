# *Tembo and the Singing Spring*: the score (before picture)

[`score.m4a`](score.m4a) is the full 5:22 score, one cue per scene, crossfaded at the scene cuts. There are no
voices or ambience yet. Every cue is also a [MIDI file](sc01.mid) that opens in MuseScore or any DAW, so an
artist can re-orchestrate it.

Made by `python scripts/savannah_score.py --publish examples/showcase/savannah-score` from the cue sheet
[`films/savannah/05_cue_sheet.json`](../../../films/savannah/05_cue_sheet.json) (per-scene intent and music notes
from the production screenplay). The Composer is `animatica.audio.composer`, and it renders with FluidSynth +
GeneralUser GS 2.0.3. Without FluidSynth, a numpy fallback synth plays the same notes.

## Leitmotifs (original melodies; each character owns a tune and a timbre)

| motif | instrument | shape |
|---|---|---|
| Main theme, "The Singing Spring" | kalimba | a rising call that answers itself |
| Tembo (elephant calf) | marimba doubled by tuba | heavy-footed and bouncy, with a stumble |
| Zuri (zebra) | piccolo | quick runs and a show-off leap |
| Kiki (meerkat) | pizzicato strings | a repeated-note alarm, then a nervous scurry |
| Neema (giraffe) | flute | a shy start, then a long rising line ("standing tall") |
| Bibi Kobe (tortoise) | hummed voices | slow and low; falls, then comes home |

Motifs are stored as scale degrees. The same tune changes mode with the story: Tembo's motif plays in a minor key
when he is lost at sunset (sc07), then in a major key when he decides "we're not lost if we're together".

## Cues

| cue | scene / intent | key, mode | tempo | moods |
|---|---|---|---|---|
| sc01 | title + dawn: wonder turning to worry | D major → minor | 62 | wonder, worry |
| sc02 | the puddle: comedy, then embarrassment | F major → minor | 120 | comedy, droop |
| sc03 | the singing spring: mystery → hope → resolve | A dorian → major → mixolydian | 74 | mystery, tender, adventure |
| sc04 | the journey: fun, then a quiet breath | G mixolydian → major | 113 | adventure, tender |
| sc05 | the fork: conflict | E minor → dorian | 92 | tension |
| sc06 | stripes in the grass: worry → Neema's triumph → relief | B minor → major | 73 | mystery, soaring, tender |
| sc07 | lost together: the low point, then the choice | D minor → major | 55 | sad, solo kalimba |
| sc08 | night: each gift clicks into place | E♭ lydian | 64 | night (all motifs layered) |
| sc09 | the singing spring: climax | C minor → major | 102 | tension, build, triumph, comedy |
| sc10 | home + end card: the main theme reprised, ending on solo kalimba | D major | 89 | triumph, solo |

Measured on this render (`score.json`): whole score −18.9 LUFS integrated, before the dialogue mix (the film mix
ducks it under voices and normalises the whole film to −14 LUFS). No two cues have the same key, tempo,
progression and instrument set. [`spectrogram.png`](spectrogram.png) shows the scene-to-scene changes.

The East/Southern African colour comes from the instruments and rhythms: kalimba (a lamellophone, like the mbira)
with a 3-against-2 cross-rhythm, interlocking marimba, shakers and congas. No existing song is quoted.
