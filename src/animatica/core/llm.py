"""Provider-agnostic LLM client.

Every agent asks for *structured JSON* via ``complete_json(task, system, payload)``. Providers:

* ``AnthropicProvider`` — Claude via the official SDK if installed, else plain HTTPS (no extra deps).
* ``ScriptedProvider`` — deterministic, offline. Each agent registers a pure function for its task
  that produces a valid answer from the same payload. The whole pipeline (and CI) runs without keys.

``get_provider("auto")`` picks Anthropic when ``ANTHROPIC_API_KEY`` is set, otherwise scripted.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ScriptedFn = Callable[[dict[str, Any]], dict[str, Any]]
_SCRIPTED: dict[str, ScriptedFn] = {}


def scripted(task: str) -> Callable[[ScriptedFn], ScriptedFn]:
    """Decorator: register the deterministic offline answer for ``task``."""

    def deco(fn: ScriptedFn) -> ScriptedFn:
        _SCRIPTED[task] = fn
        return fn

    return deco


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    by_task: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMError(RuntimeError):
    pass


class Provider:
    name = "base"

    def __init__(self) -> None:
        self.usage = Usage()

    def complete_json(
        self,
        task: str,
        system: str,
        payload: dict[str, Any],
        images: list[str | Path] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def supports_vision(self) -> bool:
        return False


class ScriptedProvider(Provider):
    name = "scripted"

    def complete_json(
        self,
        task: str,
        system: str,
        payload: dict[str, Any],
        images: list[str | Path] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        fn = _SCRIPTED.get(task)
        if fn is None:
            raise LLMError(f"scripted provider has no handler for task {task!r}")
        t0 = time.time()
        out = fn(json.loads(json.dumps(payload)))  # deep copy: handlers can't mutate caller state
        self.usage.calls += 1
        self.usage.seconds += time.time() - t0
        self.usage.by_task[task] = self.usage.by_task.get(task, 0) + 1
        return out


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model response (handles ```json fences)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = m.group(1) if m else text[text.find("{") : text.rfind("}") + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise LLMError(f"model did not return valid JSON: {e}; got: {text[:300]!r}") from None


class AnthropicProvider(Provider):
    name = "anthropic"
    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str | None = None, api_key: str | None = None, max_retries: int = 3):
        super().__init__()
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY not set")
        self.model = model or os.environ.get("ANIMATICA_MODEL", "claude-sonnet-4-5")
        self.max_retries = max_retries

    @property
    def supports_vision(self) -> bool:
        return True

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            import anthropic  # type: ignore

            client = anthropic.Anthropic(api_key=self.api_key)
            resp = client.messages.create(**body)
            return json.loads(resp.model_dump_json())
        except ImportError:
            req = urllib.request.Request(
                self.API_URL,
                data=json.dumps(body).encode(),
                method="POST",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310 - fixed https URL
                return json.loads(r.read())

    def complete_json(
        self,
        task: str,
        system: str,
        payload: dict[str, Any],
        images: list[str | Path] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for img in images or []:
            data = base64.b64encode(Path(img).read_bytes()).decode()
            content.append(
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}
            )
        content.append(
            {
                "type": "text",
                "text": json.dumps(payload, separators=(",", ":"))
                + "\n\nRespond with a single JSON object only.",
            }
        )
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }
        last: Exception | None = None
        for attempt in range(self.max_retries):
            t0 = time.time()
            try:
                resp = self._post(body)
                text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
                u = resp.get("usage", {})
                self.usage.calls += 1
                self.usage.input_tokens += int(u.get("input_tokens", 0))
                self.usage.output_tokens += int(u.get("output_tokens", 0))
                self.usage.seconds += time.time() - t0
                self.usage.by_task[task] = self.usage.by_task.get(task, 0) + 1
                return extract_json(text)
            except Exception as e:  # noqa: BLE001 - retry any transport/parse error
                last = e
                time.sleep(2**attempt)
        raise LLMError(f"anthropic call for {task!r} failed: {last}")


def get_provider(name: str = "auto") -> Provider:
    if name == "scripted":
        return ScriptedProvider()
    if name == "anthropic":
        return AnthropicProvider()
    if name == "auto":
        return AnthropicProvider() if os.environ.get("ANTHROPIC_API_KEY") else ScriptedProvider()
    raise LLMError(f"unknown provider {name!r}")
