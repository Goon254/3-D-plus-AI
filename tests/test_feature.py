"""Feature mode (docs/FEATURE_MODE.md): the story engine and the stage machine with its owner gates."""

import json
from pathlib import Path

import pytest

from animatica.core.llm import ScriptedProvider
from animatica.feature import NEXT_STEP, animatic_path, approve, film_path, next_stage, run, slug, status
from animatica.feature.story import species_in, validate_premise, validate_screenplay, write_story

IDEA = "a shy tortoise and a fast horse race to the river before sunset"


def test_animals_map_to_the_body_plans_the_library_builds():
    order, mapped = species_in(IDEA)
    assert order == ["tortoise", "zebra"] and mapped == {"horse": "zebra"}
    assert species_in("an elephant calf")[0] == ["elephant"]


def test_the_offline_story_engine_writes_a_valid_premise_and_screenplay():
    prem, play = write_story(IDEA, ScriptedProvider())
    assert not validate_premise(prem) and not validate_screenplay(play, prem)
    assert [c["species"] for c in prem["cast"]][:2] == ["tortoise", "zebra"]
    assert "river" in prem["logline"]
    assert write_story(IDEA, ScriptedProvider()) == (prem, play)  # same idea, same story


def test_validation_catches_what_production_cant_make():
    prem, play = write_story(IDEA, ScriptedProvider())
    bad = json.loads(json.dumps(prem))
    bad["cast"][0]["species"] = "dragon"
    assert any("dragon" in e for e in validate_premise(bad))
    play["scenes"][0]["lines"].append({"who": "owl", "text": "Hoo.", "mood": "neutral"})
    play["scenes"][1]["lines"][0]["text"] = " ".join(["word"] * 30)
    errs = validate_screenplay(play, prem)
    assert any("owl" in e for e in errs) and any("25 words" in e for e in errs)


def test_the_stages_resume_and_stop_at_the_owner_gates(tmp_path):
    film = tmp_path / "films" / slug(IDEA)
    assert next_stage(film).name == "story"
    log = run(film, IDEA, ScriptedProvider())
    assert (film / "01_premise.json").exists() and (film / "04_screenplay.json").exists()
    st = {s.name: s for s in status(film)}
    assert st["story"].done and not st["design"].ready and next_stage(film).name == "design"
    assert any(line.startswith("next: run the design loop") for line in log)
    with pytest.raises(ValueError):  # nothing to look at yet
        approve(film, "design")
    for c in json.loads((film / "01_premise.json").read_text(encoding="utf-8"))["cast"]:
        (film / "design" / c["id"]).mkdir(parents=True)
        (film / "design" / c["id"] / "approved.json").write_text("{}", encoding="utf-8")
    st = {s.name: s for s in status(film)}
    assert st["design"].ready and st["design"].state == "awaiting owner" and next_stage(film).name == "design"
    approve(film, "design", "looks good")
    assert (film / "06_voices.json").exists()  # casting ran with the story
    assert next_stage(film).name == "scenes"
    before = (film / "01_premise.json").read_text(encoding="utf-8")
    run(film, None, ScriptedProvider())  # a second run doesn't redo the story
    assert (film / "01_premise.json").read_text(encoding="utf-8") == before
    with pytest.raises(ValueError):
        approve(film, "story")


def test_casting_gives_every_character_a_distinct_voice():
    from animatica.feature.casting import cast_voices

    prem, _ = write_story(IDEA, ScriptedProvider())
    v = cast_voices(prem)
    assert set(v["cast"]) == {"narrator"} | {c["id"] for c in prem["cast"]}
    keys = [(c["voice"], c["pitch"]) for c in v["cast"].values()]
    assert len(set(keys)) == len(keys) and all(c["ref_text"] for c in v["cast"].values())
    # five tortoises still get five different voices
    many = {"cast": [{"id": f"t{i}", "species": "tortoise", "personality": "old and wise"} for i in range(5)]}
    keys = [(c["voice"], c["pitch"]) for c in cast_voices(many)["cast"].values()]
    assert len(set(keys)) == len(keys)


def test_the_planned_scenes_load_schedule_and_pass_continuity():
    from animatica.feature.planner import check_plan, plan_scenes
    from animatica.production.scene import scene_from_dict

    prem, play = write_story(IDEA, ScriptedProvider())
    plan = plan_scenes(play, prem)
    assert [s["id"] for s in plan["scenes"]] == [s["id"] for s in play["scenes"]]
    assert check_plan(plan) == []
    for d in plan["scenes"]:
        spec = scene_from_dict(d)
        speakers = {ln.who for ln in spec.lines} - {"narrator"}
        assert speakers <= set(spec.cast)  # everyone who speaks is on stage
        assert spec.shots[0].type == "ews" and spec.shots[-1].type == "ws"


def test_the_full_flow_plans_scenes_after_the_design_gate(tmp_path):
    film = tmp_path / "films" / "race"
    run(film, IDEA, ScriptedProvider())
    for c in json.loads((film / "01_premise.json").read_text(encoding="utf-8"))["cast"]:
        (film / "design" / c["id"]).mkdir(parents=True)
        (film / "design" / c["id"] / "approved.json").write_text("{}", encoding="utf-8")
    run(film, None, ScriptedProvider())
    assert not (film / "07_scenes.json").exists()  # the owner hasn't passed the design gate
    approve(film, "design")
    log = run(film, None, ScriptedProvider())
    assert (film / "07_scenes.json").exists() and any(line.startswith("scenes: 5 planned") for line in log)
    assert next_stage(film).name == "animatic"


def test_the_cue_sheet_gives_every_scene_a_cue_the_composer_reads(tmp_path):
    from animatica.audio import composer
    from animatica.feature.planner import plan_cues

    prem, play = write_story(IDEA, ScriptedProvider())
    p = tmp_path / "05_cue_sheet.json"
    p.write_text(json.dumps(plan_cues(play, prem["title"])), encoding="utf-8")
    cues = composer.load_cue_sheet(p)
    assert [c.id for c in cues] == [s["id"] for s in play["scenes"]]
    assert cues[0].sections[0].mood == "wonder" and cues[-1].sections[-1].mood == "triumph"
    for c in cues:  # every cue arranges
        assert composer.arrange(c).bars > 0


def test_a_feature_films_animatic_lands_where_its_gate_looks(tmp_path, monkeypatch):
    """The animatic hint names the script; the script's defaults for a feature film write the file the
    animatic gate checks, and never the savannah's showcase copy."""
    import importlib

    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    sa = importlib.import_module("savannah_animatic")
    film = tmp_path / "films" / "kiki-and-the-lost-rain"
    film.mkdir(parents=True)
    work, out = sa.default_paths(film, None, None)
    assert Path(out) == animatic_path(film.resolve()) and Path(work) == Path(out).parent
    assert "showcase" not in out
    work, out = sa.default_paths(sa.FILM, None, None)  # the savannah keeps its showcase paths
    assert Path(out).parts[-3:] == ("showcase", "savannah-animatic", "animatic.mp4")
    assert sa.default_paths(film, "w", "o.mp4") == ("w", "o.mp4")
    nxt = NEXT_STEP["animatic"].format(film=film, animatic=animatic_path(film), out=film_path(film).parent)
    assert "savannah_animatic.py --film" in nxt and str(animatic_path(film)) in nxt
