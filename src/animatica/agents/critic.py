"""Critic: renders previews and reviews every shot. Cheap geometric checks first (frustum, floor,
framing size, mouth activity, exposure), then an optional vision review when the provider can see.

Each issue carries a machine-applicable fix (a tuning delta) so the orchestrator can loop
plan -> batch -> preview -> critique -> fix without a human, capped by the budget.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from .base import Agent

if TYPE_CHECKING:
    from ..core.orchestrator import Context

SYSTEM = """You are the Critic in an animation studio. You see one low-res preview frame per shot and the
shot's goal. Flag only concrete, fixable problems (subject cut off, unreadable silhouette, too dark,
character intersecting the floor, wrong focus). Return JSON {"issues": [{"shot": id, "severity":
"blocker"|"minor", "message": str, "fix": {"kind": "camera"|"lighting", "fill_mul": float?,
"azimuth_add": float?, "exposure_add": float?}}]}. Return {"issues": []} if the shots work."""

SIZE_RANGE = {"wide": (0.14, 0.62), "medium": (0.3, 0.92), "closeup": (0.2, 0.9)}


@dataclass
class Issue:
    shot: str
    check: str
    severity: str
    message: str
    fix: dict[str, Any] = field(default_factory=dict)


class Critic(Agent):
    role = "critic"
    task = "critic.review"
    system_prompt = SYSTEM

    def sample_frames(self, f0: int, f1: int) -> list[int]:
        n = f1 - f0
        return sorted({f0 + 2, f0 + n // 4, f0 + n // 2, f0 + 3 * n // 4, f1 - 2})

    def review(self, ctx: Context, iteration: int) -> tuple[list[Issue], dict[str, Any]]:
        plan = ctx.plan
        frames = plan.shot_frames()
        issues: list[Issue] = []
        previews: dict[str, str] = {}
        stats: dict[str, Any] = {}
        prev_dir = ctx.state.root / "log" / "previews"
        # one batch: all inspections; one batch: all previews (round-trips are the enemy)
        dialogue_frames: dict[str, list[tuple[int, int]]] = {}
        for d in plan.dialogue:
            line = ctx.state.artifacts.get("lines", {}).get(d.id)
            if line:
                a = int(line["start_s"] * plan.fps) + 1
                dialogue_frames.setdefault(d.shot, []).append((a, a + int(line["duration"] * plan.fps)))

        inspect_ops = []
        for s in plan.shots:
            f0, f1 = frames[s.id]
            subj = ["hero_head"] if s.type == "closeup" else ["hero_root"]
            if s.subject in ("both", "prop") and plan.prop and s.type != "closeup":
                subj.append("prop")
            sample = set(self.sample_frames(f0, f1))
            for a, b in dialogue_frames.get(s.id, []):
                sample |= set(range(a, b + 1, 3))
            inspect_ops.append({"op": "inspect", "subjects": subj, "frames": sorted(sample),
                                "camera": f"cam_{s.id}", "shape_key_target": "hero_mouth"})
        res = ctx.engine.run_batch({"batch_id": f"critic-inspect-{iteration}", "agent": "critic",
                                    "intent": "geometric checks", "ops": inspect_ops})
        reports = dict(zip([s.id for s in plan.shots], res.data.get("inspects", [])))
        preview_ops = []
        for s in plan.shots:
            f0, f1 = frames[s.id]
            mid = (f0 + f1) // 2
            path = str(prev_dir / f"iter{iteration}_{s.id}_f{mid}.png")
            preview_ops.append({"op": "render_preview", "camera": f"cam_{s.id}", "frame": mid, "path": path,
                                "resolution": [480, 270], "engine": ctx.options.get("preview_engine", "cycles")})
        pr = ctx.engine.run_batch({"batch_id": f"critic-preview-{iteration}", "agent": "critic",
                                   "intent": "one preview per shot", "ops": preview_ops})
        for s, p in zip(plan.shots, pr.data.get("previews", [])):
            previews[s.id] = p["path"]
            stats[s.id] = p["stats"]

        for s in plan.shots:
            rep = reports.get(s.id, {})
            fr = rep.get("frames", {})
            subj_main = "hero_head" if s.type == "closeup" else "hero_root"
            vis = [f["subjects"][subj_main] for f in fr.values() if subj_main in f.get("subjects", {})]
            if vis:
                worst = min(v.get("visible_fraction", 1) for v in vis)
                heights = [v.get("screen_height", 0) for v in vis]
                lo, hi = SIZE_RANGE[s.type]
                if worst < 0.85:
                    issues.append(Issue(s.id, "off_frame", "blocker",
                                        f"{subj_main} only {worst:.0%} inside frame in {s.id}", {"kind": "camera", "fill_mul": 0.85}))
                if max(heights) > hi:
                    issues.append(Issue(s.id, "too_tight", "blocker", f"subject fills {max(heights):.0%} of frame height (max {hi:.0%})",
                                        {"kind": "camera", "fill_mul": round(hi / max(heights) * 0.95, 3)}))
                elif max(heights) < lo:
                    issues.append(Issue(s.id, "too_small", "minor", f"subject only {max(heights):.0%} of frame height (min {lo:.0%})",
                                        {"kind": "camera", "fill_mul": round(lo / max(max(heights), 0.01) * 1.05, 3)}))
                if any(v.get("behind_camera") for v in vis):
                    issues.append(Issue(s.id, "behind_camera", "blocker", "subject behind the camera", {"kind": "camera", "azimuth_add": 15}))
            if s.type != "closeup":
                mins = [f["subjects"]["hero_root"]["min_z"] for f in fr.values() if "hero_root" in f.get("subjects", {})]
                if mins and min(mins) < -0.03:
                    issues.append(Issue(s.id, "floor_intersection", "blocker", f"hero dips {abs(min(mins)):.2f} m into the floor",
                                        {"kind": "animator", "floor_offset_add": round(-min(mins), 3)}))
                elif mins and min(mins) > 0.08 and s.beat not in ("react", "celebrate"):
                    issues.append(Issue(s.id, "floating", "blocker", f"hero floats {min(mins):.2f} m above the floor",
                                        {"kind": "animator", "floor_offset_add": round(-min(mins), 3)}))
            if s.subject in ("both", "prop") and plan.prop and s.type != "closeup":
                pv = [f["subjects"]["prop"].get("visible_fraction", 1) for f in fr.values() if "prop" in f.get("subjects", {})]
                if pv and min(pv) < 0.8:
                    issues.append(Issue(s.id, "prop_off_frame", "blocker", f"the {plan.prop.kind} leaves the frame",
                                        {"kind": "camera", "fill_mul": 0.85}))
            for a, b in dialogue_frames.get(s.id, []):
                inside = [f for k, f in fr.items() if a <= int(k) <= b]
                mouth_vals = [f.get("mouth", 0) for f in inside]
                if inside and max(mouth_vals) < 0.05:
                    issues.append(Issue(s.id, "mouth_static", "blocker", "mouth not moving during dialogue", {"kind": "voice"}))
            st = stats.get(s.id, {})
            if st:
                if st.get("mean", 0.5) < 0.07 or st.get("black", 0) > 0.6:
                    issues.append(Issue(s.id, "too_dark", "blocker", f"preview too dark (mean {st.get('mean')})",
                                        {"kind": "lighting", "exposure_add": 0.6}))
                elif st.get("mean", 0.5) > 0.82 or st.get("white", 0) > 0.25:
                    issues.append(Issue(s.id, "blown_out", "blocker", f"preview blown out (mean {st.get('mean')})",
                                        {"kind": "lighting", "exposure_add": -0.5}))
            motion = sum(rep.get("motion", {}).values())
            if motion < 0.02 and s.camera_move == "static":
                issues.append(Issue(s.id, "static_shot", "minor", "nothing moves in this shot", {}))

        if self.provider.supports_vision and ctx.options.get("vision_critic", True):
            try:
                payload = {"shots": [{"id": s.id, "type": s.type, "goal": s.description} for s in plan.shots],
                           "geometric_issues": [asdict(i) for i in issues]}
                out = self.provider.complete_json(self.task, self.system_prompt, payload,
                                                  images=[previews[s.id] for s in plan.shots])
                for it in out.get("issues", [])[:8]:
                    issues.append(Issue(str(it.get("shot")), "vision", it.get("severity", "minor"), str(it.get("message", ""))[:300],
                                        it.get("fix") or {}))
            except Exception as e:  # noqa: BLE001 - vision review is best-effort
                ctx.log.event("warning", self.role, f"vision review skipped: {e}")

        for s in plan.shots:
            mine = [i for i in issues if i.shot == s.id]
            verdict = "PASS" if not any(i.severity == "blocker" for i in mine) else "FAIL"
            ctx.log.event("critique", self.role,
                          f"iter {iteration} {s.id} ({s.type}): {verdict}" + (": " + "; ".join(i.message for i in mine) if mine else ""),
                          iteration=iteration, shot=s.id, verdict=verdict, issues=[asdict(i) for i in mine],
                          preview=previews.get(s.id), stats=stats.get(s.id), report=_compact(reports.get(s.id, {})))
        return issues, {"previews": previews, "stats": stats}


def _compact(rep: dict[str, Any]) -> dict[str, Any]:
    out = {"motion": rep.get("motion")}
    fr = rep.get("frames", {})
    if fr:
        k = sorted(fr, key=int)[len(fr) // 2]
        out["mid_frame"] = {k: fr[k]}
    return out
