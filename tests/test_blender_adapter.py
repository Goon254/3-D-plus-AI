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


def test_viewport_tint_grades_workbench_only(fresh, tmp_path):
    """Night grade: Workbench (flat material colours) darkens, emissive materials keep glowing."""
    res = run(
        fresh,
        {"op": "create_primitive", "id": "wall", "shape": "cube", "size": [8, 0.2, 8], "location": [0, 0, 0]},
        {"op": "set_material", "targets": ["wall"], "material": {"base_color": "#F0F0F0"}},
        {"op": "add_camera", "id": "cam", "location": [0, -4, 0], "look_at": [0, 0, 0], "lens": 30},
        {"op": "set_world", "horizon": "#202040"},
    )
    assert res.ok, res.errors

    def mean(tag):
        r = run(
            fresh,
            {
                "op": "render_preview",
                "camera": "cam",
                "frame": 1,
                "path": str(tmp_path / f"{tag}.png"),
                "resolution": [64, 36],
                "engine": "workbench",
            },
            bid=tag,
        )
        assert r.ok, r.errors
        return r.data["previews"][0]["stats"]["mean"]

    day = mean("day")
    assert run(fresh, {"op": "set_world", "horizon": "#202040", "viewport_tint": "#5060A0"}, bid="n").ok
    night = mean("night")
    assert night < day * 0.75
    # ...but a query reports the ungraded colour: the preview grade is not an artist edit (continue/revise
    # used to lock every grimed set material on a night film as "edited")
    noisy = {"base_color": "#F0F0F0", "noise": 0.5, "noise_scale": 2.0}
    assert run(fresh, {"op": "set_material", "targets": ["wall"], "material": noisy}, bid="nz").ok
    q = fresh.run_batch({"batch_id": "q", "ops": [{"op": "query", "ids": ["wall"], "fields": ["material"]}]})
    assert q.data["objects"]["wall"]["material"]["base_color"].upper() == "#F0F0F0"
    # an emissive material created after the grade shows its emission colour at full strength
    glow = {"base_color": "#202020", "emission": "#FFE0A0", "emission_strength": 4}
    assert run(fresh, {"op": "set_material", "targets": ["wall"], "material": glow}, bid="g").ok
    assert mean("glow") > night
    # removing the tint restores the ungraded colours (idempotent, reversible)
    white = {"base_color": "#F0F0F0"}
    assert run(fresh, {"op": "set_material", "targets": ["wall"], "material": white}, bid="w").ok
    assert run(fresh, {"op": "set_world", "horizon": "#202040"}, bid="d").ok
    assert mean("day2") == pytest.approx(day, abs=0.02)


