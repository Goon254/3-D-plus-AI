"""Editor: final timeline -> rendered frames -> MP4 with sound. Also puts the mix on the .blend's VSE
so an artist opening the project hears the same soundtrack."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

from ..audio import mux
from .base import Agent

if TYPE_CHECKING:
    from ..core.orchestrator import Context

QUALITY = {
    # name: engine, resolution, samples
    "ci": ("workbench", (192, 108), 1),
    "preview": ("workbench", (480, 270), 1),
    "draft": ("cycles", (640, 360), 8),
    "final": ("cycles", (960, 540), 16),
    "high": ("cycles", (1280, 720), 48),
}


class Editor(Agent):
    role = "editor"
    task = "editor"
    system_prompt = "Editor."

    def run(self, ctx: Context) -> dict[str, Any]:
        plan = ctx.plan
        root = ctx.state.root
        quality = ctx.options.get("quality", "final")
        engine, res, samples = QUALITY[quality]
        frames_dir = root / "frames"
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
        mix = ctx.state.artifacts.get("mix")
        ops: list[dict[str, Any]] = [
            {"op": "set_render", "engine": engine, "resolution": list(res), "samples": samples, "fps": plan.fps},
        ]
        if mix:
            ops.append({"op": "add_sound_strip", "id": "soundtrack", "path": mix, "frame_start": 1, "channel": 1})
        ops.append({"op": "save", "path": str(ctx.state.blend)})
        self.submit(ctx, self.batch(f"Set up the edit: {engine} {res[0]}x{res[1]}, soundtrack on the VSE, save .blend", ops))
        ctx.log.event("render", self.role, f"rendering {plan.frame_end} frames ({plan.duration:.1f}s) with {engine} at "
                      f"{res[0]}x{res[1]}, {samples} samples ...")
        r = ctx.engine.run_batch({"batch_id": "render-final", "agent": "editor", "intent": "render all shots",
                                  "ops": [{"op": "render_final", "output_dir": str(frames_dir)}]})
        if not r.ok:
            raise RuntimeError(f"render failed: {r.errors}")
        secs = r.data.get("render_seconds", 0)
        ctx.log.event("render", self.role, f"rendered in {secs:.0f}s ({secs / max(plan.frame_end, 1):.2f}s/frame)",
                      render_seconds=secs)
        out = root / "final.mp4"
        lines = ctx.state.artifacts.get("lines", {})
        srt = None
        if lines:
            srt = mux.write_srt([(v["start_s"], v["start_s"] + v["duration"] + 0.4, d.text) for d in plan.dialogue
                                 if (v := lines.get(d.id))], root / "final.srt")
        mux.encode(frames_dir, plan.fps, mix, out, crf=int(ctx.options.get("crf", 23)), subtitles=srt)
        if not ctx.options.get("no_title"):
            card = mux.make_title_png(plan.title, f"an Animatica short · {plan.hero.name}", res, root / "log" / "title.png",
                                      accent=plan.style.palette.sun)
            titled = root / "final_titled.mp4"
            mux.overlay_title(out, card, titled, crf=int(ctx.options.get("crf", 23)))
            titled.replace(out)
            ctx.log.event("render", self.role, f"title overlay '{plan.title}' over the opening shot")
        from ..audio.timeline import write_mlt

        mlt = write_mlt(root, plan, ctx.state.artifacts, res)
        ctx.state.artifacts["edit_mlt"] = str(mlt)
        sheet = root / "log" / "contact_sheet.jpg"
        try:
            mux.contact_sheet(out, sheet)
        except Exception as e:  # noqa: BLE001
            ctx.log.event("warning", self.role, f"contact sheet failed: {e}")
        info = mux.probe(out)
        ctx.log.event("render", self.role, f"final cut -> {out} ({out.stat().st_size / 1e6:.1f} MB)", output=str(out), probe=info)
        if not ctx.options.get("keep_frames", False):
            shutil.rmtree(frames_dir, ignore_errors=True)
        ctx.state.artifacts.update({"final": str(out), "contact_sheet": str(sheet), "render_seconds": secs, "quality": quality})
        return {"final": str(out)}
