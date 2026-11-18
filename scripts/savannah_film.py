"""The savannah film's final render (Stage 2, item 10) and its trailer (item 11).

    python scripts/savannah_film.py                 # render every scene not yet final, then assemble
    python scripts/savannah_film.py --only sc03     # (re-)render some scenes, then assemble
    python scripts/savannah_film.py --assemble      # assemble what is rendered
    python scripts/savannah_film.py --trailer       # cut the trailer from the final scenes

Each scene runs ``savannah_scene.py <scene> --quality final`` (Cycles on OptiX, 1280x720, 24 fps) in turn, one
heavy process at a time; a scene whose ``report.json`` says ``final`` and whose MP4 exists is skipped, so a run
that stops resumes at the next scene. The film joins the scenes with picture and sound handled separately (no
lip offset, ``savannah_animatic.join_av``), puts the title over the opening and the end card over the last
shot, and normalises the whole mix to -14 LUFS (two-pass loudnorm). Full quality goes to
``output/savannah/film.mp4``; a web copy at most 25 MB (two-pass bitrate) to
``examples/showcase/savannah-film/``. The trailer is the cut list ``TRAILER`` (scene, start, seconds) between
a title card and the end card "Made with Animatica · open source", also at most 25 MB.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from savannah_animatic import FONT, TITLE, esc, join_av  # noqa: E402

from animatica.production.scene import load_scenes  # noqa: E402

FILM = ROOT / "films" / "savannah"
OUT = ROOT / "output" / "savannah"
SHOW = ROOT / "examples" / "showcase"
END = "Made with Animatica · open source"
MAX_MB = 24.0  # web copies stay under the 25 MB repo limit with a margin
LUFS = -14.0

# the trailer: (scene, start s, seconds), in order. Built from the story beats: the world, the need, the
# friends, the trouble, the night, the push, the spring, the rainbow. Times are within each final scene.
TRAILER: list[tuple[str, float, float]] = [
    ("sc01", 1.0, 5.0),
    ("sc02", 2.0, 5.0),
    ("sc03", 6.0, 6.0),
    ("sc03", 24.0, 5.0),
    ("sc04", 3.0, 5.0),
    ("sc05", 2.0, 5.0),
    ("sc06", 4.0, 5.0),
    ("sc07", 3.0, 5.0),
    ("sc08", 0.0, 5.0),
    ("sc09", 8.0, 7.0),
    ("sc09", 16.0, 6.0),
    ("sc10", 4.0, 7.0),
]


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def duration(p: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


def is_final(sid: str) -> bool:
    rp = OUT / sid / "report.json"
    if not rp.exists():
        return False
    r = json.loads(rp.read_text(encoding="utf-8"))
    return r.get("quality") == "final" and (OUT / sid / f"{sid}.mp4").exists()


def render(ids: list[str], force: bool) -> int:
    for sid in ids:
        if not force and is_final(sid):
            print(f"== {sid} already final", flush=True)
            continue
        t0 = time.time()
        print(f"== {sid}", flush=True)
        r = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "savannah_scene.py"),
                sid,
                "--quality",
                "final",
                "--out",
                str(OUT),
            ]
        )
        if r.returncode:
            print(f"{sid} failed ({r.returncode})", flush=True)
            return r.returncode
        print(f"== {sid} done in {time.time() - t0:.0f}s", flush=True)
    return 0


def loudnorm(src: Path, dst: Path) -> dict:
    """Two-pass EBU R128 normalisation of ``src``'s audio to -14 LUFS (true peak -1 dB); the video is copied."""
    target = f"I={LUFS}:TP=-1.0:LRA=11"
    r = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(src),
            "-af",
            f"loudnorm={target}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    m = json.loads(r.stderr[r.stderr.rindex("{") : r.stderr.rindex("}") + 1])
    ff(
        "-i",
        str(src),
        "-c:v",
        "copy",
        "-af",
        f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
        f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(dst),
    )
    return {"input_lufs": float(m["input_i"]), "target_lufs": LUFS}


def cards(src: Path, dst: Path, secs: float, title_s: float = 5.0, end_s: float = 5.0) -> None:
    """The title over the opening and the end card over the last seconds (fades), re-encoded at high quality."""
    draw = [
        f"drawtext=fontfile='{FONT}':text='{esc(TITLE)}':x=(w-tw)/2:y=h*0.36:fontsize=58:fontcolor=white:"
        f"shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha='if(lt(t,0.8),t/0.8,if(lt(t,{title_s - 0.8}),1,"
        f"max(0,({title_s}-t)/0.8)))':enable='lt(t,{title_s})'",
        f"drawtext=fontfile='{FONT}':text='{esc(END)}':x=(w-tw)/2:y=h*0.42:fontsize=46:fontcolor=white:"
        f"shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha='min(1,max(0,(t-{secs - end_s:.2f})/0.8))':"
        f"enable='gt(t,{secs - end_s:.2f})'",
    ]
    ff(
        "-i",
        str(src),
        "-vf",
        ",".join(draw),
        "-c:v",
        "libx264",
        "-crf",
        "17",
        "-preset",
        "slow",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(dst),
    )


