"""The savannah film's final render (Stage 2, item 10) and its trailer (item 11).

    python scripts/savannah_film.py                 # render every scene not yet final, then assemble
    python scripts/savannah_film.py --only sc03     # (re-)render some scenes, then assemble
    python scripts/savannah_film.py --assemble      # assemble what is rendered
    python scripts/savannah_film.py --trailer       # cut the trailer from the final scenes
    python scripts/savannah_film.py --deliver       # CHALLENGE "Output": final.mp4, captions, edit, log, poster
    python scripts/savannah_film.py --film films/<slug> [--assemble | --deliver]   # a feature-mode film

Each scene runs ``savannah_scene.py <scene> --quality final`` (Cycles on OptiX, 1280x720, 24 fps) in turn, one
heavy process at a time; a scene whose ``report.json`` says ``final`` and whose MP4 exists is skipped, so a run
that stops resumes at the next scene. The film joins the scenes with picture and sound handled separately (no
lip offset, ``savannah_animatic.join_av``), puts the title over the opening and the end card over the last
shot, and normalises the whole mix to -14 LUFS (two-pass loudnorm). Full quality goes to
``output/savannah/film.mp4``; a web copy at most 25 MB (two-pass bitrate) to
``examples/showcase/savannah-film/``. The trailer is the cut list ``TRAILER`` (scene, start, seconds) between
a title card and the end card "Made with Animatica · open source", also at most 25 MB.

``--film films/<slug>`` (feature mode, DECISIONS #106) does the same for a film the planner wrote: the scenes and
the title come from the film folder, everything lands in ``output/<slug>/`` (``film.mp4`` where the production
gate looks, ``feature.stages.film_path``; the web copy and the deliverables beside it, nothing in the showcase),
and ``--trailer`` cuts ``<film>/trailer.json`` (``[[scene, start, seconds], ...]``) or, without one, a list picked
from the final scenes' lines (``production.trailer``, DECISIONS #107; written to ``trailer_cuts.json`` to edit).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from savannah_animatic import FONT, TITLE, esc, join_av  # noqa: E402

from animatica.audio.mux import loudness, master  # noqa: E402
from animatica.feature.stages import film_path  # noqa: E402
from animatica.production import deliverables as dlv  # noqa: E402
from animatica.production.scene import load_scenes  # noqa: E402
from animatica.production.trailer import trailer_cuts  # noqa: E402

FILM = ROOT / "films" / "savannah"
OUT = ROOT / "output" / "savannah"
SHOW = ROOT / "examples" / "showcase"
WEB_FILM = SHOW / "savannah-film" / "film_web.mp4"
WEB_TRAILER = SHOW / "savannah-trailer" / "trailer_web.mp4"
DELIVER = SHOW / "savannah"
END = "Made with Animatica · open source"
MAX_MB = 24.0  # web copies stay under the 25 MB repo limit with a margin
LUFS = -14.0

# the trailer: (scene, start s, seconds), in order, cut on the lines (timings from the scene reports): the world
# and the need, the friends, the legend and the vow, setting off, the trouble, lost together, the night, the push
# and the spring, the moral. About 64 s of film between two 3 s cards.
TRAILER: list[tuple[str, float, float]] = [
    ("sc01", 1.8, 5.6),  # "Far away, where the grass grows golden..."
    ("sc01", 8.2, 4.8),  # "...smaller... and smaller"
    ("sc02", 6.2, 2.8),  # "Morning, Zuri! Morning, Kiki! Water!"
    ("sc02", 15.2, 1.9),  # "Your trunk's a hose with hiccups!"
    ("sc03", 9.2, 7.7),  # the singing spring past the two baobabs
    ("sc03", 22.6, 2.7),  # "Then I'll find it. For everyone."
    ("sc03", 45.0, 6.0),  # "So five friends set off together..."
    ("sc04", 10.2, 2.6),  # "DANGER! ...Oh. It's a rock."
    ("sc05", 15.5, 1.9),  # "EVERYBODY PANIC!"
    ("sc06", 11.1, 4.1),  # "There! Stripes!" / "And I hear her."
    ("sc07", 16.4, 2.6),  # "We're not lost if we're together."
    ("sc08", 17.0, 4.0),  # "Two trees, bowing! Right under the stars!"
    ("sc09", 7.0, 5.4),  # "I can't... do it... alone." / "Then don't."
    ("sc09", 16.6, 7.4),  # "One... two... PUSH!", the gush, the spring lights up
    ("sc10", 3.8, 4.8),  # "Fast or slow, tall or small... it takes all of us."
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
                "--film",
                str(FILM),
            ]
        )
        if r.returncode:
            print(f"{sid} failed ({r.returncode})", flush=True)
            return r.returncode
        print(f"== {sid} done in {time.time() - t0:.0f}s", flush=True)
    return 0


def loudnorm(src: Path, dst: Path) -> dict:
    """Two-pass EBU R128 normalisation of ``src``'s audio to -14 LUFS with a true-peak limiter, measured on the
    encoded file (``animatica.audio.mux.master``: at or under -1 dBTP); the video is copied."""
    got = master(src, dst, lufs=LUFS)
    return {
        "input_lufs": got["input_lufs"],
        "target_lufs": LUFS,
        "lufs": got.get("i"),
        "true_peak_dbtp": got.get("tp"),
        "limit_db": got["limit_db"],
    }


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


def web_copy(src: Path, dst: Path, height: int = 540, audio_k: int = 192) -> float:
    """A copy at most ``MAX_MB``: two-pass x264 at the bitrate that fits, scaled to ``height``. The mastered
    audio is copied, not re-encoded (a second AAC pass added overs: the 11-18 web film peaked at +0.5 dBTP);
    ``audio_k`` is its bitrate, kept out of the video budget."""
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
        "copy",
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
    web = WEB_FILM
    mb = web_copy(film, web)
    rep = {"scenes": ids, "seconds": round(sum(secs), 2), "film": str(film), "web_mb": round(mb, 1), **loud}
    rep["web_true_peak_dbtp"] = loudness(web).get("tp")
    (OUT / "film.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    return rep


def auto_cuts() -> list[tuple[str, float, float]]:
    """No hand-made cut list: pick one from the final scenes' reports (``production.trailer``, DECISIONS #107)
    and write it to ``OUT/trailer_cuts.json``, to copy to ``<film>/trailer.json`` and edit by hand."""
    ids = list(load_scenes(FILM / "07_scenes.json"))
    missing = [s for s in ids if not is_final(s)]
    if missing:
        raise SystemExit(
            f"no trailer cut list for this film ({FILM / 'trailer.json'}) and not every scene is final "
            f"({', '.join(missing)}): render the scenes first, or write the cut list ([[scene, start, s], ...])"
        )
    reports = [json.loads((OUT / sid / "report.json").read_text(encoding="utf-8")) for sid in ids]
    cuts = trailer_cuts(reports)
    if not cuts:
        raise SystemExit(f"no spoken line to cut a trailer on: write {FILM / 'trailer.json'} by hand")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trailer_cuts.json").write_text(json.dumps(cuts, indent=1) + "\n", encoding="utf-8")
    return [(str(c[0]), float(c[1]), float(c[2])) for c in cuts]


def trailer() -> dict:
    cuts, source = (TRAILER, "hand") if TRAILER else (auto_cuts(), "auto")
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
    for k, (sid, start, secs) in enumerate(cuts):
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
    web = WEB_TRAILER
    mb = web_copy(full, web, height=720)
    rep = {"cuts": cuts, "cuts_from": source, "seconds": round(secs, 2), "web_mb": round(mb, 1), **loud}
    rep["web_true_peak_dbtp"] = loudness(web).get("tp")
    (OUT / "trailer.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    if not 60 <= secs <= 90:
        print(f"warning: trailer is {secs:.1f} s (want 60-90)")
    return rep


TAGLINE = "Fast or slow, tall or small, it takes all of us."


def use_film(film: Path) -> None:
    """Point every path, the title, the tagline and the trailer's cut list at ``film``. The savannah keeps its
    showcase paths; any other film writes only under ``output/<slug>/``."""
    global FILM, OUT, WEB_FILM, WEB_TRAILER, DELIVER, TITLE, TAGLINE, TRAILER
    film = Path(film).resolve()
    if film == (ROOT / "films" / "savannah").resolve():
        return
    FILM = film
    OUT = film_path(film).parent
    WEB_FILM = OUT / "film_web.mp4"
    WEB_TRAILER = OUT / "trailer_web.mp4"
    DELIVER = OUT / "deliver"
    prem = film / "01_premise.json"
    p = json.loads(prem.read_text(encoding="utf-8")) if prem.exists() else {}
    TITLE = p.get("title", film.name.replace("-", " ").title())
    theme = p.get("tagline") or p.get("theme") or ""
    TAGLINE = (theme[:1].upper() + theme[1:]).rstrip(".") + "." if theme else ""
    cuts = film / "trailer.json"
    TRAILER = (
        [(str(c[0]), float(c[1]), float(c[2])) for c in json.loads(cuts.read_text(encoding="utf-8"))]
        if cuts.exists()
        else []
    )


def deliver(poster_at: float | None = None) -> dict:
    """CHALLENGE-SAVANNAH "Output" in ``examples/showcase/savannah/``: ``final.mp4`` (1280x720, at most 25 MB,
    the captions as a soft English track), ``captions.srt`` / ``.vtt``, ``edit.mlt`` (the scene renders, one
    entry per shot; paths point at ``output/savannah/``, which isn't committed), ``production_log.md`` and
    ``poster.jpg`` (from the full-quality film). Needs the final scenes and ``assemble()``'s film."""
    ids = list(load_scenes(FILM / "07_scenes.json"))
    missing = [s for s in ids if not is_final(s)]
    film = OUT / "film.mp4"
    if missing or not film.exists():
        raise SystemExit(f"assemble the final film first (not final: {', '.join(missing) or 'film.mp4'})")
    reports = [json.loads((OUT / sid / "report.json").read_text(encoding="utf-8")) for sid in ids]
    dst = DELIVER
    dst.mkdir(parents=True, exist_ok=True)
    cues = dlv.caption_cues(reports)
    srt = dlv.write_srt(cues, dst / "captions.srt")
    dlv.write_vtt(cues, dst / "captions.vtt")
    rel = Path(os.path.relpath(OUT, dst))
    dlv.write_mlt(reports, [(rel / sid / f"{sid}.mp4").as_posix() for sid in ids], dst / "edit.mlt", TITLE)
    t = dlv.poster_time(reports) if poster_at is None else poster_at
    dlv.write_poster(film, t, dst / "poster.jpg", TITLE, TAGLINE)
    work = OUT / "deliver"
    work.mkdir(parents=True, exist_ok=True)
    pic = work / "final_nosubs.mp4"
    mb = web_copy(film, pic, height=720)
    final = dst / "final.mp4"
    ff(
        "-i",
        str(pic),
        "-i",
        str(srt),
        "-map",
        "0",
        "-map",
        "1",
        "-c",
        "copy",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=eng",
        "-movflags",
        "+faststart",
        str(final),
    )
    film_rep = (
        json.loads((OUT / "film.json").read_text(encoding="utf-8")) if (OUT / "film.json").exists() else {}
    )
    film_rep["web_true_peak_dbtp"] = loudness(final).get("tp")
    film_rep["web_mb"] = round(final.stat().st_size / 2**20, 1)
    trl = OUT / "trailer.json"
    trailer_rep = json.loads(trl.read_text(encoding="utf-8")) if trl.exists() else None
    log = dlv.production_log(reports, TITLE, film_rep, trailer_rep, cues)
    (dst / "production_log.md").write_text(log, encoding="utf-8")
    return {
        "final_mb": film_rep["web_mb"],
        "picture_mb": round(mb, 1),
        "poster_at": round(t, 2),
        "cues": len(cues),
        "caption_issues": len(dlv.caption_issues(cues)),
        "web_true_peak_dbtp": film_rep["web_true_peak_dbtp"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--assemble", action="store_true")
    ap.add_argument("--trailer", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-render scenes that are already final")
    ap.add_argument("--deliver", action="store_true", help="write examples/showcase/savannah/ from the film")
    ap.add_argument("--poster-at", type=float, default=None, help="film time of the poster frame (s)")
    ap.add_argument(
        "--film", default=str(FILM), help="the film folder (feature mode); default films/savannah"
    )
    a = ap.parse_args()
    use_film(Path(a.film))
    if a.deliver:
        print(json.dumps(deliver(a.poster_at), indent=1))
        return 0
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
