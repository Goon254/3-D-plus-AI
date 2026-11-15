"""Production log: one JSON line per event (agent decision, batch, critique, render), plus previews."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ProductionLog:
    def __init__(self, project_dir: str | Path, echo: bool = True):
        self.dir = Path(project_dir) / "log"
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "previews").mkdir(exist_ok=True)
        self.path = self.dir / "production.jsonl"
        self.echo = echo
        self.t0 = time.time()

    def event(self, kind: str, agent: str, message: str, **data: Any) -> dict[str, Any]:
        rec = {
            "t": round(time.time() - self.t0, 2),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": kind,
            "agent": agent,
            "message": message,
            **data,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        if self.echo:
            print(f"[{rec['t']:7.1f}s] {agent:>9} | {kind:<8} | {message}", flush=True)
        return rec

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]


def read_log(project_dir: str | Path) -> list[dict[str, Any]]:
    return ProductionLog(project_dir, echo=False).read()
