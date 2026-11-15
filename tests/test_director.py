from animatica.agents.director import normalize_plan, scripted_plan
from animatica.core.plan import FilmPlan

NORTH_STAR = (
    "A curious little robot discovers a flower growing in a junkyard at sunset. It says: 'Hello, little one.'"
)


def plan(prompt):
    return normalize_plan(FilmPlan.model_validate(scripted_plan(prompt)), prompt)


def test_north_star_plan():
    p = plan(NORTH_STAR)
    assert p.hero.kind == "robot"
    assert p.setting.kind == "junkyard" and p.setting.time_of_day == "sunset"
    assert p.prop.kind == "flower"
    assert [d.text for d in p.dialogue] == ["Hello, little one."]
    assert 15 <= p.duration <= 30
    assert [s.beat for s in p.shots] == ["enter", "discover", "speak", "settle"]


def test_deterministic():
    assert scripted_plan(NORTH_STAR) == scripted_plan(NORTH_STAR)


def test_other_prompts_parse():
    p = plan("A sleepy blue cat finds a glowing crystal in a snowy forest at night.")
    assert p.hero.kind == "critter" and p.prop.kind == "crystal"
    assert p.setting.time_of_day == "night"
    assert p.dialogue == [] and 15 <= p.duration <= 30
    p2 = plan(
        'A tiny green robot plays with a ball on the beach. It shouts "Catch!" and then "Again, again!"'
    )
    assert p2.setting.kind == "beach" and p2.prop.kind == "ball"
    assert len(p2.dialogue) == 2


def test_frames_contiguous():
    p = plan(NORTH_STAR)
    fr = list(p.shot_frames().values())
    assert fr[0][0] == 1
    for (_a0, a1), (b0, _) in zip(fr, fr[1:]):
        assert b0 == a1 + 1
    assert p.frame_end == fr[-1][1]


def test_story_arcs_vary_with_the_prompt():
    lonely = plan(
        "A lonely robot sits in a junkyard at dusk until a flower blooms. It says: 'You came back.' Then it heads home."
    )
    assert [s.beat for s in lonely.shots] == ["idle", "discover", "speak", "exit"]
    playful = plan("A happy robot plays with a ball on the beach.")
    assert playful.shots[-1].beat == "celebrate"


def test_exit_verbs_and_locomotion():
    for verb in ("hops away", "runs off", "flies home", "scampers off", "wanders away", "leaves"):
        p = plan(f"A small fox finds a lantern in a snowy forest at night and then {verb}.")
        assert p.shots[-1].beat == "exit", verb
    fox = plan("A small fox finds a lantern in a meadow.")
    assert "hops into" in fox.shots[0].description
    assert "rolls into" in plan("A robot finds a ball.").shots[0].description


def test_celebrate_verb_fits_the_hero():
    assert "bounces for joy" in plan("A happy robot plays with a ball on the beach.").shots[-1].description
    assert "hops for joy" in plan("A happy fox plays with a ball on the beach.").shots[-1].description


def test_set_dressing_pebbles_and_heap_silhouettes():
    from animatica.agents.asset import set_ops

    p = plan(NORTH_STAR)
    ops = set_ops(p, 1.0, 7, [])
    pebbles = [o for o in ops if o.get("id", "").startswith("set_pebble_")]
    assert len(pebbles) >= 30
    # never on the hero's travel lane (wheels and feet would cut through them)
    assert all(not (-9.5 < o["location"][0] < 4.5 and abs(o["location"][1]) < 0.7) for o in pebbles)
    piles = [o for o in ops if o.get("id", "").startswith("set_pile_") and "_junk" not in o["id"]]
    assert piles and all(o.get("smooth") and o["segments"] >= 64 for o in piles)
    junk = [o for o in ops if o.get("id", "").startswith("set_pile_") and "_junk" in o["id"]]
    assert len(junk) == 5 * len(piles)
    ground = next(o for o in ops if o["op"] == "set_material" and o["targets"] == ["set_ground"])
    assert ground["material"]["grain"] > 0 and ground["material"]["bump"] > 0
