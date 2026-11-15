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


def encode(
    frames_dir: str | Path,
    fps: int,
    audio: str | Path | None,
    out: str | Path,
    crf: int = 22,
    pattern: str = "frame_%04d.png",
    start_number: int = 1,
    preset: str = "medium",
    subtitles: str | Path | None = None,
    loudnorm: bool = True,
) -> Path:
    """PNG sequence + audio (+ optional soft subtitles) -> MP4. Audio is loudness-normalised (EBU R128, -16 LUFS)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-loglevel",
        "error",
        "-framerate",
        str(fps),
        "-start_number",
        str(start_number),
        "-i",
        str(Path(frames_dir) / pattern),
    ]
    if audio:
        cmd += ["-i", str(audio)]
    if subtitles:
        cmd += ["-i", str(subtitles)]
    cmd += ["-map", "0:v"]
    if audio:
        cmd += ["-map", "1:a"]
    if subtitles:
        cmd += ["-map", f"{2 if audio else 1}:s", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if audio:
        if loudnorm:
            cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000"]
        cmd += ["-c:a", "aac", "-b:a", "160k"]  # no -shortest: the subtitle stream would end the file early
    cmd.append(str(out))
    subprocess.run(cmd, check=True, timeout=3600)
    return out


def probe(path: str | Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        return {}
    out = subprocess.run(
        [
            exe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    import json

    return json.loads(out.stdout)


def contact_sheet(video: str | Path, out: str | Path, cols: int = 4, rows: int = 3, width: int = 320) -> Path:
    """Tile evenly spaced frames into one image (used by the log viewer and the Critic)."""
    info = probe(video)
    dur = float(info.get("format", {}).get("duration", 10))
    n = cols * rows
    fps = n / max(dur, 0.1)
    subprocess.run(
        [
            ffmpeg_bin(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={fps:.4f},scale={width}:-1,tile={cols}x{rows}",
            "-frames:v",
            "1",
            str(out),
        ],
        check=True,
        timeout=600,
    )
    return Path(out)


def write_srt(lines: list[tuple[float, float, str]], out: str | Path) -> Path:
    """Captions from the script + TTS timings (exact text, no ASR)."""

    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    blocks = [f"{i}\n{ts(a)} --> {ts(b)}\n{text}\n" for i, (a, b, text) in enumerate(lines, 1)]
    Path(out).write_text("\n".join(blocks))
    return Path(out)


FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _font(size: int):
    from PIL import ImageFont

    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def make_title_png(
    title: str, subtitle: str, size: tuple[int, int], out: str | Path, accent: str = "#FFD9A8"
) -> Path:
    """Transparent title overlay (lower-left third, soft shadow) in the film's palette."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    size_big = max(18, h // 11)
    big = _font(size_big)
    probe = ImageDraw.Draw(img)
    while size_big > 14 and probe.textlength(title, font=big) > w * 0.6:  # fit: at most 60% of the width
        size_big -= 2
        big = _font(size_big)
    small = _font(max(13, h // 26))
    x, y = int(w * 0.06), int(h * 0.08)  # upper-left: sits in the sky, away from the action
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.text((x + 3, y + 3), title, font=big, fill=(0, 0, 0, 170))
    sd.text((x + 2, y + int(h * 0.12) + 2), subtitle, font=small, fill=(0, 0, 0, 230))
    sd.text((x + 1, y + int(h * 0.12) + 1), subtitle, font=small, fill=(0, 0, 0, 230))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(4)))
    d = ImageDraw.Draw(img)
    r, g, b = (int(accent[i : i + 2], 16) for i in (1, 3, 5))
    d.text((x, y), title, font=big, fill=(255, 255, 255, 245))
    d.text((x, y + int(h * 0.12)), subtitle, font=small, fill=(r, g, b, 235))
    img.save(out)
    return Path(out)


def overlay_title(
    video: str | Path,
    title_png: str | Path,
    out: str | Path,
    start: float = 0.6,
    end: float = 4.4,
    crf: int = 22,
) -> Path:
    """Fade the title overlay in/out over the opening shot (timing, audio and captions unchanged)."""
    fade = 0.7
    flt = (
        f"[1:v]format=rgba,fade=in:st={start}:d={fade}:alpha=1,fade=out:st={end - fade}:d={fade}:alpha=1[t];"
        f"[0:v][t]overlay=0:0:eof_action=pass[v]"
    )
    subprocess.run(
        [
            ffmpeg_bin(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-loop",
            "1",
            "-t",
            str(end + 0.1),
            "-i",
            str(title_png),
            "-filter_complex",
            flt,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-c:s",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
        timeout=1800,
    )
    return Path(out)
