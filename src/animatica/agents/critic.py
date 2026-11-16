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

        # the robot has a screen face; a critter's face is its head
        face = "hero_face" if "hero_face" in ctx.engine.known_ids else "hero_head"
        inspect_ops = []
        for s in plan.shots:
            f0, f1 = frames[s.id]
            subj = ["hero_head"] if s.type == "closeup" else ["hero_root"]
            if s.subject in ("both", "prop") and plan.prop and s.type != "closeup":
                subj.append("prop")
            if dialogue_frames.get(s.id):
                if face not in subj:
                    subj.append(face)  # lip sync must be readable on screen
                if plan.prop and "prop" not in subj:
                    subj.append("prop")  # ...and the one being addressed should be in the shot
            sample = set(self.sample_frames(f0, f1))
            for a, b in dialogue_frames.get(s.id, []):
                sample |= set(range(a, b + 1, 3))
            inspect_ops.append(
                {
                    "op": "inspect",
                    "subjects": subj,
                    "frames": sorted(sample),
                    "camera": f"cam_{s.id}",
                    "shape_key_target": "hero_mouth",
                    **({"facing_target": "hero_head_pivot"} if dialogue_frames.get(s.id) else {}),
                }
            )
        res = ctx.engine.run_batch(
            {
                "batch_id": f"critic-inspect-{iteration}",
                "agent": "critic",
                "intent": "geometric checks",
                "ops": inspect_ops,
            }
        )
        reports = dict(zip([s.id for s in plan.shots], res.data.get("inspects", [])))
        preview_ops = []
        for s in plan.shots:
            f0, f1 = frames[s.id]
            mid = (f0 + f1) // 2
            path = str(prev_dir / f"iter{iteration}_{s.id}_f{mid}.png")
            preview_ops.append(
                {
                    "op": "render_preview",
                    "camera": f"cam_{s.id}",
                    "frame": mid,
                    "path": path,
                    "resolution": [480, 270],
                    "engine": ctx.options.get("preview_engine", "cycles"),
                    **({"device": ctx.options["device"]} if ctx.options.get("device") else {}),
                }
            )
        pr = ctx.engine.run_batch(
            {
                "batch_id": f"critic-preview-{iteration}",
                "agent": "critic",
                "intent": "one preview per shot",
                "ops": preview_ops,
            }
        )
        for s, p in zip(plan.shots, pr.data.get("previews", [])):
            previews[s.id] = p["path"]
            stats[s.id] = p["stats"]

        exit_note = (ctx.results.get("anim") or {}).get("exit") or {}
        for s in plan.shots:
            rep = reports.get(s.id, {})
            fr = rep.get("frames", {})
            subj_main = "hero_head" if s.type == "closeup" else "hero_root"
            if exit_note.get("shot") == s.id:
                # an exit: framing rules hold until the hero departs; after that it must leave the frame
                depart_f = int(float(exit_note["depart_t"]) * plan.fps) + 1
                issues += exit_issues(s.id, fr, depart_f, subj_main)
                framing = {k: f for k, f in fr.items() if int(k) <= depart_f}
                # floor contact still matters while any of the hero is on screen
                fr = {
                    k: f
                    for k, f in fr.items()
                    if f.get("subjects", {}).get(subj_main, {}).get("visible_fraction", 1) > 0
                }
            else:
                framing = fr
            vis = [f["subjects"][subj_main] for f in framing.values() if subj_main in f.get("subjects", {})]
            if vis:
                worst = min(v.get("visible_fraction", 1) for v in vis)
                heights = [v.get("screen_height", 0) for v in vis]
                lo, hi = SIZE_RANGE[s.type]
                if worst < 0.85:
                    issues.append(
                        Issue(
                            s.id,
                            "off_frame",
                            "blocker",
                            f"{subj_main} only {worst:.0%} inside frame in {s.id}",
                            {"kind": "camera", "fill_mul": 0.85},
                        )
                    )
                if max(heights) > hi:
                    issues.append(
                        Issue(
                            s.id,
                            "too_tight",
                            "blocker",
                            f"subject fills {max(heights):.0%} of frame height (max {hi:.0%})",
                            {"kind": "camera", "fill_mul": round(hi / max(heights) * 0.95, 3)},
                        )
                    )
                elif max(heights) < lo:
                    issues.append(
                        Issue(
                            s.id,
                            "too_small",
                            "minor",
                            f"subject only {max(heights):.0%} of frame height (min {lo:.0%})",
                            {"kind": "camera", "fill_mul": round(lo / max(max(heights), 0.01) * 1.05, 3)},
                        )
                    )
                if any(v.get("behind_camera") for v in vis):
                    issues.append(
                        Issue(
                            s.id,
                            "behind_camera",
                            "blocker",
                            "subject behind the camera",
                            {"kind": "camera", "azimuth_add": 15},
                        )
                    )
            if s.type != "closeup":
                mins = [
                    f["subjects"]["hero_root"]["min_z"]
                    for f in fr.values()
                    if "hero_root" in f.get("subjects", {})
                ]
                if mins and min(mins) < -0.03:
                    issues.append(
                        Issue(
                            s.id,
                            "floor_intersection",
                            "blocker",
                            f"hero dips {abs(min(mins)):.2f} m into the floor",
                            {"kind": "animator", "floor_offset_add": round(-min(mins), 3)},
                        )
                    )
                elif mins and min(mins) > 0.08 and s.beat not in ("react", "celebrate"):
                    issues.append(
                        Issue(
                            s.id,
                            "floating",
                            "blocker",
                            f"hero floats {min(mins):.2f} m above the floor",
                            {"kind": "animator", "floor_offset_add": round(-min(mins), 3)},
                        )
                    )
            if s.subject in ("both", "prop") and plan.prop and s.type != "closeup":
                pv = [
                    f["subjects"]["prop"].get("visible_fraction", 1)
                    for f in rep.get("frames", {}).values()
                    if "prop" in f.get("subjects", {})
                ]
                if pv and min(pv) < 0.8:
                    issues.append(
                        Issue(
                            s.id,
                            "prop_off_frame",
                            "blocker",
                            f"the {plan.prop.kind} leaves the frame",
                            {"kind": "camera", "fill_mul": 0.85},
                        )
                    )
            if s.id in ctx.state.artifacts.get("single_shots", []):
                issues += prop_sliver_issues(s.id, fr, plan.prop.kind if plan.prop else None)
            issues += dialogue_framing_issues(
                s.id,
                fr,
                dialogue_frames.get(s.id, []),
                plan.prop.kind if plan.prop else None,
                shot_type=s.type,
                face=face,
                addressee=s.id not in ctx.state.artifacts.get("single_shots", []),
            )
            for a, b in dialogue_frames.get(s.id, []):
                inside = [f for k, f in fr.items() if a <= int(k) <= b]
                mouth_vals = [f.get("mouth", 0) for f in inside]
                if inside and max(mouth_vals) < 0.05:
                    issues.append(
                        Issue(
                            s.id,
                            "mouth_static",
                            "blocker",
                            "mouth not moving during dialogue",
                            {"kind": "voice"},
                        )
                    )
            st = stats.get(s.id, {})
            if st:
                if st.get("mean", 0.5) < 0.07 or st.get("black", 0) > 0.6:
                    issues.append(
                        Issue(
                            s.id,
                            "too_dark",
                            "blocker",
                            f"preview too dark (mean {st.get('mean')})",
                            {"kind": "lighting", "exposure_add": 0.6},
                        )
                    )
                elif st.get("mean", 0.5) > 0.82 or st.get("white", 0) > 0.25:
                    issues.append(
                        Issue(
                            s.id,
                            "blown_out",
                            "blocker",
                            f"preview blown out (mean {st.get('mean')})",
                            {"kind": "lighting", "exposure_add": -0.5},
                        )
                    )
            motion = sum(rep.get("motion", {}).values())
            if motion < 0.02 and s.camera_move == "static":
                issues.append(Issue(s.id, "static_shot", "minor", "nothing moves in this shot", {}))

        if self.provider.supports_vision and ctx.options.get("vision_critic", True):
            try:
                payload = {
                    "shots": [{"id": s.id, "type": s.type, "goal": s.description} for s in plan.shots],
                    "geometric_issues": [asdict(i) for i in issues],
                }
                out = self.provider.complete_json(
                    self.task, self.system_prompt, payload, images=[previews[s.id] for s in plan.shots]
                )
                for it in out.get("issues", [])[:8]:
                    issues.append(
                        Issue(
                            str(it.get("shot")),
                            "vision",
                            it.get("severity", "minor"),
                            str(it.get("message", ""))[:300],
                            it.get("fix") or {},
                        )
                    )
            except Exception as e:  # noqa: BLE001 - vision review is best-effort
                ctx.log.event("warning", self.role, f"vision review skipped: {e}")

        for s in plan.shots:
            mine = [i for i in issues if i.shot == s.id]
            verdict = "PASS" if not any(i.severity == "blocker" for i in mine) else "FAIL"
            ctx.log.event(
                "critique",
                self.role,
                f"iter {iteration} {s.id} ({s.type}): {verdict}"
                + (": " + "; ".join(i.message for i in mine) if mine else ""),
                iteration=iteration,
                shot=s.id,
                verdict=verdict,
                issues=[asdict(i) for i in mine],
                preview=previews.get(s.id),
                stats=stats.get(s.id),
                report=_compact(reports.get(s.id, {})),
            )
        return issues, {"previews": previews, "stats": stats}


