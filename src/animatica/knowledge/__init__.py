"""Knowledge base: small markdown notes the agents retrieve instead of guessing.

``lookup(query)`` returns the best-matching sections (keyword overlap scoring) — cheap, deterministic,
and good enough for a few dozen notes. Swap for embeddings when the corpus grows.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent
_WORD = re.compile(r"[a-z0-9]+")


@lru_cache(maxsize=1)
def sections() -> list[tuple[str, str, str]]:
    out = []
    for md in sorted(_DIR.glob("*.md")):
        doc, title, buf = md.stem, md.stem, []
        for line in md.read_text().splitlines():
            if line.startswith("## "):
                if buf:
                    out.append((doc, title, "\n".join(buf).strip()))
                title, buf = line[3:].strip(), []
            elif not line.startswith("# "):
                buf.append(line)
        if buf:
            out.append((doc, title, "\n".join(buf).strip()))
    return out


def lookup(query: str, k: int = 3) -> list[dict[str, str]]:
    q = set(_WORD.findall(query.lower()))
    scored = []
    for doc, title, body in sections():
        words = _WORD.findall((title + " " + body).lower())
        score = sum(3 for w in _WORD.findall(title.lower()) if w in q) + sum(1 for w in set(words) if w in q)
        if score:
            scored.append((score, doc, title, body))
    scored.sort(key=lambda s: -s[0])
    return [{"doc": d, "section": t, "text": b} for _, d, t, b in scored[:k]]