def test_bone_keys_smooth_bind_and_rigid_bind_keep_local(fresh):
    # an armature under a body empty, a 3-bone tail along +Y, a long tail mesh skinned to the chain
    res = run(
        fresh,
        {"op": "create_empty", "id": "body", "location": [0, 0, 1]},
        {
            "op": "create_armature",
            "id": "rig",
            "parent": "body",
            "bones": [
                {"name": "t0", "head": [0, 0, 0], "tail": [0, 0.3, 0]},
                {"name": "t1", "head": [0, 0.3, 0], "tail": [0, 0.6, 0], "parent": "t0"},
                {"name": "t2", "head": [0, 0.6, 0], "tail": [0, 0.9, 0], "parent": "t1"},
            ],
        },
        {
            "op": "create_primitive",
            "id": "tail",
            "shape": "uv_sphere",
            "radius": 0.1,
            "scale": [1, 4.5, 1],
            "location": [0, 0.45, 0],
            "parent": "body",
        },
        {
            "op": "create_primitive",
            "id": "tip",
            "shape": "uv_sphere",
            "radius": 0.08,
            "location": [0, 0.95, 0],
            "parent": "body",
        },
        {"op": "bind_mesh_to_armature", "mesh": "tail", "armature": "rig", "bones": ["t0", "t1", "t2"]},
        {"op": "bind_mesh_to_armature", "mesh": "tip", "armature": "rig", "bone": "t2"},
        {"op": "set_frame_range", "start": 1, "end": 10},
        {
            "op": "insert_keyframes",
            "target": "rig",
            "property": "bone:t0.rotation",
            "keys": [[1, [0, 0, 0], "BEZIER"], [10, [40, 0, 0], "BEZIER"]],
        },
        {
            "op": "insert_keyframes",
            "target": "rig",
            "property": "bone:t1.rotation",
            "keys": [[1, [0, 0, 0], "BEZIER"], [10, [40, 0, 0], "BEZIER"]],
        },
        {"op": "inspect", "subjects": ["tail", "tip"], "frames": [1, 10]},
    )
    assert res.ok, res.errors
    fr = res.data["inspect"]["frames"]
    # the skinned tail *bends* up (measured on the deformed mesh) and the rigid tip follows the last bone
    assert fr["10"]["subjects"]["tail"]["center"][2] > fr["1"]["subjects"]["tail"]["center"][2] + 0.1
    assert fr["10"]["subjects"]["tip"]["center"][2] > fr["1"]["subjects"]["tip"]["center"][2] + 0.4
    assert fr["1"]["subjects"]["tip"]["center"] == pytest.approx(
        [0, 0.95, 1.0], abs=0.01
    )  # bind didn't move it
    # binding keeps the local transform (scene-model replay / artist-edit diffs still match)
    q = fresh.run_batch(
        {"batch_id": "q", "ops": [{"op": "query", "ids": ["tip", "tail"], "fields": ["transform", "parent"]}]}
    )
    objs = q.data["objects"]
    assert objs["tip"]["location"] == pytest.approx([0, 0.95, 0], abs=1e-3)
    assert objs["tail"]["scale"] == pytest.approx([1, 4.5, 1], abs=1e-3)
    assert objs["tip"].get("parent") == "rig"
    # clearing animation returns the pose to rest
    c = run(
        fresh,
        {"op": "clear_animation", "targets": ["rig"]},
        {"op": "inspect", "subjects": ["tip"], "frames": [10]},
        bid="c",
    )
    assert c.data["inspect"]["frames"]["10"]["subjects"]["tip"]["center"][2] == pytest.approx(1.0, abs=0.01)


def test_ik_leg_reaches_its_foot_target_and_bone_tails_report_it(fresh):
    res = run(
        fresh,
        {"op": "create_empty", "id": "root", "location": [0, 0, 1.0]},
        {
            "op": "create_armature",
            "id": "rig",
            "parent": "root",
            "bones": [
                {"name": "thigh", "head": [0, 0, 0], "tail": [0, -0.05, -0.5]},
                {"name": "shin", "head": [0, -0.05, -0.5], "tail": [0, 0, -1.0], "parent": "thigh"},
            ],
        },
        {"op": "create_empty", "id": "foot_target", "location": [0, 0.0, 0.0]},
        {"op": "create_empty", "id": "pole", "location": [0, -2.0, 0.5], "parent": "root"},
        {
            "op": "add_bone_constraint",
            "armature": "rig",
            "bone": "shin",
            "type": "ik",
            "subject": "foot_target",
            "pole": "pole",
        },
        {"op": "set_frame_range", "start": 1, "end": 10},
        # the foot target steps forward and up; the body stays: the knee must bend, the foot must follow exactly
        {
            "op": "insert_keyframes",
            "target": "foot_target",
            "property": "location",
            "keys": [[1, [0, 0, 0.1], "LINEAR"], [10, [0, -0.3, 0.25], "LINEAR"]],
        },
        {
            "op": "inspect",
            "subjects": ["root"],
            "frames": [1, 5, 10],
            "bone_tails": ["rig:shin", "rig:thigh"],
        },
    )
    assert res.ok, res.errors
    fr = res.data["inspect"]["frames"]
    assert fr["1"]["bone_tails"]["rig:shin"] == pytest.approx([0, 0, 0.1], abs=0.01)
    assert fr["10"]["bone_tails"]["rig:shin"] == pytest.approx([0, -0.3, 0.25], abs=0.01)
    # the knee bends toward the pole (in front, -Y)
    assert fr["10"]["bone_tails"]["rig:thigh"][1] < -0.1


