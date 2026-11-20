"""Produce one scene of *Tembo and the Singing Spring* from its spec (films/savannah/07_scenes.json).

    python scripts/savannah_scene.py sc02 --quality preview     # cloud CPU check: 480x270, 12 fps
    python scripts/savannah_scene.py sc02 --quality final       # laptop GPU: 1280x720, 24 fps, OptiX

Pipeline: cast voices (06_voices.json: Chatterbox steered by the Kokoro blends, Kokoro fallback) -> line timing -> set + creatures on bone rigs + faces ->
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
import os
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
from animatica.creatures.gesture import Gesture, Rig, acting_layers, gaze_track, spray_droplets  # noqa: E402
from animatica.creatures.perform import back_point, plan_for, ride_plan, walk_keys  # noqa: E402
from animatica.creatures.species import SPECIES  # noqa: E402
from animatica.production import acting, continuity, sound, staging  # noqa: E402
from animatica.production.scene import (  # noqa: E402
    Occluder,
    Subject,
    cut_list,
    expression_tracks,
    frame_shot,
    load_scenes,
    schedule,
    set_subject,
    shot_move,
    split_long,
    vfov,
)
from animatica.sets.savannah import Layout, baobab_ops, bird_flock_ops, log_ops, savannah_set  # noqa: E402

FILM = ROOT / "films" / "savannah"
QUALITY = {  # resolution, samples, frame step, device
    "preview": ((480, 270), 8, 2, "cpu"),
    "draft": ((960, 540), 16, 1, "auto"),
    "final": ((1280, 720), 48, 1, "optix"),
    # the animatic gate (DESIGN_STAGE §7): fast EEVEE frames on the GPU with the final voices, music and timing
    "animatic": ((960, 540), 16, 1, "optix"),
}
ENGINE = {"animatic": "eevee"}  # everything else renders in Cycles


def heading_yaw(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The yaw that faces from ``a`` toward ``b`` (rest faces -Y)."""
    return math.degrees(math.atan2(b[0] - a[0], -(b[1] - a[1])))


def waypoints(actor, seconds: float) -> tuple[list[Waypoint], float]:
    if not actor.path:
        return [Waypoint(0.0, *actor.at), Waypoint(seconds, *actor.at)], actor.yaw
    pts = [Waypoint(w[0], w[1], w[2], glide=len(w) > 3 and bool(w[3])) for w in actor.path]
    if pts[0].t > 0:
        pts.insert(0, Waypoint(0.0, pts[0].x, pts[0].y))
    if pts[-1].t < seconds:
        pts.append(Waypoint(seconds, pts[-1].x, pts[-1].y))
    moving = [p for p in actor.path]
    yaw0 = heading_yaw(moving[0][1:3], moving[1][1:3]) if len(moving) > 1 else actor.yaw
    return pts, yaw0


