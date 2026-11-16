"""Camera & Lighting: one camera per shot (cut with timeline markers), framed geometrically, plus a
lighting rig and world per time of day.

Framing: shot type sets how much of the frame the subject fills; distance follows from the lens FOV.
Rule of thirds: the aim point is offset so the subject sits on a third line with look-room in the
direction it faces. Moves (dolly/pan/orbit/crane/track) are keyed on the camera and on an aim empty
the camera tracks, so artists can tweak either in Blender.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ..core.llm import scripted
from ..knowledge import lookup
from .asset import sun_direction
from .base import Agent

if TYPE_CHECKING:
    from ..core.orchestrator import Context

SYSTEM = """You are the Cinematographer/Lighting lead. For each shot choose camera parameters.
Return JSON {"shots": {"<id>": {"azimuth": -60..60 (degrees, 0 = camera in front of the stage on -Y),
"height": 0.3..3 (m), "lens": 24..85, "fill": 0.2..0.9 (fraction of frame height the subject fills),
"move": one of [static, dolly_in, dolly_out, pan, orbit, crane_up, track]}},
"lighting": {"key_energy": 0.5..8, "fill_energy": 0..400, "rim_energy": 0..600, "world_strength": 0.1..2,
"exposure": -2..2}}"""

SENSOR_W = 36.0
ASPECT = 16 / 9

DEFAULTS = {
    "wide": {"azimuth": -8, "height": 1.5, "lens": 30, "fill": 0.4},
    "medium": {"azimuth": 18, "height": 1.15, "lens": 40, "fill": 0.55},
    "closeup": {"azimuth": 42, "height": 1.15, "lens": 55, "fill": 0.6},
}
VIEWPORT_TINT = {"night": "#6E7FB4"}  # Workbench-only grade (Cycles is lit by the night rig)
SKY_GLOW = {"sunset": "#C8607A", "dawn": "#E8A0B8", "day": "#8EC5F0", "night": "#16224A"}
LIGHTING = {
    "sunset": {
        "key_energy": 4.0,
        "fill_energy": 220,
        "rim_energy": 300,
        "world_strength": 1.4,
        "exposure": 0.0,
    },
    "dawn": {
        "key_energy": 3.5,
        "fill_energy": 220,
        "rim_energy": 250,
        "world_strength": 1.3,
        "exposure": 0.0,
    },
    "day": {
        "key_energy": 4.5,
        "fill_energy": 150,
        "rim_energy": 150,
        "world_strength": 1.0,
        "exposure": -0.3,
    },
    "night": {
        "key_energy": 0.6,
        "fill_energy": 120,
        "rim_energy": 250,
        "world_strength": 0.35,
        "exposure": 0.4,
    },
}


@scripted("camera.plan")
def _scripted_camera(payload: dict[str, Any]) -> dict[str, Any]:
    plan = payload["plan"]
    shots = {}
    for i, s in enumerate(plan["shots"]):
        d = dict(DEFAULTS[s["type"]])
        if s["beat"] == "settle":
            d["azimuth"] = -22
        if i > 0 and plan["shots"][i - 1]["type"] == s["type"]:
            d["azimuth"] = -d["azimuth"]  # avoid jump cuts between same-size shots
        d["move"] = s.get("camera_move", "static")
        shots[s["id"]] = d
    return {"shots": shots, "lighting": dict(LIGHTING[plan["setting"]["time_of_day"]])}


def _hfov(lens: float) -> float:
    return 2 * math.atan(SENSOR_W / 2 / lens)


def _vfov(lens: float) -> float:
    return 2 * math.atan(SENSOR_W / ASPECT / 2 / lens)


def frame_shot(
    subject_center: tuple[float, float, float],
    subject_h: float,
    subject_w: float,
    cam: dict[str, Any],
    facing: float = 1.0,
    thirds: bool = True,
) -> tuple[list[float], list[float]]:
    """Return (camera_location, aim_point) so the subject fills ``fill`` of the frame."""
    lens, fill = cam["lens"], cam["fill"]
    need_h = subject_h / fill
    need_w = subject_w / min(0.95, fill * 1.4)
    dist = max(need_h / 2 / math.tan(_vfov(lens) / 2), need_w / 2 / math.tan(_hfov(lens) / 2))
    az = math.radians(cam["azimuth"])
    cx, cy, cz = subject_center
    horiz = math.sqrt(max(dist**2 - (cam["height"] - cz) ** 2, 0.25))
    loc = [cx + horiz * math.sin(az), cy - horiz * math.cos(az), cam["height"]]
    aim = [cx, cy, cz]
    if thirds:
        frame_w = 2 * dist * math.tan(_hfov(lens) / 2)
        right = (math.cos(az), math.sin(az))  # camera right vector on the ground plane
        shift = (
            facing * frame_w / 6
        )  # aim right of the subject when it looks right -> subject on the left third
        aim = [cx + right[0] * shift, cy + right[1] * shift, cz]
    return [round(v, 3) for v in loc], [round(v, 3) for v in aim]


class CameraLighting(Agent):
    role = "camera"
    task = "camera.plan"
    system_prompt = SYSTEM

    def plan_cameras(self, ctx: Context) -> dict[str, Any]:
        out = self.ask(
            ctx,
            {
                "plan": ctx.plan.model_dump(mode="json"),
                "knowledge": lookup(f"{ctx.plan.setting.time_of_day} lighting shot sizes framing moves"),
            },
        )
        for sid, adj in ctx.state.tuning.get("camera", {}).items():  # critic-driven corrections
            if sid in out.get("shots", {}):
                for k, v in adj.items():
                    if k == "fill_mul":
                        out["shots"][sid]["fill"] = round(out["shots"][sid]["fill"] * v, 3)
                    elif k == "azimuth_add":
                        out["shots"][sid]["azimuth"] += v
                    else:
                        out["shots"][sid][k] = v
        for k, v in ctx.state.tuning.get("lighting", {}).items():
            out.setdefault("lighting", {})[k] = v
        return out

    def lighting_ops(self, ctx: Context, L: dict[str, Any]) -> list[dict[str, Any]]:
        plan = ctx.plan
        tod = plan.setting.time_of_day
        pal = plan.style.palette
        sx, sy, sz = sun_direction(tod)
        # sun light rotation: light travels along -sun_dir
        az = math.degrees(math.atan2(-sx, sy))
        elev = math.degrees(math.asin(sz))
        ops: list[dict[str, Any]] = [
            {
                "op": "set_world",
                "zenith": pal.sky_zenith,
                "horizon": pal.sky_horizon,
                "ground": pal.ground,
                "glow": SKY_GLOW.get(tod),
                "strength": L.get("world_strength", 1.0),
                # the flat-colour Workbench preview has no lights: grade it so night reads as night
                **({"viewport_tint": VIEWPORT_TINT[tod]} if tod in VIEWPORT_TINT else {}),
            },
            {
                "op": "add_light",
                "id": "light_key",
                "light_type": "sun",
                "energy": L.get("key_energy", 4.0),
                "color": pal.sun,
                "rotation": [round(90 - elev, 2), 0, round(az, 2)],
                "size": 0.08,
                "tags": ["light"],
            },
            {
                "op": "add_light",
                "id": "light_fill",
                "light_type": "area",
                "energy": L.get("fill_energy", 200),
                "color": "#C9D6FF" if tod in ("sunset", "night") else "#FFF1DD",
                "size": 4.0,
                "location": [2.5, -5.0, 3.2],
                "rotation": [55, 0, 25],
                "tags": ["light"],
            },
            {
                "op": "add_light",
                "id": "light_rim",
                "light_type": "area",
                "energy": L.get("rim_energy", 250),
                "color": pal.sun if tod != "night" else "#A9C2FF",
                "size": 2.5,
                "location": [-2.0, 3.5, 2.8],
                "rotation": [-55, 0, -30],
                "tags": ["light"],
            },
            {"op": "set_render", "exposure": L.get("exposure", 0.0), "look": "AgX - Medium High Contrast"},
        ]
        return ops

    def run(
        self, ctx: Context, asset_info: dict[str, Any], anim_notes: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        plan = ctx.plan
        cp = self.plan_cameras(ctx)
        L = cp.get("lighting", LIGHTING[plan.setting.time_of_day])
        self.submit(ctx, self.batch(f"Light the scene: {plan.style.lighting}", self.lighting_ops(ctx, L)))

        frames = plan.shot_frames()
        fps = plan.fps
        hero_h = asset_info.get("hero_height", 1.5)
        head_z = asset_info.get("head_z", 1.1)
        prop_h = asset_info.get("prop_height", 0.5)
        prop_x = plan.prop.location[0] if plan.prop else 1.3
        stand_x = (anim_notes or {}).get("stand_x", prop_x - 0.95)
        ops: list[dict[str, Any]] = []
        x_track = (anim_notes or {}).get("root_x")  # callable time->x, when available
        singles: list[str] = []  # dialogue singles: the addressee is intentionally out of frame
        ctx.state.artifacts["single_shots"] = singles
        for _i, shot in enumerate(plan.shots):
            c = dict(DEFAULTS[shot.type])
            c.update(cp["shots"].get(shot.id, {}))
            move = c.get("move", shot.camera_move)
            f0, f1 = frames[shot.id]
            _t0, _t1 = (f0 - 1) / fps, f1 / fps
            hx0 = x_track((f0 - 1) / fps) if x_track else stand_x
            hx1 = x_track(f1 / fps) if x_track else stand_x
            if shot.beat == "exit":
                hx1 = hx0  # the camera holds on where the hero stood; the hero leaves the frame
            two_shot = False
            if shot.type == "closeup" and shot.beat == "speak" and plan.hero.kind == "critter":
                # a small critter speaking to something at its feet: a head-and-shoulders *single* at eye
                # level (ear tips to chest) so the snout and mouth read; the medium before it already showed
                # the addressee, and the speaker's eyeline/glance keeps it present (review 11-16 17:25)
                top = asset_info.get("head_top", head_z + 0.3) + 0.12 * plan.hero.scale  # ear-tip headroom
                bottom = max(0.0, head_z - 0.45 * plan.hero.scale)
                center = (hx1 + 0.05, 0.0, (top + bottom) / 2)
                sub_h, sub_w = top - bottom, 0.9 * plan.hero.scale
                c["height"] = round(head_z + 0.08 * plan.hero.scale, 3)
                c["fill"] = round(
                    0.95 * ctx.state.tuning.get("camera", {}).get(shot.id, {}).get("fill_mul", 1.0), 3
                )
                singles.append(shot.id)
            elif shot.type == "closeup" and shot.beat == "speak" and plan.prop:
                # dialogue close-up: the face fills the frame (lip sync must read) with the prop's
                # blossom entering from below — head and shoulders, not a medium shot
                # head (and ears) to the whole blossom
                top = asset_info.get("head_top", head_z + 0.3) + 0.05
                bottom = max(0.0, prop_h - 0.3)
                center = ((hx1 * 2 + prop_x) / 3, 0.0, (top + bottom) / 2)
                sub_h, sub_w = top - bottom, abs(prop_x - hx1) * 0.8 + 0.5
                c["fill"] = round(
                    0.98 * ctx.state.tuning.get("camera", {}).get(shot.id, {}).get("fill_mul", 1.0), 3
                )
                two_shot = True
            elif shot.type == "closeup":
                center, sub_h, sub_w = (hx1 + 0.1, 0.0, head_z - 0.1), 0.75, 0.7
            elif shot.subject == "both" and plan.prop:
                mid = (min(hx0, hx1) + prop_x) / 2
                center = (mid, 0.0, hero_h * 0.45)
                sub_h, sub_w = hero_h, abs(prop_x - min(hx0, hx1)) + 1.2
            elif shot.type == "wide" and move == "track":
                # travelling shot: frame the hero (plus lead room), the camera moves with it
                center = ((hx0 + hx1) / 2, 0.0, hero_h * 0.5)
                sub_h, sub_w = hero_h, 2.4
            elif shot.type == "wide":
                center = ((hx0 + hx1) / 2, 0.0, hero_h * 0.5)
                sub_h, sub_w = hero_h, abs(hx1 - hx0) + 1.6
            else:
                center, sub_h, sub_w = ((hx0 + hx1) / 2, 0.0, hero_h * 0.5), hero_h, 1.2
            thirds = (
                (shot.type != "wide" or shot.subject == "hero") and not two_shot and shot.subject != "both"
            )
            loc, aim = frame_shot(center, sub_h, sub_w, c, facing=1.0, thirds=thirds)
            cid, aid = f"cam_{shot.id}", f"cam_{shot.id}_aim"
            ops += [
                {"op": "create_empty", "id": aid, "location": aim, "tags": ["camera"]},
                {
                    "op": "add_camera",
                    "id": cid,
                    "location": loc,
                    "lens": c["lens"],
                    "look_at": aid,
                    "tags": ["camera"],
                    **({"dof_target": "hero_head_pivot", "fstop": 2.2} if shot.type == "closeup" else {}),
                },
                {"op": "set_camera_active", "id": cid, "frame": f0},
            ]
            loc0, loc1, aim0, aim1 = list(loc), list(loc), list(aim), list(aim)
            if move in ("dolly_in", "dolly_out"):
                k = 0.85 if move == "dolly_in" else 1.18
                far = [aim[j] + (loc[j] - aim[j]) / k for j in range(3)]
                near = [aim[j] + (loc[j] - aim[j]) * k for j in range(3)]
                loc0, loc1 = (far, loc) if move == "dolly_in" else (near, loc)
                loc0[2], loc1[2] = loc[2], loc[2]
            elif move == "pan":
                aim0 = [aim[0] + (hx0 - center[0]) * 0.7, aim[1], aim[2]]
                aim1 = [aim[0] + (hx1 - center[0]) * 0.7, aim[1], aim[2]]
                loc0 = [loc[0] - 0.6, loc[1], loc[2]]
                loc1 = [loc[0] + 0.6, loc[1], loc[2]]
            elif move == "orbit":
                a = math.radians(10)
                dx, dy = loc[0] - aim[0], loc[1] - aim[1]
                loc0 = [
                    aim[0] + dx * math.cos(-a) - dy * math.sin(-a),
                    aim[1] + dx * math.sin(-a) + dy * math.cos(-a),
                    loc[2],
                ]
                loc1 = [
                    aim[0] + dx * math.cos(a) - dy * math.sin(a),
                    aim[1] + dx * math.sin(a) + dy * math.cos(a),
                    loc[2],
                ]
            elif move == "crane_up":
                loc0 = list(loc)
                loc1 = [aim[0] + (loc[0] - aim[0]) * 1.25, aim[1] + (loc[1] - aim[1]) * 1.25, loc[2] + 1.6]
                aim1 = [aim[0], aim[1], aim[2] + 0.2]
            elif move == "track":
                loc0 = [loc[0] + hx0 - center[0], loc[1], loc[2]]
                loc1 = [loc[0] + hx1 - center[0], loc[1], loc[2]]
                aim0 = [aim[0] + hx0 - center[0], aim[1], aim[2]]
                aim1 = [aim[0] + hx1 - center[0], aim[1], aim[2]]
            if loc0 != loc1:
                ops.append(
                    {
                        "op": "insert_keyframes",
                        "target": cid,
                        "property": "location",
                        "keys": [
                            [f0, [round(v, 3) for v in loc0], "EASE_IN_OUT"],
                            [f1, [round(v, 3) for v in loc1], "EASE_IN_OUT"],
                        ],
                    }
                )
            if aim0 != aim1:
                ops.append(
                    {
                        "op": "insert_keyframes",
                        "target": aid,
                        "property": "location",
                        "keys": [
                            [f0, [round(v, 3) for v in aim0], "EASE_IN_OUT"],
                            [f1, [round(v, 3) for v in aim1], "EASE_IN_OUT"],
                        ],
                    }
                )
            ctx.log.event(
                "decision",
                self.role,
                f"{shot.id} {shot.type}/{move}: lens {c['lens']}mm, az {c['azimuth']}°, "
                f"fill {c['fill']:.2f}, camera {loc} -> aim {aim}",
                shot=shot.id,
                camera=c,
            )
        # sunset: the sun sinks and the key dims during the last shot (time passing)
        if plan.setting.time_of_day in ("sunset", "dawn") and len(plan.shots) > 1:
            last = plan.shots[-1]
            f0, f1 = frames[last.id]
            ops.append(
                {
                    "op": "insert_keyframes",
                    "target": "light_key",
                    "property": "light.energy",
                    "keys": [
                        [f0, L.get("key_energy", 4.0), "EASE_IN_OUT"],
                        [f1, round(L.get("key_energy", 4.0) * 0.55, 2), "EASE_IN_OUT"],
                    ],
                }
            )
        self.submit(ctx, self.batch(f"Cameras for {len(plan.shots)} shots with cuts", ops))
        return {"cameras": [f"cam_{s.id}" for s in plan.shots], "lighting": L}
