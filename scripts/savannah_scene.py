"""Produce one scene of *Tembo and the Singing Spring* from its spec (films/savannah/07_scenes.json).

    python scripts/savannah_scene.py sc02 --quality preview     # cloud CPU check: 480x270, 12 fps
    python scripts/savannah_scene.py sc02 --quality final       # laptop GPU: 1280x720, 24 fps, OptiX

Pipeline: cast voices (06_voices.json, Kokoro) -> line timing -> set + creatures on bone rigs + faces ->
foot-locked gaits along the blocking paths, idles, lip sync and expression tracks -> cameras framed on the
measured head positions, cut on the lines -> Cycles render -> sound (the scene's Composer cue re-timed to
the scene, ducked under the lines; ambience bed; species footsteps from the gait touchdowns; SFX) ->
``<out>/<scene>/<scene>.mp4`` (-14 LUFS), ``scene.blend``, ``report.json``.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animatica.audio import ambience, composer, lipsync, tts  # noqa: E402
from animatica.audio.voice_fx import PRE  # noqa: E402
from animatica.core.engine import BlenderSession  # noqa: E402
from animatica.creatures.build import build_creature  # noqa: E402
from animatica.creatures.face import BROW_COLOR, face_keys, face_ops, refresh_rest  # noqa: E402
from animatica.creatures.gait import GAITS, Waypoint  # noqa: E402
from animatica.creatures.perform import walk_keys  # noqa: E402
from animatica.creatures.species import SPECIES  # noqa: E402
from animatica.production import sound  # noqa: E402
from animatica.production.scene import (  # noqa: E402
    Subject,
    cut_list,
    expression_tracks,
    frame_shot,
    load_scenes,
    schedule,
    set_subject,
)
from animatica.sets.savannah import Layout, savannah_set  # noqa: E402

FILM = ROOT / "films" / "savannah"
QUALITY = {  # resolution, samples, frame step, device
    "preview": ((480, 270), 8, 2, "cpu"),
    "draft": ((960, 540), 16, 1, "auto"),
    "final": ((1280, 720), 48, 1, "optix"),
}


def heading_yaw(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The yaw that faces from ``a`` toward ``b`` (rest faces -Y)."""
    return math.degrees(math.atan2(b[0] - a[0], -(b[1] - a[1])))


def waypoints(actor, seconds: float) -> tuple[list[Waypoint], float]:
    if not actor.path:
        return [Waypoint(0.0, *actor.at), Waypoint(seconds, *actor.at)], actor.yaw
    pts = [Waypoint(t, x, y) for t, x, y in actor.path]
    if pts[0].t > 0:
        pts.insert(0, Waypoint(0.0, pts[0].x, pts[0].y))
    if pts[-1].t < seconds:
        pts.append(Waypoint(seconds, pts[-1].x, pts[-1].y))
    moving = [p for p in actor.path]
    yaw0 = heading_yaw(moving[0][1:], moving[1][1:]) if len(moving) > 1 else actor.yaw
    return pts, yaw0


