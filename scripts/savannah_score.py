"""Render the savannah film's score from its cue sheet and publish a listening copy.

    python scripts/savannah_score.py [--out output/savannah-score] [--publish examples/showcase/savannah-score]

Writes per-cue ``.mid`` + ``.wav``, the assembled ``score.wav`` and ``score.json`` (key, mode, tempo, instruments,
leitmotifs, level per cue). ``--publish`` copies the MIDI files, the report, a spectrogram and a compressed
``score.m4a`` (≈5 MB) into the showcase folder.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from animatica.audio import composer
from animatica.audio.mux import ffmpeg_bin

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "films" / "savannah" / "05_cue_sheet.json"
GM_NAMES = {v: k for k, v in composer.GM.items()}


def lufs(path: Path) -> float | None:
    p = subprocess.run(
        [ffmpeg_bin(), "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    for line in reversed(p.stderr.splitlines()):
        if line.strip().startswith("I:"):
            return float(line.split()[1])
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default=str(SHEET))
    ap.add_argument("--out", default=str(ROOT / "output" / "savannah-score"))
    ap.add_argument("--publish", default=None)
    ap.add_argument("--engine", choices=["fluidsynth", "soundfont", "numpy"], default=None)
    a = ap.parse_args()
    out = Path(a.out)
    rep = composer.score_film(a.sheet, out, engine=a.engine)
    rep["score_lufs"] = lufs(out / "score.wav")
    (out / "score.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(f"renderer: {rep['renderer']}   score: {out / 'score.wav'}   {rep['score_lufs']} LUFS")
    for c in rep["cues"]:
        inst = ", ".join(GM_NAMES.get(p, str(p)) for p in c["programs"])
        print(
            f"{c['id']}  {c['key']:>2} {'/'.join(c['modes']):<24} {c['bpm']:>6} bpm  {c['rms_db']:>6} dB  [{inst}]  motifs: {' '.join(c['motifs'])}"
        )
    if a.publish:
        pub = Path(a.publish)
        pub.mkdir(parents=True, exist_ok=True)
        for c in rep["cues"]:
            shutil.copy(out / c["midi"], pub / c["midi"])
        ff = ffmpeg_bin()
        subprocess.run(
            [
                ff,
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(out / "score.wav"),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(pub / "score.m4a"),
            ],
            check=True,
        )
        subprocess.run(
            [
                ff,
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(out / "score.wav"),
                "-lavfi",
                "showspectrumpic=s=1400x360:legend=1:fscale=log",
                str(pub / "spectrogram.png"),
            ],
            check=True,
        )
        pubrep = dict(
            rep,
            cue_sheet=str(Path(a.sheet).relative_to(ROOT)) if Path(a.sheet).is_relative_to(ROOT) else a.sheet,
        )
        (pub / "score.json").write_text(json.dumps(pubrep, indent=2))
        print(f"published to {pub}")


if __name__ == "__main__":
    main()
