import json
import time
from pathlib import Path

import pytest

from animatica.core.protocol import BatchValidationError

pytestmark = pytest.mark.blender
ROOT = Path(__file__).resolve().parents[1]


def run(engine, *ops, **kw):
    return engine.run_batch({"batch_id": kw.pop("bid", "t"), "ops": list(ops), **kw})


def test_robot_example_makes_blend_and_preview(fresh, tmp_path):
    data = json.loads((ROOT / "examples/batches/robot.json").read_text())
    for op in data["ops"]:
        if op["op"] == "save":
            op["path"] = str(tmp_path / "robot.blend")
    res = fresh.run_batch(data)
    assert res.ok, res.errors
    assert {"robot_body", "robot_head", "cam"} <= set(res.created)
    assert Path(res.preview).exists() and (tmp_path / "robot.blend").exists()
    assert res.data["preview_stats"]["mean"] > 0.02


def test_failed_batch_rolls_back_everything(fresh):
    res = run(fresh, {"op": "create_primitive", "id": "keep", "shape": "cube"})
    assert res.ok
    bad = run(
        fresh,
        {"op": "create_primitive", "id": "temp", "shape": "cube"},
        {"op": "set_property", "target": "temp", "path": "no_such_prop", "value": 1},
        bid="bad",
    )
    assert not bad.ok and "no_such_prop" in bad.errors[0]
    ids = set(fresh.call("ids")["ids"])
    assert "keep" in ids and "temp" not in ids


def test_validation_happens_before_execution(fresh):
    with pytest.raises(BatchValidationError):
        run(fresh, {"op": "transform", "target": "ghost", "location": [0, 0, 0]})


def test_300_ops_in_one_round_trip(fresh):
    ops = [
        {
            "op": "create_primitive",
            "id": f"tree_{i}",
            "shape": "cone",
            "radius": 0.3,
            "depth": 1.0,
            "location": [i % 20, i // 20, 0.5],
            "segments": 8,
        }
        for i in range(300)
    ]
    t = time.time()
    res = run(fresh, *ops, bid="forest")
    assert res.ok and len(res.created) == 300
    assert time.time() - t < 60


def test_keyframes_shape_keys_and_query(fresh):
    from animatica.agents.asset import mouth_mesh

    v, f, keys = mouth_mesh()
    res = run(
        fresh,
        {"op": "create_mesh", "id": "mouth", "vertices": v, "faces": f},
        {"op": "add_shape_keys", "target": "mouth", "keys": keys},
        {"op": "set_frame_range", "start": 1, "end": 48},
        {
            "op": "insert_keyframes",
            "target": "mouth",
            "property": "shape_key:open",
            "keys": [[1, 0.0, "LINEAR"], [12, 1.0, "BEZIER"], [24, 0.0, "EASE_OUT"]],
        },
        {
            "op": "insert_keyframes",
            "target": "mouth",
            "property": "location",
            "keys": [[1, [0, 0, 0], "BEZIER"], [48, [1, 0, 0], "BACK"]],
        },
    )
    assert res.ok, res.errors
    q = run(fresh, {"op": "query", "ids": ["mouth"], "fields": ["type", "shape_keys", "animation"]})
    assert q.data["objects"]["mouth"]["shape_keys"] == ["Basis", "open", "wide", "round"]
    insp = run(
        fresh, {"op": "inspect", "subjects": ["mouth"], "frames": [1, 12], "shape_key_target": "mouth"}
    )
    frames = insp.data["inspect"]["frames"]
    assert frames["1"]["mouth"] == 0.0 and frames["12"]["mouth"] > 0.9


def test_armature_and_rigid_bind(fresh):
    res = run(
        fresh,
        {
            "op": "create_armature",
            "id": "rig",
            "bones": [
                {"name": "root", "head": [0, 0, 0], "tail": [0, 0, 0.5]},
                {"name": "head", "head": [0, 0, 0.5], "tail": [0, 0, 1.0], "parent": "root"},
            ],
        },
        {
            "op": "create_primitive",
            "id": "skull",
            "shape": "uv_sphere",
            "radius": 0.2,
            "location": [0, 0, 0.8],
        },
        {"op": "bind_mesh_to_armature", "mesh": "skull", "armature": "rig", "bone": "head"},
    )
    assert res.ok, res.errors


def test_script_mode_is_sandboxed(fresh):
    ok = fresh.run_batch(
        {
            "batch_id": "s",
            "mode": "script",
            "script": (
                "for i in range(5):\n"
                "    ax.run_ops([{'op': 'create_primitive', 'id': f'rock{i}', 'shape': 'ico_sphere', 'location': [i, 0, 0]}])\n"
            ),
        }
    )
    assert ok.ok and len(ok.created) == 5
    bad = fresh.run_batch({"batch_id": "s2", "mode": "script", "script": "import os\nos.system('echo hi')"})
    assert not bad.ok and "not allowed" in bad.errors[0]
    loop = fresh.run_batch(
        {"batch_id": "s3", "mode": "script", "script": "while True: pass", "script_timeout_s": 1}
    )
    assert not loop.ok and "exceeded" in loop.errors[0]


def test_inspect_frustum_and_floor(fresh):
    res = run(
        fresh,
        {"op": "create_primitive", "id": "box", "shape": "cube", "size": [1, 1, 1], "location": [0, 0, 0.5]},
        {"op": "create_primitive", "id": "far", "shape": "cube", "location": [50, 0, -0.3]},
        {"op": "add_camera", "id": "cam", "location": [0, -6, 1], "look_at": [0, 0, 0.5]},
        {"op": "inspect", "subjects": ["box", "far"], "frames": [1], "camera": "cam"},
    )
    assert res.ok
    sub = res.data["inspect"]["frames"]["1"]["subjects"]
    assert sub["box"]["visible_fraction"] == 1.0 and abs(sub["box"]["min_z"]) < 1e-3
    assert sub["far"]["visible_fraction"] < 0.5 and sub["far"]["min_z"] < 0
