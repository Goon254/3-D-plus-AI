import pytest

from animatica.core.protocol import OP_NAMES, BatchValidationError, batch_json_schema, validate_batch


def b(*ops, **kw):
    return {"batch_id": "t", "ops": list(ops), **kw}


CUBE = {"op": "create_primitive", "id": "a", "shape": "cube"}


def test_valid_batch_parses():
    batch = validate_batch(b(CUBE, {"op": "transform", "target": "a", "location": [1, 2, 3]}))
    assert batch.ops[1].location == (1.0, 2.0, 3.0)


def test_minimum_op_set_present():
    required = {
        "create_primitive",
        "delete",
        "transform",
        "parent",
        "add_modifier",
        "set_material",
        "add_light",
        "add_camera",
        "set_camera_active",
        "insert_keyframes",
        "set_frame_range",
        "create_armature",
        "bind_mesh_to_armature",
        "import_asset",
        "add_sound_strip",
        "render_preview",
        "render_final",
        "query",
    }
    assert required <= set(OP_NAMES)


@pytest.mark.parametrize(
    "ops,needle",
    [
        ([{"op": "transform", "target": "nope", "location": [0, 0, 0]}], "unknown id 'nope'"),
        ([CUBE, CUBE], "duplicate id 'a'"),
        ([{**CUBE, "id": "1bad id"}], "invalid id"),
        ([{"op": "explode"}], "op"),
        ([CUBE, {"op": "set_material", "targets": ["a"], "material": {"base_color": "red"}}], "#RRGGBB"),
        (
            [
                CUBE,
                {
                    "op": "insert_keyframes",
                    "target": "a",
                    "property": "location",
                    "keys": [[10, [0, 0, 0], "LINEAR"], [5, [1, 0, 0], "LINEAR"]],
                },
            ],
            "strictly increasing",
        ),
        (
            [
                CUBE,
                {
                    "op": "insert_keyframes",
                    "target": "a",
                    "property": "location",
                    "keys": [[1, 2.0, "LINEAR"]],
                },
            ],
            "vector values",
        ),
        (
            [
                CUBE,
                {
                    "op": "insert_keyframes",
                    "target": "a",
                    "property": "warp_drive",
                    "keys": [[1, 2.0, "LINEAR"]],
                },
            ],
            "unsupported property",
        ),
        (
            [
                {
                    "op": "create_mesh",
                    "id": "m",
                    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                    "faces": [[0, 1, 7]],
                }
            ],
            "out of range",
        ),
        ([{**CUBE, "location": [float("nan"), 0, 0]}], "finite"),
        ([{"op": "set_frame_range", "start": 50, "end": 10}], "end 10 < start 50"),
    ],
)
def test_invalid_batches_rejected_with_precise_errors(ops, needle):
    with pytest.raises(BatchValidationError) as exc:
        validate_batch(b(*ops))
    assert any(needle in e for e in exc.value.errors), exc.value.errors


def test_existing_ids_are_known():
    validate_batch(b({"op": "delete", "targets": ["old"]}), existing_ids={"old"})


def test_delete_then_reference_fails():
    with pytest.raises(BatchValidationError):
        validate_batch(
            b(
                CUBE,
                {"op": "delete", "targets": ["a"]},
                {"op": "transform", "target": "a", "scale": [1, 1, 1]},
            )
        )


def test_locked_ids_cannot_be_modified():
    with pytest.raises(BatchValidationError) as exc:
        validate_batch(
            b({"op": "transform", "target": "hero", "location": [0, 0, 1]}, locked=["hero"]), {"hero"}
        )
    assert "locked" in exc.value.errors[0]


def test_script_mode_requires_script():
    with pytest.raises(BatchValidationError):
        validate_batch(b(mode="script"))


def test_300_op_batch_validates_fast():
    ops = [
        {"op": "create_primitive", "id": f"o{i}", "shape": "cube", "location": [i * 0.1, 0, 0]}
        for i in range(300)
    ]
    batch = validate_batch(b(*ops))
    assert len(batch.ops) == 300


def test_schema_exports():
    schema = batch_json_schema()
    assert schema["title"] == "Batch"
    assert "ops" in schema["properties"]


def test_scalar_keyframes_with_index():
    validate_batch(
        b(
            CUBE,
            {
                "op": "insert_keyframes",
                "target": "a",
                "property": "location",
                "index": 2,
                "keys": [[1, 0.0, "LINEAR"], [10, 1.0, "BEZIER"]],
            },
        )
    )
