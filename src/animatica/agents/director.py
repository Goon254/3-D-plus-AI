"""Director: prompt -> style bible, story beats, shot list, dialogue (a FilmPlan)."""

from __future__ import annotations

import re
import zlib
from typing import TYPE_CHECKING, Any

from ..core.llm import scripted
from ..core.plan import FilmPlan
from .base import Agent

if TYPE_CHECKING:
    from ..core.orchestrator import Context

SYSTEM = """You are the Director of a tiny animation studio. Turn the user's prompt into a production plan
for a 15-30 second stylized 3D short rendered in Blender. Keep it simple and achievable: ONE character
(kind "robot" or "critter"), at most one hero prop, 3-4 shots with cuts.
Return JSON matching this shape exactly:
{"title": str, "logline": str,
 "style": {"palette": {"primary","secondary","accent","ground","sky_zenith","sky_horizon","sun": "#RRGGBB"},
           "mood": one of [warm, wonder, melancholy, playful, mysterious, tense],
           "shape_language": str, "lighting": str, "notes": [str]},
 "setting": {"kind": one of [junkyard, forest, meadow, beach, desert, snow, city, space, room],
             "time_of_day": one of [dawn, day, sunset, night], "density": 0..3},
 "characters": [{"id": "hero", "kind": "robot"|"critter", "name": str, "color": hex, "eye_color": hex,
                 "voice": {"voice": one of [af_heart, af_bella, af_nicole, am_puck, am_michael, bf_emma, bm_george], "pitch": 0.8-1.4, "rate": 0.8-1.1, "robot": 0-0.5}}],
 "props": [{"id": "prop", "kind": one of [flower, lantern, ball, crystal, mushroom, star, egg, book], "color": hex}],
 "shots": [{"id": "s1", "type": "wide"|"medium"|"closeup", "duration": seconds,
            "beat": one of [enter, discover, approach, speak, react, celebrate, settle, exit, idle],
            "description": str, "camera_move": one of [static, dolly_in, dolly_out, pan, orbit, crane_up, track],
            "subject": "hero"|"prop"|"both"}],
 "dialogue": [{"id": "line1", "character": "hero", "text": str, "shot": shot id, "at": seconds into shot}]}
Total duration 15-30 s. Any quoted speech in the prompt must appear verbatim as dialogue in a "speak" shot."""

# --------------------------------------------------------------------------- offline (scripted) director
CHARACTER_WORDS = {
    "robot": ["robot", "droid", "android", "machine", "bot", "automaton", "mech"],
    "critter": ["cat", "fox", "dog", "bunny", "rabbit", "creature", "critter", "mouse", "bear", "owl", "hamster", "monster"],
}
SETTING_WORDS = {
    "junkyard": ["junkyard", "scrapyard", "dump", "junk", "scrap", "wasteland"],
    "forest": ["forest", "woods", "jungle", "trees"],
    "meadow": ["meadow", "field", "garden", "park", "hill", "grass"],
    "beach": ["beach", "shore", "ocean", "sea", "island"],
    "desert": ["desert", "dune", "sand", "canyon", "mars"],
    "snow": ["snowy", "snow", "winter", "ice", "arctic", "frozen", "tundra"],
    "city": ["city", "street", "rooftop", "alley", "town"],
    "space": ["space", "moon", "asteroid", "planet", "stars", "orbit"],
    "room": ["room", "kitchen", "bedroom", "workshop", "attic", "house", "lab"],
}
TIME_WORDS = {
    "sunset": ["sunset", "dusk", "evening", "golden hour", "twilight"],
    "night": ["night", "midnight", "moonlight", "dark"],
    "dawn": ["dawn", "sunrise", "morning"],
    "day": ["noon", "day", "afternoon", "sunny"],
}
PROP_WORDS = {
    "flower": ["flower", "rose", "daisy", "tulip", "blossom", "bloom", "plant", "sprout"],
    "lantern": ["lantern", "lamp", "light bulb", "candle"],
    "ball": ["ball", "orb", "marble"],
    "crystal": ["crystal", "gem", "diamond", "jewel", "shard"],
    "mushroom": ["mushroom", "toadstool", "fungus"],
    "star": ["star", "starfish", "comet"],
    "egg": ["egg", "hatchling"],
    "book": ["book", "letter", "map", "note"],
}
MOOD_WORDS = {
    "wonder": ["discover", "curious", "wonder", "magic", "first", "amazed", "finds"],
    "melancholy": ["lonely", "sad", "alone", "lost", "abandoned", "rain", "old"],
    "playful": ["play", "dance", "bounce", "silly", "chase", "happy", "jump"],
    "mysterious": ["mysterious", "strange", "secret", "glow", "ancient", "hidden"],
    "tense": ["danger", "storm", "escape", "chase", "afraid", "scary"],
}
SKIES = {
    "sunset": ("#2E3A73", "#F59E5B", "#FFB36B"),
    "dawn": ("#6C8FD0", "#F7C6A3", "#FFD7A8"),
    "day": ("#3D7FD9", "#BFE3FF", "#FFF4E0"),
    "night": ("#070B1F", "#1D2A55", "#A9C2FF"),
}
GROUNDS = {"junkyard": "#6B5646", "forest": "#3F5A2E", "meadow": "#5E8C3A", "beach": "#E3CF9E", "desert": "#D29A5B",
           "snow": "#E8EEF5", "city": "#5A5E66", "space": "#8A8790", "room": "#9C7A5B"}
