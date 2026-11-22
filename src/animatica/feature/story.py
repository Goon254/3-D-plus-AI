"""The story engine of feature mode (docs/FEATURE_MODE.md): idea -> premise -> screenplay.

Two structured LLM tasks, ``feature.premise`` and ``feature.screenplay``, each with a deterministic
offline handler (``core.llm.scripted``), so the whole flow runs without a key and in CI. Characters are
limited to the species the creature library can build; other animals in the idea map to the nearest body
plan, and the premise records the mapping.
"""

from __future__ import annotations

import re
import zlib
from typing import Any

from ..core.llm import Provider, scripted

# what the creature library builds, and the words that pick each body plan
SPECIES_WORDS: dict[str, tuple[str, ...]] = {
    "elephant": ("elephant", "calf", "mammoth", "rhino", "hippo", "buffalo"),
    "giraffe": ("giraffe", "okapi", "camel", "llama"),
    "zebra": ("zebra", "horse", "pony", "donkey", "antelope", "gazelle", "deer", "foal"),
    "meerkat": ("meerkat", "mongoose", "squirrel", "mouse", "rabbit", "hare", "rat", "weasel", "ferret"),
    "tortoise": ("tortoise", "turtle", "terrapin", "snail"),
}
TIMES = ("dawn", "midday", "afternoon", "sunset", "night")
MAX_KEYS = 4  # "key": true lines (the want, the low point, the climax): the automatic trailer keeps them
KEY_RULE = 'mark the 2-4 lines that carry the story (the hero\'s want or vow, the low point, the climax) with "key": true'
MOODS = ("neutral", "happy", "sad", "excited", "worried", "determined", "scared", "surprised")

NAMES = {
    "elephant": ("Tembo", "Ndovu", "Kubwa"),
    "giraffe": ("Neema", "Twiga", "Refu"),
    "zebra": ("Zuri", "Punda", "Milia"),
    "meerkat": ("Kiki", "Dodo", "Pipi"),
    "tortoise": ("Bibi Kobe", "Kobe", "Polepole"),
}
TRAITS = {
    "elephant": ("strong and big-hearted", "thinks he must do everything alone", "strength"),
    "giraffe": ("tall and dreamy", "always looking far away, never close by", "sees far"),
    "zebra": ("fast and proud", "rushes ahead of everyone", "speed"),
    "meerkat": ("small, quick and nervous", "worries about every danger", "digging and keeping watch"),
    "tortoise": ("slow, old and wise", "too slow to keep up", "patience and memory"),
}
# what each body plan says when its gift is needed (spoken lines: "My patience and memory!" is not speech)
GIFT_LINES = {
    "elephant": "I can help. I'm strong!",
    "giraffe": "I can help. I can see far!",
    "zebra": "I can help. I'm fast!",
    "meerkat": "I can help. I'll keep watch!",
    "tortoise": "I can help. I remember the old way.",
}
SYSTEM = (
    "You are the story engine of a children's animated short-film studio (ages 4-9). Answer with JSON only."
)


def species_in(idea: str) -> tuple[list[str], dict[str, str]]:
    """The body plans an idea asks for, in the order they appear, and {word: species} for animals that
    were mapped to a different body plan."""
    text = idea.lower()
    found: list[tuple[int, str, str]] = []
    for sp, words in SPECIES_WORDS.items():
        for w in words:
            m = re.search(rf"\b{w}s?\b", text)
            if m:
                found.append((m.start(), sp, w))
    found.sort()
    order, mapped = [], {}
    for _, sp, w in found:
        if w != sp:
            mapped[w] = sp
        if sp not in order:
            order.append(sp)
    return order, mapped


def _goal(idea: str) -> str:
    """The thing the friends look for, as a noun phrase that reads in a sentence: the idea's own article is
    kept ("look for the lost rain" -> "the lost rain", "go to find water" -> "water")."""
    m = re.search(
        r"\b(?:to|find|reach|for)\s+(?!(?:find|reach|look|get|go|search)\b)((?:(?:the|a|an)\s+)?[a-z ]{3,40}?)(?:[.,!]|$| and\b| before\b)",
        idea.lower(),
    )
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else "the water"


