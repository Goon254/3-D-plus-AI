"""The scene planner of feature mode (docs/FEATURE_MODE.md, stage 4): screenplay -> ``07_scenes.json``.

A first, rule-based pass that produces specs in the savannah format (``production.scene``), so the animatic
pipeline can render them: per scene a set layout for its time of day, the speaking cast in a shallow arc that
opens toward the cameras, each line addressed to the previous speaker, the mood as the line's expression,
listeners reacting, and a shot list cut on the lines (an establishing extreme wide, a close shot on each
speaker sized by species, an over-the-shoulder two-shot for every exchange, a closing wide). Every plan is
checked with ``production.continuity`` before it is written. A director pass (an LLM with the savannah critique
as its brief) can refine the blocking and shots later; the rules keep the stage working offline.
"""

from __future__ import annotations

import math
import zlib
from typing import Any

# close shot by species: a small head needs a tighter shot to read
CLOSE = {"elephant": "mcu", "giraffe": "mcu", "zebra": "mcu", "meerkat": "cu", "tortoise": "mcu"}
SPACING = {"elephant": 2.2, "giraffe": 2.4, "zebra": 2.0, "meerkat": 1.0, "tortoise": 1.3}
SFX = {
    "elephant": "trumpet",
    "zebra": "zebra_bark",
    "meerkat": "meerkat_chirp",
    "giraffe": "giraffe_hum",
    "tortoise": "tortoise_huff",
}
REACT = {
    "happy": "happy",
    "sad": "sad",
    "worried": "worried",
    "scared": "worried",
    "excited": "happy",
    "surprised": "surprised",
}
LEAD = 1.0


def _layout(sid: str, tod: str) -> dict[str, Any]:
    rng = zlib.crc32(sid.encode())
    side = 1 if rng % 2 else -1
    lay: dict[str, Any] = {
        "acacias": [[-12.0 * side, 16.0, 0.9], [13.0 * side, 22.0, 0.85]],
        "mounds": [[-4.5 * side, 4.0, 0.8]] if rng % 3 else [],
        "action": [[0.0, 1.5, 3.6]],
        "grass_density": 30.0,
    }
    if tod in ("dawn", "midday"):
        lay["birds"] = [{"t0": 1.0, "t1": 9.0, "n": 7, "from": [-30.0, 40.0, 14.0], "to": [30.0, 36.0, 16.0]}]
    return lay


def _blocking(ids: list[str], species: dict[str, str]) -> dict[str, tuple[float, float, float]]:
    """A shallow arc across the action, opening toward the cameras (at -Y): (x, y, yaw) per character, the
    first speaker in the middle, everyone turned a little toward the centre."""
    order = ids[1:2] + ids[:1] + ids[2:] if len(ids) > 1 else ids
    # centre-out: the middle slot first, then alternate right/left
    width = sum(SPACING[species[c]] for c in order)
    xs, x = [], -width / 2
    for c in order:
        x += SPACING[species[c]] / 2
        xs.append(x)
        x += SPACING[species[c]] / 2
    out = {}
    for c, x in zip(order, xs):
        y = 1.2 + 0.08 * x * x  # the ends of the arc come forward
        yaw = max(-40.0, min(40.0, -math.degrees(math.atan2(x, 4.0))))
        out[c] = (round(x, 2), round(y, 2), round(yaw, 1))
    return out


