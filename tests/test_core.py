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
