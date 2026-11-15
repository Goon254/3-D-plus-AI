"""``animatica`` command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEMO_PROMPT = ("A curious little robot discovers a flower growing in a junkyard at sunset. "
               "It says: 'Hello, little one.'")


def _studio(args: argparse.Namespace):
    from ..core.orchestrator import Studio

    opts = {"quality": args.quality, "critic_iterations": args.critic_iterations}
    if getattr(args, "no_render", False):
        opts["no_render"] = True
    if getattr(args, "tts", None):
        opts["tts_engine"] = args.tts
    if getattr(args, "preview_engine", None):
        opts["preview_engine"] = args.preview_engine
    if getattr(args, "keep_frames", False):
        opts["keep_frames"] = True
    return Studio(provider=args.llm, options=opts)


def cmd_film(args: argparse.Namespace) -> int:
    state = _studio(args).film(args.prompt, args.out, args.name)
    final = state.artifacts.get("final")
    print(f"\nproject: {state.root}\nblend:   {state.blend}\nvideo:   {final or '(not rendered)'}\nlog:     {state.root / 'log' / 'index.html'}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    args.prompt = DEMO_PROMPT
    args.name = args.name or "hello-little-one"
    return cmd_film(args)


def cmd_continue(args: argparse.Namespace) -> int:
    from ..core.continuation import continue_project

    continue_project(args.project, provider=args.llm, options={"quality": args.quality,
                                                               "critic_iterations": args.critic_iterations,
                                                               **({"no_render": True} if args.no_render else {})})
    return 0


def cmd_revise(args: argparse.Namespace) -> int:
    from ..core.continuation import revise_project

    revise_project(args.project, args.instruction, provider=args.llm,
                   options={"quality": args.quality, "critic_iterations": args.critic_iterations,
                            **({"no_render": True} if args.no_render else {})})
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    from ..core.continuation import render_project

    render_project(args.project, quality=args.quality)
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    from .logview import write_log_html

    path = write_log_html(Path(args.project))
    print(path)
    return 0


def cmd_run_batch(args: argparse.Namespace) -> int:
    from ..core.engine import BlenderSession
    from ..core.protocol import BatchValidationError

    data = json.loads(Path(args.batch).read_text())
    workdir = Path(args.workdir)
    with BlenderSession(workdir=workdir) as s:
        if args.blend:
            s.open(args.blend)
        try:
            res = s.run_batch(data)
        except BatchValidationError as e:
            print(json.dumps({"ok": False, "errors": e.errors}, indent=1))
            return 2
        print(json.dumps(res.model_dump(), indent=1))
        return 0 if res.ok else 1


def cmd_schema(args: argparse.Namespace) -> int:
    from ..core.protocol import batch_json_schema

    print(json.dumps(batch_json_schema(), indent=1))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    import shutil

    from ..audio import lipsync, tts
    from ..core import engine

    checks = {
        "blender": " ".join(engine.blender_command()[:3]) if engine.blender_available() else None,
        "ffmpeg": shutil.which("ffmpeg"),
        "tts_engines": tts.available_engines(),
        "rhubarb": lipsync.find_rhubarb(),
        "anthropic_key": bool(__import__("os").environ.get("ANTHROPIC_API_KEY")),
    }
    print(json.dumps(checks, indent=1))
    return 0 if checks["blender"] and checks["ffmpeg"] else 1


def cmd_game(args: argparse.Namespace) -> int:
    from ..games.studio import make_game

    make_game(args.prompt, args.out, args.name, provider=args.llm)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="animatica", description="AI-native animation & game studio")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser, render: bool = True) -> None:
        sp.add_argument("--llm", default="auto", choices=["auto", "scripted", "anthropic"],
                        help="LLM provider (auto = anthropic if ANTHROPIC_API_KEY else offline scripted)")
        if render:
            sp.add_argument("--quality", default="final", choices=["preview", "draft", "final", "high"])
            sp.add_argument("--critic-iterations", type=int, default=3)
            sp.add_argument("--no-render", action="store_true", help="build and review the scene, skip the final render")

    f = sub.add_parser("film", help="prompt -> animated short (MP4 with sound) + editable .blend")
    f.add_argument("prompt")
    f.add_argument("--out", default="output")
    f.add_argument("--name", default=None)
    f.add_argument("--tts", default=None, choices=["auto", "piper", "espeak", "synth"])
    f.add_argument("--preview-engine", default=None, choices=["workbench", "eevee", "cycles"])
    f.add_argument("--keep-frames", action="store_true")
    common(f)
    f.set_defaults(fn=cmd_film)

    d = sub.add_parser("demo", help="render the north-star demo short")
    d.add_argument("--out", default="output")
    d.add_argument("--name", default=None)
    d.add_argument("--tts", default=None, choices=["auto", "piper", "espeak", "synth"])
    d.add_argument("--preview-engine", default=None, choices=["workbench", "eevee", "cycles"])
    d.add_argument("--keep-frames", action="store_true")
    common(d)
    d.set_defaults(fn=cmd_demo)

    c = sub.add_parser("continue", help="continue a project after hand edits in Blender (edits are preserved)")
    c.add_argument("project")
    common(c)
    c.set_defaults(fn=cmd_continue)

    r = sub.add_parser("revise", help="targeted change, e.g. 'make the robot blue and slow down shot 2'")
    r.add_argument("project")
    r.add_argument("instruction")
    common(r)
    r.set_defaults(fn=cmd_revise)

    rr = sub.add_parser("render", help="re-render a project's .blend + soundtrack to final.mp4")
    rr.add_argument("project")
    rr.add_argument("--quality", default="final", choices=["preview", "draft", "final", "high"])
    rr.set_defaults(fn=cmd_render)

    lg = sub.add_parser("log", help="write the production log viewer (static HTML)")
    lg.add_argument("project")
    lg.set_defaults(fn=cmd_log)

    g = sub.add_parser("game", help="prompt -> runnable Godot project (games track)")
    g.add_argument("prompt")
    g.add_argument("--out", default="output")
    g.add_argument("--name", default=None)
    g.add_argument("--llm", default="auto", choices=["auto", "scripted", "anthropic"])
    g.set_defaults(fn=cmd_game)

    dev = sub.add_parser("dev", help="developer tools")
    dsub = dev.add_subparsers(dest="dev_cmd", required=True)
    rb = dsub.add_parser("run-batch", help="execute one batch JSON file in a fresh (or given) scene")
    rb.add_argument("batch")
    rb.add_argument("--blend", default=None)
    rb.add_argument("--workdir", default="output/dev")
    rb.set_defaults(fn=cmd_run_batch)
    sc = dsub.add_parser("schema", help="print the batch JSON Schema")
    sc.set_defaults(fn=cmd_schema)
    dr = dsub.add_parser("doctor", help="check installed engines and tools")
    dr.set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
