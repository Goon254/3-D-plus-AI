"""Milestone 5: hand edits survive `continue` and `revise`."""

import pytest

from animatica.core.continuation import continue_project, revise_project, scripted_revise
from animatica.core.engine import BlenderSession
from animatica.core.orchestrator import Studio
from animatica.core.state import ProjectState

PROMPT = "A curious little robot discovers a flower growing in a junkyard at sunset. It says: 'Hello, little one.'"
OPTS = {"quality": "ci", "tts_engine": "synth", "preview_engine": "workbench", "critic_iterations": 1, "no_render": True}


def test_scripted_revise_parser():
    plan = {"characters": [{"name": "Bolt", "kind": "robot"}], "props": [{"kind": "flower"}]}
    edits = scripted_revise({"instruction": "make the robot blue and slow down shot 2", "plan": plan})["edits"]
    assert edits == [{"type": "recolor", "target": "hero", "color": "#3A78C8"},
                     {"type": "speed", "shot": "s2", "factor": 0.7}]


@pytest.mark.blender
@pytest.mark.slow
def test_hand_edits_are_preserved(tmp_path):
    Studio("scripted", OPTS, echo=False).film(PROMPT, tmp_path, "p")
    root = tmp_path / "p"
    # --- the "artist" opens the .blend, recolours the robot's body and moves the wrecked car, saves
    with BlenderSession(workdir=tmp_path) as s:
        s.open(root / "scene.blend")
        res = s.run_batch({"batch_id": "artist", "agent": "human", "ops": [
            {"op": "set_material", "targets": ["hero_body"], "material": {"base_color": "#22AA55", "name": "artist_green"}},
            {"op": "transform", "target": "set_car", "location": [6.5, 3.0, 0.5]},
            {"op": "save", "path": str(root / "scene.blend")}]})
        assert res.ok, res.errors

    continue_project(root, provider="scripted", options=OPTS)
    st = ProjectState.load(root)
    assert "material" in st.locked["hero_body"] and "transform" in st.locked["set_car"]

    def check(s):
        q = s.run_batch({"batch_id": "q", "ops": [{"op": "query", "ids": ["hero_body", "set_car", "hero_head"],
                                                   "fields": ["transform", "material"]}]}).data["objects"]
        assert q["hero_body"]["material"]["base_color"] == "#22AA55"
        assert q["set_car"]["location"] == [6.5, 3.0, 0.5]
        return q

    with BlenderSession(workdir=tmp_path) as s:
        s.open(root / "scene.blend")
        check(s)

    # --- a targeted revision: recolour the robot (body stays the artist's green) and slow down shot 2
    before = {sh.id: sh.duration for sh in st.plan.shots}
    revise_project(root, "make the robot blue and slow down shot 2", provider="scripted", options=OPTS)
    st2 = ProjectState.load(root)
    assert st2.plan.shots[1].duration > before["s2"]
    assert st2.plan.shots[0].duration == before["s1"]
    with BlenderSession(workdir=tmp_path) as s:
        s.open(root / "scene.blend")
        q = check(s)
        assert q["hero_head"]["material"]["base_color"] == "#3A78C8"
