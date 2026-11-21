"""The savannah animatic (DESIGN_STAGE §7): the whole film as fast EEVEE renders with the final voices, music and
timing, for the owner's approval before any expensive render.

    python scripts/savannah_animatic.py                  # every scene in 07_scenes.json, then assemble
    python scripts/savannah_animatic.py --only sc03,sc04 # re-render some scenes, then re-assemble
    python scripts/savannah_animatic.py --assemble       # assemble what is already rendered

Each scene runs ``savannah_scene.py <scene> --quality animatic`` in turn (one heavy process at a time): EEVEE at
960x540, 24 fps, every shot on a slow eased push-in / orbit, and any set-up longer than 4.5 s cut into parts from
new angles (``production.scene.split_long``). Then the scenes are joined with the title over the opening and the
end card over the last shot, a burn-in of scene / shot / note on every frame (it is an animatic), and a check that
no shot holds still: a shot fails when it is longer than ``--max-static`` seconds and neither the camera nor its
subjects move by 2 % of the frame. Every shot's middle frame is also measured for a horizon stripe
(``animatica.sets.frames``; soft: listed as ``horizon_stripes``, not an exit failure), and every scene for dead
air across its cuts on its own cameras (``production.pacing.dead_air_in_report``: nothing on screen moving but the
camera for over 4.5 s; soft, listed as ``dead_air``), and every close or medium shot's subject for a head that
renders near black (``production.exposure.dark_faces_in_report``; soft, listed as ``dark_faces``). The report
lands next to the film (``animatic.json``).
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animatica.production.exposure import dark_faces_in_report  # noqa: E402
from animatica.production.pacing import dead_air_in_report  # noqa: E402
from animatica.production.scene import load_scenes, vfov  # noqa: E402
from animatica.sets.frames import stripes_in_video  # noqa: E402

FILM = ROOT / "films" / "savannah"
FONT = "C\\:/Windows/Fonts/arial.ttf" if sys.platform == "win32" else "DejaVuSans"
TITLE = "Tembo and the Singing Spring"
END = "Made with Animatica"


def esc(s: str) -> str:
    """ffmpeg drawtext text escaping."""
    return (
        s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%").replace(",", "\\,")
    )


def burn_in(
    src: Path, dst: Path, sid: str, title: str, shots: list[dict], first: bool, last: bool, secs: float
) -> None:
    draw = [
        f"drawtext=fontfile='{FONT}':text='{esc(sid.upper() + '  ' + title)}':x=12:y=10:fontsize=16:"
        "fontcolor=white@0.85:box=1:boxcolor=black@0.35:boxborderw=4"
    ]
    for i, sh in enumerate(shots):
        label = f"{i + 1:02d} {sh['type'].upper()}" + (f"  {sh['note']}" if sh.get("note") else "")
        draw.append(
            f"drawtext=fontfile='{FONT}':text='{esc(label[:90])}':x=12:y=h-28:fontsize=15:fontcolor=white@0.85:"
            f"box=1:boxcolor=black@0.35:boxborderw=4:enable='between(t,{sh['start']:.3f},{sh['end'] - 0.001:.3f})'"
        )
    if first:
        draw.append(
            f"drawtext=fontfile='{FONT}':text='{esc(TITLE)}':x=(w-tw)/2:y=h*0.36:fontsize=46:fontcolor=white:"
            "shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha='if(lt(t,0.6),t/0.6,if(lt(t,4.2),1,max(0,(5-t)/0.8)))':"
            "enable='lt(t,5)'"
        )
    if last:
        draw.append(
            f"drawtext=fontfile='{FONT}':text='{esc(END)}':x=(w-tw)/2:y=h*0.42:fontsize=40:fontcolor=white:"
            f"shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha='min(1,max(0,(t-{secs - 5:.2f})/0.8))':"
            f"enable='gt(t,{secs - 5:.2f})'"
        )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-vf",
            ",".join(draw),
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(dst),
        ],
        check=True,
    )


def fix_fracs(sh: dict) -> dict:
    """Reports written before ``frame_h_m`` existed measured the frame with the field of view converted to
    radians twice (a frame far too small); rescale those fractions to the true frame height."""
    if "frame_h_m" in sh or "lens" not in sh:
        return sh
    v = vfov(sh["lens"])
    k = math.tan(math.radians(v) / 2) / math.tan(v / 2)
    return {**sh, **{f: round(sh[f] * k, 3) for f in ("camera_move_frac", "subject_move_frac") if f in sh}}


def static_shots(rep: dict, max_static: float) -> list[dict]:
    bad = []
    for sh in map(fix_fracs, rep.get("shots", [])):
        dur = sh["end"] - sh["start"]
        moving = max(sh.get("camera_move_frac", 0.0), sh.get("subject_move_frac", 0.0)) >= 0.02
        if dur > max_static and not moving:
            bad.append({"shot": sh["shot"], "type": sh["type"], "seconds": round(dur, 2)})
    return bad


def dead_air_rows(spec, rep: dict) -> list[dict]:
    """The scene's dead-air stretches on its own cameras, as report rows (soft: the animatic still assembles)."""
    return [{"scene": v.scene, "t": v.t, "detail": v.detail} for v in dead_air_in_report(spec, rep)]


