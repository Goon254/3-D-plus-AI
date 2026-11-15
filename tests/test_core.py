import pytest

from animatica.core.llm import LLMError, ScriptedProvider, extract_json
from animatica.core.orchestrator import Context, TaskGraph


def test_extract_json_handles_fences():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('prefix {"b": [1, 2]} suffix') == {"b": [1, 2]}
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_scripted_provider_unknown_task():
    with pytest.raises(LLMError):
        ScriptedProvider().complete_json("nope", "", {})


def test_task_graph_order_and_cycles():
    g = TaskGraph()
    g.add("c", lambda: 3, ["b"])
    g.add("a", lambda: 1)
    g.add("b", lambda: 2, ["a"])
    assert g.order() == ["a", "b", "c"]
    g.add("a", lambda: 1, ["c"])
    with pytest.raises(ValueError):
        g.order()


class _Log:
    def __init__(self):
        self.events = []

    def event(self, *a, **k):
        self.events.append(a)


def test_filter_locked_keeps_artist_edits(tmp_path):
    from animatica.core.state import ProjectState

    st = ProjectState(root=tmp_path, locked={"hero_body": ["material"], "rock": ["transform"]})
    ctx = Context(st, None, _Log(), ScriptedProvider(), None)
    batch = {"agent": "asset", "ops": [
        {"op": "set_material", "targets": ["hero_body", "hero_head"], "material": {"base_color": "#FF0000"}},
        {"op": "transform", "target": "rock", "location": [0, 0, 0]},
        {"op": "transform", "target": "hero_body", "location": [0, 0, 1]},
    ]}
    out = ctx.filter_locked(batch)["ops"]
    assert out[0]["targets"] == ["hero_head"]
    assert [o["op"] for o in out] == ["set_material", "transform"]
    assert out[1]["target"] == "hero_body"


def test_knowledge_lookup():
    from animatica.knowledge import lookup

    hits = lookup("sunset lighting key fill")
    assert hits and "Lighting" in hits[0]["section"]
    assert lookup("fcurves channelbags")[0]["doc"] == "blender_api"
