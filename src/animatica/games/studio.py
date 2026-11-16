"""Games track (Milestone 7): prompt -> runnable Godot 4 project, confirmed by a headless Playtester.

Agents (same pattern as the film track: the LLM picks parameters, code emits validated batches):

* Game Designer  -> GDD: genre, hero, collectible, count, physics feel, palette, win/lose rules
* Level Builder  -> platform layout, checked for reachability against the jump physics
* Gameplay Programmer -> GDScript files from templates parameterised by the GDD (+ script validation)
* (scene assembly) -> one batch through the Godot adapter: nodes, shapes, polygons, scripts, input map
* Playtester     -> runs the game headless at fixed 60 fps with a bot driving the player; parses events
                    (collect / fell / win) and engine errors; reports pass/fail
* Critic         -> turns playtest results into fixes (e.g. lower gaps) and asks the builder to retry
"""

from __future__ import annotations

import json
import math
import random
import re
import zlib
from pathlib import Path
from typing import Any

from ..core.llm import Provider, ScriptedProvider, get_provider, scripted
from ..core.log import ProductionLog
from ..core.state import slugify
from . import godot

COLLECTIBLES = {
    "flower": ["flower", "flowers", "rose", "daisy", "blossom"],
    "coin": ["coin", "coins", "gold"],
    "star": ["star", "stars"],
    "gem": ["gem", "gems", "crystal", "crystals", "diamond"],
    "battery": ["battery", "batteries", "bolt", "bolts"],
}
COLLECTIBLE_COLORS = {
    "flower": "#FF5C8A",
    "coin": "#FFD23F",
    "star": "#FFE066",
    "gem": "#7FE7FF",
    "battery": "#7CFC7C",
}


