"""Project state persisted to ``<project>/project.json``: plan, scene model, history, locks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .plan import FilmPlan
from .scene_model import SceneModel


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:max_len].rstrip("-")) or "project"


@dataclass
class ProjectState:
    root: Path
    prompt: str = ""
    plan: FilmPlan | None = None
    scene: SceneModel = field(default_factory=SceneModel)
    history: list[dict[str, Any]] = field(default_factory=list)
    locked: dict[str, list[str]] = field(default_factory=dict)  # id -> ["transform", "material", ...]
    artifacts: dict[str, Any] = field(default_factory=dict)  # paths: blend, audio, frames, final
    tuning: dict[str, Any] = field(default_factory=dict)  # critic-driven adjustments, persisted
    provider: str = "scripted"

    @property
    def path(self) -> Path:
        return self.root / "project.json"

    @property
    def blend(self) -> Path:
        return self.root / "scene.blend"

    def save(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {
            "format": "animatica-project/0.1",
            "prompt": self.prompt,
            "provider": self.provider,
            "plan": self.plan.model_dump(mode="json") if self.plan else None,
            "scene": self.scene.to_dict(),
            "history": self.history,
            "locked": self.locked,
            "artifacts": self.artifacts,
            "tuning": self.tuning,
        }
        self.path.write_text(json.dumps(data, indent=1))
        return self.path

    @classmethod
    def load(cls, root: str | Path) -> ProjectState:
        root = Path(root)
        data = json.loads((root / "project.json").read_text())
        return cls(
            root=root,
            prompt=data.get("prompt", ""),
            plan=FilmPlan.model_validate(data["plan"]) if data.get("plan") else None,
            scene=SceneModel.from_dict(data.get("scene", {})),
            history=data.get("history", []),
            locked=data.get("locked", {}),
            artifacts=data.get("artifacts", {}),
            tuning=data.get("tuning", {}),
            provider=data.get("provider", "scripted"),
        )