def _title_goal(goal: str) -> str:
    """The goal for a title, after "the": "the lost rain" -> "Lost Rain"."""
    return re.sub(r"^(?:the|a|an)\s+", "", goal).title()


@scripted("feature.premise")
def scripted_premise(payload: dict[str, Any]) -> dict[str, Any]:
    idea = payload["idea"]
    order, mapped = species_in(idea)
    if len(order) < 2:  # an ensemble needs at least two: pad with the plans that contrast best
        for sp in ("tortoise", "zebra", "elephant", "meerkat", "giraffe"):
            if sp not in order:
                order.append(sp)
            if len(order) >= 3:
                break
    order = order[:5]
    seed = zlib.crc32(idea.encode("utf-8"))
    goal = _goal(idea)
    cast = []
    for k, sp in enumerate(order):
        name = NAMES[sp][(seed >> (3 * k)) % len(NAMES[sp])]
        who, flaw, gift = TRAITS[sp]
        cast.append(
            {
                "id": re.sub(r"[^a-z]+", "_", name.lower()).strip("_"),
                "name": name,
                "species": sp,
                "personality": who,
                "want": f"to reach {goal} first" if k == 0 else f"to help reach {goal}",
                "need": "to trust the others",
                "flaw": flaw,
                "gift": gift,
            }
        )
    hero = cast[0]
    return {
        "title": f"{hero['name']} and the {_title_goal(goal)}",
        "logline": f"{hero['name']} the {hero['species']} sets out for {goal}, and learns it takes all of them.",
        "theme": "everyone's gift counts",
        "idea": idea,
        "mapped_species": mapped,
        "cast": cast,
        "beats": [
            {"act": 1, "beat": f"Morning: the friends need {goal}; {hero['name']} wants to go alone."},
            {"act": 1, "beat": "They set off together, each in their own way."},
            {"act": 2, "beat": f"{hero['name']}'s flaw costs them: {hero['flaw']}."},
            {"act": 2, "beat": "Night: they are lost; each gift is needed in turn."},
            {"act": 3, "beat": f"Together they reach {goal}."},
        ],
    }


@scripted("feature.screenplay")
def scripted_screenplay(payload: dict[str, Any]) -> dict[str, Any]:
    prem = payload["premise"]
    cast = prem["cast"]
    hero, rest = cast[0], cast[1:]
    goal = _goal(prem.get("idea", "")) if prem.get("idea") else "the water"
    nm = {c["id"]: c["name"] for c in cast}
    scenes = [
        {
            "id": "sc01",
            "tod": "dawn",
            "intent": "the world and the need",
            "beats": [0],
            "lines": [
                {
                    "who": "narrator",
                    "text": f"One morning, far away, the friends needed {goal}.",
                    "mood": "neutral",
                },
                {
                    "who": hero["id"],
                    "text": f"I'll find {goal}. By myself!",
                    "mood": "determined",
                    "key": True,  # the want
                },
            ],
        },
        {
            "id": "sc02",
            "tod": "midday",
            "intent": "setting off together",
            "beats": [1],
            "lines": [
                {"who": c["id"], "text": f"Wait for me, {nm[hero['id']]}!", "mood": "excited"}
                for c in rest[:2]
            ],
        },
        {
            "id": "sc03",
            "tod": "afternoon",
            "intent": "the hero's flaw costs them",
            "beats": [2],
            "lines": [
                {"who": hero["id"], "text": "Come on, keep up!", "mood": "happy"},
                {"who": rest[0]["id"], "text": "We can't go as fast as you.", "mood": "sad"},
            ],
        },
        {
            "id": "sc04",
            "tod": "night",
            "intent": "lost; every gift needed",
            "beats": [3],
            "lines": [{"who": hero["id"], "text": "I don't know the way.", "mood": "worried", "key": True}]
            + [{"who": c["id"], "text": GIFT_LINES[c["species"]], "mood": "determined"} for c in rest],
        },
        {
            "id": "sc05",
            "tod": "sunset",
            "intent": "together they reach the goal",
            "beats": [4],
            "lines": [
                {"who": hero["id"], "text": "We did it. All of us.", "mood": "happy"},
                {"who": "narrator", "text": "It took all of them. Every gift counted.", "mood": "happy"},
            ],
        },
    ]
    return {"title": prem["title"], "scenes": scenes}