CHARACTER_COLORS = {"orange": "#D9822B", "red": "#C8433A", "blue": "#3A78C8", "green": "#4FA35A", "yellow": "#E8C33A",
                    "purple": "#8A5AC8", "pink": "#E87AA8", "white": "#E8E8E8", "silver": "#B8C0C8", "teal": "#2FA3A0",
                    "black": "#2A2A2E", "grey": "#8C9096", "gray": "#8C9096", "gold": "#D4AF37", "brown": "#8B5A3C"}
PROP_COLORS = {"flower": "#FF5C8A", "lantern": "#FFC857", "ball": "#E84855", "crystal": "#7FE7FF", "mushroom": "#E4572E",
               "star": "#FFE066", "egg": "#F2E8CF", "book": "#7B4B94"}
NAMES = {"robot": ["Bolt", "Pip", "Cog", "Rivet", "Sprocket", "Tinker"], "critter": ["Mochi", "Pebble", "Tofu", "Bean", "Nib"]}


def _pick(text: str, table: dict[str, list[str]], default: str) -> str:
    best, best_pos = default, 10**9
    for key, words in table.items():
        for w in words:
            m = re.search(r"\b" + re.escape(w) + r"s?\b", text)
            if m and m.start() < best_pos:
                best, best_pos = key, m.start()
    return best


def scripted_plan(prompt: str) -> dict[str, Any]:
    """Deterministic plan from keywords. Same prompt -> same film."""
    text = prompt.lower()
    seed = zlib.crc32(prompt.encode())
    kind = _pick(text, CHARACTER_WORDS, "robot")
    setting = _pick(text, SETTING_WORDS, "meadow" if kind == "critter" else "junkyard")
    tod = _pick(text, TIME_WORDS, "sunset" if setting not in ("space", "room") else "night")
    prop = _pick(text, PROP_WORDS, "flower")
    mood = _pick(text, MOOD_WORDS, "warm")
    color = None
    for cname, hexv in CHARACTER_COLORS.items():
        if re.search(rf"\b{cname}\b[^.]*\b({'|'.join(CHARACTER_WORDS[kind])})", text):
            color = hexv
            break
    color = color or ("#D9822B" if kind == "robot" else "#E8A15A")
    zenith, horizon, sun = SKIES[tod]
    if setting == "space":
        zenith, horizon = "#05060F", "#1B1F3B"
    quotes = re.findall(r"[\"“']([^\"”]{2,200}?)[\"”']", prompt)
    quotes = [q.strip() for q in quotes if len(q.split()) >= 2 or q.endswith(("!", "?", "."))]
    name = NAMES[kind][seed % len(NAMES[kind])]
    subject = {"robot": "little robot", "critter": "small creature"}[kind]

    # story arc: openings and endings vary with the prompt's verbs/mood (not one fixed template)
    lonely = re.search(r"\b(sits?|sitting|waits?|waiting|alone|lonely|sleepy|rests?|resting|bored|sad)\b", text)
    leaves = re.search(r"\b(leaves?|goes home|walks? away|rolls? away|heads? home|says goodbye|farewell)\b", text)
    opening = ({"id": "s1", "type": "wide", "duration": 5.0, "beat": "idle", "camera_move": "orbit", "subject": "hero",
                "description": f"Establishing: {name} sits alone in the {setting} at {tod}, looking around, then sighs."}
               if lonely else
               {"id": "s1", "type": "wide", "duration": 5.5, "beat": "enter", "camera_move": "track", "subject": "hero",
                "description": f"Establishing: the {subject} rolls into the {setting} at {tod}."})
    shots = [
        opening,
        {"id": "s2", "type": "medium", "duration": 5.0, "beat": "discover", "camera_move": "dolly_in", "subject": "both",
         "description": f"{name} notices the {prop}, hesitates (anticipation), then approaches and leans in."},
    ]
    dialogue = []
    if quotes:
        shots.append({"id": "s3", "type": "closeup", "duration": max(5.0, 3.0 + 0.45 * len(" ".join(quotes).split())),
                      "beat": "speak", "camera_move": "dolly_in", "subject": "hero",
                      "description": f"Close-up: {name} speaks softly to the {prop}."})
        at = 1.2
        for i, q in enumerate(quotes[:3]):
            dialogue.append({"id": f"line{i + 1}", "character": "hero", "text": q, "shot": "s3", "at": round(at, 2)})
            at += 0.6 + 0.42 * len(q.split())
    else:
        shots.append({"id": "s3", "type": "closeup", "duration": 4.5, "beat": "react", "camera_move": "dolly_in",
                      "subject": "hero", "description": f"Close-up: {name}'s eyes light up with delight."})
    if leaves:
        shots.append({"id": "s4", "type": "wide", "duration": 5.5, "beat": "exit", "camera_move": "crane_up", "subject": "both",
                      "description": f"{name} turns, looks back at the {prop} once, and heads home."})
    elif mood == "playful":
        shots.append({"id": "s4", "type": "wide", "duration": 5.0, "beat": "celebrate", "camera_move": "orbit", "subject": "both",
                      "description": f"{name} hops for joy around the {prop}."})
    else:
        shots.append({"id": "s4", "type": "wide", "duration": 5.5, "beat": "settle", "camera_move": "crane_up", "subject": "both",
                      "description": f"{name} settles beside the {prop}; the camera rises as the light fades."})

    voice = {"voice": "am_puck", "speaker": 20, "pitch": 1.1, "rate": 0.88, "robot": 0.18} if kind == "robot" else \
            {"voice": "af_bella", "speaker": 3, "pitch": 1.15, "rate": 0.92, "robot": 0.0}
    return {
        "title": f"{name} and the {prop.capitalize()}",
        "logline": prompt.strip(),
        "prompt": prompt,
        "style": {
            "palette": {"primary": color, "secondary": "#3E4A59", "accent": "#7FE7FF", "ground": GROUNDS[setting],
                        "sky_zenith": zenith, "sky_horizon": horizon, "sun": sun},
            "mood": mood if mood != "warm" or tod != "sunset" else "wonder" if prop in ("flower", "crystal", "star") else "warm",
            "shape_language": "rounded, chunky, friendly; bevelled edges; big readable silhouettes",
            "lighting": {"sunset": "low warm golden key from behind-left, cool blue fill",
                         "dawn": "soft peach key, misty fill", "day": "high white key, bright sky fill",
                         "night": "cool moonlight key, warm practical glow on the prop"}[tod],
            "notes": [f"keep {name} the warmest saturated object on screen", f"the {prop} is the visual focal point"],
        },
        "setting": {"kind": setting, "time_of_day": tod, "density": 1.0},
        "characters": [{"id": "hero", "kind": kind, "name": name, "color": color, "eye_color": "#7FE7FF",
                        "voice": voice}],
        "props": [{"id": "prop", "kind": prop, "color": PROP_COLORS[prop]}],
        "shots": shots,
        "dialogue": dialogue,
    }