@pytest.mark.parametrize("pattern", ["stripes", "patches", "spots", "bands"])
def test_coat_patterns_render_markings(fresh, tmp_path, pattern):
    plain = {"base_color": "#E8E0D0", "roughness": 0.8}
    marked = {
        **plain,
        "pattern": pattern,
        "pattern_color": "#1A1410",
        "pattern_scale": 6.0,
        "pattern_width": 0.5,
    }
    stats = {}
    for tag, m in (("plain", plain), ("marked", marked)):
        r = run(
            fresh,
            {
                "op": "create_primitive",
                "id": f"s_{tag}",
                "shape": "uv_sphere",
                "size": [1.0, 1.0, 1.4],
                "smooth": True,
            },
            {"op": "set_material", "targets": [f"s_{tag}"], "material": m},
            {
                "op": "add_camera",
                "id": f"c_{tag}",
                "location": [0, -3.2, 0],
                "look_at": [0, 0, 0],
                "lens": 50,
            },
            {"op": "set_world", "horizon": "#FFFFFF", "zenith": "#FFFFFF", "strength": 1.0},
            {
                "op": "render_preview",
                "camera": f"c_{tag}",
                "engine": "cycles",
                "samples": 4,
                "resolution": [96, 96],
                "path": str(tmp_path / f"{tag}.png"),
            },
            {"op": "delete", "targets": [f"s_{tag}", f"c_{tag}"]},
            bid=f"{pattern}-{tag}",
        )
        assert r.ok, r.errors
        stats[tag] = r.data["previews"][0]["stats"]
    # markings add strong light/dark contrast on the same sphere
    assert stats["marked"]["std"] > stats["plain"]["std"] + 0.05, stats


@pytest.mark.parametrize("pole_y, angle", [(-2.0, -90.0), (2.0, 90.0)])
def test_ik_pole_angle_does_not_twist_the_leg(fresh, pole_y, angle):
    # a marker hung off the side of the thigh must stay put when IK + pole are added at rest
    knee_y = -0.08 if pole_y < 0 else 0.08
    res = run(
        fresh,
        {"op": "create_empty", "id": "root", "location": [0, 0, 1.0]},
        {
            "op": "create_armature",
            "id": "rig",
            "parent": "root",
            "bones": [
                {"name": "up", "head": [0, 0, 0], "tail": [0, knee_y, -0.5]},
                {"name": "lo", "head": [0, knee_y, -0.5], "tail": [0, 0, -1.0], "parent": "up"},
            ],
        },
        {
            "op": "create_primitive",
            "id": "mark",
            "shape": "cube",
            "size": [0.05, 0.05, 0.05],
            "location": [0.3, 0, -0.25],
            "parent": "root",
        },
        {"op": "bind_mesh_to_armature", "mesh": "mark", "armature": "rig", "bone": "up"},
        {"op": "create_empty", "id": "tgt", "location": [0, 0, 0.0]},
        {"op": "create_empty", "id": "pole", "location": [0, pole_y, 0.5], "parent": "root"},
        {
            "op": "add_bone_constraint",
            "armature": "rig",
            "bone": "lo",
            "type": "ik",
            "subject": "tgt",
            "pole": "pole",
            "pole_angle": angle,
        },
        {"op": "inspect", "subjects": ["mark"], "frames": [1]},
    )
    assert res.ok, res.errors
    assert res.data["inspect"]["frames"]["1"]["subjects"]["mark"]["center"] == pytest.approx(
        [0.3, 0, 0.75], abs=0.01
    )


def _bent_tail(fresh, coat_before_bind: bool):
    """A striped tube skinned to a 2-bone chain that bends 50 deg between frames 1 and 10."""
    stripes = {
        "base_color": "#EEEEEE",
        "pattern": "stripes",
        "pattern_color": "#111111",
        "pattern_scale": 8.0,
    }
    ops = [
        {"op": "create_empty", "id": "body", "location": [0, 0, 1]},
        {
            "op": "create_armature",
            "id": "rig",
            "parent": "body",
            "bones": [
                {"name": "a", "head": [0, 0, 0], "tail": [0, 0.5, 0]},
                {"name": "b", "head": [0, 0.5, 0], "tail": [0, 1.0, 0], "parent": "a"},
            ],
        },
        {
            "op": "create_primitive",
            "id": "tube",
            "shape": "uv_sphere",
            "radius": 0.1,
            "scale": [1, 5, 1],
            "location": [0, 0.5, 0],
            "parent": "body",
        },
    ]
    mat = {"op": "set_material", "targets": ["tube"], "material": {**stripes, "name": "coat"}}
    bind = {"op": "bind_mesh_to_armature", "mesh": "tube", "armature": "rig", "bones": ["a", "b"]}
    ops += [mat, bind] if coat_before_bind else [bind, mat]
    ops += [
        {"op": "set_frame_range", "start": 1, "end": 10},
        {
            "op": "insert_keyframes",
            "target": "rig",
            "property": "bone:b.rotation",
            "keys": [[1, [0, 0, 0], "LINEAR"], [10, [50, 0, 0], "LINEAR"]],
        },
    ]
    run(fresh, *ops)
    r = run(fresh, {"op": "inspect", "subjects": ["tube"], "frames": [1, 10], "swim": ["tube"]})
    return r.data["inspect"]["frames"]["10"]["swim"]["tube"]


