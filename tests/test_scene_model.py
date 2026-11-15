from animatica.core.protocol import validate_batch
from animatica.core.scene_model import SceneModel


def model():
    m = SceneModel()
    m.apply(
        validate_batch(
            {
                "batch_id": "x",
                "ops": [
                    {"op": "create_primitive", "id": "box", "shape": "cube", "location": [1, 0, 0]},
                    {"op": "set_material", "targets": ["box"], "material": {"base_color": "#ff0000"}},
                    {"op": "create_empty", "id": "root"},
                    {"op": "parent", "child": "box", "parent": "root"},
                ],
            }
        )
    )
    return m


def test_replay_tracks_prims():
    m = model()
    assert m.prims["box"].material == "#FF0000"
    assert m.prims["box"].parent == "root"
    assert m.prims["box"].translate == [1.0, 0.0, 0.0]


def test_diff_detects_artist_edits():
    m = model()
    snap = {
        "box": {
            "type": "mesh",
            "location": [2, 0, 0],
            "rotation": [0, 0, 0],
            "scale": [1, 1, 1],
            "material": {"base_color": "#0000FF"},
            "parent": "root",
        },
        "lamp": {"type": "light", "location": [0, 0, 3]},
    }
    changes = m.diff_snapshot(snap)
    assert changes["box"] == ["transform", "material"]
    assert changes["lamp"] == ["added"]
    assert changes["root"] == ["deleted"]


def test_spec_to_ops_emits_only_deltas():
    m = model()
    ops = m.spec_to_ops(
        {
            "objects": {
                "box": {"location": [1, 0, 0], "scale": [2, 2, 2]},
                "ball": {"create": {"shape": "uv_sphere"}, "location": [0, 0, 1]},
                "root": {"delete": True},
            }
        }
    )
    kinds = [o["op"] for o in ops]
    assert kinds == ["transform", "create_primitive", "delete"]
    assert "location" not in ops[0]


def test_usda_export_is_usd_shaped():
    text = model().to_usda()
    assert text.startswith("#usda 1.0")
    assert 'def Xform "root"' in text and "xformOp:translate" in text


def test_roundtrip_dict():
    m = model()
    m2 = SceneModel.from_dict(m.to_dict())
    assert m2.prims.keys() == m.prims.keys()
