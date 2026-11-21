"""The feature-film stage machine (docs/FEATURE_MODE.md): story -> design gate -> voices -> scenes ->
animatic gate -> production. Each stage has a ``done`` test on the film folder; the two gates also need
the owner's approval (``approvals.json``). ``status`` reports every stage, ``next_stage`` the first one
that isn't done, so every run resumes where the last one stopped."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APPROVALS = "approvals.json"
GATES = ("design", "animatic")


def _read(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def approvals(film: Path) -> dict[str, Any]:
    return _read(film / APPROVALS) or {}


def approve(film: Path, stage: str, note: str = "") -> dict[str, Any]:
    """Record the owner's approval of a gate (``design`` or ``animatic``). Refused while the gate's work
    isn't there to look at."""
    if stage not in GATES:
        raise ValueError(f"only the gates can be approved: {', '.join(GATES)}")
    st = {s.name: s for s in status(film)}[stage]
    if not st.ready:
        raise ValueError(f"nothing to approve yet for {stage}: {st.missing}")
    a = approvals(film)
    a[stage] = {"date": dt.date.today().isoformat(), "note": note}
    (film / APPROVALS).write_text(json.dumps(a, indent=1) + "\n", encoding="utf-8")
    return a


def characters(film: Path) -> list[dict[str, Any]]:
    prem = _read(film / "01_premise.json") or {}
    return list(prem.get("cast", []))


def _story(film: Path) -> tuple[bool, str]:
    from .story import validate_premise, validate_screenplay

    prem, play = _read(film / "01_premise.json"), _read(film / "04_screenplay.json")
    if prem is None or play is None:
        return False, "01_premise.json and 04_screenplay.json"
    errs = validate_premise(prem) + validate_screenplay(play, prem)
    return (not errs), "; ".join(errs)


def design_dir(film: Path) -> Path:
    """Approved designs live in the repo's ``design/<char>/`` (shared across films), or the film's own."""
    own = film / "design"
    return own if own.exists() else film.parents[1] / "design"


def _design_ready(film: Path) -> tuple[bool, str]:
    cast = characters(film)
    if not cast:
        return False, "the story's cast"
    missing = [c["id"] for c in cast if not (design_dir(film) / c["id"] / "approved.json").exists()]
    return (not missing), ("approved designs for " + ", ".join(missing)) if missing else ""


def _file(name: str) -> Callable[[Path], tuple[bool, str]]:
    return lambda film: ((film / name).exists(), name)


def animatic_path(film: Path) -> Path:
    """Where a film's animatic lands; ``scripts/savannah_animatic.py --film`` writes it here by default."""
    film = Path(film)
    return film.parents[1] / "output" / f"{film.name}-animatic" / "animatic.mp4"


def film_path(film: Path) -> Path:
    """Where a film's final cut lands."""
    film = Path(film)
    return film.parents[1] / "output" / film.name / "film.mp4"


def _animatic(film: Path) -> tuple[bool, str]:
    p = animatic_path(film)
    return p.exists(), str(p)


def _production(film: Path) -> tuple[bool, str]:
    p = film_path(film)
    return p.exists(), str(p)


@dataclass
class Stage:
    name: str
    ready: bool  # its work exists
    approved: bool  # gates only: the owner passed it (always True for the other stages)
    missing: str  # what isn't there yet

    @property
    def gate(self) -> bool:
        return self.name in GATES

    @property
    def done(self) -> bool:
        return self.ready and self.approved

    @property
    def state(self) -> str:
        if self.done:
            return "done"
        if self.ready:
            return "awaiting owner"
        return "todo"


STAGES: list[tuple[str, Callable[[Path], tuple[bool, str]]]] = [
    ("story", _story),
    ("design", _design_ready),
    ("voices", _file("06_voices.json")),
    ("scenes", _file("07_scenes.json")),
    ("animatic", _animatic),
    ("production", _production),
]


def status(film: Path) -> list[Stage]:
    film = Path(film)
    ok = approvals(film)
    out = []
    for name, test in STAGES:
        ready, missing = test(film)
        out.append(Stage(name, ready, (name in ok) if name in GATES else True, "" if ready else missing))
    return out


def next_stage(film: Path) -> Stage | None:
    """The first stage that isn't done (a later stage never runs before an earlier gate is passed)."""
    return next((s for s in status(film) if not s.done), None)
