"""ffmpeg helpers: encode a PNG sequence + audio into an MP4 (H.264 + AAC)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FileNotFoundError("ffmpeg not found on PATH (see docs/SETUP.md)")
    return exe


def encode(frames_dir: str | Path, fps: int, audio: str | Path | None, out: str | Path,
           crf: int = 22, pattern: str = "frame_%04d.png", start_number: int = 1, preset: str = "medium",
           subtitles: str | Path | None = None, loudnorm: bool = True) -> Path:
    """PNG sequence + audio (+ optional soft subtitles) -> MP4. Audio is loudness-normalised (EBU R128, -16 LUFS)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error", "-framerate", str(fps), "-start_number", str(start_number),
           "-i", str(Path(frames_dir) / pattern)]
    if audio:
        cmd += ["-i", str(audio)]
    if subtitles:
        cmd += ["-i", str(subtitles)]
    cmd += ["-map", "0:v"]
    if audio:
        cmd += ["-map", "1:a"]
    if subtitles:
        cmd += ["-map", f"{2 if audio else 1}:s", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio:
        if loudnorm:
            cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000"]
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd.append(str(out))
    subprocess.run(cmd, check=True, timeout=3600)
    return out


def probe(path: str | Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        return {}
    out = subprocess.run([exe, "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    import json

    return json.loads(out.stdout)


def contact_sheet(video: str | Path, out: str | Path, cols: int = 4, rows: int = 3, width: int = 320) -> Path:
    """Tile evenly spaced frames into one image (used by the log viewer and the Critic)."""
    info = probe(video)
    dur = float(info.get("format", {}).get("duration", 10))
    n = cols * rows
    fps = n / max(dur, 0.1)
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(video), "-vf",
                    f"fps={fps:.4f},scale={width}:-1,tile={cols}x{rows}", "-frames:v", "1", str(out)],
                   check=True, timeout=600)
    return Path(out)


def write_srt(lines: list[tuple[float, float, str]], out: str | Path) -> Path:
    """Captions from the script + TTS timings (exact text, no ASR)."""

    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    blocks = [f"{i}\n{ts(a)} --> {ts(b)}\n{text}\n" for i, (a, b, text) in enumerate(lines, 1)]
    Path(out).write_text("\n".join(blocks))
    return Path(out)
