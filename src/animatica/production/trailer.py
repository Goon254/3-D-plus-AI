"""An automatic trailer cut list for a film without a hand-made one (feature mode, DECISIONS #107).

``savannah_film.py --trailer`` cuts ``(scene, start, seconds)`` windows out of the final scene renders, between a
title card and the end card. The savannah's 15 cuts were chosen by hand; a film the planner wrote has none, so
``trailer_cuts`` picks them from the scene reports (``report.json``: ``scene``, ``seconds``, ``lines`` with
``who`` / ``text`` / ``start`` / ``end``), the way the hand list was made:

* every cut is one line (or a quick two-speaker exchange, like "I can't do it alone." / "Then don't."), from a
  breath before the voice to a beat after it, and never clips another line: a cut starts after the previous
  line's voice and ends before the next one's;
* the opening line of the film (the world) and its last line (the moral) are always in, and so is every line
  the screenplay marked ``"key": true`` (the story beats: the hero's vow, the low point, the climax); a beat
  ends its cut, with the line it answers when it answers at once ("I can't do it alone." / "Then don't."),
  never followed by a reply that would undercut it (a tease after a vow);
* every shot marked ``"trailer": true`` (a picture moment, like the spring bursting) gets a picture-only cut:
  the longest stretch of it without a voice, up to ``PICTURE_S``;
* every scene gets a cut, so the trailer follows the story's arc;
* then the punchiest lines (short, exclaimed or asked; the narrator only for the opening and the close), with
  speakers who have had fewer cuts first, until the cuts add up to about ``TARGET_S``;
* the cuts play in film order.

Deterministic (same reports, same list). ``savannah_film.py`` writes the list it used to
``output/<slug>/trailer_cuts.json`` so it can be copied to ``<film>/trailer.json`` and edited by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..audio.delivery import plain

TARGET_S = 64.0  # of film between the two 3 s cards: a 60-90 s trailer, like the savannah's 70.6 s
MAX_CUT_S = 8.0
MIN_CUT_S = 1.6  # shorter than this and a cut is a flash
PRE_S = 0.35  # a breath before the voice
POST_S = 0.5  # a beat after it
PICTURE_S = 4.0  # a picture-only cut: long enough to see the moment, short enough not to stall
EXCHANGE_GAP_S = 0.8  # a reply this soon after a line, by someone else, is one cut with it
NARRATOR = "narrator"


@dataclass
class Cut:
    scene: str
    start: float
    seconds: float
    score: float
    who: tuple[str, ...]
    order: tuple[int, int]  # (scene index, first line index): film order
    lines: tuple[int, int]  # first and last line index covered (-1, -1: a picture-only cut)
    key: bool = False  # covers a line marked as a story beat

    def as_list(self) -> list[Any]:
        return [self.scene, round(self.start, 3), round(self.seconds, 3)]


def punch(text: str) -> float:
    """How well a line plays out of context: short, exclaimed or asked lines play best."""
    t = plain(text).strip()
    words = len(t.split())
    s = 0.0
    s += 2.0 if "!" in t else 0.0
    s += 1.0 if "?" in t else 0.0
    s += 1.5 if words <= 8 else (0.5 if words <= 14 else -1.5)
    s += 0.5 if any(w.isupper() and len(w) > 1 for w in t.replace("!", " ").split()) else 0.0
    return s


def _window(lines: list[dict[str, Any]], i: int, j: int, seconds: float) -> tuple[float, float]:
    """The cut around lines ``i..j``: a breath before, a beat after, never into a neighbour's voice."""
    lo = float(lines[i - 1]["end"]) + 0.05 if i > 0 else 0.0
    hi = float(lines[j + 1]["start"]) - 0.05 if j + 1 < len(lines) else seconds
    a = max(lo, float(lines[i]["start"]) - PRE_S, 0.0)
    b = min(hi, float(lines[j]["end"]) + POST_S, seconds)
    return a, b


def _lines(r: dict[str, Any]) -> list[dict[str, Any]]:
    """A scene report's spoken lines in time order (the indices every cut refers to)."""
    return sorted(
        (ln for ln in r.get("lines", []) if plain(ln.get("text", "")).strip()), key=lambda ln: ln["start"]
    )


def candidates(reports: list[dict[str, Any]]) -> list[Cut]:
    out: list[Cut] = []
    for k, r in enumerate(reports):
        lines = _lines(r)
        secs = float(r["seconds"])
        for i, ln in enumerate(lines):
            spans = [(i, i)]
            if (
                i + 1 < len(lines)
                and lines[i + 1]["who"] != ln["who"]
                and float(lines[i + 1]["start"]) - float(ln["end"]) <= EXCHANGE_GAP_S
            ):
                spans.append((i, i + 1))
            for a_i, b_i in spans:
                a, b = _window(lines, a_i, b_i, secs)
                if b - a < MIN_CUT_S or b - a > MAX_CUT_S:
                    continue
                who = tuple(dict.fromkeys(lines[x]["who"] for x in range(a_i, b_i + 1)))
                sc = sum(punch(lines[x]["text"]) for x in range(a_i, b_i + 1)) / (b_i - a_i + 1)
                sc += 0.75 if b_i > a_i else 0.0  # an exchange plays as a scene
                sc -= 2.0 if NARRATOR in who else 0.0
                key = any(lines[x].get("key") for x in range(a_i, b_i + 1))
                out.append(Cut(r["scene"], a, b - a, sc, who, (k, a_i), (a_i, b_i), key))
    return out


