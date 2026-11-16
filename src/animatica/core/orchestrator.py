"""Orchestrator: builds the task graph from the Director's plan, dispatches agents, runs the Critic
loop (plan -> batch -> preview -> critique -> fix), enforces budgets and writes the production log."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agents.animator import Animator
from ..agents.asset import AssetAgent
from ..agents.camera import CameraLighting
from ..agents.critic import Critic, Issue
from ..agents.director import Director
from ..agents.editor import Editor
from ..agents.voice import VoiceSound
from .budget import Budget, BudgetExceeded
from .engine import BlenderSession
from .llm import Provider, get_provider
from .log import ProductionLog
from .plan import FilmPlan
from .state import ProjectState, slugify


@dataclass
class Context:
    state: ProjectState
    engine: Any  # BlenderSession | LiveBlenderSession
    log: ProductionLog
    provider: Provider
    budget: Budget
    options: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)

    @property
    def plan(self) -> FilmPlan:
        assert self.state.plan is not None, "Director has not produced a plan yet"
        return self.state.plan

    def filter_locked(self, batch: dict[str, Any]) -> dict[str, Any]:
        """Drop ops that would modify artist-locked aspects; log what was skipped."""
        if not self.state.locked:
            return batch
        kept, skipped = [], []
        aspect_of = {
            "transform": "transform",
            "insert_keyframes": "transform",
            "set_material": "material",
            "delete": "deleted",
            "add_modifier": "transform",
            "parent": "parent",
            "clear_animation": "transform",
        }
        for op in batch.get("ops", []):
            kind = op.get("op")
            targets = op.get("targets") or [op.get("target") or op.get("child")]
            aspect = aspect_of.get(kind)
            if aspect and any(
                t in self.state.locked and (aspect in self.state.locked[t] or "all" in self.state.locked[t])
                for t in targets
                if t
            ):
                if kind in ("set_material",) and len(targets) > 1:
                    free = [
                        t
                        for t in targets
                        if t not in self.state.locked or "material" not in self.state.locked[t]
                    ]
                    if free:
                        kept.append({**op, "targets": free})
                skipped.append(f"{kind}:{','.join(t for t in targets if t)}")
                continue
            if kind in _CREATE_OPS and op.get("id") in self.state.locked:
                skipped.append(f"{kind}:{op.get('id')}")
                continue
            kept.append(op)
        if skipped:
            self.log.event(
                "locked",
                batch.get("agent", "?"),
                f"kept artist edits; skipped {len(skipped)} ops: {skipped[:6]}",
            )
        return {**batch, "ops": kept}


_CREATE_OPS = {
    "create_primitive",
    "create_mesh",
    "create_empty",
    "add_light",
    "add_camera",
    "create_armature",
    "import_asset",
}


@dataclass
class Task:
    name: str
    fn: Callable[[], Any]
    deps: list[str] = field(default_factory=list)
    retries: int = 1


class TaskGraph:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}

    def add(self, name: str, fn: Callable[[], Any], deps: list[str] | None = None, retries: int = 1) -> None:
        self.tasks[name] = Task(name, fn, deps or [], retries)

    def order(self) -> list[str]:
        done: list[str] = []
        seen: set[str] = set()

        def visit(n: str, stack: tuple[str, ...] = ()) -> None:
            if n in stack:
                raise ValueError(f"cycle in task graph: {' -> '.join(stack + (n,))}")
            if n in seen:
                return
            for d in self.tasks[n].deps:
                visit(d, stack + (n,))
            seen.add(n)
            done.append(n)

        for n in self.tasks:
            visit(n)
        return done

    def run(self, ctx: Context) -> dict[str, Any]:
        for name in self.order():
            task = self.tasks[name]
            attempt = 0
            while True:
                ctx.budget.check(ctx.provider.usage.total_tokens)
                t0 = time.time()
                ctx.log.event(
                    "task", "orchestr.", f"start {name}" + (f" (retry {attempt})" if attempt else "")
                )
                try:
                    ctx.results[name] = task.fn()
                    ctx.log.event("task", "orchestr.", f"done {name} in {time.time() - t0:.1f}s")
                    ctx.state.history.append(
                        {"task": name, "ok": True, "seconds": round(time.time() - t0, 2)}
                    )
                    ctx.state.save()
                    break
                except BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001
                    attempt += 1
                    ctx.log.event("error", "orchestr.", f"{name} failed: {type(e).__name__}: {str(e)[:300]}")
                    ctx.state.history.append({"task": name, "ok": False, "error": str(e)[:500]})
                    if attempt > min(task.retries, ctx.budget.max_task_retries):
                        raise
        return ctx.results


HERO_ANIMATED = [
    "hero_root",
    "hero_body",
    "hero_head_pivot",
    "hero_antenna_pivot",
    "hero_arm_pivot_L",
    "hero_arm_pivot_R",
    "hero_eye_L",
    "hero_eye_R",
    "hero_mouth",
    "prop_pivot",
    "prop",
    "hero_elbow_L",
    "hero_elbow_R",
]


class Studio:
    """High-level entry points: film, continue, revise."""

    def __init__(
        self,
        provider: str | Provider = "auto",
        options: dict[str, Any] | None = None,
        budget: Budget | None = None,
        echo: bool = True,
    ):
        self.provider = provider if isinstance(provider, Provider) else get_provider(provider)
        self.options = {
            "quality": "final",
            "preview_engine": "cycles",
            "critic_iterations": 3,
            "device": "auto",
            **(options or {}),
        }
        self.budget = budget or Budget(max_critic_iterations=int(self.options["critic_iterations"]))
        self.echo = echo

    # ------------------------------------------------------------------ film
    def film(self, prompt: str, out_root: str | Path = "output", name: str | None = None) -> ProjectState:
        root = Path(out_root) / (name or slugify(prompt))
        if root.exists() and (root / "project.json").exists():
            for p in ("log/production.jsonl",):
                (root / p).unlink(missing_ok=True)
        root.mkdir(parents=True, exist_ok=True)
        state = ProjectState(root=root, prompt=prompt, provider=self.provider.name)
        log = ProductionLog(root, echo=self.echo)
        log.event(
            "start",
            "orchestr.",
            f"new film from prompt: {prompt!r} (provider: {self.provider.name})",
            options=self.options,
        )
        with BlenderSession(workdir=root / "log") as engine:
            ctx = Context(state, engine, log, self.provider, self.budget, dict(self.options))
            log.event("info", "orchestr.", f"engine: Blender {engine.blender_version} (headless adapter)")
            self._build_graph(ctx).run(ctx)
        self._finish(ctx)
        return state

    def _build_graph(self, ctx: Context, from_plan: bool = False) -> TaskGraph:
        director, asset, animator = (
            Director(self.provider),
            AssetAgent(self.provider),
            Animator(self.provider),
        )
        camera, voice, critic, editor = (
            CameraLighting(self.provider),
            VoiceSound(self.provider),
            Critic(self.provider),
            Editor(self.provider),
        )
        g = TaskGraph()

        def do_director() -> Any:
            if not from_plan or ctx.state.plan is None:
                ctx.state.plan = director.run(ctx)
            return ctx.state.plan.title

        g.add("director", do_director)
        g.add("voice", lambda: voice.run(ctx), ["director"])

        def do_asset() -> Any:
            ctx.results["asset_info"] = asset.run(ctx)
            ctx.state.artifacts["asset_info"] = ctx.results["asset_info"]
            return "ok"

        g.add("asset", do_asset, ["director"])
        g.add(
            "animator", lambda: ctx.results.__setitem__("anim", animator.run(ctx)) or "ok", ["asset", "voice"]
        )
        g.add("camera", lambda: camera.run(ctx, ctx.results["asset_info"], ctx.results["anim"]), ["animator"])
        g.add(
            "review", lambda: self._critic_loop(ctx, critic, camera, animator, voice), ["camera"], retries=0
        )
        if not ctx.options.get("no_render"):
            g.add("edit", lambda: editor.run(ctx), ["review"])
        else:
            g.add("save", lambda: engine_save(ctx), ["review"])
        return g

    def _critic_loop(
        self, ctx: Context, critic: Critic, camera: CameraLighting, animator: Animator, voice: VoiceSound
    ) -> dict[str, Any]:
        history = []
        max_it = self.budget.max_critic_iterations
        for it in range(1, max_it + 1):
            issues, info = critic.review(ctx, it)
            blockers = [i for i in issues if i.severity == "blocker"]
            polish = [i for i in issues if i.severity == "minor" and i.fix.get("kind") == "camera"]
            history.append(
                {
                    "iteration": it,
                    "issues": len(issues),
                    "blockers": len(blockers),
                    "messages": [f"{i.shot}: {i.message}" for i in issues],
                }
            )
            if not blockers and not polish:
                ctx.log.event(
                    "critique",
                    critic.role,
                    f"iteration {it}: all shots pass" + (f" ({len(issues)} minor notes)" if issues else ""),
                )
                break
            if it == max_it:
                ctx.log.event(
                    "critique",
                    critic.role,
                    f"iteration cap ({max_it}) reached with {len(blockers)} blockers, "
                    f"{len(polish)} minor notes; continuing with best effort",
                )
                break
            if not blockers:
                ctx.log.event(
                    "critique",
                    critic.role,
                    f"iteration {it}: no blockers; polishing {len(polish)} actionable minor camera notes",
                )
            self._apply_fixes(ctx, blockers + polish, camera, animator, voice)
        ctx.state.artifacts["critic_history"] = history
        return {"iterations": history}

    def _apply_fixes(
        self, ctx: Context, issues: list[Issue], camera: CameraLighting, animator: Animator, voice: VoiceSound
    ) -> None:
        tuning = ctx.state.tuning
        redo_camera = redo_anim = redo_voice = False
        for i in issues:
            k = i.fix.get("kind")
            if k == "camera":
                cam = tuning.setdefault("camera", {}).setdefault(i.shot, {})
                if "fill_mul" in i.fix:
                    cam["fill_mul"] = round(cam.get("fill_mul", 1.0) * i.fix["fill_mul"], 3)
                if "azimuth_add" in i.fix:
                    cam["azimuth_add"] = cam.get("azimuth_add", 0) + i.fix["azimuth_add"]
                redo_camera = True
            elif k == "lighting":
                L = tuning.setdefault("lighting", {})
                L["exposure"] = round(L.get("exposure", 0.0) + float(i.fix.get("exposure_add", 0.0)), 2)
                redo_camera = True
            elif k == "animator":
                if "face_cam_add" in i.fix:
                    A = tuning.setdefault("animator", {})
                    A["face_cam"] = round(A.get("face_cam", 0.0) + float(i.fix["face_cam_add"]), 1)
                if "exit_speed_mul" in i.fix:
                    A = tuning.setdefault("animator", {})
                    A["exit_speed_mul"] = round(
                        A.get("exit_speed_mul", 1.0) * float(i.fix["exit_speed_mul"]), 3
                    )
                redo_anim = True
            elif k == "voice":
                redo_voice = redo_anim = True
        floor = [float(i.fix["floor_offset_add"]) for i in issues if "floor_offset_add" in i.fix]
        if floor:
            # one global correction (the root offset is shared by every shot): use the smallest move that
            # fixes the worst intersection, or the smallest float, never the sum of per-shot reports
            dips = [f for f in floor if f > 0]
            add = max(dips) if dips else max(floor)
            A = tuning.setdefault("animator", {})
            A["floor_offset"] = round(A.get("floor_offset", 0.0) + add, 3)
        ctx.log.event(
            "fix",
            "orchestr.",
            f"applying fixes: camera={redo_camera} animation={redo_anim} voice={redo_voice}; "
            f"tuning={json.dumps(tuning)}",
        )
        if redo_voice:
            voice.run(ctx)
        if redo_anim:
            ctx.engine.run_batch(
                {
                    "batch_id": f"clear-anim-{time.time():.0f}",
                    "agent": "animator",
                    "intent": "clear hero animation",
                    "ops": [
                        {
                            "op": "clear_animation",
                            "targets": [t for t in HERO_ANIMATED if t in ctx.engine.known_ids],
                        }
                    ],
                }
            )
            ctx.results["anim"] = animator.run(ctx)
        if redo_camera or redo_anim:
            ids = [i for i in ctx.engine.known_ids if i.startswith("cam_") or i.startswith("light_")]
            if ids:
                ctx.engine.run_batch(
                    {
                        "batch_id": f"clear-cams-{time.time():.0f}",
                        "agent": "camera",
                        "intent": "remove cameras and lights for re-layout",
                        "ops": [{"op": "delete", "targets": sorted(ids)}],
                    }
                )
            camera.run(ctx, ctx.results["asset_info"], ctx.results["anim"])

    def _finish(self, ctx: Context) -> None:
        u = self.provider.usage
        ctx.state.artifacts["llm_usage"] = {
            "provider": self.provider.name,
            "calls": u.calls,
            "tokens": u.total_tokens,
        }
        ctx.state.artifacts["usda"] = str(ctx.state.root / "scene.usda")
        (ctx.state.root / "scene.usda").write_text(ctx.state.scene.to_usda(), encoding="utf-8")
        ctx.state.save()
        ctx.log.event(
            "done",
            "orchestr.",
            f"finished in {self.budget.elapsed():.0f}s; LLM calls {u.calls}, tokens {u.total_tokens}",
            artifacts={k: v for k, v in ctx.state.artifacts.items() if k not in ("mouth_keys",)},
        )
        try:
            from ..cli.logview import write_log_html

            write_log_html(ctx.state.root)
        except Exception as e:  # noqa: BLE001
            ctx.log.event("warning", "orchestr.", f"log viewer failed: {e}")


def engine_save(ctx: Context) -> str:
    ctx.engine.run_batch(
        {"batch_id": "save", "agent": "editor", "ops": [{"op": "save", "path": str(ctx.state.blend)}]}
    )
    return str(ctx.state.blend)
