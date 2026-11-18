"""Rig stress test (DESIGN_STAGE.md §5): one take that exercises the whole rig, measured and rendered.

    python scripts/rig_stress_test.py kiki            # -> output/rig-stress/kiki/{report.json, motion.mp4}
    python scripts/rig_stress_test.py --all --no-render

The take (13-17 s at 24 fps): standing (the meerkat in her sentinel), a walk, a turn of up to 90 degrees, a stop (the
meerkat drops to all fours to walk and rises again when she stops: her sit/stand; the other rigs have no sit pose,
so they bow and come back up instead), head turns left and right, every expression in turn, blinks from the idle
layer, and a lip-synced line in the character's voice with its emotional beats and a nod after it.

Measured on the deformed rig in Blender, every third frame (eyes, lids, brows, mouth) or every frame (feet):

* ``eye_socket``: each eye stays 50-80 % deep and does not drift in its socket (``creatures.qa``);
* ``brow_float`` / ``lid_float`` / ``mouth_float``: no face part leaves the skin;
* ``part_float``: ears, mane, ossicones, muzzle and nose touch what they grow from (``creatures.qa.part_seating``);
* ``texture_swim``: the coat pattern is pinned to the rest pose;
* ``foot_slide``: a planted foot drifts less than :data:`SLIDE_MAX` of the leg, measured on the deformed skin (each
  foot's sole: the lowest skin under its lower-leg bone tip, followed frame to frame), and at least one planted foot-frame pair was
  measured (zero pairs fails: it would otherwise read as perfect);
* ``foot_plant``: over a whole stance phase the sole strays less than :data:`PLANT_MAX` of the foot's radius
  from where it landed (a rigid hoof that rocks about its fetlock skates by its height times the leg's sweep);
* ``ground``: no foot sinks into the ground;
* ``sentinel_tail`` (meerkat): the tail tip reaches the ground in the sentinel (the tripod).

Not measured: mesh-mesh intersections in general (only the face parts' contact and the feet against the ground).
The report's ``checks`` feed the rubric (``animatica.design.rubric.score(..., stress=report)``).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from creature_face_test import CAST as LINES  # noqa: E402
from creature_walk_test import set_ops  # noqa: E402

from animatica.audio import lipsync, tts  # noqa: E402
from animatica.core.engine import BlenderSession  # noqa: E402
from animatica.creatures.build import build_creature  # noqa: E402
from animatica.creatures.face import BROW_COLOR, face_keys, face_ops, refresh_rest  # noqa: E402
from animatica.creatures.gait import GAITS, LEGS, Waypoint, planted_drift, planted_travel  # noqa: E402
from animatica.creatures.gesture import Gesture, Rig, acting_layers  # noqa: E402
from animatica.creatures.perform import plan_for, walk_keys  # noqa: E402
from animatica.creatures.qa import part_seating, rig_checks, rig_probe  # noqa: E402
from animatica.creatures.species import CAST, SPECIES  # noqa: E402
from animatica.design.fingerprint import fingerprint  # noqa: E402

FPS = 24
SLIDE_MAX = 0.04  # share of the leg length a planted foot may drift
PLANT_MAX = 0.5  # share of the foot's radius a sole may stray over one stance phase (soft)
SINK_MAX = 0.03  # share of the leg length a foot may sink below its rest height
STAND, WALK, TURN = 0.8, 2.8, 1.4  # seconds
MAX_TURN_S = 4.0  # longest the turn may take
EXPR_EACH = 0.4  # seconds per expression in the expression run


def _smooth(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def choreography(meta: Any, species: str) -> dict[str, Any]:
    """Waypoints, gaze, gestures, expression track and the line's timing for the take."""
    gait = GAITS[species]["walk"]
    v = gait.nominal_speed(meta.leg)
    d1 = v * WALK * 0.8
    # the turn: an arc to the right (toward the camera's side, so the face is on camera after it), on a radius of
    # at least half the body (the planner steps only as the body travels, so a tighter arc is a turn in place on
    # planted feet), up to 90 degrees within MAX_TURN_S. The tortoise walks 3.6 cm/s: in that time she manages
    # about 18 degrees (turning on the spot is not planned)
    r = 0.5 * meta.length
    ang = min(math.pi / 2, MAX_TURN_S * 0.8 * v / r)
    turn_s = max(TURN, ang * r / (0.8 * v))
    t_walk = STAND
    t_turn = t_walk + WALK
    t_stop = t_turn + turn_s
    arc = [
        Waypoint(t_turn + turn_s * u, d1 + r * math.sin(u * ang), -r * (1 - math.cos(u * ang)), glide=u < 1)
        for u in (0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0)
    ]
    # one move, walk straight into the turn and stop at its end (glide points: no stop at the corner)
    pts = [Waypoint(0.0, 0.0, 0.0), Waypoint(t_walk, 0.0, 0.0), Waypoint(t_turn, d1, 0.0, glide=True), *arc]
    order = ["neutral", "happy", "sad", "surprised", "worried", "determined", "curious", "scared", "proud"]
    t_expr = t_stop + 0.4
    track = [(t_expr + i * EXPR_EACH, e) for i, e in enumerate(order)]
    t_line = t_expr + len(order) * EXPR_EACH + 0.3
    _name, _text, _voice, beats = LINES[species]
    track += [(t_line + t, e) for t, e in beats]
    # head turns during the expression run: left, then right
    turns = [(t_expr + 0.2, 1.0, 35.0), (t_expr + 1.6, 1.0, -35.0)]
    gestures = [Gesture(species, "nod", 0.0, 0.9)]  # placed after the line once its length is known
    if SPECIES[species].default_pose != "sentinel":  # no sit pose on these rigs: a bow and back up
        gestures.append(Gesture(species, "head_duck", t_stop - 0.2, 1.4, amount=0.6))
    return {
        "points": pts,
        "track": track,
        "line_start": t_line,
        "turns": turns,
        "gestures": gestures,
        "times": {"walk": t_walk, "turn": t_turn, "stop": t_stop, "expressions": t_expr, "line": t_line},
        "turn_degrees": round(math.degrees(ang)),
    }


