"""Natural delivery for TTS lines: pace per mood, punctuation pauses, breaths, and emphasised words.

A line is split into *phrases* at sentence ends, ellipses and dashes (commas stay inside a phrase so the
model keeps its own intonation across them). Each phrase is spoken separately and the gaps between them are
ours: longer after a question or an ellipsis, shorter after an exclamation, scaled by the mood. A soft
breath goes into the longer gaps after a sentence of some length. Key words, marked ``*word*`` in the script
or written in CAPS, are stressed in the phoneme string (primary stress on the word, the stressed vowel
lengthened) and lifted ~2.5 dB in level.

Mood comes from the line's face expression (``animatica.creatures.face.EXPRESSIONS`` names) or a free word
from the screenplay's parenthetical ("laughing", "quietly"...). Every line also gets a small deterministic
tempo variation so a character never speaks two lines at exactly the same rate.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field

# mood -> (rate multiplier, pause multiplier)
MOODS: dict[str, tuple[float, float]] = {
    "neutral": (1.0, 1.0),
    "happy": (1.05, 0.9),
    "excited": (1.1, 0.75),
    "laughing": (1.08, 0.8),
    "proud": (0.97, 1.1),
    "dignified": (0.94, 1.2),
    "sad": (0.88, 1.35),
    "worried": (1.06, 0.85),
    "scared": (1.12, 0.7),
    "surprised": (1.06, 0.9),
    "curious": (0.98, 1.1),
    "determined": (0.95, 1.15),
    "quietly": (0.92, 1.25),
    "wise": (0.93, 1.3),
}

# pause after a phrase, by its closing punctuation (seconds, before the mood multiplier)
PAUSE = {".": 0.34, "!": 0.26, "?": 0.38, "...": 0.52, "-": 0.22, "": 0.0}
BREATH_MIN_WORDS = 7  # breathe after a sentence at least this long
BREATH_MIN_GAP = 0.3
EMPHASIS_DB = 2.5

_SPLIT = re.compile(r"(\.\.\.|…|—|--|[.!?]+)(\s+|$)")


@dataclass
class Phrase:
    text: str  # spoken text, markup removed
    end: str  # closing punctuation class: . ! ? ... - or ''
    emphasis: list[int] = field(default_factory=list)  # word indices in ``text`` to stress
    pause: float = 0.0  # silence after this phrase (s)
    breath: bool = False  # a breath inside the pause


def plain(text: str) -> str:
    """The line as written for captions and lip-sync dialog: markup removed, CAPS kept."""
    return text.replace("*", "")


def _words(s: str) -> list[str]:
    return s.split()


def _mark(raw: str) -> tuple[str, list[int]]:
    """Strip ``*...*`` markup and CAPS words to spoken text; return indices of the emphasised words."""
    words, emph, on = [], [], False
    for w in raw.split():
        start = w.startswith("*")
        core = w.replace("*", "")
        letters = re.sub(r"[^A-Za-z]", "", core)
        caps = len(letters) >= 2 and letters.isupper() and letters not in ("OK", "TV")
        if start:
            on = True
        if on or caps:
            emph.append(len(words))
        if caps:
            core = core.lower().capitalize() if not words else core.lower()
        words.append(core)
        if w.rstrip(".,!?;:'\"").endswith("*"):
            on = False
    return " ".join(words), emph


def mood_of(mood: str | None) -> tuple[float, float]:
    if not mood:
        return MOODS["neutral"]
    for m in re.split(r"[ ,;]+", mood.lower()):
        if m in MOODS:
            return MOODS[m]
    return MOODS["neutral"]


def plan(text: str, mood: str | None = None) -> list[Phrase]:
    """Split a line into phrases with pauses and breaths. Pure: no audio."""
    _, pmul = mood_of(mood)
    out: list[Phrase] = []
    pos = 0
    for m in _SPLIT.finditer(text):
        chunk = text[pos : m.start()] + m.group(1)
        pos = m.end()
        p = m.group(1)
        end = "..." if p in ("...", "…") else "-" if p in ("—", "--") else p[-1]
        spoken = chunk[: -len(p)] + ("," if end in ("...", "-") else p)  # suspended, not falling
        s, emph = _mark(spoken.strip())
        if s.strip(" .,!?"):
            out.append(Phrase(s, end, emph))
        elif out:  # a bare "..." after a phrase lengthens that phrase's pause
            out[-1].end = end
    rest = text[pos:].strip()
    if rest:
        s, emph = _mark(rest)
        out.append(Phrase(s, "", emph))
    for i, ph in enumerate(out):
        last = i == len(out) - 1
        ph.pause = 0.0 if last else round(PAUSE[ph.end] * pmul, 3)
        ph.breath = (
            not last
            and ph.end in (".", "!", "?", "...")
            and len(_words(ph.text)) >= BREATH_MIN_WORDS
            and ph.pause >= BREATH_MIN_GAP
        )
    return out


def line_rate(text: str, base: float, mood: str | None = None) -> float:
    """Base rate x mood x a deterministic +-3 % per-line variation (seeded by the text)."""
    r, _ = mood_of(mood)
    jitter = ((zlib.crc32(text.encode("utf-8")) % 1000) / 1000 - 0.5) * 0.06
    return round(base * r * (1 + jitter), 4)


# ---------------------------------------------------------------- phoneme emphasis

_VOWELS = set("aeiouɑɐɒæɔəɚɛɜɝɪʊʌᵻɨʉøœɤɯyɘɵɞɶ")


def stress_word(ph: str) -> str:
    """One word's phonemes, stressed: primary stress on its stressed syllable (secondary -> primary, none ->
    word start) and the stressed vowel lengthened with Kokoro's length mark."""
    if "ˈ" not in ph:
        ph = ph.replace("ˌ", "ˈ", 1) if "ˌ" in ph else "ˈ" + ph
    i = ph.index("ˈ") + 1
    while i < len(ph) and ph[i] not in _VOWELS:
        i += 1
    j = i
    while j < len(ph) and ph[j] in _VOWELS:  # diphthongs: lengthen after the vowel cluster
        j += 1
    if i < len(ph) and (j >= len(ph) or ph[j] != "ː"):
        ph = ph[:j] + "ː" + ph[j:]
    return ph


def emphasise_phonemes(phonemes: str, emphasis: list[int], n_words: int) -> str | None:
    """Apply :func:`stress_word` to the emphasised word tokens of a phrase's phoneme string. Returns None if
    the phoneme tokens don't line up one-to-one with the words (then the phrase is spoken from text)."""
    toks = phonemes.split(" ")
    if len(toks) != n_words:
        return None
    for k in emphasis:
        if 0 <= k < len(toks):
            core = toks[k].rstrip(".,!?;:")
            toks[k] = stress_word(core) + toks[k][len(core) :]
    return " ".join(toks)


def prefix_phonemes(phonemes: str, k: int) -> str:
    """Phonemes of the first ``k`` words (for timing an emphasised word by rendering its prefix)."""
    return " ".join(phonemes.split(" ")[:k])


def spoken(text: str) -> tuple[str, list[int]]:
    """The whole line as Kokoro should read it (markup removed, CAPS words lower-cased) and the indices of
    its emphasised words."""
    return _mark(text)
