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
    batch = {
        "agent": "asset",
        "ops": [
            {
                "op": "set_material",
                "targets": ["hero_body", "hero_head"],
                "material": {"base_color": "#FF0000"},
            },
            {"op": "transform", "target": "rock", "location": [0, 0, 0]},
            {"op": "transform", "target": "hero_body", "location": [0, 0, 1]},
        ],
    }
    out = ctx.filter_locked(batch)["ops"]
    assert out[0]["targets"] == ["hero_head"]
    assert [o["op"] for o in out] == ["set_material", "transform"]
    assert out[1]["target"] == "hero_body"


def test_knowledge_lookup():
    from animatica.knowledge import lookup

    hits = lookup("sunset lighting key fill")
    assert hits and "Lighting" in hits[0]["section"]
    assert lookup("fcurves channelbags")[0]["doc"] == "blender_api"


def test_critic_dialogue_framing_checks():
    from animatica.agents.critic import dialogue_framing_issues

    def frame(face_h, face_vis, prop_vis):
        return {
            "subjects": {
                "hero_face": {"screen_height": face_h, "visible_fraction": face_vis},
                "prop": {"visible_fraction": prop_vis},
            }
        }

    frames = {"100": frame(0.12, 1.0, 1.0), "110": frame(0.3, 0.8, 0.3), "300": frame(0.01, 0.0, 0.0)}
    issues = dialogue_framing_issues("s3", frames, [(95, 120)], "flower")
    checks = {i.check: i for i in issues}
    assert set(checks) == {"face_too_small", "face_cut", "addressee_cut"}
    assert checks["face_too_small"].fix["fill_mul"] > 1.5  # zoom in
    assert checks["face_cut"].fix["fill_mul"] < 1
    assert dialogue_framing_issues("s3", {"100": frame(0.3, 1.0, 1.0)}, [(95, 120)], "flower") == []


def test_wheel_spin_rolls_by_distance_without_skating():
    import math

    from animatica.agents.animator import wheel_spin_degrees
    from animatica.agents.asset import robot_ops

    r = 0.075
    xs = [0.0, 0.01, 0.03, 0.03, 0.02]  # forward, faster, stop, then drive back (hero yaws to face travel)
    spin = wheel_spin_degrees(xs, r)
    assert spin[0] == 0.0
    assert spin[2] == pytest.approx(math.degrees(0.03 / r))  # slow: physically exact
    assert spin[3] == spin[2]  # standing still: wheels don't turn
    assert spin[4] > spin[3]  # always rolls forward
    assert all(b >= a for a, b in zip(spin, spin[1:]))
    fast = wheel_spin_degrees([0.0, 0.5, 1.0], r)  # 0.5 m/frame would strobe: capped
    assert max(b - a for a, b in zip(fast, fast[1:])) <= 35.0
    # every wheel is an animatable pivot with a spoke + off-centre bolt so the rotation is visible
    ids = {o["id"] for o in robot_ops("#E08A2E", "#BFF4FF", "#2B3A55") if "id" in o}
    for side in "LR":
        for j in range(3):
            assert {
                f"hero_wheel_{side}{j}",
                f"hero_cog_{side}{j}",
                f"hero_spoke_{side}{j}",
                f"hero_bolt_{side}{j}",
            } <= ids


def test_critter_hops_instead_of_gliding():
    from animatica.agents.animator import hop_locomotion

    fps = 24
    xs = [min(2.0, 0.05 * i) for i in range(80)]  # glides 2 m at 1.2 m/s, then stands
    hx, lift, land = hop_locomotion(xs, fps)
    p = round(0.42 * fps)
    # cycle boundaries keep the planned positions; the end position is unchanged
    assert all(hx[k] == pytest.approx(xs[k]) for k in range(0, 40, p))
    assert hx[-1] == pytest.approx(2.0)
    # there are stationary contact frames while moving (no gliding) and airborne frames with lift
    still = [i for i in range(1, 40) if hx[i] == hx[i - 1]]
    assert still and max(lift[:40]) > 0.1
    assert all(lift[i] == 0.0 for i in still)
    assert max(land) > 0.5
    # standing still: no hops
    assert max(lift[50:]) == 0.0 and max(land[50:]) == 0.0


@pytest.mark.parametrize(
    "prompt",
    [
        "A lonely robot sits in a junkyard at dusk until a flower blooms. It says: 'You came back.' Then it heads home.",
        "A small fox finds a lantern in a snowy forest at night and then hops away.",
    ],
)
def test_exit_beat_leaves_and_camera_holds(tmp_path, prompt):
    from animatica.agents.animator import Animator, default_performance
    from animatica.agents.director import normalize_plan, scripted_plan
    from animatica.core.plan import FilmPlan
    from animatica.core.state import ProjectState

    plan = normalize_plan(FilmPlan.model_validate(scripted_plan(prompt)), prompt)
    st = ProjectState(root=tmp_path, plan=plan)
    ctx = Context(st, None, _Log(), ScriptedProvider(), None)
    perf = default_performance(plan.model_dump(mode="json"))
    rig, notes = Animator(ScriptedProvider()).build_rig(ctx, perf)
    ex = notes["exit"]
    f0, f1 = plan.shot_frames()[ex["shot"]]
    t1 = f1 / plan.fps
    # holds still (turn + look back) until it departs, then travels well clear of the departure point
    assert rig.root_x(ex["depart_t"]) == pytest.approx(ex["from_x"])
    assert ex["from_x"] - rig.root_x(t1) > 5.0
    # it is still moving at the end (it doesn't stop just outside the frame line)
    assert rig.root_x(t1 - 0.5) - rig.root_x(t1) > 0.8
    # artist/critic tuning makes it leave faster
    st.tuning = {"animator": {"exit_speed_mul": 1.3}}
    rig2, _ = Animator(ScriptedProvider()).build_rig(ctx, perf)
    assert rig2.root_x(t1) < rig.root_x(t1) - 1.0


