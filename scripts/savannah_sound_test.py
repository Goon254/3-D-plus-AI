"""A 40-second sound test of the savannah film's audio: music + ambience + footsteps + narrator + cast voices.

    python scripts/savannah_sound_test.py --out output/savannah-sound

Layers: the sc01 dawn cue (real SoundFont samples via the Composer), ducked ~18 dB under every voice line; the
dawn ambience bed by the water; Tembo's footsteps at the gait planner's touchdowns as he walks across; the
narrator's opening and lines from the cast (06_voices.json). Normalised to -14 LUFS; the picture is a still of
the set at dawn.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animatica.audio import ambience, composer, tts  # noqa: E402
from animatica.creatures.build import build_creature  # noqa: E402
from animatica.creatures.gait import GAITS, Waypoint, plan_locomotion  # noqa: E402
from animatica.creatures.species import SPECIES  # noqa: E402

SR = composer.SR
SCRIPT = [  # (start seconds, speaker, line) from 04_screenplay.md
    (
        2.0,
        "narrator",
        "Far away, where the grass grows golden and the sky goes on forever, the rains were late.",
        None,
    ),
    (10.5, "narrator", "And the old watering hole was getting smaller... and smaller... and smaller.", "sad"),
    (19.0, "tembo", "Morning, Zuri! Morning, Kiki! Water!", "happy"),
    (23.5, "kiki", "Thank you, Tembo. Very refreshing.", "dignified"),
    (27.0, "zuri", "Your trunk's a hose with *hiccups*!", "laughing"),
    (
        31.0,
        "bibi_kobe",
        "When I was young... there was a spring past the two baobabs that bow to each other.",
        "wise",
    ),
]


def to_stereo48(x: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    """A line placed outdoors (EQ, light compression, reflections, room tone), stereo at 48 kHz."""
    from animatica.production.sound import dialogue

    return dialogue(x, sr, seed=seed)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "output" / "savannah-sound"))
    ap.add_argument(
        "--still", default=str(ROOT / "examples" / "showcase" / "savannah-set-tests" / "set_dawn.jpg")
    )
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    seconds = 40.0
    n = int(seconds * SR)
    cast = json.loads((ROOT / "films" / "savannah" / "06_voices.json").read_text(encoding="utf-8"))["cast"]
    # voices
    voices = np.zeros((n, 2), np.float32)
    duck = np.zeros(n, np.float32)
    for i, (t, who, line, mood) in enumerate(SCRIPT):
        c = cast[who]
        info = tts.synthesize(
            line,
            out / f"line_{i}.wav",
            tts.VoiceSpec(engine="kokoro", voice=c["voice"], pitch=c["pitch"], rate=c["rate"], mood=mood),
        )
        x, sr = tts.read_wav(info["path"])
        v = to_stereo48(x, sr, seed=i) * 0.9
        s = int((t - 0.08) * SR)  # the placed line carries 80 ms of room tone before the first word
        e = min(n, s + len(v))
        voices[s:e] += v[: e - s]
        duck[max(0, s - int(0.25 * SR)) : min(n, e + int(0.4 * SR))] = 1.0
    # smooth the duck envelope (attack/release ~0.3 s)
    k = int(0.3 * SR)
    duck = np.convolve(duck, np.ones(k) / k, mode="same")
    # music: the dawn cue, then the comedy cue from 18 s (scene 2)
    cues = {c.id: c for c in composer.load_cue_sheet(ROOT / "films" / "savannah" / "05_cue_sheet.json")}
    music = np.zeros((n, 2), np.float32)
    start = 0.0
    for cid, length in (("sc01", 18.0), ("sc02", 22.0)):
        rep = composer.render_cue(composer.arrange(cues[cid]), out / "cues")
        m = composer._read(out / "cues" / rep["wav"])
        s, e = int(start * SR), min(n, int((start + length + 1.5) * SR))
        seg = m[: e - s]
        fade = min(len(seg), int(0.6 * SR))
        seg = seg.copy()
        seg[:fade] *= np.linspace(0, 1, fade)[:, None]
        music[s : s + len(seg)] += seg
        start += length
    music *= (1.0 - 0.88 * duck)[:, None]  # about -18 dB under voices
    # ambience: dawn by the water, then morning
    amb = ambience.bed("dawn", seconds, water=True, seed=11)
    # Tembo hurries in at 17 s: footsteps from his real gait plan
    ops, meta = build_creature("tembo", SPECIES["elephant"])
    g = GAITS["elephant"]["walk"]
    v = g.nominal_speed(meta.leg)
    plan = plan_locomotion(
        [Waypoint(0, -3, 0), Waypoint(5.5, -3 + v * 5.5 * 0.8, 0)],
        g,
        meta.feet,
        meta.leg,
        meta.body_z,
        meta.foot_z,
        24,
        joints=meta.joints,
    )
    steps = ambience.footsteps_track(
        "elephant", [(t + 16.5, p) for t, p in ambience.touchdowns_from_plan(plan, 24)], seconds
    )
    dip = (1.0 - 0.5 * duck)[:, None]  # ambience and footsteps dip 6 dB under a line too
    bg = music * 0.55 + amb * dip + steps * 0.8 * dip
    mix = bg + voices
    # dialogue clarity: voice level over everything else, inside the voice windows (target >= +10 dB)
    win = duck > 0.99

    def db(x: np.ndarray) -> float:
        return 20 * float(np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12))

    clarity = db(voices[win]) - db(bg[win])
    wav = out / "sound_test_raw.wav"
    import soundfile as sf

    sf.write(str(wav), mix, SR)
    mp4 = out / "sound_test.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "2",
            "-i",
            a.still,
            "-i",
            str(wav),
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:v",
            "libx264",
            "-tune",
            "stillimage",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-t",
            str(seconds),
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
    )
    print(
        json.dumps(
            {
                "mp4": str(mp4),
                "footsteps": len(ambience.touchdowns_from_plan(plan, 24)),
                "lines": len(SCRIPT),
                "dialogue_clarity_db": round(clarity, 1),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
