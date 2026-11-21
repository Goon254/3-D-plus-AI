"""Feature mode: ``animatica feature "story"`` (docs/FEATURE_MODE.md)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .stages import animatic_path, approve, film_path, next_stage, status
from .story import write_story

__all__ = ["animatic_path", "approve", "film_path", "next_stage", "run", "slug", "status", "write_story"]

NEXT_STEP = {
    "story": "the story engine runs on the next `animatica feature` call",
    "design": "run the design loop for each character (scripts/design_loop.py, design_packet.py) and approve "
    "the packets; then `animatica feature --film {film} --approve design`",
    "voices": "casting runs on the next `animatica feature` call",
    "scenes": "the scene planner runs on the next `animatica feature` call (after the design gate)",
    "animatic": "render the animatic (`python scripts/savannah_animatic.py --film {film}`, writes {animatic}) and "
    "review it; then `animatica feature --film {film} --approve animatic`",
    "production": "render and mix the film (`python scripts/savannah_film.py --film {film}`: every scene not yet "
    "final, resumable, then the -14 LUFS film in {out}); `--deliver` adds captions, edit, log and poster",
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
    st = next_stage(film)
    if (
        st is not None and st.name == "scenes"
    ):  # after the design gate: plan the scenes, checked for continuity
        from .planner import check_plan, plan_scenes

        prem = json.loads((film / "01_premise.json").read_text(encoding="utf-8"))
        play = json.loads((film / "04_screenplay.json").read_text(encoding="utf-8"))
        plan = plan_scenes(play, prem)
        errs = check_plan(plan)
        if errs:
            log.append("scenes: the plan fails continuity, not written: " + "; ".join(errs[:5]))
        else:
            (film / "07_scenes.json").write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
            from .planner import plan_cues

            cues = plan_cues(play, prem["title"])
            (film / "05_cue_sheet.json").write_text(json.dumps(cues, indent=1) + "\n", encoding="utf-8")
            log.append(
                f"scenes: {len(plan['scenes'])} planned, {sum(len(s['shots']) for s in plan['scenes'])} shots"
            )
    for s in status(film):
        log.append(
            f"  {s.name:<11} {s.state}{'' if s.done else '  (' + s.missing + ')' if s.missing else ''}"
        )
    nxt = next_stage(film)
    log.append(
        "next: "
        + (
            NEXT_STEP[nxt.name].format(film=film, animatic=animatic_path(film), out=film_path(film).parent)
            if nxt
            else "the film is finished"
        )
    )
    return log
