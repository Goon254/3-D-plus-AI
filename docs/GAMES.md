# Games track (Godot 4)

```bash
animatica game "a 2D platformer where a robot collects flowers"
godot --path output/game-a-2d-platformer-where-a-robot-collects-f/godot   # play it (Godot 4.5+)
```

Pipeline: **Game Designer** (GDD JSON) → **Level Builder** (platform layout, reachability check against
jump physics) → **Gameplay Programmer** (GDScript from templates: `player.gd`, `collectible.gd`, `main.gd`)
→ **one batch** through the Godot adapter (`adapters/godot/addons/animatica/runner.gd`, MIT) building the
scene tree, shapes, art polygons, scripts and input map → **Playtester** (bot plays headless at fixed
60 fps, reports collect/fell/win events and script errors) → **Critic** (if it fails, make the level easier
and rebuild, up to 3 attempts). Outputs: `godot/` project, `GDD.json`, `PLAYTEST.json`, `screenshot.png`,
`log/production.jsonl`.

## Godot batch ops

`load_scene, create_node(id, type, parent, props), add_shape(target, rect|circle), add_polygon(target, id,
points, color), attach_script(target, path), set_property(target, path, value),
add_input_action(name, keys), save_scene(path, main)` — validated in Python
(`games/godot.py: validate_godot_batch`) before Godot runs them.

## Setup

Godot 4.5.1 Linux binary from the official GitHub release, unpacked to `~/.cache/animatica/godot/`
(`scripts/setup_assets.sh --godot`), or set `ANIMATICA_GODOT_BIN`. Screenshots need `xvfb-run`.
