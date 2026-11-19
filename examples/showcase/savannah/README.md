# Tembo and the Singing Spring: the deliverables

CHALLENGE-SAVANNAH "Output", written by `python scripts/savannah_film.py --deliver` (after the final scenes are
rendered and `--assemble` has made `output/savannah/film.mp4`; DECISIONS #92):

| File | What |
|---|---|
| `final.mp4` | the film at 1280×720, at most 25 MB (two-pass x264), the −14 LUFS master's audio copied, English captions as a soft subtitle track (`mov_text`, switch on in the player) |
| `poster.jpg` | a frame of the full-quality film with the title; by default the first daytime medium shot of the lead with a friend (`--poster-at <seconds>` picks another) |
| `captions.srt`, `captions.vtt` | one cue per line of the screenplay at the times the takes were placed (no speech recognition); the narrator in italics, an off-screen speaker named |
| `edit.mlt` | the edit for Shotcut / Kdenlive / `melt`: the ten scene renders, one entry per shot. Its paths point at `output/savannah/<scene>/<scene>.mp4` (not committed: 200 MB+), so open it in a checkout that has the renders |
| `production_log.md` | runtime, scenes, shots, render time, voices (engine, Whisper's word error, fallbacks), music cues, continuity findings, the master's loudness and true peak, caption reading speed |

The full-quality film (`output/savannah/film.mp4`) stays out of git. Once `final.mp4` is here,
`savannah-film/film_web.mp4` (the 540p copy) duplicates it and can go.