@scripted("game.design")
def scripted_design(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload["prompt"].lower()
    item = next(
        (k for k, ws in COLLECTIBLES.items() if any(re.search(rf"\b{w}\b", text) for w in ws)), "star"
    )
    hero = "robot" if re.search(r"\b(robot|bot|droid)\b", text) else "critter"
    seed = zlib.crc32(payload["prompt"].encode()) % 100000
    return {
        "title": payload["prompt"].strip().rstrip(".")[:60],
        "genre": "platformer_2d",
        "hero": hero,
        "hero_color": "#D9822B" if hero == "robot" else "#4A7FD9",
        "collectible": item,
        "collectible_color": COLLECTIBLE_COLORS[item],
        "count": 6,
        "speed": 230.0,
        "jump_velocity": -460.0,
        "gravity": 980.0,
        "palette": {"sky": "#7EC8E3", "ground": "#5B8C3A", "platform": "#8B5A3C"},
        "win": f"collect all {item}s",
        "lose": "fall off the world (respawn at start)",
        "seed": seed,
    }


def jump_reach(d: dict[str, Any]) -> tuple[float, float]:
    """(max jump height, max horizontal distance at that height ~0) in pixels."""
    v, g, s = abs(d["jump_velocity"]), d["gravity"], d["speed"]
    return v * v / (2 * g), s * 2 * v / g


def build_level(d: dict[str, Any], safety: float = 0.6) -> dict[str, Any]:
    """Staircase-ish run of platforms to the right; every gap/step is within ``safety`` × jump reach."""
    rng = random.Random(d["seed"])
    hmax, xmax = jump_reach(d)
    plats = [{"x": 0, "y": 500, "w": 520, "h": 40}]  # start ground
    flowers = []
    x, y = 520, 500
    for _ in range(d["count"]):
        gap = rng.uniform(0.25, 1.0) * xmax * safety * 0.6
        dy = rng.choice([-1, -1, 0, 1]) * rng.uniform(0.3, 1.0) * hmax * safety
        y = max(260, min(560, y + dy))
        w = rng.uniform(180, 320)
        x += gap
        plats.append({"x": round(x), "y": round(y), "w": round(w), "h": 40})
        flowers.append({"x": round(x + w * rng.uniform(0.35, 0.7)), "y": round(y - 34)})
        x += w
    plats.append({"x": round(x + 60), "y": 500, "w": 400, "h": 40})  # finish
    return {"platforms": plats, "collectibles": flowers, "spawn": [120, 440], "kill_y": 900, "width": x + 460}


def check_reachability(d: dict[str, Any], level: dict[str, Any]) -> list[str]:
    hmax, xmax = jump_reach(d)
    issues = []
    plats = level["platforms"]
    for a, b in zip(plats, plats[1:]):
        gap = b["x"] - (a["x"] + a["w"])
        rise = a["y"] - b["y"]
        if rise > hmax * 0.9:
            issues.append(f"step up {rise:.0f}px exceeds jump height {hmax:.0f}px")
        if gap > xmax * 0.8:
            issues.append(f"gap {gap:.0f}px exceeds jump distance {xmax:.0f}px")
    return issues


# ------------------------------------------------------------------------------------------ GDScript
PLAYER_GD = """extends CharacterBody2D
## Animatica player controller (platformer). Bot mode is enabled by the Playtester.

const SPEED := {speed}
const JUMP_VELOCITY := {jump_velocity}
var gravity := {gravity}
var bot := false
var spawn := Vector2.ZERO
var _stuck := 0.0
var _last_x := 0.0


func _ready() -> void:
	spawn = global_position


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y += gravity * delta
	var dir := 0.0
	var jump := false
	if bot:
		var t: Node2D = get_parent().nearest_collectible(global_position)
		if t != null:
			var dx := t.global_position.x - global_position.x
			dir = signf(dx) if absf(dx) > 8.0 else 0.0
			var above := t.global_position.y < global_position.y - 30.0
			jump = is_on_floor() and (is_on_wall() or _gap_ahead(dir) or (above and absf(dx) < 140.0) or _stuck > 0.5)
		_stuck = _stuck + delta if absf(global_position.x - _last_x) < 0.5 and dir != 0.0 else 0.0
		_last_x = global_position.x
	else:
		dir = Input.get_axis("move_left", "move_right")
		jump = Input.is_action_just_pressed("jump") and is_on_floor()
	if jump:
		velocity.y = JUMP_VELOCITY
	velocity.x = dir * SPEED
	move_and_slide()
	if global_position.y > {kill_y}:
		get_parent().fell(self)
		global_position = spawn
		velocity = Vector2.ZERO


func _gap_ahead(dir: float) -> bool:
	if dir == 0.0 or not is_on_floor():
		return false
	var from := global_position + Vector2(dir * 26.0, 0.0)
	var q := PhysicsRayQueryParameters2D.create(from, from + Vector2(0.0, 80.0))
	q.exclude = [get_rid()]
	return get_world_2d().direct_space_state.intersect_ray(q).is_empty()
"""

COLLECTIBLE_GD = """extends Area2D
## A collectible: tells the level when the player touches it.

var t := 0.0


func _ready() -> void:
	add_to_group("collectible")
	body_entered.connect(_on_body_entered)


func _process(delta: float) -> void:
	t += delta
	rotation = sin(t * 3.0) * 0.15


func _on_body_entered(body: Node) -> void:
	if body.name == "Player":
		get_parent().collect(self)
"""

MAIN_GD = """extends Node2D
## Level controller: score, win/lose, playtest events (printed as ANIMATICA_EVENT json lines).

var total := 0
var collected := 0
var falls := 0
var playtest := false
var elapsed := 0.0


func _ready() -> void:
	playtest = "--playtest" in OS.get_cmdline_user_args()
	for c in get_children():
		if c.is_in_group("collectible"):
			total += 1
	$Player.bot = playtest
	_update_hud()
	_event({"type": "start", "total": total})


func _physics_process(delta: float) -> void:
	elapsed += delta
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--screenshot=") and Engine.get_physics_frames() == 150:
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(a.split("=")[1])
			_event({"type": "screenshot", "path": a.split("=")[1]})


func nearest_collectible(from: Vector2) -> Node2D:
	var best: Node2D = null
	var best_d := INF
	for c in get_tree().get_nodes_in_group("collectible"):
		if c.is_queued_for_deletion():
			continue
		var d := absf(c.global_position.x - from.x) + 0.3 * absf(c.global_position.y - from.y)
		if c.global_position.x < from.x - 40.0:
			d += 2000.0  # prefer moving forward through the level
		if d < best_d:
			best_d = d
			best = c
	return best


func collect(item: Node) -> void:
	if item.is_queued_for_deletion():
		return
	item.remove_from_group("collectible")
	item.queue_free()
	collected += 1
	_update_hud()
	_event({"type": "collect", "collected": collected, "total": total, "t": snappedf(elapsed, 0.01)})
	if collected >= total:
		_event({"type": "win", "t": snappedf(elapsed, 0.01), "falls": falls})
		$HUD/Message.text = "You win!"
		if playtest:
			get_tree().quit()


func fell(_body: Node) -> void:
	falls += 1
	_event({"type": "fell", "falls": falls, "t": snappedf(elapsed, 0.01)})


func _update_hud() -> void:
	$HUD/Score.text = "{label}: %d / %d" % [collected, total]


func _event(data: Dictionary) -> void:
	print("ANIMATICA_EVENT " + JSON.stringify(data))
"""

PROJECT_GODOT = """; Engine configuration file generated by Animatica.
config_version=5

[application]

config/name="{title}"
config/features=PackedStringArray("4.5", "GL Compatibility")

[display]

window/size/viewport_width=1280
window/size/viewport_height=720

[rendering]

renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
environment/defaults/default_clear_color=Color({sky})
"""


def _color_tuple(hexc: str) -> str:
    r, g, b = (int(hexc[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return f"{r:.3f}, {g:.3f}, {b:.3f}, 1"


def hero_polygons(kind: str, color: str) -> list[dict[str, Any]]:
    if kind == "robot":
        return [
            {"id": "P_treads", "points": [[-18, 10], [18, 10], [18, 24], [-18, 24]], "color": "#2B2B30"},
            {"id": "P_body", "points": [[-16, -12], [16, -12], [16, 12], [-16, 12]], "color": color},
            {"id": "P_head", "points": [[-14, -34], [14, -34], [14, -14], [-14, -14]], "color": color},
            {"id": "P_face", "points": [[-10, -31], [10, -31], [10, -17], [-10, -17]], "color": "#1B1F27"},
            {"id": "P_eye", "points": [[2, -28], [7, -28], [7, -22], [2, -22]], "color": "#7FE7FF"},
            {"id": "P_antenna", "points": [[-1, -44], [1, -44], [1, -34], [-1, -34]], "color": "#FF4D4D"},
        ]
    pts = [[18 * math.cos(a) * 1.0, 18 * math.sin(a) * 1.1 - 2] for a in [i * math.pi / 8 for i in range(16)]]
    return [
        {"id": "P_body", "points": [[round(x, 1), round(y, 1)] for x, y in pts], "color": color},
        {"id": "P_eye", "points": [[6, -8], [10, -8], [10, -3], [6, -3]], "color": "#151515"},
    ]


def collectible_polygon(kind: str, color: str) -> list[list[float]]:
    if kind == "flower":
        pts = []
        for i in range(20):
            a = i * math.pi / 10
            r = 13 if i % 2 == 0 else 7
            pts.append([round(r * math.cos(a), 1), round(r * math.sin(a), 1)])
        return pts
    if kind == "star":
        return [
            [
                round((12 if i % 2 == 0 else 5) * math.cos(-math.pi / 2 + i * math.pi / 5), 1),
                round((12 if i % 2 == 0 else 5) * math.sin(-math.pi / 2 + i * math.pi / 5), 1),
            ]
            for i in range(10)
        ]
    return [[0, -12], [10, 0], [0, 12], [-10, 0]]


def scene_batch(d: dict[str, Any], level: dict[str, Any]) -> dict[str, Any]:
    pal = d["palette"]
    ops: list[dict[str, Any]] = [
        {"op": "add_input_action", "name": "move_left", "keys": ["A", "Left"]},
        {"op": "add_input_action", "name": "move_right", "keys": ["D", "Right"]},
        {"op": "add_input_action", "name": "jump", "keys": ["Space", "W", "Up"]},
        {"op": "create_node", "id": "Main", "type": "Node2D", "parent": None},
    ]
    for i, p in enumerate(level["platforms"]):
        pid = f"Platform{i}"
        ops += [
            {
                "op": "create_node",
                "id": pid,
                "type": "StaticBody2D",
                "parent": "Main",
                "props": {"position": [p["x"] + p["w"] / 2, p["y"] + p["h"] / 2]},
            },
            {"op": "add_shape", "target": pid, "shape": "rect", "size": [p["w"], p["h"]]},
            {
                "op": "add_polygon",
                "target": pid,
                "id": f"{pid}_top",
                "color": pal["ground"],
                "points": [
                    [-p["w"] / 2, -p["h"] / 2],
                    [p["w"] / 2, -p["h"] / 2],
                    [p["w"] / 2, -p["h"] / 2 + 10],
                    [-p["w"] / 2, -p["h"] / 2 + 10],
                ],
            },
            {
                "op": "add_polygon",
                "target": pid,
                "id": f"{pid}_dirt",
                "color": pal["platform"],
                "points": [
                    [-p["w"] / 2, -p["h"] / 2 + 10],
                    [p["w"] / 2, -p["h"] / 2 + 10],
                    [p["w"] / 2, p["h"] / 2],
                    [-p["w"] / 2, p["h"] / 2],
                ],
            },
        ]
    sx, sy = level["spawn"]
    ops += [
        {
            "op": "create_node",
            "id": "Player",
            "type": "CharacterBody2D",
            "parent": "Main",
            "props": {"position": [sx, sy]},
        },
        {"op": "add_shape", "target": "Player", "shape": "rect", "size": [32, 56], "offset": [0, -4]},
    ]
    for poly in hero_polygons(d["hero"], d["hero_color"]):
        ops.append({"op": "add_polygon", "target": "Player", **poly})
    ops += [
        {
            "op": "create_node",
            "id": "Camera",
            "type": "Camera2D",
            "parent": "Player",
            "props": {"position": [0, -80]},
        },
        {"op": "attach_script", "target": "Player", "path": "res://scripts/player.gd"},
    ]
    shape = collectible_polygon(d["collectible"], d["collectible_color"])
    for i, c in enumerate(level["collectibles"]):
        cid = f"Item{i}"
        ops += [
            {
                "op": "create_node",
                "id": cid,
                "type": "Area2D",
                "parent": "Main",
                "props": {"position": [c["x"], c["y"]]},
            },
            {"op": "add_shape", "target": cid, "shape": "circle", "radius": 16},
            {
                "op": "add_polygon",
                "target": cid,
                "id": f"{cid}_art",
                "points": shape,
                "color": d["collectible_color"],
            },
            {
                "op": "add_polygon",
                "target": cid,
                "id": f"{cid}_core",
                "points": [[-4, -4], [4, -4], [4, 4], [-4, 4]],
                "color": "#FFD23F",
            },
            {"op": "attach_script", "target": cid, "path": "res://scripts/collectible.gd"},
            {"op": "set_property", "target": cid, "path": "monitoring", "value": True},
        ]
    ops += [
        {"op": "create_node", "id": "HUD", "type": "CanvasLayer", "parent": "Main"},
        {
            "op": "create_node",
            "id": "Score",
            "type": "Label",
            "parent": "HUD",
            "props": {"position": [24, 16]},
        },
        {
            "op": "create_node",
            "id": "Message",
            "type": "Label",
            "parent": "HUD",
            "props": {"position": [560, 320]},
        },
        {"op": "attach_script", "target": "Main", "path": "res://scripts/main.gd"},
        {"op": "save_scene", "path": "res://main.tscn", "main": True},
    ]
    return {
        "batch_id": "game-scene",
        "agent": "level_builder",
        "intent": "assemble level, player, collectibles, HUD",
        "ops": ops,
    }


def write_scripts(project: Path, d: dict[str, Any], level: dict[str, Any]) -> list[str]:
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    files = {
        "player.gd": PLAYER_GD.format(
            speed=f"{d['speed']:.1f}",
            jump_velocity=f"{d['jump_velocity']:.1f}",
            gravity=f"{d['gravity']:.1f}",
            kill_y=level["kill_y"],
        ),
        "collectible.gd": COLLECTIBLE_GD,
        "main.gd": MAIN_GD.replace("{label}", d["collectible"].capitalize() + "s"),
    }
    for name, src in files.items():
        (project / "scripts" / name).write_text(src, encoding="utf-8")
    return [f"res://scripts/{n}" for n in files]


def playtest(project: Path, seconds: int = 60) -> dict[str, Any]:
    code, out, err = godot.run_game(project, frames=seconds * 60, args=["--playtest"])
    events = []
    for line in out.splitlines():
        if line.startswith("ANIMATICA_EVENT "):
            events.append(json.loads(line[len("ANIMATICA_EVENT ") :]))
    start = next((e for e in events if e["type"] == "start"), {"total": 0})
    win = next((e for e in events if e["type"] == "win"), None)
    collected = max([e["collected"] for e in events if e["type"] == "collect"], default=0)
    errors = godot.script_errors(err + out)
    return {
        "exit_code": code,
        "started": bool(events),
        "total": start.get("total", 0),
        "collected": collected,
        "won": win is not None,
        "win_time": win["t"] if win else None,
        "falls": sum(1 for e in events if e["type"] == "fell"),
        "errors": errors,
        "events": events[-12:],
    }


def screenshot(project: Path, out: Path) -> Path | None:
    """Render one frame of the bot playtest under Xvfb (Godot --headless cannot render)."""
    import shutil
    import subprocess

    exe, xvfb = godot.godot_bin(), shutil.which("xvfb-run")
    if not exe or not xvfb:
        return None
    cmd = [
        xvfb,
        "-a",
        "-s",
        "-screen 0 1280x720x24",
        exe,
        "--path",
        str(project),
        "--rendering-driver",
        "opengl3",
        "--fixed-fps",
        "60",
        "--quit-after",
        "200",
        "--",
        "--playtest",
        f"--screenshot={out.resolve()}",
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    return out if out.exists() else None


def make_game(
    prompt: str,
    out_root: str | Path = "output",
    name: str | None = None,
    provider: str | Provider = "auto",
    max_attempts: int = 3,
) -> dict[str, Any]:
    prov = provider if isinstance(provider, Provider) else get_provider(provider)
    root = Path(out_root) / (name or ("game-" + slugify(prompt)))
    project = root / "godot"
    project.mkdir(parents=True, exist_ok=True)
    log = ProductionLog(root)
    log.event(
        "start",
        "orchestr.",
        f"new game from prompt: {prompt!r} (provider {prov.name}, Godot {godot.godot_bin()})",
    )
    try:
        d = prov.complete_json(
            "game.design", "You are a game designer. Return a compact GDD JSON.", {"prompt": prompt}
        )
    except Exception as e:  # noqa: BLE001
        log.event("fallback", "designer", f"LLM GDD unusable ({e}); using scripted design")
        d = ScriptedProvider().complete_json("game.design", "", {"prompt": prompt})
    log.event(
        "decision",
        "designer",
        f"GDD: {d['genre']}, hero {d['hero']}, collect {d['count']} {d['collectible']}s; "
        f"win: {d['win']}; lose: {d['lose']}",
        gdd=d,
    )
    (project / "project.godot").write_text(
        PROJECT_GODOT.format(title=d["title"].replace('"', "'"), sky=_color_tuple(d["palette"]["sky"])),
        encoding="utf-8",
    )
    (root / "GDD.json").write_text(json.dumps(d, indent=1), encoding="utf-8")
    report: dict[str, Any] = {}
    safety = 0.6
    for attempt in range(1, max_attempts + 1):
        level = build_level(d, safety)
        issues = check_reachability(d, level)
        log.event(
            "decision",
            "level",
            f"attempt {attempt}: {len(level['platforms'])} platforms, {len(level['collectibles'])} items, "
            f"reachability issues: {issues or 'none'}",
            level=level,
        )
        scripts = write_scripts(project, d, level)
        log.event("code", "programmer", f"wrote {', '.join(s.split('/')[-1] for s in scripts)}")
        batch = scene_batch(d, level)
        res = godot.run_batch(project, batch)
        log.event(
            "batch",
            "level",
            f"{batch['intent']} ({len(batch['ops'])} ops) -> ok={res['ok']} "
            f"created {len(res.get('created', []))} errors {res.get('errors') or res.get('engine_errors') or []}",
            ok=res["ok"],
            errors=res.get("errors"),
        )
        if not res["ok"]:
            raise godot.GodotError(f"scene batch failed: {res.get('errors')}")
        report = playtest(project)
        verdict = "PASS" if report["won"] and not report["errors"] else "FAIL"
        log.event(
            "critique",
            "playtester",
            f"attempt {attempt}: {verdict} — collected {report['collected']}/{report['total']}, "
            f"falls {report['falls']}, win time {report['win_time']}, script errors {len(report['errors'])}",
            verdict=verdict,
            report=report,
        )
        if verdict == "PASS":
            break
        safety *= 0.75  # critic fix: make gaps/steps easier and rebuild
        log.event(
            "fix", "critic", f"level too hard or broken; reducing gap/step safety factor to {safety:.2f}"
        )
    shot = screenshot(project, root / "screenshot.png")
    log.event(
        "render",
        "playtester",
        f"screenshot: {shot or 'unavailable (needs xvfb-run + OpenGL)'}",
        preview=str(shot) if shot else None,
    )
    (root / "PLAYTEST.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    readme = (
        f"# {d['title']}\n\nGenerated by Animatica from: _{prompt}_\n\nRun: `godot --path godot` (Godot 4.5+).\n"
        f"Controls: A/D or arrows to move, Space/W/Up to jump. Goal: {d['win']}.\n\n"
        f"Playtest: {'won' if report.get('won') else 'did not win'} — collected {report.get('collected')}/"
        f"{report.get('total')} in {report.get('win_time')} s, falls {report.get('falls')}, script errors "
        f"{len(report.get('errors', []))}.\n"
    )
    (root / "README.md").write_text(readme, encoding="utf-8")
    log.event(
        "done", "orchestr.", f"game project at {project}; playtest {'PASS' if report.get('won') else 'FAIL'}"
    )
    return {"project": str(project), "playtest": report}