def plan_scene(sc: dict[str, Any], premise: dict[str, Any], k: int) -> dict[str, Any]:
    species = {c["id"]: c["species"] for c in premise["cast"]}
    speakers = [ln["who"] for ln in sc["lines"] if ln["who"] in species]
    present = list(dict.fromkeys(speakers)) or [premise["cast"][0]["id"]]
    if k == 0 or sc is not None and sc.get("intent", "").startswith("together"):
        present = [c["id"] for c in premise["cast"]]  # the opening and the ending have everyone
    pos = _blocking(present, species)
    cast = {c: {"species": species[c], "at": [x, y], "yaw": yaw} for c, (x, y, yaw) in pos.items()}
    lines, reactions, sfx = [], [], []
    prev = None
    for i, ln in enumerate(sc["lines"]):
        item: dict[str, Any] = {
            "who": ln["who"],
            "text": ln["text"],
            "expr": [[0, ln.get("mood", "neutral")]],
        }
        if ln.get("key"):
            item["key"] = True  # a story beat: the automatic trailer keeps it (DECISIONS #108)
        item["at" if i == 0 else "gap"] = 3.5 if i == 0 else (0.6 if ln["who"] != prev else 0.4)
        if ln["who"] in species and prev in species and prev != ln["who"]:
            item["to"] = prev
        lines.append(item)
        mood = REACT.get(ln.get("mood", "neutral"))
        if mood and ln["who"] in species:
            for c in present:
                if c != ln["who"]:
                    reactions.append({"who": c, "line": i, "dt": 0.3, "expr": mood})
                    break
        if ln["who"] in species and i == 0:
            sfx.append({"line": 0, "dt": -1.2, "kind": SFX[species[ln["who"]]], "who": ln["who"]})
        prev = ln["who"]
    shots: list[dict[str, Any]] = [
        {
            "type": "ews",
            "subjects": [],
            "t": 0,
            "look": [0.0, 10.0, 3.0],
            "frame_h": 9.0,
            "note": sc.get("intent", ""),
        },
        {"type": "ws", "subjects": present, "t": 2.0},
    ]
    prev = None
    for i, ln in enumerate(sc["lines"]):
        if ln["who"] not in species:
            continue  # the narrator speaks over the wides
        if prev in species and prev != ln["who"] and i % 2 == 0:
            shots.append({"type": "ms", "subjects": [ln["who"], prev], "line": i, "side": 25})
        else:
            shots.append({"type": CLOSE[species[ln["who"]]], "subjects": [ln["who"]], "line": i})
        prev = ln["who"]
    shots.append({"type": "ws", "subjects": present, "line": len(sc["lines"]) - 1, "after": 0.4})
    return {
        "id": sc["id"],
        "title": sc.get("intent", sc["id"]),
        "tod": sc["tod"],
        "cue": sc["id"],
        "seconds": 20,
        "lead": LEAD,
        "layout": _layout(sc["id"], sc["tod"]),
        "ambience": {"tod": sc["tod"]},
        "cast": cast,
        "lines": lines,
        "reactions": reactions,
        "gestures": [],
        "shots": shots,
        "sfx": sfx,
    }


def plan_scenes(screenplay: dict[str, Any], premise: dict[str, Any]) -> dict[str, Any]:
    return {
        "_about": "Planned by animatica.feature.planner (rule-based first pass); edit freely, the animatic gate judges it.",
        "scenes": [plan_scene(sc, premise, k) for k, sc in enumerate(screenplay["scenes"])],
    }


def check_plan(plan: dict[str, Any]) -> list[str]:
    """Load every planned scene, schedule it with nominal line lengths and run the continuity checks."""
    from ..production.continuity import check_scene
    from ..production.scene import cut_list, scene_from_dict, schedule

    errs = []
    for d in plan["scenes"]:
        spec = scene_from_dict(d)
        secs = schedule(spec, [max(1.0, 0.36 * len(ln.text.split())) for ln in spec.lines])
        vs, _ = check_scene(spec, cut_list(spec, secs), secs)
        errs += [f"{v.scene} {v.kind} {v.who}: {v.message}" for v in vs]
    return errs


# the score: one cue per scene, its mood from where the scene sits in the story and its time of day
CUE_MOOD = {
    "dawn": "wonder",
    "midday": "adventure",
    "afternoon": "tension",
    "sunset": "tender",
    "night": "mystery",
}
CUE_BPM = {"wonder": 66, "adventure": 96, "tension": 84, "tender": 64, "mystery": 60, "triumph": 92}


def plan_cues(screenplay: dict[str, Any], title: str) -> dict[str, Any]:
    """``05_cue_sheet.json`` for the Composer: the opening is wonder, the last scene ends in triumph, the
    others take their time of day's mood (a night scene is mystery). Every cue states the main theme."""
    scenes = screenplay["scenes"]
    cues = []
    for k, sc in enumerate(scenes):
        mood = CUE_MOOD.get(sc["tod"], "wonder")
        sections = [{"at": 0.0, "mood": "wonder" if k == 0 else mood, "motifs": ["main"]}]
        if k == len(scenes) - 1:
            sections.append({"at": 0.5, "mood": "triumph", "motifs": ["main"]})
        cues.append(
            {
                "id": sc["id"],
                "scene": sc.get("intent", sc["id"]),
                "seconds": 20,
                "key": "D" if k % 2 == 0 else "G",
                "bpm": CUE_BPM[sections[0]["mood"]],
                "intent": sc.get("intent", ""),
                "sections": sections,
            }
        )
    return {
        "film": title,
        "notes": "planned by animatica.feature.planner; re-timed to picture per scene",
        "cues": cues,
    }
