"""Milestone 7: a playable Godot game is generated and the Playtester confirms it runs without errors."""

import pytest

from animatica.games import godot
from animatica.games.studio import build_level, check_reachability, make_game, scene_batch, scripted_design


def test_design_and_level_are_reachable():
    d = scripted_design({"prompt": "a 2D platformer where a robot collects flowers"})
    assert d["hero"] == "robot" and d["collectible"] == "flower"
    level = build_level(d)
    assert len(level["collectibles"]) == d["count"]
    assert check_reachability(d, level) == []
    assert godot.validate_godot_batch(scene_batch(d, level)) == []


def test_godot_batch_validation_errors():
    errs = godot.validate_godot_batch({"ops": [
        {"op": "create_node", "id": "Main", "type": "Node2D", "parent": None},
        {"op": "create_node", "id": "Main", "type": "Node2D", "parent": "Main"},
        {"op": "add_shape", "target": "Ghost", "shape": "rect", "size": [1, 1]},
        {"op": "explode"}]})
    assert any("duplicate" in e for e in errs) and any("unknown id 'Ghost'" in e for e in errs)
    assert any("unsupported" in e for e in errs)


@pytest.mark.skipif(godot.godot_bin() is None, reason="Godot 4 not installed")
def test_generated_game_is_playable(tmp_path):
    out = make_game("a 2D platformer where a robot collects flowers", tmp_path, "g", provider="scripted")
    rep = out["playtest"]
    assert rep["started"] and rep["errors"] == []
    assert rep["won"] and rep["collected"] == rep["total"] == 6
    assert (tmp_path / "g" / "godot" / "main.tscn").exists()