def web_copy(src: Path, dst: Path, height: int = 540, audio_k: int = 128) -> float:
    """A copy at most ``MAX_MB``: two-pass x264 at the bitrate that fits, scaled to ``height``."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    secs = duration(src)
    total_k = MAX_MB * 8 * 1024 / secs
    v_k = max(300, int(total_k - audio_k - 24))
    log = dst.parent / "x264pass"
    common = [
        "-vf",
        f"scale=-2:{height}:flags=lanczos",
        "-c:v",
        "libx264",
        "-b:v",
        f"{v_k}k",
        "-preset",
        "slow",
    ]
    common += ["-pix_fmt", "yuv420p", "-passlogfile", str(log)]
    ff(
        "-i",
        str(src),
        *common,
        "-pass",
        "1",
        "-an",
        "-f",
        "mp4",
        "NUL" if sys.platform == "win32" else "/dev/null",
    )
    ff(
        "-i",
        str(src),
        *common,
        "-pass",
        "2",
        "-c:a",
        "aac",
        "-b:a",
        f"{audio_k}k",
        "-movflags",
        "+faststart",
        str(dst),
    )
    for p in dst.parent.glob("x264pass*"):
        p.unlink()
    mb = dst.stat().st_size / 2**20
    if mb > 25:
        raise RuntimeError(f"{dst} is {mb:.1f} MB")
    return mb


def assemble() -> dict:
    ids = list(load_scenes(FILM / "07_scenes.json"))
    missing = [s for s in ids if not is_final(s)]
    if missing:
        raise SystemExit(f"not final yet: {', '.join(missing)}")
    parts, secs = [], []
    for sid in ids:
        r = json.loads((OUT / sid / "report.json").read_text(encoding="utf-8"))
        parts.append(OUT / sid / f"{sid}.mp4")
        secs.append(float(r["seconds"]))
    work = OUT / "assemble"
    work.mkdir(parents=True, exist_ok=True)
    joined = work / "joined.mp4"
    join_av(parts, secs, work, joined, crf=16)
    titled = work / "titled.mp4"
    cards(joined, titled, sum(secs))
    film = OUT / "film.mp4"
    loud = loudnorm(titled, film)
    mb = web_copy(film, SHOW / "savannah-film" / "film_web.mp4")
    rep = {"scenes": ids, "seconds": round(sum(secs), 2), "film": str(film), "web_mb": round(mb, 1), **loud}
    (OUT / "film.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    return rep


def trailer() -> dict:
    work = OUT / "trailer"
    work.mkdir(parents=True, exist_ok=True)
    clips = []
    card_s = 3.0
    title_card = work / "title.mp4"
    end_card = work / "end.mp4"
    for path, text, size in ((title_card, TITLE, 62), (end_card, END, 50)):
        ff(
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x1A1410:s=1280x720:r=24:d={card_s}",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=48000:cl=stereo:d={card_s}",
            "-vf",
            f"drawtext=fontfile='{FONT}':text='{esc(text)}':x=(w-tw)/2:y=(h-th)/2:fontsize={size}:fontcolor=0xF2E2C0:"
            f"alpha='min(1,min(t/0.6,({card_s}-t)/0.6))'",
            "-shortest",
            "-c:v",
            "libx264",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        )
    clips.append((title_card, card_s))
    for k, (sid, start, secs) in enumerate(TRAILER):
        src = OUT / sid / f"{sid}.mp4"
        dst = work / f"cut_{k:02d}.mp4"
        fade = f"afade=t=in:d=0.25,afade=t=out:st={secs - 0.35:.2f}:d=0.35"
        ff(
            "-ss",
            f"{start:.3f}",
            "-i",
            str(src),
            "-t",
            f"{secs:.3f}",
            "-vf",
            f"fade=t=in:d=0.25,fade=t=out:st={secs - 0.3:.2f}:d=0.3",
            "-af",
            fade,
            "-c:v",
            "libx264",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "24",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(dst),
        )
        clips.append((dst, secs))
    clips.append((end_card, card_s))
    joined = work / "joined.mp4"
    join_av([c for c, _ in clips], [s for _, s in clips], work, joined, crf=16)
    full = OUT / "trailer.mp4"
    loud = loudnorm(joined, full)
    secs = duration(full)
    mb = web_copy(full, SHOW / "savannah-trailer" / "trailer_web.mp4", height=720)
    rep = {"cuts": TRAILER, "seconds": round(secs, 2), "web_mb": round(mb, 1), **loud}
    (OUT / "trailer.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    if not 60 <= secs <= 90:
        print(f"warning: trailer is {secs:.1f} s (want 60-90)")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--assemble", action="store_true")
    ap.add_argument("--trailer", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-render scenes that are already final")
    a = ap.parse_args()
    if a.trailer:
        print(json.dumps(trailer(), indent=1))
        return 0
    if not a.assemble:
        ids = a.only.split(",") if a.only else list(load_scenes(FILM / "07_scenes.json"))
        rc = render(ids, a.force or bool(a.only))
        if rc:
            return rc
    print(json.dumps(assemble(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
