"""Anthropic provider plumbing (no network) and the agent fallback path."""

import json

from animatica.agents.director import Director
from animatica.core.llm import AnthropicProvider, Provider


def test_anthropic_provider_parses_and_counts(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    p = AnthropicProvider(model="claude-test")
    sent = {}

    def fake_post(body):
        sent.update(body)
        return {"content": [{"type": "text", "text": "Here you go:\n```json\n{\"ok\": true}\n```"}],
                "usage": {"input_tokens": 120, "output_tokens": 30}}

    monkeypatch.setattr(p, "_post", fake_post)
    assert p.complete_json("director.plan", "sys", {"prompt": "hi"}) == {"ok": True}
    assert sent["model"] == "claude-test" and sent["system"] == "sys"
    assert json.loads(sent["messages"][0]["content"][-1]["text"].split("\n")[0]) == {"prompt": "hi"}
    assert p.usage.total_tokens == 150 and p.usage.by_task == {"director.plan": 1}


class BrokenProvider(Provider):
    name = "broken"

    def complete_json(self, task, system, payload, images=None, max_tokens=4096):
        return {"title": "x", "shots": "not a list"}


class _Log:
    def __init__(self):
        self.events = []

    def event(self, kind, agent, message, **data):
        self.events.append((kind, agent, message))


class _Ctx:
    def __init__(self, tmp_path):
        from animatica.core.state import ProjectState

        self.state = ProjectState(root=tmp_path, prompt="A robot finds a flower in a junkyard at sunset. It says: 'Hi.'")
        self.log = _Log()
        self.options = {}


def test_invalid_llm_answer_falls_back_to_scripted(tmp_path):
    ctx = _Ctx(tmp_path)
    plan = Director(BrokenProvider()).run(ctx)
    assert plan.dialogue[0].text == "Hi."
    assert any(k == "fallback" for k, _, _ in ctx.log.events)