def validate_premise(p: dict[str, Any]) -> list[str]:
    from ..creatures.species import SPECIES

    errs = []
    for k in ("title", "logline", "theme", "cast", "beats"):
        if not p.get(k):
            errs.append(f"premise: no {k}")
    ids = set()
    for c in p.get("cast", []):
        if c.get("species") not in SPECIES:
            errs.append(
                f"premise: {c.get('name')} is a {c.get('species')!r}, which the creature library can't build"
            )
        if not re.fullmatch(r"[a-z][a-z_]*", c.get("id", "")):
            errs.append(f"premise: bad character id {c.get('id')!r}")
        if c.get("id") in ids:
            errs.append(f"premise: two characters called {c.get('id')!r}")
        ids.add(c.get("id"))
    if not 2 <= len(p.get("cast", [])) <= 5:
        errs.append("premise: the cast needs 2 to 5 characters")
    return errs


def validate_screenplay(s: dict[str, Any], premise: dict[str, Any]) -> list[str]:
    errs = []
    who = {c["id"] for c in premise.get("cast", [])} | {"narrator"}
    scenes = s.get("scenes", [])
    if not 3 <= len(scenes) <= 10:
        errs.append("screenplay: 3 to 10 scenes")
    spoken = set()
    for sc in scenes:
        if sc.get("tod") not in TIMES:
            errs.append(f"screenplay {sc.get('id')}: time of day {sc.get('tod')!r}")
        for ln in sc.get("lines", []):
            if ln.get("who") not in who:
                errs.append(f"screenplay {sc.get('id')}: {ln.get('who')!r} isn't in the cast")
            if not ln.get("text") or len(ln["text"].split()) > 25:
                errs.append(f"screenplay {sc.get('id')}: lines must be 1-25 words (kids' film)")
            if ln.get("mood", "neutral") not in MOODS:
                errs.append(f"screenplay {sc.get('id')}: mood {ln.get('mood')!r}")
            if "key" in ln and not isinstance(ln["key"], bool):
                errs.append(f"screenplay {sc.get('id')}: key must be true or false")
            spoken.add(ln.get("who"))
    keys = sum(bool(ln.get("key")) for sc in scenes for ln in sc.get("lines", []))
    if keys > MAX_KEYS:
        errs.append(f"screenplay: {keys} key lines; mark only the {MAX_KEYS} biggest story beats")
    silent = sorted(who - spoken - {"narrator"})
    if silent:
        errs.append("screenplay: no lines for " + ", ".join(silent))
    return errs


def write_story(idea: str, llm: Provider) -> tuple[dict[str, Any], dict[str, Any]]:
    """Premise then screenplay; each is validated and asked for once more with the errors if it fails."""
    from ..creatures.species import SPECIES

    rules = {"species": sorted(SPECIES), "times": list(TIMES), "moods": list(MOODS), "key": KEY_RULE}
    prem = llm.complete_json("feature.premise", SYSTEM, {"idea": idea, "rules": rules})
    errs = validate_premise(prem)
    if errs:
        prem = llm.complete_json("feature.premise", SYSTEM, {"idea": idea, "rules": rules, "fix": errs})
        errs = validate_premise(prem)
        if errs:
            raise ValueError("; ".join(errs))
    prem.setdefault("idea", idea)
    play = llm.complete_json("feature.screenplay", SYSTEM, {"premise": prem, "rules": rules})
    errs = validate_screenplay(play, prem)
    if errs:
        play = llm.complete_json("feature.screenplay", SYSTEM, {"premise": prem, "rules": rules, "fix": errs})
        errs = validate_screenplay(play, prem)
        if errs:
            raise ValueError("; ".join(errs))
    return prem, play
