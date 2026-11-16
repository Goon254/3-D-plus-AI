# Savannah film: sound test (before picture)

[`sound_test.mp4`](sound_test.mp4) (40 s, over a still of the dawn set): every audio layer of the film together.

| layer | what |
|---|---|
| music | the Composer's sc01 (dawn) and sc02 (puddle comedy) cues on real SoundFont instruments, ducked ~18 dB under each line |
| ambience | the dawn bed by the water: wind in dry grass, birds, water lapping (procedural) |
| footsteps | Tembo hurrying in: 17 padded elephant thumps at his gait planner's real touchdown times |
| voices | narrator + Tembo, Kiki, Zuri and Bibi Kobe in their cast voices (`films/savannah/06_voices.json`) |

Measured: **-14.3 LUFS** integrated; **dialogue +12.6 dB** above everything else inside the lines (target ≥ +10).

[`voices.m4a`](voices.m4a): the casting reel (two screenplay lines per character). [`voices.json`](voices.json): median pitch
(YIN) and brightness per voice. All six are pairwise distinct: narrator 114 Hz, Bibi Kobe 144, Neema 157,
Tembo 168, Zuri 218, Kiki 240.

`python scripts/savannah_sound_test.py` · `python scripts/savannah_voices.py`
