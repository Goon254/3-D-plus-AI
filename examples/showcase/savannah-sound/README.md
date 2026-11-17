# Savannah film: voices A/B and sound test (before picture)

## [`voices.m4a`](voices.m4a): old vs new voices, side by side (2:20)

Each character says their two sample lines in the **first casting** ("…, before.": one stock voice, big pitch
shift, flat delivery, dry), then in the **new casting** ("…, after."). Every take is matched to the same
loudness so neither version wins by being louder.

What changed in "after":

* **Smaller pitch shifts, using voice blends.** Each character mixes two stock Kokoro voices' style vectors,
  chosen from a pitch and brightness survey of all 28 English voices. Every shift is within ±2 semitones.
* **Delivery.**
  * **Pace:** set by mood, plus a small variation per line.
  * **Pauses:** longer after a question or an ellipsis, shorter after an exclamation.
  * **Breaths:** a soft breath between longer sentences.
  * **Emphasis:** key words (`*marked*` in the script, or CAPS) are stressed in the phonemes, held a little
    longer and lifted 2.5 dB.
* **Placed outdoors.**
  * Gentle EQ and light 2:1 compression.
  * A ground reflection and a few distant soft reflections, with no room reverb.
  * Faint outdoor room tone.
  * Clean (windowed-sinc) resampling: the old linear resampling put a metallic fizz on the top end.

| at | character | before → after voice | pitch shift before → after |
|---|---|---|---|
| 0:02 | Narrator | `bm_fable` → `bm_fable:0.8+bm_lewis:0.2` | −0.7 → 0 st |
| 0:27 | Tembo | `am_puck` → `am_eric:0.5+af_sky:0.5` | **+4.8** → +1.0 st |
| 0:41 | Zuri | `af_bella` → `af_bella:0.6+af_jessica:0.4` | +1.3 → 0 st |
| 0:56 | Kiki | `af_sky` → `bf_alice:0.7+af_jessica:0.3` | **+5.6** → +2.0 st |
| 1:11 | Neema | `af_nicole` → `af_nicole:0.7+af_sky:0.3` | +0.5 → 0 st |
| 1:23 | Bibi Kobe | `bf_emma` → `bf_emma:0.55+af_alloy:0.45` | **−4.7** → −2.0 st |
| 1:44 | engine test | 3 lines: Kokoro (new casting), then Chatterbox | — |

The engine test (1:44 to the end) puts the same three lines through Kokoro and Chatterbox:

* the narrator's opening (1:46);
* Kiki's "EVERYBODY PANIC!" (2:01);
* Bibi Kobe's "When you walk slowly…" (2:12).

[Chatterbox](https://github.com/resemble-ai/chatterbox) is MIT-licensed, with MIT weights. It's the only expressive
engine marked TRIAL in `docs/research/03` with no non-commercial licence attached. It is steered by that
character's own Kokoro take of a *different* line: a synthetic stock voice, not a recording of a person.

**Intelligibility** (faster-whisper round trip, word error rate, in [`voice_ab.json`](voice_ab.json)):

| version | word error rate |
|---|---|
| before | 0.08 |
| after | 0.10 |
| engine test: Kokoro | 0.00 |
| engine test: Chatterbox | 0.04 |

The remaining errors are spelling or homophone misses that happen in both versions: "Zuri" heard as "Yuri",
"There!" as "their", "baobabs" as "bay of abs".

[`voices.json`](voices.json): median pitch and brightness per voice in the new casting. All six are pairwise
distinct:

| voice | median pitch |
|---|---|
| Narrator | 114 Hz |
| Bibi Kobe | 153 Hz |
| Neema | 155 Hz |
| Tembo | 175 Hz |
| Zuri | 200 Hz |
| Kiki | 253 Hz |

Bibi Kobe and Neema are kept apart by brightness, not pitch: 857 Hz against 477 Hz spectral centroid.

## [`sound_test.mp4`](sound_test.mp4): every audio layer together (40 s, over a still of the dawn set)

| layer | what |
|---|---|
| music | the Composer's sc01 (dawn) and sc02 (puddle comedy) cues on real SoundFont instruments, ducked ~18 dB under each line |
| ambience | the dawn bed by the water: wind in dry grass, birds, water lapping (procedural) |
| footsteps | Tembo hurrying in: 17 padded elephant thumps at his gait planner's real touchdown times |
| voices | the narrator, Tembo, Kiki, Zuri and Bibi Kobe in the new casting, placed outdoors |

Measured:

* integrated loudness: **−14.0 LUFS**;
* dialogue level above everything else inside the lines: **+14.2 dB** (target ≥ +10; it was +12.6 with the
  old voices).

Scripts:

* `python scripts/savannah_voice_ab.py` builds this reel;
* `python scripts/savannah_voices.py` runs the distinctness check;
* `python scripts/savannah_sound_test.py` builds the sound test;
* `scripts/tts_trial_worker.py` runs Chatterbox and Whisper in their own venv.
