"""Artist in the loop: ``continue`` after hand edits, ``revise`` with an instruction, ``render`` again.

continue: open the saved .blend, query it, diff against the stored scene model, lock every aspect the
artist changed (authoritative), absorb the edits into the model, then re-run the downstream agents
(voice if missing → animator → camera → critic → editor). Locked aspects are never overwritten
(``Context.filter_locked``).

revise: an instruction ("make the robot blue and slow down shot 2") becomes a list of typed edits (LLM
or the scripted parser), applied as plan/tuning deltas plus spec-mode batches, then the same downstream
pass runs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..agents.animator import Animator
from ..agents.camera import CameraLighting
from ..agents.critic import Critic
from ..agents.director import CHARACTER_COLORS
from ..agents.editor import Editor
from ..agents.voice import VoiceSound
from .budget import Budget
from .engine import BlenderSession
from .llm import Provider, get_provider, scripted
from .log import ProductionLog
from .orchestrator import HERO_ANIMATED, Context, Studio, TaskGraph
from .state import ProjectState

HERO_PAINT = {"robot": ["hero_body", "hero_head"], "critter": ["hero_body", "hero_head", "hero_ear_L", "hero_ear_R",
                                                               "hero_tail", "hero_arm_L", "hero_arm_R"]}


def _open(project: str | Path, provider: str | Provider, options: dict[str, Any] | None, kind: str):
    root = Path(project)
    state = ProjectState.load(root)
    prov = provider if isinstance(provider, Provider) else get_provider(provider)
    studio = Studio(prov, options or {})
    log = ProductionLog(root)
    log.event("start", "orchestr.", f"{kind} project {root.name} (provider: {prov.name})")
    return root, state, studio, log


def detect_artist_edits(ctx: Context) -> dict[str, list[str]]:
    q = ctx.engine.run_batch({"batch_id": "continue-query", "agent": "orchestrator", "intent": "read the artist's scene",
                              "ops": [{"op": "query", "fields": ["type", "transform", "material", "parent"], "limit": 10000}]})
    objects = q.data["objects"]
    changes = ctx.state.scene.diff_snapshot(objects)
    for oid, aspects in changes.items():
        lock = ctx.state.locked.setdefault(oid, [])
        for a in aspects:
            a = "all" if a == "added" else a
            if a not in lock:
                lock.append(a)
    ctx.state.scene.absorb_snapshot(objects)
    return changes


def downstream(ctx: Context, studio: Studio, redo_voice: bool = False) -> None:
    prov = studio.provider
    voice, animator, camera = VoiceSound(prov), Animator(prov), CameraLighting(prov)
    critic, editor = Critic(prov), Editor(prov)
    asset_info = ctx.state.artifacts.get("asset_info") or {"hero_height": 1.55, "head_z": 1.12, "prop_height": 0.52}
    ctx.results["asset_info"] = asset_info

    def do_voice() -> Any:
        if redo_voice or not ctx.state.artifacts.get("mix") or not Path(ctx.state.artifacts["mix"]).exists():
            return voice.run(ctx)
        return "kept"

    def do_anim() -> Any:
        ids = [t for t in HERO_ANIMATED if t in ctx.engine.known_ids]
        ctx.engine.run_batch(ctx.filter_locked({"batch_id": "continue-clear-anim", "agent": "animator",
                                                "ops": [{"op": "clear_animation", "targets": ids}]}))
        ctx.results["anim"] = animator.run(ctx)
        return "ok"

    def do_camera() -> Any:
        ids = sorted(i for i in ctx.engine.known_ids if (i.startswith("cam_") or i.startswith("light_")) and i not in ctx.state.locked)
        if ids:
            ctx.engine.run_batch({"batch_id": "continue-clear-cams", "agent": "camera", "ops": [{"op": "delete", "targets": ids}]})
            for i in ids:
                ctx.state.scene.prims.pop(i, None)
        return camera.run(ctx, asset_info, ctx.results["anim"])

    g = TaskGraph()
    g.add("voice", do_voice)
    g.add("animator", do_anim, ["voice"])
    g.add("camera", do_camera, ["animator"])
    g.add("review", lambda: studio._critic_loop(ctx, critic, camera, animator, voice), ["camera"], retries=0)
    if ctx.options.get("no_render"):
        g.add("save", lambda: ctx.engine.run_batch({"batch_id": "save", "agent": "editor",
                                                    "ops": [{"op": "save", "path": str(ctx.state.blend)}]}), ["review"])
    else:
        g.add("edit", lambda: editor.run(ctx), ["review"])
    g.run(ctx)


def continue_project(project: str | Path, provider: str | Provider = "auto", options: dict[str, Any] | None = None) -> ProjectState:
    root, state, studio, log = _open(project, provider, options, "continue")
    with BlenderSession(workdir=root / "log") as engine:
        engine.open(state.blend, workdir=root / "log")
        ctx = Context(state, engine, log, studio.provider, studio.budget, dict(studio.options))
        changes = detect_artist_edits(ctx)
        log.event("decision", "orchestr.", f"artist edits detected on {len(changes)} objects; locked as authoritative: "
                  + ", ".join(f"{k}({'/'.join(v)})" for k, v in list(changes.items())[:12]), changes=changes)
        state.save()
        downstream(ctx, studio)
    studio._finish(ctx)
    return state


# ------------------------------------------------------------------------------------------ revise
COLOR_WORDS = {**CHARACTER_COLORS, "pink": "#E87AA8", "orange": "#D9822B", "cyan": "#2FC7D9"}


@scripted("revise.parse")
def scripted_revise(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload["instruction"].lower()
    plan = payload["plan"]
    hero_words = ["robot", "cat", "critter", "creature", "hero", "character", plan["characters"][0]["name"].lower(),
                  plan["characters"][0]["kind"]]
    edits: list[dict[str, Any]] = []
    for clause in re.split(r"\band\b|,|;", text):
        clause = clause.strip()
        m = re.search(r"(?:make|paint|colou?r|turn)\s+(?:the\s+)?(\w+)\s+(?:\w+\s+)?(" + "|".join(COLOR_WORDS) + r")\b", clause)
        if m:
            target = "hero" if m.group(1) in hero_words else "prop" if plan.get("props") and m.group(1) in (
                plan["props"][0]["kind"], "prop") else "hero"
            edits.append({"type": "recolor", "target": target, "color": COLOR_WORDS[m.group(2)]})
            continue
        m = re.search(r"(slow down|speed up|slower|faster)\s+(?:in\s+)?(?:shot\s*(\d+)|the\s+(\w+)\s+shot)?", clause)
        if m:
            factor = 0.7 if m.group(1) in ("slow down", "slower") else 1.35
            shot = f"s{m.group(2)}" if m.group(2) else None
            edits.append({"type": "speed", "shot": shot, "factor": factor})
            continue
        m = re.search(r"(closer|tighter|wider|further)\s*(?:in\s+)?(?:on\s+)?(?:shot\s*(\d+))?", clause)
        if m and ("shot" in clause or "camera" in clause):
            edits.append({"type": "framing", "shot": f"s{m.group(2)}" if m.group(2) else None,
                          "fill_mul": 1.25 if m.group(1) in ("closer", "tighter") else 0.8})
            continue
        m = re.search(r"\b(night|sunset|dawn|day)\b", clause)
        if m and any(w in clause for w in ("make it", "set it", "time", "change", "at ")):
            edits.append({"type": "time_of_day", "value": m.group(1)})
            continue
        m = re.search(r"(?:say|says|line)\s*[:\-]?\s*[\"'“](.+?)[\"'”]", payload["instruction"], re.I)
        if m and "say" in clause:
            edits.append({"type": "dialogue", "text": m.group(1)})
    return {"edits": edits}


REVISE_SYSTEM = """Turn an artist's revision note into typed edits. Return JSON {"edits": [...]} using only:
{"type":"recolor","target":"hero"|"prop","color":"#RRGGBB"} · {"type":"speed","shot":"s2"|null,"factor":0.5..2}
· {"type":"framing","shot":"s1"|null,"fill_mul":0.6..1.6} · {"type":"time_of_day","value":"dawn|day|sunset|night"}
· {"type":"dialogue","text":str}"""


def revise_project(project: str | Path, instruction: str, provider: str | Provider = "auto",
                   options: dict[str, Any] | None = None) -> ProjectState:
    root, state, studio, log = _open(project, provider, options, "revise")
    assert state.plan is not None
    from ..agents.base import Agent

    parser = Agent(studio.provider)
    parser.role, parser.task, parser.system_prompt = "director", "revise.parse", REVISE_SYSTEM
    with BlenderSession(workdir=root / "log") as engine:
        engine.open(state.blend, workdir=root / "log")
        ctx = Context(state, engine, log, studio.provider, studio.budget, dict(studio.options))
        changes = detect_artist_edits(ctx)
        if changes:
            log.event("decision", "orchestr.", f"preserving {len(changes)} artist edits: {list(changes)[:10]}")
        edits = parser.ask(ctx, {"instruction": instruction, "plan": state.plan.model_dump(mode="json")}).get("edits", [])
        log.event("decision", "director", f"revision '{instruction}' -> {edits}", edits=edits)
        if not edits:
            log.event("warning", "director", "no actionable edits understood; nothing changed")
        redo_voice = False
        spec: dict[str, Any] = {"objects": {}}
        for e in edits:
            t = e.get("type")
            if t == "recolor":
                color = e["color"].upper()
                if e.get("target") == "prop":
                    ids = [i for i in ctx.engine.known_ids if i.startswith("prop_petal") or i in ("prop_body", "prop_gem", "prop_cap", "prop_star")]
                    if state.plan.prop:
                        state.plan.prop.color = color
                else:
                    ids = [i for i in HERO_PAINT[state.plan.hero.kind] if i in ctx.engine.known_ids]
                    state.plan.hero.color = color
                    state.tuning.setdefault("asset_overrides", {})["color"] = color
                for i in ids:
                    if "material" in state.locked.get(i, []):
                        continue
                    spec["objects"][i] = {"material": {"base_color": color, "metallic": 0.35, "roughness": 0.38,
                                                       "name": f"revised_{e.get('target', 'hero')}"}}
            elif t == "speed":
                f = float(e.get("factor", 1.0))
                for s in state.plan.shots:
                    if e.get("shot") in (None, s.id):
                        s.duration = round(min(20.0, max(1.5, s.duration / f)), 2)
                perf = state.tuning.setdefault("performance", {})
                for s in state.plan.shots:
                    if e.get("shot") in (None, s.id):
                        perf.setdefault(s.id, {})["speed"] = f
                redo_voice = True  # the mix/timing depends on shot lengths
            elif t == "framing":
                for s in state.plan.shots:
                    if e.get("shot") in (None, s.id):
                        cam = state.tuning.setdefault("camera", {}).setdefault(s.id, {})
                        cam["fill_mul"] = round(cam.get("fill_mul", 1.0) * float(e.get("fill_mul", 1.0)), 3)
            elif t == "time_of_day":
                from ..agents.director import SKIES

                state.plan.setting.time_of_day = e["value"]
                pal = state.plan.style.palette
                pal.sky_zenith, pal.sky_horizon, pal.sun = SKIES[e["value"]]
            elif t == "dialogue":
                if state.plan.dialogue:
                    state.plan.dialogue[0].text = e["text"]
                redo_voice = True
        if spec["objects"]:
            ops = state.scene.spec_to_ops(spec)
            # scene model may not track materials of every part; force ops for each requested id
            have = {o.get("targets", [None])[0] for o in ops if o["op"] == "set_material"}
            for i, want in spec["objects"].items():
                if i not in have:
                    ops.append({"op": "set_material", "targets": [i], "material": want["material"]})
            res = ctx.engine.run_batch(ctx.filter_locked({"batch_id": "revise-spec", "agent": "asset", "mode": "ops",
                                                          "intent": f"spec delta for: {instruction}", "ops": ops}))
            log.event("batch", "asset", f"spec-mode revision -> {res.summary()}", batch_id=res.batch_id, ok=res.ok,
                      n_ops=len(ops))
            from .protocol import Batch

            state.scene.apply(Batch.model_validate({"batch_id": "revise-spec", "ops": ops}))
        state.save()
        downstream(ctx, studio, redo_voice=redo_voice)
    studio._finish(ctx)
    return state


def render_project(project: str | Path, quality: str = "final") -> ProjectState:
    root, state, studio, log = _open(project, "scripted", {"quality": quality}, "render")
    with BlenderSession(workdir=root / "log") as engine:
        engine.open(state.blend, workdir=root / "log")
        ctx = Context(state, engine, log, studio.provider, Budget(), dict(studio.options))
        Editor(studio.provider).run(ctx)
    studio._finish(ctx)
    return state
