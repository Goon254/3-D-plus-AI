"""Budgets bound cost: LLM tokens, critic iterations, and wall time."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    max_tokens: int = 400_000
    max_critic_iterations: int = 3
    max_wall_seconds: float = 3 * 3600
    max_task_retries: int = 2
    started: float = field(default_factory=time.time)

    def elapsed(self) -> float:
        return time.time() - self.started

    def check(self, tokens_used: int = 0) -> None:
        if tokens_used > self.max_tokens:
            raise BudgetExceeded(f"token budget exceeded: {tokens_used} > {self.max_tokens}")
        if self.elapsed() > self.max_wall_seconds:
            raise BudgetExceeded(f"wall-time budget exceeded: {self.elapsed():.0f}s")