def gaze_curve(turns: list[tuple[float, float, float]], n: int) -> list[float]:
    out = []
    for k in range(n):
        t = k / FPS
        a = 0.0
        for start, dur, deg in turns:
            e = _smooth((t - start) / 0.3) * (1 - _smooth((t - start - dur) / 0.3))
            a += deg * e
        out.append(a)
    return out


def camera_ops(plan: list, heads: list, size: float, sp: Any, ch: dict[str, Any]) -> list[dict[str, Any]]:
    """A wide, lagging three-quarter shot for the walk and turn; after the stop, a dolly into a three-quarter
    close-up on the head (as in the face test) for the head turns, the expressions and the line."""
    n = len(plan)
    # the close-up: from the measured head at the end of the stop, 25 degrees off the final facing, to the
    # stage camera's side (-Y)
    k_set = min(n - 1, int(round((ch["times"]["stop"] + 0.6) * FPS)))
    hx, hy, hz = heads[k_set]
    yaw = math.radians(plan[k_set].yaw)
    fx, fy = math.sin(yaw), -math.cos(yaw)
    cands = []
    for s in (1, -1):
        a = math.radians(25 * s)
        cands.append((fx * math.cos(a) - fy * math.sin(a), fx * math.sin(a) + fy * math.cos(a)))
    dx, dy = min(cands, key=lambda d: d[1])
    hs = max(sp.head_size) * (3.6 if sp.name == "giraffe" else 3.2)
    # the face test's distance; the meerkat gets more room, since she rises into the sentinel during the dolly
    far = 2.3 if sp.default_pose == "sentinel" else 1.8
    drop = hs * 0.12 if sp.default_pose == "sentinel" else 0.0  # aim below the head: her head rises
    close = [hx + dx * hs * far, hy + dy * hs * far, hz + hs * 0.05]
    wide_d = size * 2.4
    aim_wide = max(heads[0][2] * 0.6, size * 0.25)
    cx, cy = plan[0].root[0], plan[0].root[1]
    cam, aim = [], []
    t0 = ch["times"]["stop"]
    for k, p in enumerate(plan):
        cx += (p.root[0] - cx) * 0.06
        cy += (p.root[1] - cy) * 0.06
        w = _smooth((k / FPS - t0) / 1.4)
        wide_c = [cx + wide_d * 0.5, cy - wide_d, size * 0.45]
        wide_a = [cx, cy, aim_wide]
        # the close aim follows the head softly (it turns and nods; the frame should not)
        ha = heads[k]
        close_a = [hx * 0.7 + ha[0] * 0.3, hy * 0.7 + ha[1] * 0.3, hz * 0.7 + ha[2] * 0.3 - drop]
        cam.append([k + 1, [round(a + (b - a) * w, 3) for a, b in zip(wide_c, close)], "LINEAR"])
        aim.append([k + 1, [round(a + (b - a) * w, 3) for a, b in zip(wide_a, close_a)], "LINEAR"])
    return [
        {"op": "create_empty", "id": "cam_aim", "location": aim[0][1]},
        {"op": "add_camera", "id": "cam", "location": cam[0][1], "lens": 40, "look_at": "cam_aim"},
        {"op": "set_camera_active", "id": "cam", "frame": 1},
        {"op": "insert_keyframes", "target": "cam", "property": "location", "keys": cam},
        {"op": "insert_keyframes", "target": "cam_aim", "property": "location", "keys": aim},
    ]