def exit_issues(shot_id: str, frames: dict[str, Any], depart_f: int, subj: str = "hero_root") -> list[Issue]:
    """An exit beat must read as leaving: by the shot's last sampled frame the hero is out of frame."""
    after = sorted(
        (int(k), f) for k, f in frames.items() if int(k) > depart_f and subj in f.get("subjects", {})
    )
    if not after:
        return []
    last_f, last = after[-1]
    v = last["subjects"][subj]
    seen = 0.0 if v.get("behind_camera") else float(v.get("visible_fraction", 0))
    if seen > 0.05:
        return [
            Issue(
                shot_id,
                "exit_in_frame",
                "blocker",
                f"the hero is still {seen:.0%} in frame at f{last_f}: the exit doesn't read as leaving",
                {"kind": "animator", "exit_speed_mul": 1.3},
            )
        ]
    return []


FACE_TURN_MAX = 35.0  # degrees of head yaw away from the lens while speaking (review 14:50)
ADDRESSEE_MIN = {"closeup": 0.8, "medium": 0.8, "wide": 0.6}
# per-kind face-size floor while speaking: the robot's screen face is big; a critter's mouth sits on a small
# snout, so its head (the measured "face") must fill more of the frame (review 11-16 17:25)
FACE_MIN = {"hero_face": 0.2, "hero_head": 0.3}


