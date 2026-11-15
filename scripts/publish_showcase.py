#!/usr/bin/env python3
"""Copy a rendered project into examples/showcase/<name>/ (small: compressed MP4, previews, log viewer).

usage: python scripts/publish_showcase.py output/<project> [name]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_MB = 9.0


def main() -> None:
    src = Path(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else src.name
    dst = ROOT / "examples" / "showcase" / name
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "log" / "previews").mkdir(parents=True)
    final = src / "final.mp4"
    if final.exists():
        for crf in (24, 27, 30, 33):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(final), "-map", "0", "-c:v", "libx264", "-crf", str(crf),
                            "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "copy", "-c:s", "copy", "-movflags", "+faststart",
                            str(dst / "final.mp4")], check=True)
            if (dst / "final.mp4").stat().st_size / 1e6 < MAX_MB:
                break
    for f in ("final.srt", "scene.usda", "GDD.json", "PLAYTEST.json", "README.md", "screenshot.png"):
        if (src / f).exists():
            shutil.copy2(src / f, dst / f)
    if (src / "audio" / "audio_manifest.json").exists():
        shutil.copy2(src / "audio" / "audio_manifest.json", dst / "audio_manifest.json")
    for f in ("production.jsonl", "contact_sheet.jpg"):
        if (src / "log" / f).exists():
            shutil.copy2(src / "log" / f, dst / "log" / f)
    for p in sorted((src / "log" / "previews").glob("iter*.png")):
        shutil.copy2(p, dst / "log" / "previews" / p.name)
    if (src / "project.json").exists():
        data = json.loads((src / "project.json").read_text())
        data.get("artifacts", {}).pop("mouth_keys", None)
        # make artifact paths relative to the showcase folder
        arts = data.get("artifacts", {})
        for k in ("final", "contact_sheet"):
            if arts.get(k):
                rel = Path(arts[k]).relative_to(src.resolve() if Path(arts[k]).is_absolute() else src)
                arts[k] = str((dst / rel).relative_to(ROOT))
        (dst / "project.json").write_text(json.dumps(data, indent=1))
        # previews in the log point at the original project; rewrite them to the copied folder
        log = dst / "log" / "production.jsonl"
        if log.exists():
            lines = []
            for line in log.read_text().splitlines():
                ev = json.loads(line)
                if ev.get("preview"):
                    p = dst / "log" / "previews" / Path(ev["preview"]).name
                    ev["preview"] = str(p.relative_to(ROOT)) if p.exists() else None
                lines.append(json.dumps(ev))
            log.write_text("\n".join(lines) + "\n")
        sys.path.insert(0, str(ROOT / "src"))
        import os

        from animatica.cli.logview import write_log_html

        os.chdir(ROOT)
        write_log_html(dst)
    total = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) / 1e6
    print(f"{dst} ({total:.1f} MB)")


if __name__ == "__main__":
    main()