def voice_line(species: str, out: Path) -> tuple[Path, list, float, str]:
    """The character's line: Kokoro when available, else the face test's recorded line (output/faces)."""
    _name, text, voice, _beats = LINES[species]
    wav = out / "line.wav"
    try:
        info = tts.synthesize(text, wav, voice)
        dur = float(info["duration"])
    except Exception as e:  # noqa: BLE001 - no TTS on this machine: reuse the face test's take
        old = ROOT / "output" / "faces" / species / "line.wav"
        if not old.exists():
            raise SystemExit(f"no TTS ({e}) and no recorded line at {old}") from e
        shutil.copy(old, wav)
        import wave

        with wave.open(str(wav)) as w:
            dur = w.getnframes() / w.getframerate()
    cues, engine = lipsync.lipsync(wav, text)
    return wav, cues, dur, engine


def skin_feet(meta: Any, sp: Any, ids: set[Any], plan: list[Any]) -> list[dict[str, Any]]:
    """``inspect`` skin-foot probes, one per leg: the sole (the lowest skin within reach of the lower-leg bone
    tip, on the body mesh and the leg's separate hoof or pad where it has one), chosen at the leg's first planted
    frame so a raised paw (the meerkat's sentinel) doesn't pick up the belly under it. The reach stays under half
    the distance to the nearest other foot."""
    _shape, fr, fh = sp.foot
    spacing = min(2 * sp.fore_foot[0], 2 * sp.hind_foot[0], abs(sp.hind_foot[1] - sp.fore_foot[1]))
    radius = round(min(2.0 * fr + fh, 0.45 * spacing), 4)
    out = []
    for leg in LEGS:
        first = next((k + 1 for k, p in enumerate(plan) if p.stance[leg]), 1)
        meshes = [f"{meta.cid}_body"] + [m for m in (f"{meta.cid}_foot_{leg}",) if m in ids]
        out.append(
            {
                "id": leg,
                "bone": f"{meta.rig}:leg_{leg}_lo",
                "meshes": meshes,
                "k": 24,
                "radius": radius,
                "pick": "sole",
                "ref_frame": first,
            }
        )
    return out


def _check(cid: str, passed: bool, message: str, value: Any = None, hard: bool = True) -> dict[str, Any]:
    return {"id": cid, "passed": bool(passed), "hard": hard, "message": message, "value": value}