def dialogue_framing_issues(
    shot: str,
    frames: dict[str, Any],
    windows: list[tuple[int, int]],
    prop_kind: str | None,
    shot_type: str = "closeup",
    face: str = "hero_face",
    addressee: bool = True,
) -> list[Issue]:
    """Lip-sync readability, eyeline and addressee checks over the inspected frames inside dialogue windows."""
    issues: list[Issue] = []
    inside = [f for k, f in frames.items() if any(a <= int(k) <= b for a, b in windows)]
    faces = [f["subjects"][face] for f in inside if face in f.get("subjects", {})]
    if faces:
        fh = min(v.get("screen_height", 0) for v in faces)
        fv = min(v.get("visible_fraction", 1) for v in faces)
        floor = FACE_MIN.get(face, 0.2)
        if fh < floor:
            issues.append(
                Issue(
                    shot,
                    "face_too_small",
                    "blocker",
                    f"face is {fh:.0%} of frame height while speaking (min {floor:.0%}): lip sync unreadable",
                    {"kind": "camera", "fill_mul": round(min(1.6, (floor + 0.02) / max(fh, 0.02)), 3)},
                )
            )
        if fv < 0.95:
            issues.append(
                Issue(
                    shot,
                    "face_cut",
                    "blocker",
                    f"face only {fv:.0%} in frame while speaking",
                    {"kind": "camera", "fill_mul": 0.9},
                )
            )
    turns = sorted(f["facing_deg"] for f in inside if "facing_deg" in f)
    if turns:
        med = turns[len(turns) // 2]
        if med > FACE_TURN_MAX:
            issues.append(
                Issue(
                    shot,
                    "face_turned_away",
                    "blocker",
                    f"the speaker's face is turned {med:.0f} deg away from the lens (max {FACE_TURN_MAX:.0f}): "
                    "no eyeline, the mouth reads edge-on",
                    {"kind": "animator", "face_cam_add": round(med - FACE_TURN_MAX + 8, 1)},
                )
            )
    props = [f["subjects"]["prop"] for f in inside if "prop" in f.get("subjects", {})]
    if prop_kind and props and addressee:
        pv = min(v.get("visible_fraction", 1) for v in props)
        need = ADDRESSEE_MIN.get(shot_type, 0.6)
        if pv < need:
            issues.append(
                Issue(
                    shot,
                    "addressee_cut",
                    "blocker",
                    f"the {prop_kind} being spoken to is only {pv:.0%} in frame (min {need:.0%})",
                    {"kind": "camera", "fill_mul": round(max(0.8, min(0.95, pv / need)), 3)},
                )
            )
    return issues


SLIVER_MAX = 0.25  # a prop less than this much in frame reads as a stray object on the edge, not as the prop


def prop_sliver_issues(shot: str, frames: dict[str, Any], prop_kind: str | None) -> list[Issue]:
    """A dialogue single keeps the addressee out of frame on purpose, but must not clip a sliver of it.

    In the fox close-up only the lantern's handle loop poked up at the bottom edge and read as a stray black
    ring (review 11-16 17:55). Raise the bottom edge until the prop leaves the frame completely (``lift_frac``:
    the share of the frame height to crop from the bottom; the camera keeps the ear-tip headroom).
    """
    if not prop_kind:
        return []
    props = [f["subjects"]["prop"] for f in frames.values() if "prop" in f.get("subjects", {})]
    peeking = [
        v
        for v in props
        if not v.get("behind_camera") and 0.0 < float(v.get("visible_fraction", 0.0)) < SLIVER_MAX
    ]
    if not peeking:
        return []
    # visible share of the frame height ~ fraction x on-screen height; lift a little more than that
    worst = max(float(v["visible_fraction"]) * float(v.get("screen_height", 0.3)) for v in peeking)
    lift = round(min(0.25, worst + 0.04), 3)
    return [
        Issue(
            shot,
            "prop_sliver",
            "blocker",
            f"only a sliver of the {prop_kind} pokes into the frame edge "
            f"({max(float(v['visible_fraction']) for v in peeking):.0%}): it reads as a stray object",
            {"kind": "camera", "lift_frac": lift},
        )
    ]


def _compact(rep: dict[str, Any]) -> dict[str, Any]:
    out = {"motion": rep.get("motion")}
    fr = rep.get("frames", {})
    if fr:
        k = sorted(fr, key=int)[len(fr) // 2]
        out["mid_frame"] = {k: fr[k]}
    return out