def run(eng: BlenderSession, bid: str, ops: list[dict]) -> dict:
    r = eng.run_batch({"batch_id": bid, "ops": ops})
    if not r.ok:
        raise SystemExit(json.dumps({"batch": bid, "errors": r.errors[:6]}, indent=1))
    if r.warnings:
        print(json.dumps({"batch": bid, "warnings": r.warnings[:4]}))
    return r.data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--quality", default="preview", choices=sorted(QUALITY))
    ap.add_argument("--out", default=str(ROOT / "output" / "savannah"))
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--no-render", action="store_true", help="build, mix and save the .blend only")
    ap.add_argument(
        "--stills", action="store_true", help="render one still per shot (framing check), no film"
    )
    a = ap.parse_args()
    t0 = time.time()
    spec = load_scenes(FILM / "07_scenes.json")[a.scene]
    res, samples, step, device = QUALITY[a.quality]
    out = Path(a.out).resolve() / spec.id
    if out.exists():
        shutil.rmtree(out)
    (out / "voices").mkdir(parents=True)
    fps = a.fps

    # ---- voices and timing
    cast_voices = json.loads((FILM / "06_voices.json").read_text(encoding="utf-8"))["cast"]
    takes = []
    for i, ln in enumerate(spec.lines):
        c = cast_voices[ln.who]
        wav = out / "voices" / f"{i:02d}_{ln.who}.wav"
        info = tts.synthesize(
            ln.text,
            wav,
            tts.VoiceSpec(
                engine="kokoro",
                voice=c["voice"],
                pitch=c["pitch"],
                rate=c["rate"],
                mood=ln.expr[0][1] if ln.expr else None,
            ),
        )
        takes.append((Path(info["path"]), float(info["duration"])))
    seconds = schedule(spec, [d for _, d in takes])
    n = int(round(seconds * fps)) + 1
    shots = cut_list(spec, seconds)
    tracks = expression_tracks(spec)

    # ---- set + cast
    lay = spec.layout
    layout = Layout(
        water=tuple(lay["water"]) if lay.get("water") else None,
        acacias=[tuple(x) for x in lay.get("acacias", [])],
        mounds=[tuple(x) for x in lay.get("mounds", [])],
        action=[tuple(x) for x in lay.get("action", [(0.0, 0.0, 4.0)])],
    )
    ops = savannah_set(layout, spec.tod)
    metas, faces, plans = {}, {}, {}
    face_batch: list[dict] = []
    for cid, actor in spec.cast.items():
        sp = SPECIES[actor.species]
        pts, yaw0 = waypoints(actor, seconds)
        c_ops, meta = build_creature(cid, sp, at=(pts[0].x, pts[0].y), yaw=yaw0)
        f_ops, face = face_ops(cid, sp, meta.root, meta.rig, BROW_COLOR[actor.species])
        ops += c_ops
        face_batch += f_ops
        metas[cid], faces[cid] = meta, face
    ops.append({"op": "set_frame_range", "start": 1, "end": n, "fps": fps})
    with BlenderSession(workdir=out) as eng:
        run(eng, "set+cast", ops)
        if face_batch:
            run(eng, "faces", face_batch)
            brows = [b["id"] for f in faces.values() for b in f["brows"].values()]
            q = run(eng, "q", [{"op": "query", "ids": brows, "fields": ["transform"]}])
            for f in faces.values():
                refresh_rest(f, q["objects"])
        # ---- performance: gaits/idles, lip sync, expressions
        anim: list[dict] = []
        for k, (cid, actor) in enumerate(spec.cast.items()):
            meta = metas[cid]
            pts, yaw0 = waypoints(actor, seconds)
            gait = GAITS[actor.species].get(actor.gait) or GAITS[actor.species]["walk"]
            keys, plan = walk_keys(meta, gait, pts, fps, 1, seed=11 + k, yaw0=yaw0)
            plans[cid] = plan
            cues = []
            for ln, (wav, _) in zip(spec.lines, takes):
                if ln.who == cid:
                    cs, _engine = lipsync.lipsync(wav, ln.text.replace("*", ""))
                    cues += [
                        dataclasses.replace(c, start=c.start + ln.start, end=c.end + ln.start) for c in cs
                    ]
            anim += keys + face_keys(faces[cid], tracks[cid], cues or None, fps, 1, n)
        if anim:
            run(eng, "perform", anim)

        # ---- cameras, framed on where the heads really are
        cam_ops: list[dict] = []
        shot_report = []
        for i, sh in enumerate(shots):
            f0, f1 = 1 + int(sh.start * fps), 1 + min(n - 1, int(sh.end * fps))
            samples_f = sorted({f0, (f0 + f1) // 2, max(f0, f1 - 1)})
            subs: list[Subject] = []
            if sh.subjects:
                bones = [f"{metas[c].rig}:head" for c in sh.subjects]
                d = run(
                    eng,
                    f"m{i}",
                    [
                        {
                            "op": "inspect",
                            "subjects": [metas[c].root for c in sh.subjects],
                            "frames": samples_f,
                            "bone_tails": bones,
                        }
                    ],
                )["inspect"]["frames"]
                use = samples_f if sh.type in ("ws", "ews") else [samples_f[len(samples_f) // 2]]
                for f in use:
                    for c in sh.subjects:
                        head = tuple(d[str(f)]["bone_tails"][f"{metas[c].rig}:head"])
                        p = plans[c][min(len(plans[c]) - 1, f - 1)]
                        hs = max(SPECIES[spec.cast[c].species].head_size)
                        subs.append(
                            Subject(
                                head=head,
                                root=p.root,
                                yaw=p.yaw,
                                head_size=hs,
                                height=head[2] + hs * 0.5,
                                length=metas[c].length,
                            )
                        )
            else:
                subs = [set_subject(sh.look, sh.frame_h)]  # type: ignore[arg-type]
            cam = frame_shot(sh.type, subs, side=sh.side, aim_z=sh.look[2] if sh.look else None)
            cid = f"cam_{i:02d}_{sh.type}"
            cam_ops += [
                {"op": "create_empty", "id": f"{cid}_aim", "location": cam["aim"]},
                {
                    "op": "add_camera",
                    "id": cid,
                    "location": cam["location"],
                    "lens": cam["lens"],
                    "look_at": f"{cid}_aim",
                },
                {"op": "set_camera_active", "id": cid, "frame": f0},
            ]
            shot_report.append(
                {
                    "shot": i,
                    "type": sh.type,
                    "subjects": sh.subjects,
                    "start": sh.start,
                    "end": round(sh.end, 3),
                    "note": sh.note,
                    **cam,
                }
            )
        run(eng, "cameras", cam_ops)
        run(
            eng,
            "render-settings",
            [
                {
                    "op": "set_render",
                    "engine": "cycles",
                    "resolution": list(res),
                    "samples": samples,
                    "fps": fps,
                    "device": device,
                    "look": "AgX - Medium High Contrast",
                },
                {"op": "save", "path": str(out / "scene.blend")},
            ],
        )
        render_s = None
        if a.stills:
            a.no_render = True
            still_ops = []
            for r_ in shot_report:
                mid = 1 + int((r_["start"] + r_["end"]) / 2 * fps)
                cam_id = f"cam_{r_['shot']:02d}_{r_['type']}"
                still_ops.append(
                    {
                        "op": "render_preview",
                        "camera": cam_id,
                        "frame": mid,
                        "engine": "cycles",
                        "samples": samples,
                        "resolution": list(res),
                        "path": str(out / "stills" / f"shot_{r_['shot']:02d}_{r_['type']}.png"),
                        "device": device,
                    }
                )
            run(eng, "stills", still_ops)
        if not a.no_render:
            r = run(
                eng, "render", [{"op": "render_final", "output_dir": str(out / "frames"), "frame_step": step}]
            )
            render_s = r.get("render_seconds")

    # ---- sound
    voices = []
    for ln, (wav, _) in zip(spec.lines, takes):
        x, sr = tts.read_wav(wav)
        voices.append((ln.start - PRE, sound.dialogue(x, sr, seed=len(voices))))
    cue = next(c for c in composer.load_cue_sheet(FILM / "05_cue_sheet.json") if c.id == spec.cue)
    cue = dataclasses.replace(cue, seconds=seconds)  # re-timed to picture: the arrangement fits the bars
    rep = composer.render_cue(composer.arrange(cue), out / "music")
    music = composer._read(out / "music" / rep["wav"])
    amb = ambience.bed(
        spec.ambience.get("tod", spec.tod), seconds, water=bool(spec.ambience.get("water")), seed=7
    )
    steps = np.zeros((int(seconds * sound.SR), 2), np.float32)
    nsteps = 0
    for cid, actor in spec.cast.items():
        if actor.path:
            td = ambience.touchdowns_from_plan(plans[cid], fps)
            nsteps += len(td)
            steps += ambience.footsteps_track(actor.species, td, seconds, seed=len(cid))
    sfx = [(b.time(spec.lines), ambience.sfx(b.value, seed=j)) for j, b in enumerate(spec.sfx)]
    mix, mrep = sound.mix_scene(seconds, voices, music, amb, steps, sfx)
    composer.write_wav(out / "mix.wav", mix)

    # ---- picture + sound
    report = {
        "scene": spec.id,
        "title": spec.title,
        "quality": a.quality,
        "seconds": seconds,
        "frames": n,
        "lines": [{"who": ln.who, "start": ln.start, "end": ln.end, "text": ln.text} for ln in spec.lines],
        "shots": shot_report,
        "cue": {k: rep[k] for k in ("id", "bpm", "bars", "moods", "programs", "engine")},
        "footsteps": nsteps,
        "sound": mrep,
        "warnings": spec.warnings,
        "render_seconds": render_s,
        "wall_seconds": None,
    }
    if not a.no_render:
        mp4 = out / f"{spec.id}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-framerate",
                str(fps / step),
                "-pattern_type",
                "glob",
                "-i",
                str(out / "frames" / "frame_*.png"),
                "-i",
                str(out / "mix.wav"),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-af",
                "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:v",
                "libx264",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
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
        report["mp4"] = str(mp4)
    report["wall_seconds"] = round(time.time() - t0, 1)
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("scene", "seconds", "frames", "sound", "warnings", "render_seconds", "wall_seconds")
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
