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


def test_species_reads_from_the_prompt_and_drives_the_recipe():
    from animatica.agents.asset import critter_ops

    cases = {"A tiny fox in the snow": "fox", "A rabbit in a meadow": "bunny", "A cat naps": "cat"}
    for prompt, species in cases.items():
        assert scripted_plan(prompt)["characters"][0]["species"] == species
    assert scripted_plan("A tiny fox in the snow")["characters"][0]["color"] == "#E0712B"  # orange coat

    ids = {op["id"] for op in critter_ops("#E0712B", "#7FE7FF", "#333333", species="fox") if "id" in op}
    # species-defining parts: a matched pair of pointed ears with dark tips, a snout, a white-tipped
    # bushy tail, four legs (front legs = the rig's arms, hind paws on the root), eyes with catch-lights
    for part in (
        "hero_ear_L",
        "hero_ear_R",
        "hero_ear_tip_L",
        "hero_ear_tip_R",
        "hero_muzzle",
        "hero_tail",
        "hero_tail_tip",
        "hero_arm_L",
        "hero_arm_R",
        "hero_paw_L",
        "hero_paw_R",
        "hero_foot_L",
        "hero_foot_R",
        "hero_eye_glint_L",
        "hero_eye_glint_R",
    ):
        assert part in ids, part
    generic = {op["id"] for op in critter_ops("#E8A15A", "#7FE7FF", "#333333") if "id" in op}
    assert "hero_muzzle" not in generic and "hero_ear_L" in generic and "hero_mouth" in generic


def test_snow_pebbles_are_rock_not_puddles_and_horizon_has_a_ridge():
    from animatica.agents.asset import set_ops

    def ops_for(prompt):
        plan = normalize_plan(FilmPlan.model_validate(scripted_plan(prompt)), prompt)
        return plan, set_ops(plan, 1.0, 7, [])

    plan, ops = ops_for("A tiny fox finds a lantern in a snowy forest at night.")
    peb = next(o for o in ops if o.get("op") == "set_material" and "set_pebble_0" in o["targets"])
    r, g, b = (int(peb["material"]["base_color"][i : i + 2], 16) for i in (1, 3, 5))
    assert max(r, g, b) - min(r, g, b) < 20 and max(r, g, b) < 110  # neutral dark rock, not blue
    _, ops = ops_for("A robot finds a flower in a junkyard at sunset.")
    ridge = [o for o in ops if o.get("id", "").startswith("set_ridge_")]
    assert len(ridge) >= 8
    import math

    for o in ridge:  # far away, low: peaks under 2.6 deg so the sunset disc stays visible
        d = math.hypot(*o["location"][:2])
        assert 55 < d < 82 and o["radius"] * o["scale"][2] / d < math.tan(math.radians(2.6))
    # heap junk spread around the crest, not bunched on one side
    junk = [o for o in ops if o.get("id", "").startswith("set_pile_0_junk")]
    pile = next(o for o in ops if o.get("id") == "set_pile_0")
    angs = sorted(
        math.atan2(o["location"][1] - pile["location"][1], o["location"][0] - pile["location"][0])
        for o in junk
    )
    gaps = [b - a for a, b in zip(angs, angs[1:])] + [angs[0] + 2 * math.pi - angs[-1]]
    assert max(gaps) < math.radians(150)


def test_night_lantern_light_escapes_its_glass_and_snow_rocks_are_few_and_large():
    from animatica.agents.asset import critter_ops, prop_ops, set_ops
    from animatica.core.protocol import parse_batch

    ops, _ = prop_ops("lantern", "#FFC857", (1.0, 0.0, 0.0), glow=1.5)
    glass = next(o for o in ops if o.get("id") == "prop_glass")
    light = next(o for o in ops if o.get("id") == "prop_light")
    # the point light sits inside the glass: the glass must not shadow it (review 11-16 17:55)
    assert glass["cast_shadow"] is False and light["energy"] >= 70
    gems, _ = prop_ops("crystal", "#88CCFF", (1.0, 0.0, 0.0))
    assert all(o["cast_shadow"] is False for o in gems if o.get("id") in ("prop_gem", "prop_gem_2"))
    parse_batch({"batch_id": "b", "ops": ops})  # the protocol accepts cast_shadow

    snow = normalize_plan(
        FilmPlan.model_validate(scripted_plan("A tiny fox finds a lantern in a snowy forest at night.")),
        "A tiny fox finds a lantern in a snowy forest at night.",
    )
    rocks = [o for o in set_ops(snow, 1.0, 7, []) if o.get("id", "").startswith("set_pebble_")]
    dirt = [o for o in set_ops(plan(NORTH_STAR), 1.0, 7, []) if o.get("id", "").startswith("set_pebble_")]
    assert len(rocks) <= len(dirt) // 2
    mean = lambda xs: sum(o["radius"] for o in xs) / len(xs)  # noqa: E731
    assert mean(rocks) > 2 * mean(dirt)

    fur = next(
        o
        for o in critter_ops("#E0712B", "#7FE7FF", "#333333", species="fox")
        if o.get("op") == "set_material" and o["material"].get("name") == "hero_fur"
    )
    assert fur["material"]["sheen"] > 0.3 and fur["material"]["sheen_tint"]
