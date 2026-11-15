"""Export the edit as an MLT XML timeline (opens in Shotcut / Kdenlive / `melt`).

Artist hand-off for editing: one clip per shot (cuts visible), dialogue lines on their own audio track
at the right frames, and the music bed on another — so timing and the mix can be adjusted in a real
editor. Paths are relative to the project folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr


def _frames(seconds: float, fps: int) -> int:
    return int(round(seconds * fps))


def write_mlt(
    project_root: Path,
    plan: Any,
    artifacts: dict[str, Any],
    resolution: tuple[int, int],
    out_name: str = "edit.mlt",
    picture: str = "edit/picture.mp4",
) -> Path:
    """``picture`` is a clean, picture-only render (no title, no baked mix) so a re-cut stays clean."""
    fps = plan.fps
    total = plan.frame_end
    w, h = resolution
    root = Path(project_root)

    def rel(p: str | Path) -> str:
        p = Path(p)
        try:
            return str(p.resolve().relative_to(root.resolve()))
        except ValueError:
            return str(p)

    x = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<mlt LC_NUMERIC="C" version="7.0.0" title={quoteattr(plan.title)} producer="main_bin">',
        f'  <profile description="Animatica {w}x{h} {fps}fps" width="{w}" height="{h}" progressive="1" sample_aspect_num="1" '
        f'sample_aspect_den="1" display_aspect_num="{w}" display_aspect_den="{h}" frame_rate_num="{fps}" frame_rate_den="1" colorspace="709"/>',
        f'  <producer id="picture" in="0" out="{total - 1}"><property name="resource">{picture}</property>'
        '<property name="mlt_service">avformat</property></producer>',
    ]
    lines = artifacts.get("lines", {})
    for lid, info in lines.items():
        n = _frames(info["duration"], fps)
        x.append(
            f'  <producer id="{lid}" in="0" out="{max(n - 1, 0)}"><property name="resource">{rel(info["path"])}</property>'
            '<property name="mlt_service">avformat</property></producer>'
        )
    music = artifacts.get("music")
    if music:
        x.append(
            f'  <producer id="music" in="0" out="{total - 1}"><property name="resource">{rel(music)}</property>'
            '<property name="mlt_service">avformat</property></producer>'
        )
    # V1: one entry per shot so the cuts show up as separate clips
    x.append('  <playlist id="V1">')
    for sid, (f0, f1) in plan.shot_frames().items():
        x.append(
            f'    <entry producer="picture" in="{f0 - 1}" out="{f1 - 1}"><property name="shot">{sid}</property></entry>'
        )
    x.append("  </playlist>")
    # A1: dialogue at its frames
    x.append('  <playlist id="A1">')
    cursor = 0
    for lid, info in sorted(lines.items(), key=lambda kv: kv[1]["start_s"]):
        start = _frames(info["start_s"], fps)
        if start > cursor:
            x.append(f'    <blank length="{start - cursor}"/>')
        n = max(1, _frames(info["duration"], fps))
        x.append(f'    <entry producer="{lid}" in="0" out="{n - 1}"/>')
        cursor = start + n
    x.append("  </playlist>")
    x.append(
        '  <playlist id="A2">'
        + (f'<entry producer="music" in="0" out="{total - 1}"/>' if music else "")
        + "</playlist>"
    )
    x.append(f'  <tractor id="edit" in="0" out="{total - 1}">')
    x.append(
        '    <track producer="V1" hide="audio"/>'
    )  # picture only: the editor rebuilds the mix from A1/A2
    x.append('    <track producer="A1" hide="video"/>')
    x.append('    <track producer="A2" hide="video"/>')
    x.append("  </tractor>")
    x.append("</mlt>")
    out = root / out_name
    out.write_text("\n".join(x) + "\n")
    return out