def sequence_frames(frames: Path) -> Path:
    """Number the rendered frames 00001.png, 00002.png ... (hard links, so no copies) in ``frames/seq``: frame
    steps leave gaps in Blender's numbering, and Windows ffmpeg builds have no glob input."""
    seq = frames / "seq"
    if seq.exists():
        shutil.rmtree(seq)
    seq.mkdir()
    for i, f in enumerate(sorted(frames.glob("frame_*.png")), 1):
        dst = seq / f"{i:05d}.png"
        try:
            os.link(f, dst)
        except OSError:
            shutil.copyfile(f, dst)
    return seq


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
    ap.add_argument(
        "--film", default=str(FILM), help="the film folder (feature mode); default films/savannah"
    )
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--tts", choices=["chatterbox", "kokoro"], help="override the casting's engine")
    ap.add_argument("--no-render", action="store_true", help="build, mix and save the .blend only")
    ap.add_argument(
        "--stills", action="store_true", help="render one still per shot (framing check), no film"
    )
    ap.add_argument(
        "--at",
        default="",
        help="comma-separated seconds: render a still at each, through the shot on screen then (no film)",
    )
    a = ap.parse_args()
    t0 = time.time()
    film = Path(a.film)
    spec = load_scenes(film / "07_scenes.json")[a.scene]
    res, samples, step, device = QUALITY[a.quality]
    out = Path(a.out).resolve() / spec.id
    if out.exists():
        shutil.rmtree(out)
    (out / "voices").mkdir(parents=True)
    fps = a.fps

    # ---- voices and timing
    casting = json.loads((film / "06_voices.json").read_text(encoding="utf-8"))
    cast_voices = casting["cast"]
    items = []
    for i, ln in enumerate(spec.lines):
        c = cast_voices[ln.who]
        items.append(
            (
                ln.text,
                out / "voices" / f"{i:02d}_{ln.who}.wav",
                tts.VoiceSpec(
                    engine=a.tts or casting.get("engine", "kokoro"),
                    voice=c["voice"],
                    pitch=c["pitch"],
                    rate=c["rate"],
                    mood=ln.expr[0][1] if ln.expr else None,
                    ref_text=c.get("ref_text"),
                ),
            )
        )
    voice_info = tts.synthesize_batch(items)  # one Chatterbox load for the scene; cached lines are reused
    for ln, info in zip(spec.lines, voice_info, strict=True):
        print(
            f"  {ln.who:10s} {info['engine']:10s} {info['duration']:5.2f}s"
            + (" cached" if info.get("cached") else "")
            + (f" wer {info['wer']}" if "wer" in info else "")
            + (f" FALLBACK {info['fallback']}" if "fallback" in info else "")
        )
    takes = [(Path(info["path"]), float(info["duration"])) for info in voice_info]
    seconds = schedule(spec, [d for _, d in takes], continuity.actor_speeds(spec))
    n = int(round(seconds * fps)) + 1
    shots = cut_list(spec, seconds)
    if a.quality == "animatic":  # DESIGN_STAGE §7: no set-up holds longer than about 4 s
        shots = split_long(shots, seconds)
    tracks = expression_tracks(spec)
    cont_issues, _ = continuity.check_scene(spec, shots, seconds)

    # ---- set + cast
    lay = spec.layout
    layout = Layout(
        water=tuple(lay["water"]) if lay.get("water") else None,
        acacias=[tuple(x) for x in lay.get("acacias", [])],
        mounds=[tuple(x) for x in lay.get("mounds", [])],
        action=[tuple(x) for x in lay.get("action", [(0.0, 0.0, 4.0)])],
        reeds_at=float(lay.get("reeds_at", 90.0)),
        paths=[tuple(x) for x in lay.get("paths", [])],
        grass_density=float(lay.get("grass_density", 14.0)),
    )
    ops = savannah_set(layout, spec.tod)
    cont_issues += continuity.set_assets(spec, layout.seed)  # acacia crowns as built (DECISIONS #98)

    def prop_time(
        k_,
    ) -> float:  # [seconds, xyz] or {"line": i, "dt": s, "to": xyz} (timed off the voice take)
        if isinstance(k_, dict):
            ln_ = spec.lines[int(k_["line"])]
            return (ln_.start if k_.get("from") == "start" else ln_.end) + float(k_.get("dt", 0.0))
        return float(k_[0])

    def prop_to(k_) -> list:
        return list(k_["to"]) if isinstance(k_, dict) else list(k_[1])

    # simple props the set builder has no part for (the animatic's log and baobabs): primitives with a colour
    for k, pr in enumerate(lay.get("props", [])):
        pid = f"prop_{k}_{pr.get('name', pr['shape'])}"
        model = pr.get("model") or next(
            (m for m in ("baobab", "log") if pr.get("name", "").startswith(m)), None
        )
        if model and pr["shape"] == "cylinder":  # Stage 2 (owner 11-18): real models for the stand-ins
            make = {"baobab": baobab_ops, "log": log_ops}[model]
            ops += make(
                pid, pr["size"][2], pr["size"][0], 7 + k, location=pr["at"], rotation=pr.get("rot", [0, 0, 0])
            )
        else:
            ops += [
                {
                    "op": "create_primitive",
                    "id": pid,
                    "shape": pr["shape"],
                    "size": pr["size"],
                    "location": pr["at"],
                    "rotation": pr.get("rot", [0, 0, 0]),
                    "smooth": True,
                    "segments": 24,
                },
                {
                    "op": "set_material",
                    "targets": [pid],
                    "material": {"base_color": pr.get("color", "#6B5137"), "roughness": 0.9, "name": pid},
                },
            ]
        for prop_, key in (("location", "moves"), ("scale", "scales")):  # [[seconds, [x, y, z]], ...]
            if pr.get(key):
                ops.append(
                    {
                        "op": "insert_keyframes",
                        "target": pid,
                        "property": prop_,
                        "keys": [[1 + int(prop_time(k_) * fps), prop_to(k_), "BEZIER"] for k_ in pr[key]],
                    }
                )
    if lay.get("spring") and lay.get("water"):
        # the singing spring (SC 9's payoff): the water lights up from inside, grows, and throws a cool glow
        # on everyone around it, from the moment it bursts free
        wx, wy, wr = lay["water"]
        t_on = prop_time({**lay["spring"], "to": None})
        f_on, f_full = 1 + int(t_on * fps), 1 + int((t_on + 2.5) * fps)
        ops += [
            # a glowing pool that rises over the old trickle (a separate disc: keying a material's emission on
            # an embedded node tree doesn't work in the 5.x layered actions)
            {
                "op": "create_primitive",
                "id": "spring_pool",
                "shape": "cylinder",
                "size": [2 * wr * 1.05, 2 * wr * 1.05, 0.02],
                "location": [wx, wy, 0.03],
                "segments": 48,
                "smooth": True,
            },
            {
                "op": "set_material",
                "targets": ["spring_pool"],
                "material": {
                    "base_color": "#7FD8E6",
                    "roughness": 0.05,
                    "specular": 0.7,
                    "emission": "#7FE6F5",
                    "emission_strength": 1.1,
                    "name": "spring_water",
                },
            },
            {
                "op": "insert_keyframes",
                "target": "spring_pool",
                "property": "scale",
                "keys": [
                    [1, [0.02, 0.02, 1.0], "BEZIER"],
                    [f_on, [0.02, 0.02, 1.0], "BEZIER"],
                    [f_on + 6, [0.35, 0.35, 1.0], "BEZIER"],
                    [f_full, [1.0, 1.0, 1.0], "BEZIER"],
                ],
            },
            {
                "op": "add_light",
                "id": "spring_glow",
                "light_type": "point",
                "energy": 0.0,
                "color": "#A8F4FF",
                "size": wr,
                "location": [wx, wy, 0.6],
            },
            {
                "op": "insert_keyframes",
                "target": "spring_glow",
                "property": "light.energy",
                "keys": [[1, 15.0, "BEZIER"], [f_on, 15.0, "BEZIER"], [f_full, 380.0, "BEZIER"]],
            },
        ]
    for j, fl in enumerate(lay.get("birds", [])):  # flocks crossing the sky (life in the set)
        ops += bird_flock_ops(
            f"birds{j}",
            tuple(fl["from"]),
            tuple(fl["to"]),
            fl["t0"],
            fl["t1"],
            fl.get("n", 5),
            fps,
            seed=3 + j,
        )
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
        # ---- performance: gaits/idles, eyelines and gestures, lip sync, expressions
        gaits, wps = {}, {}
        for cid, actor in spec.cast.items():
            pts, yaw0 = waypoints(actor, seconds)
            gaits[cid] = GAITS[actor.species].get(actor.gait) or GAITS[actor.species]["walk"]
            wps[cid] = (pts, yaw0)
            plans[cid] = plan_for(metas[cid], gaits[cid], pts, fps, yaw0)
        for cid, actor in spec.cast.items():  # riders sit on their mount's back (planned above)
            if actor.ride:
                mount = spec.cast[actor.ride]
                plans[cid] = ride_plan(metas[cid], plans[actor.ride], back_point(SPECIES[mount.species]))
        gestures = [
            Gesture(g.who, g.value, g.time(spec.lines), g.dur, g.target, g.amount) for g in spec.gestures
        ]
        # acting from the dialogue (the real takes): head beats on the stressed syllables, blinks at phrase
        # breaks, listeners blinking and nodding (production.acting); the spec's own gestures win
        spans = {c: [(a_.t_in, min(a_.t_out, seconds))] for c, a_ in spec.cast.items()}
        beats = acting.dialogue_beats(spec.lines, [tts.read_wav(w) for w, _ in takes], spans, gestures)
        gestures += beats.gestures
        anim: list[dict] = []
        for k, (cid, actor) in enumerate(spec.cast.items()):
            meta = metas[cid]
            pts, yaw0 = wps[cid]
            gaze = (
                gaze_track(cid, plans, spec.lines, gestures, fps, lens=(0.0, -1.0)) if spec.eyelines else None
            )
            rig = Rig(actor.species, meta.bone_dirs, meta.neck_bones, meta.trunk_bones, meta.ear_bones)
            mine = [g for g in gestures if g.who == cid]
            overlay = acting_layers(rig, plans[cid], gaze, mine, fps, targets=plans)
            keys, _ = walk_keys(
                meta,
                gaits[cid],
                pts,
                fps,
                1,
                seed=11 + k,
                yaw0=yaw0,
                plan=plans[cid],
                overlay=overlay,
                blinks=beats.blinks.get(cid),
            )
            cues = []
            for ln, (wav, _) in zip(spec.lines, takes):
                if ln.who == cid:
                    cs, _engine = lipsync.lipsync(wav, ln.text.replace("*", ""))
                    lead = ln.start - acting.LIP_LEAD_S  # the mouth lands a frame before the sound
                    cues += [
                        dataclasses.replace(c, start=max(0.0, c.start + lead), end=c.end + lead) for c in cs
                    ]
            anim += keys + face_keys(faces[cid], tracks[cid], cues or None, fps, 1, n)
        if anim:
            run(eng, "perform", anim)
        # water spray: drops leave the trunk tip during the firing part of the gesture and land on the target
        fx: list[dict] = []
        for j, g in enumerate(gg for gg in gestures if gg.kind == "trunk_spray"):
            m, tm = metas[g.who], metas[g.target]
            f0 = 1 + int((g.start + 0.32 * g.dur) * fps)
            f1 = 1 + int((g.start + 0.58 * g.dur) * fps)
            fr = list(range(f0, f1 + 1))
            tip = f"{m.rig}:{m.trunk_bones[-1]}"
            d = run(
                eng,
                f"spray{j}",
                [
                    {
                        "op": "inspect",
                        "subjects": [m.root, tm.root],
                        "frames": fr,
                        "bone_tails": [tip, f"{tm.rig}:head"],
                    }
                ],
            )["inspect"]["frames"]
            tips = {f: tuple(d[str(f)]["bone_tails"][tip]) for f in fr}
            head = tuple(d[str(f1)]["bone_tails"][f"{tm.rig}:head"])
            fx += spray_droplets(f"{g.who}{j}", tips, head, fps, n, seed=5 + j)
        if fx:
            run(eng, "fx", fx)

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
                # a single talking in a medium shot: if the face would be small in the frame (an upright
                # meerkat, a giraffe's head 3 m up, a tortoise), go in to a medium close-up so the mouth reads
                talking = any(
                    ln.who in sh.subjects
                    and not ln.offscreen
                    and ln.start < sh.end - 0.3
                    and ln.end > sh.start + 0.3
                    for ln in spec.lines
                )
                if sh.type == "ms" and len(sh.subjects) == 1 and talking:
                    c0 = sh.subjects[0]
                    sp0 = SPECIES[spec.cast[c0].species]
                    top = metas[c0].head_height + max(sp0.head_size) * 0.5
                    if max(sp0.head_size) / max(1.45 * top, 1.3 * metas[c0].length / 1.7778) < 0.24:
                        sh = dataclasses.replace(sh, type="mcu")
                        shots[i] = sh
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
            mid = (f0 + f1) // 2
            occ = []
            for c in spec.cast:
                if c in sh.subjects:
                    continue
                p = plans[c][min(len(plans[c]) - 1, mid - 1)]
                sp_ = SPECIES[spec.cast[c].species]
                top = metas[c].head_height + max(sp_.head_size) * 0.5
                # the body, and the head out in front of it (a zebra's head is a metre from its middle)
                ya = math.radians(p.yaw)
                hx, hy = sp_.head_at[0], sp_.head_at[1]
                head_xy = (
                    p.root[0] + hx * math.cos(ya) - hy * math.sin(ya),
                    p.root[1] + hx * math.sin(ya) + hy * math.cos(ya),
                )
                occ.append(Occluder(p.root[0], p.root[1], max(0.2, 0.25 * metas[c].length), top))
                occ.append(Occluder(*head_xy, max(sp_.head_size) * 0.6, top))
            cam = frame_shot(
                sh.type, subs, side=sh.side, aim_z=sh.look[2] if sh.look else None, occluders=occ
            )
            cid = f"cam_{i:02d}_{sh.type}"
            # every shot moves: a slow push-in with a small orbit round the aim (longer shots orbit further),
            # alternating sides shot to shot, eased in and out, so no shot is a locked-off still
            loc, aim = cam["location"], cam["aim"]
            end_loc = shot_move(loc, aim, sh.type, sh.end - sh.start, i)
            dist = math.dist(loc, aim)
            frame_h_m = 2 * dist * math.tan(vfov(cam["lens"]) / 2)  # vfov is in radians
            moved = math.dist(loc, end_loc)
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
                {
                    "op": "insert_keyframes",
                    "target": cid,
                    "property": "location",
                    "keys": [
                        [f0, [round(v, 4) for v in loc], "BEZIER"],
                        [max(f0 + 1, f1), [round(v, 4) for v in end_loc], "BEZIER"],
                    ],
                },
            ]
            # subjects' own travel in the shot (root positions at its first and last frame)
            sub_move = max(
                [
                    math.dist(
                        plans[c][min(len(plans[c]) - 1, f0 - 1)].root[:2],
                        plans[c][min(len(plans[c]) - 1, f1 - 1)].root[:2],
                    )
                    for c in sh.subjects
                ]
                + [0.0]
            )
            shot_report.append(
                {
                    "shot": i,
                    "type": sh.type,
                    "subjects": sh.subjects,
                    "from_behind": sh.from_behind,
                    "hold": sh.hold,
                    "start": sh.start,
                    "end": round(sh.end, 3),
                    "note": sh.note,
                    "frame_h_m": round(frame_h_m, 3),
                    "camera_move_frac": round(moved / max(frame_h_m, 1e-6), 3),
                    "subject_move_frac": round(sub_move / max(frame_h_m, 1e-6), 3),
                    "end_location": [round(v, 4) for v in end_loc],
                    **cam,
                }
            )
        run(eng, "cameras", cam_ops)
        # continuity on the real cameras: nobody off stage may be in a frame (head height over the root path)
        where = {
            c: [(p.root[0], p.root[1], metas[c].head_height) for p in plans[c]]
            for c, a_ in spec.cast.items()
            if a_.enter or a_.exit
        }
        cont_issues += continuity.check_frames(spec, shot_report, where, fps)
        # staging tangents on the real cameras: a farther animal's feet on a nearer one's back or shell
        roots = {c: [(p.root[0], p.root[1], p.yaw) for p in plans[c]] for c in spec.cast if c in plans}
        cont_issues += staging.staging_tangent(spec, shot_report, roots, fps)
        # a close or medium shot's subject seen from behind (the SC 9 climax: Kiki's back as the spring sings)
        cont_issues += staging.facing_away(spec, shot_report, roots, fps)
        for v in cont_issues:
            print(f"  CONTINUITY {v}")
        run(
            eng,
            "render-settings",
            [
                {
                    "op": "set_render",
                    "engine": ENGINE.get(a.quality, "cycles"),
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
        if a.stills or a.at:
            a.no_render = True
            still_ops = []
            picks = (
                [(r_, 1 + int((r_["start"] + r_["end"]) / 2 * fps)) for r_ in shot_report] if a.stills else []
            )
            for tt in [float(x) for x in a.at.split(",") if x.strip()]:
                r_ = [x for x in shot_report if x["start"] <= tt][-1]
                picks.append((r_, 1 + int(tt * fps)))
            for r_, mid in picks:
                cam_id = f"cam_{r_['shot']:02d}_{r_['type']}"
                still_ops.append(
                    {
                        "op": "render_preview",
                        "camera": cam_id,
                        "frame": mid,
                        "engine": "cycles",
                        "samples": samples,
                        "resolution": list(res),
                        "path": str(out / "stills" / f"shot_{r_['shot']:02d}_{r_['type']}_f{mid:04d}.png"),
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
    cue = next(c for c in composer.load_cue_sheet(film / "05_cue_sheet.json") if c.id == spec.cue)
    cue = dataclasses.replace(cue, seconds=seconds)  # re-timed to picture: the arrangement fits the bars
    rep = composer.render_cue(composer.arrange(cue), out / "music")
    music = composer._read(out / "music" / rep["wav"])
    amb = ambience.bed(
        spec.ambience.get("tod", spec.tod), seconds, water=bool(spec.ambience.get("water")), seed=7
    )

    # footsteps per species on every touchdown, placed from the camera on screen then (distance -> level,
    # side -> pan), heavier for faster gaits; calls and SFX panned toward whoever makes them
    def heard(t: float, xy: tuple[float, float]) -> tuple[float, float]:
        sh = next((r for r in reversed(shot_report) if r["start"] <= t), shot_report[0])
        cx, cy = sh["location"][0], sh["location"][1]
        ax, ay = sh["aim"][0] - cx, sh["aim"][1] - cy
        dn = math.hypot(ax, ay) or 1.0
        rx, ry = ay / dn, -ax / dn  # the camera's right
        dx, dy = xy[0] - cx, xy[1] - cy
        d = math.hypot(dx, dy) or 1.0
        return max(-0.85, min(0.85, (dx * rx + dy * ry) / d * 1.2)), min(1.0, 7.0 / (d + 3.0))

    force = {"trot": 1.3, "canter": 1.5, "fast_walk": 1.15, "scurry": 1.0}
    steps = np.zeros((int(seconds * sound.SR), 2), np.float32)
    nsteps = 0
    for cid, actor in spec.cast.items():
        if actor.path:
            plan = plans[cid]
            td, gains = [], []
            for i in range(1, len(plan)):
                for leg in plan[i].stance:
                    if plan[i].stance[leg] and not plan[i - 1].stance[leg]:
                        pan, g = heard(i / fps, plan[i].feet[leg][:2])
                        td.append((i / fps, pan))
                        gains.append(g)
            nsteps += len(td)
            steps += ambience.footsteps_track2(
                actor.species, td, seconds, seed=len(cid), gains=gains, force=force.get(actor.gait, 1.0)
            )
    sfx = []
    for j, b in enumerate(spec.sfx):
        t = b.time(spec.lines)
        pan, g = 0.0, 1.0
        if b.who in plans:
            p_ = plans[b.who][min(len(plans[b.who]) - 1, int(t * fps))]
            pan, g = heard(t, p_.root[:2])
            g = 0.45 + 0.55 * g
        sfx.append((t, ambience.sfx(b.value, seed=j, pan=pan) * g))
    mix, mrep = sound.mix_scene(seconds, voices, music, amb, steps, sfx)
    composer.write_wav(out / "mix.wav", mix)

    # ---- picture + sound
    report = {
        "scene": spec.id,
        "title": spec.title,
        "quality": a.quality,
        "seconds": seconds,
        "frames": n,
        "lines": [
            {
                "who": ln.who,
                "start": ln.start,
                "end": ln.end,
                "text": ln.text,
                **{k: v[k] for k in ("engine", "heard", "wer", "tries", "fallback") if k in v},
            }
            for ln, v in zip(spec.lines, voice_info, strict=True)
        ],
        "shots": shot_report,
        "cue": {k: rep[k] for k in ("id", "bpm", "bars", "moods", "programs", "engine")},
        "footsteps": nsteps,
        "sound": mrep,
        "warnings": spec.warnings,
        "continuity": [str(v) for v in cont_issues],
        "render_seconds": render_s,
        "wall_seconds": None,
    }
    if not a.no_render:
        mp4 = out / f"{spec.id}.mp4"
        seq = sequence_frames(out / "frames")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-framerate",
                str(fps / step),
                "-i",
                str(seq / "%05d.png"),
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
