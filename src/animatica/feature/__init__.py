"""Feature mode: ``animatica feature "story"`` (docs/FEATURE_MODE.md)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .stages import approve, next_stage, status
from .story import write_story

__all__ = ["approve", "next_stage", "run", "slug", "status", "write_story"]

NEXT_STEP = {
    "story": "the story engine runs on the next `animatica feature` call",
    "design": "run the design loop for each character (scripts/design_loop.py, design_packet.py) and approve "
    "the packets; then `animatica feature --film {film} --approve design`",
    "voices": "casting runs on the next `animatica feature` call",
    "scenes": "the scene planner (07_scenes.json) is not automated yet (docs/FEATURE_MODE.md, next pieces)",
    "animatic": "render the animatic and review it; then `animatica feature --film {film} --approve animatic`",
    "production": "render the final scenes (resumable) and mix the film",
}


def slug(idea: str) -> str:
    words = re.findall(r"[a-z0-9]+", idea.lower())
    return "-".join(words[:5]) or "film"


def run(film: Path, idea: str | None, llm) -> list[str]:  # noqa: ANN001 - core.llm.Provider
    """Do every stage this run can do on its own (today: the story), and say what comes next."""
    film.mkdir(parents=True, exist_ok=True)
    log = []
    st = next_stage(film)
    if st is not None and st.name == "story":
        if not idea:
            idea = (
                json.loads((film / "01_premise.json").read_text(encoding="utf-8")).get("idea")
                if (film / "01_premise.json").exists()
                else None
            )
        if not idea:
            raise ValueError("no story idea: pass one the first time")
        prem, play = write_story(idea, llm)
        (film / "01_premise.json").write_text(json.dumps(prem, indent=1) + "\n", encoding="utf-8")
        (film / "04_screenplay.json").write_text(json.dumps(play, indent=1) + "\n", encoding="utf-8")
        log.append(f"story: {prem['title']!r}, {len(prem['cast'])} characters, {len(play['scenes'])} scenes")
    if not (film / "06_voices.json").exists() and (film / "01_premise.json").exists():
        # casting needs no approval of its own: the voices are heard (and judged) at the animatic gate
        from .casting import cast_voices

        prem = json.loads((film / "01_premise.json").read_text(encoding="utf-8"))
        v = cast_voices(prem)
        (film / "06_voices.json").write_text(json.dumps(v, indent=1) + "\n", encoding="utf-8")
        log.append("voices: " + ", ".join(f"{k} = {c['voice']}" for k, c in v["cast"].items()))
    for s in status(film):
        log.append(
            f"  {s.name:<11} {s.state}{'' if s.done else '  (' + s.missing + ')' if s.missing else ''}"
        )
    nxt = next_stage(film)
    log.append("next: " + (NEXT_STEP[nxt.name].format(film=film) if nxt else "the film is finished"))
    return log