@pytest.mark.blender
def test_texture_swim_check_and_rest_position_pin(fresh):
    from animatica.creatures.qa import SWIM_P95

    swims = _bent_tail(fresh, coat_before_bind=True)  # set before the rig: Object coordinates, swims
    assert not swims["rest"] and swims["p95"] > SWIM_P95
    fresh.new_scene()
    pinned = _bent_tail(fresh, coat_before_bind=False)  # on a deforming mesh: rest_position
    assert pinned["rest"] and pinned["p95"] < 1e-5


@pytest.mark.blender
def test_eye_socket_snap_carry_and_seating(fresh):
    from animatica.creatures.qa import rig_checks

    run(
        fresh,
        {"op": "create_primitive", "id": "head", "shape": "uv_sphere", "radius": 0.2, "segments": 48},
        # an eye stuck on the outside of the head (the old look), and its iris
        {
            "op": "create_primitive",
            "id": "eye",
            "shape": "uv_sphere",
            "radius": 0.04,
            "location": [0, -0.23, 0],
        },
        {
            "op": "create_primitive",
            "id": "iris",
            "shape": "uv_sphere",
            "radius": 0.02,
            "location": [0, -0.26, 0],
        },
    )
    probe = {
        "op": "inspect",
        "subjects": ["head"],
        "frames": [1],
        "seating": [{"target": "eye", "surface": "head"}],
    }
    before = run(fresh, probe).data["inspect"]
    issues, _ = rig_checks(before)
    assert [i.check for i in issues] == ["eye_socket"]
    run(
        fresh,
        {
            "op": "snap_to_surface",
            "target": "eye",
            "surface": "head",
            "direction": [0, -1, 0],
            "offset": -0.012,
            "carry": ["iris"],
        },
    )
    after = run(fresh, probe).data["inspect"]
    issues, summary = rig_checks(after)
    assert not issues and 0.6 < summary["eye_embed"]["eye"][0] < 0.7
    q = run(fresh, {"op": "query", "ids": ["eye", "iris"]}).data["objects"]
    # the iris travelled with the eye: still 0.03 in front of it
    assert abs((q["eye"]["location"][1] - q["iris"]["location"][1]) - 0.03) < 1e-4


def test_transparent_render_gives_an_exact_silhouette(fresh, tmp_path):
    """Design sheets cut the silhouette from the side view's alpha (``set_render.transparent``)."""
    import numpy as np
    from PIL import Image

    r = run(
        fresh,
        {"op": "create_primitive", "id": "ball", "shape": "uv_sphere", "size": [1.0, 1.0, 1.0], "smooth": True},
        {"op": "add_camera", "id": "cam", "location": [0, -4, 0], "look_at": [0, 0, 0], "lens": 50},
        {"op": "set_camera_active", "id": "cam"},
        {"op": "set_render", "engine": "cycles", "samples": 2, "resolution": [64, 64], "transparent": True},
        {"op": "render_final", "output_dir": str(tmp_path / "f"), "frame_start": 1, "frame_end": 1},
    )
    assert r.ok, r.errors
    im = Image.open(next((tmp_path / "f").glob("*.png")))
    assert im.mode == "RGBA"
    a = np.asarray(im.getchannel("A"))
    assert a[0, 0] == 0 and a[32, 32] == 255  # world is transparent, the ball is opaque
