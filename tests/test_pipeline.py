"""End-to-end offline pipeline: prompt -> scene -> critic -> tiny render -> MP4 with audio."""

import json

import pytest

from animatica.core.orchestrator import Studio

pytestmark = [pytest.mark.blender, pytest.mark.slow]


def test_offline_film_end_to_end(tmp_path):
    studio = Studio(provider="scripted", options={"quality": "ci", "tts_engine": "synth", "preview_engine": "workbench",
                                                  "critic_iterations": 2}, echo=False)
    state = studio.film("A curious little robot discovers a flower growing in a junkyard at sunset. "
                        "It says: 'Hello, little one.'", tmp_path, "smoke")
    root = tmp_path / "smoke"
    assert (root / "scene.blend").exists()
    final = root / "final.mp4"
    assert final.exists() and final.stat().st_size > 10_000
    from animatica.audio.mux import probe

    info = probe(final)
    kinds = {s["codec_type"] for s in info["streams"]}
    assert kinds == {"video", "audio"}
    assert 15 <= float(info["format"]["duration"]) <= 31
    events = [json.loads(line) for line in (root / "log/production.jsonl").read_text().splitlines()]
    agents = {e["agent"] for e in events}
    assert {"director", "asset", "animator", "camera", "voice", "critic", "editor"} <= agents
    assert any(e["kind"] == "critique" for e in events)
    assert (root / "log/index.html").exists()
    assert state.artifacts["lines"]["line1"]["duration"] > 0.3
