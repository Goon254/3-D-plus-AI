"""Casting for feature mode (docs/FEATURE_MODE.md, stage 3): the premise's characters -> ``06_voices.json``.

Each character gets a stock Kokoro voice blend (Apache-2.0, no cloning) chosen from a small palette of tested
blends by species and personality, then Chatterbox reads in that voice (the savannah engine, DECISIONS #45).
Two characters never share a blend: the second one of a kind takes the next palette entry, and if the palette
runs out, a pitch step of +-1 semitone keeps them apart. Every character also gets a neutral ``ref_text`` (a
line that is not in the screenplay, so Chatterbox copies the voice, not a line's delivery).
"""

from __future__ import annotations

from typing import Any

# tested blends (films/savannah/06_voices.json), by the voice's register
PALETTE: dict[str, list[dict[str, Any]]] = {
    "big_young": [
        {"voice": "am_eric:0.5+af_sky:0.5", "pitch": 1.06, "rate": 1.04},
        {"voice": "am_michael:0.6+af_sky:0.4", "pitch": 1.06, "rate": 1.0},
    ],
    "tall_gentle": [
        {"voice": "af_nicole:0.7+af_sky:0.3", "pitch": 1.0, "rate": 0.95},
        {"voice": "af_sarah:0.7+af_nicole:0.3", "pitch": 1.0, "rate": 0.95},
    ],
    "fast_bright": [
        {"voice": "af_bella:0.6+af_jessica:0.4", "pitch": 1.0, "rate": 1.08},
        {"voice": "af_jessica:0.6+af_heart:0.4", "pitch": 1.03, "rate": 1.08},
    ],
    "small_quick": [
        {"voice": "bf_alice:0.7+af_jessica:0.3", "pitch": 1.12, "rate": 1.1},
        {"voice": "af_sky:0.7+bf_alice:0.3", "pitch": 1.1, "rate": 1.1},
    ],
    "old_slow": [
        {"voice": "bf_emma:0.55+af_alloy:0.45", "pitch": 0.891, "rate": 0.86},
        {"voice": "bm_george:0.6+bf_emma:0.4", "pitch": 0.94, "rate": 0.86},
    ],
}
NARRATOR = {"voice": "bm_fable:0.8+bm_lewis:0.2", "pitch": 1.0, "rate": 0.92}
BY_SPECIES = {
    "elephant": "big_young",
    "giraffe": "tall_gentle",
    "zebra": "fast_bright",
    "meerkat": "small_quick",
    "tortoise": "old_slow",
}
REF_TEXT = {
    "big_young": "I like mornings best, because the mud is cool and everybody is still a bit sleepy, like me.",
    "tall_gentle": "From up here I can see the hills, the river, and a little cloud that looks like a hat.",
    "fast_bright": "I can run to the big tree and back before you even finish counting to ten.",
    "small_quick": "I always keep one eye open, just in case something is hiding in the grass.",
    "old_slow": "When I was young, the rains came every year, and we never had to hurry anywhere.",
}
NARRATOR_REF = "Every morning the sun climbs over the hills, and the whole plain wakes up slowly."


def register(c: dict[str, Any]) -> str:
    """The voice register for a character: by personality words first (old, small, fast...), then species."""
    who = (c.get("personality", "") + " " + c.get("flaw", "")).lower()
    for words, reg in (
        (("old", "wise", "grand"), "old_slow"),
        (("tiny", "small", "nervous", "little"), "small_quick"),
        (("fast", "quick", "proud", "rush"), "fast_bright"),
        (("dreamy", "gentle", "tall", "shy"), "tall_gentle"),
    ):
        if any(w in who.split() or w in who for w in words):
            return reg
    return BY_SPECIES.get(c.get("species", ""), "fast_bright")


def cast_voices(premise: dict[str, Any], engine: str = "chatterbox") -> dict[str, Any]:
    used: dict[str, int] = {}
    seen: set[tuple[str, float]] = set()
    cast: dict[str, Any] = {
        "narrator": {**NARRATOR, "note": "storyteller", "ref_text": NARRATOR_REF},
    }
    seen.add((NARRATOR["voice"], NARRATOR["pitch"]))
    for c in premise["cast"]:
        reg = register(c)
        k = used.get(reg, 0)
        used[reg] = k + 1
        pal = PALETTE[reg]
        v = dict(pal[k % len(pal)])
        step = 0
        while (v["voice"], round(v["pitch"], 3)) in seen:  # palette exhausted: a semitone apart
            step += 1
            v["pitch"] = round(pal[k % len(pal)]["pitch"] * 2 ** ((step if step % 2 else -step) / 12), 3)
        seen.add((v["voice"], round(v["pitch"], 3)))
        cast[c["id"]] = {
            **v,
            "note": f"{c.get('species')}: {c.get('personality', '')}",
            "ref_text": REF_TEXT[reg],
        }
    return {
        "_about": "Cast by animatica.feature.casting: stock Kokoro blends (Apache-2.0, no cloning) per register; "
        "Chatterbox reads in each voice, steered by the Kokoro take of ref_text.",
        "engine": engine,
        "cast": cast,
    }