@scripted("director.plan")
def _scripted_director(payload: dict[str, Any]) -> dict[str, Any]:
    return scripted_plan(payload["prompt"])


class Director(Agent):
    role = "director"
    task = "director.plan"
    system_prompt = SYSTEM

    def run(self, ctx: Context) -> FilmPlan:
        prompt = ctx.state.prompt
        raw = self.ask(ctx, {"prompt": prompt}, validate=lambda d: FilmPlan.model_validate({**d, "title": d.get("title", "x")}))
        raw["prompt"] = prompt
        plan = FilmPlan.model_validate(raw)
        plan = normalize_plan(plan, prompt)
        style_name = ctx.options.get("style")
        if style_name:
            from ..knowledge.study import load_style

            style = load_style(style_name)
            if style is None:
                ctx.log.event("warning", self.role, f"style '{style_name}' not found in knowledge/styles")
            else:
                h = style["director_hints"]
                pal = plan.style.palette
                pal.sky_zenith, pal.sky_horizon, pal.ground = h["sky_zenith"], h["sky_horizon"], h["ground"]
                plan.style.mood = h["mood"]
                plan.style.notes.append(f"style reference '{style_name}' ({style.get('license', '?')})")
                ctx.log.event("decision", self.role, f"applied style '{style_name}': mood {h['mood']}, sky {h['sky_zenith']}"
                              f"->{h['sky_horizon']}, ground {h['ground']}", style=h)
        ctx.log.event("decision", self.role,
                      f"'{plan.title}': {len(plan.shots)} shots, {plan.duration:.1f}s, {plan.setting.kind} at "
                      f"{plan.setting.time_of_day}, {plan.hero.kind} '{plan.hero.name}', prop {plan.prop.kind if plan.prop else '-'}",
                      plan=plan.model_dump(mode="json"))
        return plan


def normalize_plan(plan: FilmPlan, prompt: str) -> FilmPlan:
    """Enforce studio constraints: 15–30 s total, quoted speech present, dialogue fits in its shot."""
    ids = {s.id for s in plan.shots}
    for line in plan.dialogue:
        if line.shot not in ids:
            speak = next((s for s in plan.shots if s.beat == "speak"), plan.shots[-1])
            line.shot = speak.id
    for s in plan.shots:
        lines = [d for d in plan.dialogue if d.shot == s.id]
        if lines:
            need = max(d.at + 0.5 * len(d.text.split()) + 1.5 for d in lines)
            s.duration = max(s.duration, round(need, 2))
    total = plan.duration
    if total > 30:
        k = 30 / total
        for s in plan.shots:
            s.duration = max(1.5, round(s.duration * k, 2))
    elif total < 15:
        k = 15 / total
        for s in plan.shots:
            s.duration = round(s.duration * k, 2)
    return plan
