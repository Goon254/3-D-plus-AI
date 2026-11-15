"""Agent base class: role, system prompt, structured LLM call with offline fallback, batch helpers."""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Any

from ..core.llm import LLMError, Provider, ScriptedProvider
from ..core.protocol import Batch, BatchResult, BatchValidationError

if TYPE_CHECKING:
    from ..core.orchestrator import Context

_batch_counter = itertools.count(1)


class Agent:
    role = "agent"
    task = "agent"
    system_prompt = "You are a helpful specialist."

    def __init__(self, provider: Provider):
        self.provider = provider
        self._fallback = ScriptedProvider()

    def ask(self, ctx: Context, payload: dict[str, Any], validate=None, images=None) -> dict[str, Any]:
        """Ask the provider for JSON; validate it; on failure fall back to the scripted answer (logged)."""
        try:
            out = self.provider.complete_json(self.task, self.system_prompt, payload, images=images)
            if validate is not None:
                validate(out)
            return out
        except (LLMError, ValueError, TypeError, KeyError) as e:
            if isinstance(self.provider, ScriptedProvider):
                raise
            ctx.log.event(
                "fallback", self.role, f"LLM answer unusable ({str(e)[:160]}); using scripted answer"
            )
            out = self._fallback.complete_json(self.task, self.system_prompt, payload)
            if validate is not None:
                validate(out)
            return out

    def batch(self, intent: str, ops: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        return {
            "batch_id": f"b-{next(_batch_counter):04d}",
            "agent": self.role,
            "intent": intent,
            "ops": ops,
            **kw,
        }

    def submit(self, ctx: Context, batch: dict[str, Any]) -> BatchResult:
        """Validate + execute one batch, filter ops touching artist-locked ids, log the result."""
        batch = ctx.filter_locked(batch)
        try:
            res = ctx.engine.run_batch(batch)
        except BatchValidationError as e:
            ctx.log.event(
                "batch",
                self.role,
                f"{batch['batch_id']} rejected: {e.errors[:3]}",
                batch_id=batch["batch_id"],
                intent=batch.get("intent"),
                ok=False,
                errors=e.errors,
            )
            raise
        if res.ok:
            ctx.state.scene.apply(Batch.model_validate(batch))
        ctx.log.event(
            "batch",
            self.role,
            f"{batch.get('intent', '')} -> {res.summary()} ({res.elapsed_ms} ms)",
            batch_id=res.batch_id,
            intent=batch.get("intent"),
            n_ops=len(batch.get("ops", [])),
            ok=res.ok,
            created=res.created[:50],
            errors=res.errors,
            warnings=res.warnings[:10],
            preview=res.preview,
        )
        if not res.ok:
            raise RuntimeError(f"batch {res.batch_id} failed: {res.errors}")
        return res