def run(
    character: str,
    out: Path,
    render: bool,
    res: tuple[int, int],
    samples: int,
    stills: list[int] | None = None,
) -> dict[str, Any]:
    species = CAST[character]
    sp = SPECIES[species]
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    ops, meta = build_creature(species, sp, at=(0.0, 0.0), yaw=90.0)
    fops, face = face_ops(species, sp, meta.root, meta.rig, BROW_COLOR[species])
    ch = choreography(meta, species)
    wav, cues, dur, lip_engine = voice_line(species, out)
    t_end = ch["line_start"] + dur + 1.6
    pts = ch["points"] + [Waypoint(t_end, ch["points"][-1].x, ch["points"][-1].y)]
    gait = GAITS[species]["walk"]
    plan = plan_for(meta, gait, pts, FPS, 90.0)
    n = len(plan)
    for g in ch["gestures"]:
        if g.kind == "nod":
            g.start = ch["line_start"] + dur + 0.15
    rig = Rig(species, meta.bone_dirs, meta.neck_bones, meta.trunk_bones, meta.ear_bones)
    overlay = acting_layers(rig, plan, gaze_curve(ch["turns"], n), ch["gestures"], FPS)
    keys, plan = walk_keys(meta, gait, pts, FPS, 1, seed=7, yaw0=90.0, plan=plan, overlay=overlay)
    size = max(meta.length, meta.head_height)
    if sp.default_pose == "sentinel":
        size = max(size, (meta.body_z + 0.75 * meta.length) * 1.25)
    scene = set_ops(size / 1.6, size) + [{"op": "set_frame_range", "start": 1, "end": n, "fps": FPS}]
    report: dict[str, Any] = {
        "character": character,
        "species": species,
        "frames": n,
        "seconds": round(n / FPS, 2),
        "timeline": {k: round(v, 2) for k, v in ch["times"].items()}
        | {"line_end": round(ch["line_start"] + dur, 2)},
        "expressions": [e for _t, e in ch["track"]],
        "line": LINES[species][1],
        "lipsync": lip_engine,
        "turn_degrees": ch["turn_degrees"],
        "sit_stand": "sentinel drop and rise"
        if sp.default_pose == "sentinel"
        else "bow and rise (no sit pose)",
    }
    with BlenderSession(workdir=out) as eng:

        def batch(bid: str, b: list[dict]) -> dict:
            r = eng.run_batch({"batch_id": bid, "ops": b})
            if not r.ok:
                raise SystemExit(json.dumps({"batch": bid, "errors": r.errors[:5]}, indent=1))
            return r.data

        batch("set", scene)
        batch("creature", ops + fops)
        q = batch(
            "q", [{"op": "query", "ids": [b["id"] for b in face["brows"].values()], "fields": ["transform"]}]
        )
        refresh_rest(face, q["objects"])
        fkeys = face_keys(face, ch["track"], cues, FPS, 1, n, line_start=ch["line_start"])
        batch("anim", keys + fkeys)
        # face parts, eyes and coat: every third frame
        parts = part_seating(
            meta, [ex.id for ex in sp.extras] + (["mane"] if sp.mane else []), bool(sp.muzzle)
        )
        probe = rig_probe(meta, list(range(1, n + 1, 3)), parts=parts)
        surf = (
            f"{meta.cid}_muzzle"
            if sp.muzzle
            else (f"{meta.cid}_head" if sp.separate_head else f"{meta.cid}_body")
        )
        probe["seating"].append({"target": face["mouth"], "surface": surf, "kind": "skin"})
        rep = batch("probe", [probe])["inspect"]
        issues, summary = rig_checks(rep, character, parts)
        # feet (and the sentinel's tail tip): every frame
        head = f"{meta.rig}:head"
        tails = [f"{meta.rig}:leg_{leg}_lo" for leg in LEGS] + [f"{meta.rig}:{meta.tail_bones[-1]}", head]
        fr = batch(
            "feet",
            [
                {
                    "op": "inspect",
                    "subjects": [meta.root],
                    "frames": list(range(1, n + 1)),
                    "bone_tails": tails,
                    "skin_feet": skin_feet(meta, sp, {o.get("id") for o in ops}, plan),
                }
            ],
        )["inspect"]["frames"]
        batch("cam", camera_ops(plan, [fr[str(k + 1)]["bone_tails"][head] for k in range(n)], size, sp, ch))
        for f in stills or []:  # cheap Workbench looks at chosen frames (CPU review of a pose)
            batch(
                f"still{f}",
                [
                    {
                        "op": "render_preview",
                        "path": str(out / "stills" / f"{character}_{f:04d}.png"),
                        "frame": f,
                        "camera": "auto",
                        "resolution": list(res),
                    }
                ],
            )
        if render:
            batch(
                "rs",
                [
                    {
                        "op": "set_render",
                        "engine": "cycles",
                        "resolution": list(res),
                        "samples": samples,
                        "fps": FPS,
                        "device": "optix",
                        "look": "AgX - Medium High Contrast",
                    }
                ],
            )
            batch("render", [{"op": "render_final", "output_dir": str(out / "frames")}])
    # --- checks
    checks: list[dict[str, Any]] = []
    by_kind: dict[str, list[str]] = {}
    for iss in issues:
        if (
            face["mouth"] in iss.message
        ):  # qa files every non-brow face part under lid_float: the mouth is its own check
            continue
        by_kind.setdefault(iss.check, []).append(iss.message)
    for kind, hard in (
        ("eye_socket", True),
        ("brow_float", False),
        ("lid_float", False),
        ("part_float", True),
        ("texture_swim", True),
    ):
        msgs = by_kind.get(kind, [])
        checks.append(_check(kind, not msgs, "; ".join(msgs) or f"{kind.replace('_', ' ')}: ok", hard=hard))
    # the mouth changes size with its shapes (an "O" is narrow), so measure its gap against its largest size
    pairs = [
        (v["gap"], v["size"])
        for f in rep["frames"].values()
        for t, v in (f.get("seating") or {}).items()
        if t == face["mouth"] and "gap" in v
    ]
    biggest = max((sz for _g, sz in pairs), default=1.0)
    gaps = [g / max(biggest, 1e-6) for g, _sz in pairs]
    mouth_gap = max(gaps, default=0.0)
    summary["mouth_gap_range"] = [round(min(gaps), 3), round(max(gaps), 3)] if gaps else None
    checks.append(
        _check(
            "mouth_float",
            mouth_gap <= 0.12,
            f"mouth off the skin by {mouth_gap:.0%} of its size",
            mouth_gap,
            False,
        )
    )
    sink = 0.0
    for leg in LEGS:
        ref = f"{meta.rig}:leg_{leg}_lo"
        for i in range(1, n):
            if plan[i].stance[leg]:
                sink = max(sink, meta.foot_z - fr[str(i + 1)]["bone_tails"][ref][2])
    # foot slide on the deformed skin (the IK-pinned bone tail only proves the IK reached its target; review
    # 11-17 21:36); the bone's drift is kept in the summary for comparison
    stance = [p.stance for p in plan]
    bone_feet = [
        {leg: fr[str(k + 1)]["bone_tails"][f"{meta.rig}:leg_{leg}_lo"] for leg in LEGS} for k in range(n)
    ]
    skin = [fr[str(k + 1)].get("skin_feet") or {} for k in range(n)]
    if all(skin[k].get(leg, {}).get("n") for k in range(n) for leg in LEGS):
        feet = [{leg: skin[k][leg]["c"] for leg in LEGS} for k in range(n)]
        summary["foot_slide_source"] = "skin"
    else:  # an older adapter or no skin near a foot: fall back to the bone and say so
        feet = bone_feet
        summary["foot_slide_source"] = "bone"
    drift = planted_drift(stance, feet)
    slide, pairs = float(drift["drift"]), int(drift["pairs"])
    summary["foot_slide"] = {k: round(v, 5) if isinstance(v, float) else v for k, v in drift.items()}
    bone_drift = planted_drift(stance, bone_feet)
    summary["foot_slide_bone"] = {
        k: round(v, 5) if isinstance(v, float) else v for k, v in bone_drift.items()
    }
    # zero stance pairs is "never measured", not "perfect": fail it (review 11-17 18:36)
    checks.append(
        _check(
            "foot_slide",
            pairs > 0 and slide <= SLIDE_MAX * meta.leg,
            (
                f"worst planted-foot drift ({summary['foot_slide_source']}) {slide * 1000:.1f} mm per frame"
                f" ({drift['leg']} at frame {drift['frame']};"
                f" limit {SLIDE_MAX * meta.leg * 1000:.0f} mm) over {pairs} planted foot-frame pairs"
                if pairs
                else "no foot stayed planted for two frames: foot slide was not measured"
            ),
            round(slide, 4),
        )
    )
    # the whole stance phase: a sole may creep under the per-frame limit, or a rigid hoof rock about its fetlock
    travel = planted_travel(stance, feet)
    summary["foot_plant"] = {k: round(v, 5) if isinstance(v, float) else v for k, v in travel.items()}
    plant_max = PLANT_MAX * sp.foot[1]
    checks.append(
        _check(
            "foot_plant",
            int(travel["phases"]) > 0 and float(travel["travel"]) <= plant_max,
            (
                f"a planted sole ({summary['foot_slide_source']}) strays up to {float(travel['travel']) * 1000:.1f} mm"
                f" within one stance ({travel['leg']}, frames {travel['start']}-{travel['end']}; limit"
                f" {plant_max * 1000:.0f} mm, half the foot's radius) over {travel['phases']} stance phases"
                if travel["phases"]
                else "no stance phase lasted two frames: foot plant was not measured"
            ),
            round(float(travel["travel"]), 4),
        )
    )
    checks.append(
        _check(
            "ground",
            sink <= SINK_MAX * meta.leg,
            f"feet sink up to {max(0.0, sink) * 1000:.1f} mm below their rest height (limit {SINK_MAX * meta.leg * 1000:.0f} mm)",
            round(sink, 4),
        )
    )
    if sp.default_pose == "sentinel":
        tip = f"{meta.rig}:{meta.tail_bones[-1]}"
        stood = [k for k in range(1, n + 1) if plan[k - 1].sentinel > 0.95]
        z = min(fr[str(k)]["bone_tails"][tip][2] for k in stood) if stood else 1.0
        checks.append(
            _check(
                "sentinel_tail",
                z <= 0.02 + meta.foot_z,
                f"in the sentinel the tail tip comes down to {z * 1000:.0f} mm (the tripod wants the ground)",
                round(z, 4),
            )
        )
    # where each face part is furthest off the skin: the frame and the expression showing then
    worst: dict[str, tuple[float, int]] = {}
    for fk, f in rep["frames"].items():
        for t, v in (f.get("seating") or {}).items():
            if "gap" in v and t != face["mouth"]:
                g = v["gap"] / max(v["size"], 1e-6)
                if g > worst.get(t, (-9.0, 0))[0]:
                    worst[t] = (g, int(fk))

    def showing(frame: int) -> str:
        t = (frame - 1) / FPS
        return max((x for x in ch["track"] if x[0] <= t), key=lambda x: x[0], default=(0.0, "neutral"))[1]

    summary["worst_gap"] = {
        t: {"gap": round(g, 3), "frame": k, "expression": showing(k)} for t, (g, k) in worst.items()
    }
    report["summary"] = summary
    report["checks"] = checks
    # ties the report to the design it measured: the rubric fails a report about other parameters (#68)
    report["fingerprint"] = fingerprint(sp)
    report["passed"] = all(c["passed"] for c in checks if c["hard"])
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    # the design record: the rubric reads it on the next sheet score (scripts/design_sheet.py)
    record = ROOT / "design" / character / "rig_stress.json"
    record.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    if render:
        mp4 = out / "motion.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(out / "frames" / "frame_%04d.png"),
            ]
            + ["-itsoffset", str(round(ch["line_start"], 3)), "-i", str(wav)]
            + ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p"]
            + ["-af", "apad", "-c:a", "aac", "-b:a", "128k", "-shortest", str(mp4)],
            check=True,
        )
        report["video"] = str(mp4)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("characters", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "output" / "rig-stress"))
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--res", default="960x540")
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--stills", default="", help="comma-separated frames to render as Workbench previews")
    a = ap.parse_args()
    names = list(CAST) if a.all else a.characters
    if not names:
        ap.error("name a character or pass --all")
    w, h = (int(v) for v in a.res.split("x"))
    ok = True
    for ch in names:
        stills = [int(f) for f in a.stills.split(",") if f.strip()]
        rep = run(ch, Path(a.out) / ch, not a.no_render, (w, h), a.samples, stills)
        ok &= rep["passed"]
        print(
            json.dumps(
                {
                    "character": ch,
                    "passed": rep["passed"],
                    "checks": {c["id"]: c["passed"] for c in rep["checks"]},
                }
            )
        )
        for c in rep["checks"]:
            if not c["passed"]:
                print("  FAIL", c["id"], c["message"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