def join_av(parts: list[Path], seconds: list[float], work: Path, out: Path, crf: int = 21) -> None:
    """Join scene clips with picture and sound concatenated separately, then muxed: the concat demuxer on
    clips with AAC audio started the joined video a frame (42 ms) after its sound (animatic v1), which the
    owner saw as lips out of sync. Each scene's sound is cut or padded to its exact length first."""
    import numpy as np

    from animatica.audio import composer

    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    video = work / "joined_video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "24",
            str(video),
        ],
        check=True,
    )
    chunks = []
    for p, secs in zip(parts, seconds):
        wav = p.with_suffix(".wav")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(p),
                "-vn",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            check=True,
        )
        x = composer._read(wav)
        n = int(round(secs * 48000))
        x = x[:n] if len(x) >= n else np.concatenate([x, np.zeros((n - len(x), x.shape[1]), x.dtype)])
        chunks.append(x)
    audio = work / "joined_audio.wav"
    composer.write_wav(audio, np.concatenate(chunks))
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
    )


def default_paths(film: Path, work: str | None, out: str | None) -> tuple[str, str]:
    """The savannah keeps its showcase paths; a feature film's animatic lands where its gate looks for it
    (``feature.stages.animatic_path``), so ``animatica feature`` sees it and the savannah's isn't overwritten."""
    if film.resolve() == FILM.resolve():
        dw, do = ROOT / "output" / "savannah-animatic", ROOT / "examples" / "showcase" / "savannah-animatic"
        return work or str(dw), out or str(do / "animatic.mp4")
    from animatica.feature.stages import animatic_path

    ap = animatic_path(film.resolve())
    return work or str(ap.parent), out or str(ap)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated scene ids to (re)render")
    ap.add_argument("--assemble", action="store_true", help="assemble the rendered scenes only")
    ap.add_argument(
        "--work",
        help="scene renders; default output/savannah-animatic, or output/<film>-animatic for a feature film",
    )
    ap.add_argument(
        "--film", default=str(FILM), help="the film folder (feature mode); default films/savannah"
    )
    ap.add_argument(
        "--out",
        help="default examples/showcase/savannah-animatic/animatic.mp4, or for a feature film the path its "
        "animatic gate checks (output/<film>-animatic/animatic.mp4)",
    )
    ap.add_argument("--max-static", type=float, default=4.5)
    a = ap.parse_args()
    film = Path(a.film)
    a.work, a.out = default_paths(film, a.work, a.out)
    work = Path(a.work)
    global TITLE
    if (film / "01_premise.json").exists():  # a feature-mode film: its own title
        TITLE = json.loads((film / "01_premise.json").read_text(encoding="utf-8"))["title"]
    scenes = load_scenes(film / "07_scenes.json")
    ids = list(scenes)
    todo = [] if a.assemble else (a.only.split(",") if a.only else ids)
    for sid in todo:
        t0 = time.time()
        print(f"== {sid}", flush=True)
        r = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "savannah_scene.py"),
                sid,
                "--quality",
                "animatic",
                "--out",
                str(work),
                "--film",
                str(film),
            ]
        )
        if r.returncode:
            print(f"{sid} failed ({r.returncode})")
            return r.returncode
        print(f"== {sid} done in {time.time() - t0:.0f}s", flush=True)

    parts, report = [], {"scenes": [], "static_shots": [], "max_static_seconds": a.max_static}
    report["horizon_stripes"], report["dead_air"], report["dark_faces"] = [], [], []
    for k, sid in enumerate(ids):
        rp = work / sid / "report.json"
        if not rp.exists():
            print(f"missing {rp}; render it first")
            return 1
        rep = json.loads(rp.read_text(encoding="utf-8"))
        burned = work / sid / f"{sid}_animatic.mp4"
        burn_in(
            work / sid / f"{sid}.mp4",
            burned,
            sid,
            scenes[sid].title,
            rep["shots"],
            k == 0,
            k == len(ids) - 1,
            rep["seconds"],
        )
        parts.append(burned)
        bad = static_shots(rep, a.max_static)
        report["static_shots"] += [{"scene": sid, **b} for b in bad]
        report["horizon_stripes"] += [
            {"scene": sid, **h}
            for h in stripes_in_video(
                work / sid / f"{sid}.mp4",
                [(sh["start"] + sh["end"]) / 2 for sh in rep["shots"]],
                [f"shot {sh['shot']} ({sh['type']})" for sh in rep["shots"]],
            )
        ]
        report["dead_air"] += dead_air_rows(scenes[sid], rep)
        report["dark_faces"] += dark_faces_in_report(scenes[sid], rep, work / sid / f"{sid}.mp4")
        report["scenes"].append(
            {
                "scene": sid,
                "title": scenes[sid].title,
                "seconds": rep["seconds"],
                "shots": len(rep["shots"]),
                "longest_shot": round(max(s["end"] - s["start"] for s in rep["shots"]), 2),
                "warnings": rep.get("warnings", []),
                "lines": [
                    {"who": v.get("who"), "engine": v.get("engine"), "wer": v.get("wer")}
                    for v in rep.get("lines", [])
                ],
            }
        )
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    join_av(parts, [r["seconds"] for r in report["scenes"]], work, out)
    report["seconds"] = round(sum(s["seconds"] for s in report["scenes"]), 2)
    report["shots"] = sum(s["shots"] for s in report["scenes"])
    report["longest_shot"] = max(s["longest_shot"] for s in report["scenes"])
    (out.parent / "animatic.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("seconds", "shots", "longest_shot", "static_shots")}))
    for h in report["horizon_stripes"]:
        print(
            f"horizon stripe (soft): {h['scene']} {h['label']} at {h['row']:.0%} height, span {h['span']:.0%}"
        )
    for d in report["dead_air"]:
        print(f"dead air (soft): {d['scene']} at {d['t']:.1f}s: {d['detail']}")
    for d in report["dark_faces"]:
        print(
            f"dark face (soft): {d['scene']} shot {d['shot']} ({d['type']}) at {d['t']:.1f}s: "
            f"{d['who']}'s head median {d['median']:.3f}"
        )
    return 1 if report["static_shots"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