def picture_cuts(reports: list[dict[str, Any]]) -> list[Cut]:
    """A cut for every shot marked ``trailer``: its longest stretch with no voice, ``MIN_CUT_S``..``PICTURE_S``."""
    out: list[Cut] = []
    for k, r in enumerate(reports):
        lines = _lines(r)
        voices = [(float(ln["start"]) - 0.05, float(ln["end"]) + 0.05) for ln in lines]
        for sh in r.get("shots", []):
            if not sh.get("trailer"):
                continue
            a0, b0 = float(sh["start"]), min(float(sh["end"]), float(r["seconds"]))
            gaps, t = [], a0
            for va, vb in voices:
                if vb <= t or va >= b0:
                    continue
                gaps.append((t, min(va, b0)))
                t = max(t, vb)
            gaps.append((t, b0))
            a, b = max(gaps, key=lambda g: (g[1] - g[0], -g[0]))
            if b - a < MIN_CUT_S:
                continue
            b = min(b, a + PICTURE_S)
            first = sum(float(ln["start"]) < a for ln in lines)  # film order among the scene's lines
            out.append(Cut(r["scene"], a, b - a, 0.0, (), (k, first), (-1, -1), True))
    return out


def _clash(c: Cut, chosen: list[Cut]) -> bool:
    return any(
        o.scene == c.scene and o.start < c.start + c.seconds and c.start < o.start + o.seconds for o in chosen
    )


def trailer_cuts(reports: list[dict[str, Any]], target: float = TARGET_S) -> list[list[Any]]:
    """``[[scene, start, seconds], ...]`` in film order, about ``target`` seconds in all (see the module doc)."""
    cands = candidates(reports)
    if not cands:
        return []
    chosen: list[Cut] = []

    def take(c: Cut) -> None:
        if c not in chosen and not _clash(c, chosen):
            chosen.append(c)

    singles = [c for c in cands if c.lines[0] == c.lines[1]]
    pool = singles or cands
    take(min(pool, key=lambda c: c.order))  # the opening: the world
    take(max(pool, key=lambda c: c.order))  # the close: the moral
    keyed = [(k, i) for k, r in enumerate(reports) for i, ln in enumerate(_lines(r)) if ln.get("key")]
    for k, i in keyed:  # the story beats
        if any(c.order[0] == k and c.lines[0] <= i <= c.lines[1] for c in chosen):
            continue
        # a beat ends its cut (a reply would undercut a vow): with the line it answers, if it answers at once
        here = [c for c in cands if c.order[0] == k and c.lines[1] == i and not _clash(c, chosen)]
        here = [c for c in here if c.lines[1] > c.lines[0]] or here
        if here:
            take(max(here, key=lambda c: (c.score, -c.order[1])))
    for c in picture_cuts(reports):  # the picture moments
        take(c)
    total = lambda: sum(c.seconds for c in chosen)  # noqa: E731
    used: dict[str, int] = {}
    for c in chosen:
        for w in c.who:
            used[w] = used.get(w, 0) + 1

    def worth(c: Cut) -> float:
        # speakers and scenes that already have cuts give way, so the trailer spreads over the cast and the arc
        again = sum(used.get(w, 0) for w in c.who) / len(c.who)
        return c.score - 0.5 * again - 0.75 * sum(o.order[0] == c.order[0] for o in chosen)

    for k in range(len(reports)):  # the arc: a cut from every scene
        if any(c.order[0] == k for c in chosen):
            continue
        here = [c for c in cands if c.order[0] == k and not _clash(c, chosen)]
        if here and total() < target:
            best = max(here, key=lambda c: (worth(c), -c.order[1]))
            take(best)
            for w in best.who:
                used[w] = used.get(w, 0) + 1
    while total() < target:
        rest = [c for c in cands if c not in chosen and not _clash(c, chosen)]
        rest = [c for c in rest if total() + c.seconds <= target + MAX_CUT_S / 2]
        if not rest:
            break
        best = max(rest, key=lambda c: (worth(c), -c.order[0], -c.order[1]))
        take(best)
        for w in best.who:
            used[w] = used.get(w, 0) + 1
    chosen.sort(key=lambda c: (c.order[0], c.start))
    return [c.as_list() for c in chosen]