def test_critic_exit_must_leave_the_frame():
    from animatica.agents.critic import exit_issues

    def fr(vis):
        return {"subjects": {"hero_root": {"visible_fraction": vis, "behind_camera": False}}}

    still_there = {"400": fr(1.0), "450": fr(1.0), "500": fr(0.6)}
    issues = exit_issues("s4", still_there, 420)
    assert [i.check for i in issues] == ["exit_in_frame"] and issues[0].fix["exit_speed_mul"] > 1
    gone = {"400": fr(1.0), "450": fr(0.5), "500": fr(0.0)}
    assert exit_issues("s4", gone, 420) == []


def test_critic_eyeline_and_addressee_thresholds():
    from animatica.agents.critic import dialogue_framing_issues

    def frame(facing, prop_vis):
        return {
            "facing_deg": facing,
            "subjects": {
                "hero_head": {"screen_height": 0.4, "visible_fraction": 1.0},
                "prop": {"visible_fraction": prop_vis},
            },
        }

    # the fox close-up of review 14:50: 3/4-away head (43 deg) and the lantern 55 % in frame
    away = {"100": frame(43, 0.55), "103": frame(44, 0.56), "106": frame(42, 0.55)}
    issues = {
        i.check: i
        for i in dialogue_framing_issues("s3", away, [(95, 120)], "lantern", "closeup", "hero_head")
    }
    assert issues["face_turned_away"].severity == "blocker"
    assert (
        issues["face_turned_away"].fix["kind"] == "animator"
        and issues["face_turned_away"].fix["face_cam_add"] > 0
    )
    assert issues["addressee_cut"].severity == "blocker" and issues["addressee_cut"].fix["fill_mul"] < 1
    # 65 % fails a close-up (0.8) but passes a wide (0.6); a face 22 deg off the lens is fine
    part = {"100": frame(22, 0.65)}
    assert {i.check for i in dialogue_framing_issues("s3", part, [(95, 120)], "lantern")} == {"addressee_cut"}
    assert dialogue_framing_issues("s1", part, [(95, 120)], "lantern", "wide", "hero_head") == []
    good = {"100": frame(22, 0.95)}
    assert dialogue_framing_issues("s3", good, [(95, 120)], "lantern", "closeup", "hero_head") == []


def test_critic_face_floor_per_kind_and_dialogue_singles():
    from animatica.agents.critic import dialogue_framing_issues

    def frame(head_h, prop_vis):
        return {
            "subjects": {
                "hero_head": {"screen_height": head_h, "visible_fraction": 1.0},
                "prop": {"visible_fraction": prop_vis},
            }
        }

    # a critter's head at 25 % of the frame: fine for a robot screen face (20 %), too small for a snout mouth
    issues = dialogue_framing_issues(
        "s3", {"100": frame(0.25, 1.0)}, [(95, 120)], "lantern", face="hero_head"
    )
    assert [i.check for i in issues] == ["face_too_small"] and issues[0].fix["fill_mul"] > 1
    # a head-and-shoulders single deliberately leaves the addressee out: no addressee_cut there
    single = dialogue_framing_issues(
        "s3", {"100": frame(0.5, 0.1)}, [(95, 120)], "lantern", face="hero_head", addressee=False
    )
    assert single == []


@pytest.mark.parametrize(
    "prompt",
    [
        "A curious little robot discovers a flower growing in a junkyard at sunset. It says: 'Hello, little one.'",
        "A tiny fox finds a glowing lantern in a snowy forest at night. It whispers: 'Are you lost too?' Then it hops away.",
    ],
)
def test_acting_beats_discovery_pause_and_glance_after_the_line(tmp_path, prompt):
    from animatica.agents.animator import Animator, default_performance
    from animatica.agents.director import normalize_plan, scripted_plan
    from animatica.core.plan import FilmPlan
    from animatica.core.state import ProjectState

    plan = normalize_plan(FilmPlan.model_validate(scripted_plan(prompt)), prompt)
    ctx = Context(ProjectState(root=tmp_path, plan=plan), None, _Log(), ScriptedProvider(), None)
    rig, notes = Animator(ScriptedProvider()).build_rig(
        ctx, default_performance(plan.model_dump(mode="json"))
    )
    # discovery: a cautious approach that stops halfway, leans in and tilts the head (not a straight glide)
    p = notes["discover_pause"]
    assert rig.root_x(p["t"] + 0.05) == pytest.approx(p["x"]) == pytest.approx(rig.root_x(p["t"] + 0.5))
    assert rig.root_x(p["t"]) < notes["stand_x"] - 0.1
    assert rig.head_tilt(p["t"] + 0.4) > 10 and rig.lean(p["t"] + 0.35) > rig.lean(p["t"]) + 4
    # after the line: the head turns from the camera cheat toward the addressee and nods down, then returns
    g = notes["glances"][0]
    cheat = notes["face_cheat_deg"]
    assert rig.head_turn(g) == pytest.approx(cheat, abs=1)
    assert rig.head_turn(g + 0.6) > cheat + 20 and rig.head_nod(g + 0.6) > rig.head_nod(g) + 6
    assert rig.head_turn(g + 1.35) == pytest.approx(cheat, abs=1)
