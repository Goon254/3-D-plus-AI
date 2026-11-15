# SPDX-License-Identifier: MIT
# Animatica Godot adapter: executes one batch of scene-tree ops headlessly.
# usage: godot --headless --path <project> -s res://addons/animatica/runner.gd -- <batch.json> <result.json>
# The scene is only written by "save_scene" and project settings only at the end, so a failing batch
# leaves the project untouched (transactional by construction).
extends SceneTree

var nodes := {}
var scene_root: Node = null
var pending_settings := {}


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var result := {"batch_id": "", "ok": true, "created": [], "modified": [], "errors": [], "warnings": []}
	if args.size() < 2:
		push_error("usage: -- <batch.json> <result.json>")
		quit(2)
		return
	var batch = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	if typeof(batch) != TYPE_DICTIONARY:
		result["ok"] = false
		result["errors"].append("batch is not a JSON object")
	else:
		result["batch_id"] = batch.get("batch_id", "")
		var ops: Array = batch.get("ops", [])
		for i in ops.size():
			var op: Dictionary = ops[i]
			var err := _apply(op, result)
			if err != "":
				result["ok"] = false
				result["errors"].append("ops[%d](%s): %s" % [i, op.get("op", "?"), err])
				break
		if result["ok"]:
			for k in pending_settings:
				ProjectSettings.set_setting(k, pending_settings[k])
			if pending_settings.size() > 0:
				ProjectSettings.save()
	var f := FileAccess.open(args[1], FileAccess.WRITE)
	f.store_string(JSON.stringify(result))
	f.close()
	if scene_root != null and scene_root.get_parent() == null:
		scene_root.free()
	quit(0 if result["ok"] else 1)


func _conv(cur, v):
	match typeof(cur):
		TYPE_VECTOR2:
			return Vector2(v[0], v[1])
		TYPE_VECTOR2I:
			return Vector2i(int(v[0]), int(v[1]))
		TYPE_COLOR:
			return Color(v) if typeof(v) == TYPE_STRING else Color(v[0], v[1], v[2], v[3] if v.size() > 3 else 1.0)
		TYPE_INT:
			return int(v)
		TYPE_FLOAT:
			return float(v)
	return v


func _set_props(n: Object, props: Dictionary) -> String:
	for k in props:
		if not (k in n):
			return "%s has no property '%s'" % [n.get_class(), k]
		n.set(k, _conv(n.get(k), props[k]))
	return ""


func _child(parent_id: String, n: Node, id: String) -> String:
	if not nodes.has(parent_id):
		return "unknown parent '%s'" % parent_id
	if nodes.has(id):
		return "duplicate id '%s'" % id
	n.name = id
	nodes[parent_id].add_child(n)
	nodes[id] = n
	return ""


func _index(n: Node) -> void:
	nodes[String(n.name)] = n
	for c in n.get_children():
		_index(c)


func _apply(op: Dictionary, result: Dictionary) -> String:
	var kind: String = op.get("op", "")
	match kind:
		"load_scene":
			var ps = load(op["path"])
			if ps == null:
				return "cannot load " + op["path"]
			scene_root = ps.instantiate()
			_index(scene_root)
		"create_node":
			if not ClassDB.class_exists(op["type"]) or not ClassDB.can_instantiate(op["type"]):
				return "unknown node type '%s'" % op["type"]
			var n: Node = ClassDB.instantiate(op["type"])
			var e := _set_props(n, op.get("props", {}))
			if e != "":
				n.free()
				return e
			if op.get("parent", null) == null:
				if scene_root != null:
					n.free()
					return "scene already has a scene_root"
				n.name = op["id"]
				scene_root = n
				nodes[op["id"]] = n
			else:
				e = _child(op["parent"], n, op["id"])
				if e != "":
					n.free()
					return e
			result["created"].append(op["id"])
		"add_shape":
			var cs := CollisionShape2D.new()
			if op.get("shape", "rect") == "rect":
				var r := RectangleShape2D.new()
				r.size = Vector2(op["size"][0], op["size"][1])
				cs.shape = r
			else:
				var c := CircleShape2D.new()
				c.radius = float(op["radius"])
				cs.shape = c
			cs.position = _conv(Vector2.ZERO, op.get("offset", [0, 0]))
			var e2 := _child(op["target"], cs, op.get("id", String(op["target"]) + "_shape"))
			if e2 != "":
				return e2
		"add_polygon":
			var p := Polygon2D.new()
			var pts := PackedVector2Array()
			for q in op["points"]:
				pts.append(Vector2(q[0], q[1]))
			p.polygon = pts
			p.color = Color(op.get("color", "#ffffff"))
			p.position = _conv(Vector2.ZERO, op.get("offset", [0, 0]))
			var e3 := _child(op["target"], p, op["id"])
			if e3 != "":
				return e3
		"attach_script":
			if not nodes.has(op["target"]):
				return "unknown id '%s'" % op["target"]
			var s = load(op["path"])
			if s == null or not s.can_instantiate():
				return "script %s failed to load/compile" % op["path"]
			nodes[op["target"]].set_script(s)
			result["modified"].append(op["target"])
		"set_property":
			if not nodes.has(op["target"]):
				return "unknown id '%s'" % op["target"]
			var e4 := _set_props(nodes[op["target"]], {op["path"]: op["value"]})
			if e4 != "":
				return e4
			result["modified"].append(op["target"])
		"add_input_action":
			var events := []
			for key in op["keys"]:
				var ev := InputEventKey.new()
				ev.physical_keycode = OS.find_keycode_from_string(key)
				if ev.physical_keycode == KEY_NONE:
					return "unknown key '%s'" % key
				events.append(ev)
			pending_settings["input/" + op["name"]] = {"deadzone": 0.5, "events": events}
		"save_scene":
			if scene_root == null:
				return "nothing to save"
			_own(scene_root, scene_root)
			var packed := PackedScene.new()
			var err := packed.pack(scene_root)
			if err != OK:
				return "pack failed (%d)" % err
			err = ResourceSaver.save(packed, op["path"])
			if err != OK:
				return "save failed (%d)" % err
			if op.get("main", false):
				pending_settings["application/run/main_scene"] = op["path"]
		_:
			return "unsupported op '%s'" % kind
	return ""


func _own(n: Node, owner_node: Node) -> void:
	for c in n.get_children():
		c.owner = owner_node
		_own(c, owner_node)
