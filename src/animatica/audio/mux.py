"""ffmpeg helpers: encode a PNG sequence + audio into an MP4 (H.264 + AAC)."""

from __future__ import annotations

import json
import re
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
    Path(out).write_text("\n".join(blocks), encoding="utf-8")
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


# ---- mastering: loudness and true peak (cloud review 11-19: the web film peaked at +0.5 dBTP)

TP_CEILING_DB = -1.0  # delivery spec: true peak at or under -1 dBTP, measured on the ENCODED file
LIMIT_DB = -2.0  # the limiter's ceiling: 1 dB of margin for the AAC encoder's inter-sample overs


def true_peak_limiter(limit_db: float = LIMIT_DB, oversample: int = 4, rate: int = 48000) -> str:
    """An ffmpeg filter chain that holds the true peak under ``limit_db``: a look-ahead limiter run at
    ``oversample`` x the rate (so it sees inter-sample peaks), then back to ``rate``. Goes after loudnorm,
    whose own TP target is not guaranteed (its linear mode falls back to dynamic, and AAC adds overs)."""
    lin = 10 ** (limit_db / 20)
    return (
        f"aresample={rate * oversample},alimiter=limit={lin:.4f}:level=false:attack=1:release=80:latency=true,"
        f"aresample={rate}"
    )


def parse_ebur128(stderr: str) -> dict[str, float]:
    """The summary of ffmpeg's ``ebur128=peak=true`` filter: integrated loudness ``i`` (LUFS), loudness range
    ``lra`` (LU) and true peak ``tp`` (dBTP)."""
    s = stderr[stderr.rindex("Summary:") :]
    out = {}
    for key, pat in (
        ("i", r"I:\s+(-?[\d.]+|-inf) LUFS"),
        ("lra", r"LRA:\s+(-?[\d.]+) LU"),
        ("tp", r"Peak:\s+(-?[\d.]+|-inf) dBFS"),
    ):
        m = re.search(pat, s)
        if m:
            out[key] = float(m.group(1))
    return out


def loudness(path: str | Path) -> dict[str, float]:
    """Measure a file's audio as delivered (EBU R128 + true peak): ``{"i", "lra", "tp"}``."""
    r = subprocess.run(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_ebur128(r.stderr)


def master(
    src: str | Path,
    dst: str | Path,
    lufs: float = -14.0,
    out_args: tuple[str, ...] = ("-c:a", "aac", "-b:a", "192k", "-ar", "48000"),
    ceiling_db: float = TP_CEILING_DB,
    tries: int = 4,
) -> dict:
    """Two-pass loudnorm to ``lufs``, then the true-peak limiter, encoded with ``out_args`` (any video stream
    is copied), and **measured on the encoded file**: while its true peak is over ``ceiling_db`` the file is
    encoded again, first (native AAC) with the "fast" coder at the same limit, then with the limiter lowered
    by the excess. Returns the final measurement plus the ``limit_db`` used, the input's loudness and the
    ``aac_coder`` forced ("" when the encoder's default passed)."""
    t = f"I={lufs}:TP={ceiling_db}:LRA=11"
    r = subprocess.run(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-i",
            str(src),
            "-af",
            f"loudnorm={t}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    m = json.loads(r.stderr[r.stderr.rindex("{") : r.stderr.rindex("}") + 1])
    norm = (
        f"loudnorm={t}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
        f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
    )
    limit = LIMIT_DB
    args = list(out_args)
    got: dict[str, float] = {}
    for _ in range(tries):
        subprocess.run(
            [
                ffmpeg_bin(),
                "-v",
                "error",
                "-y",
                "-i",
                str(src),
                "-c:v",
                "copy",
                "-af",
                f"{norm},{true_peak_limiter(limit)}",
            ]
            + args
            + ["-movflags", "+faststart", str(dst)],
            check=True,
        )
        got = loudness(dst)
        if got.get("tp", 0.0) <= ceiling_db:
            break
        if _native_aac(args) and "-aac_coder" not in args:
            # ffmpeg's default AAC coder (twoloop) overshoots hard transients by up to ~7 dB, chaotically: a lower
            # limit can make it worse and costs loudness. The "fast" coder (the default in ffmpeg 4.0-4.3) keeps
            # the limiter's peaks, so switch to it at the same limit instead of lowering the limit.
            args += ["-aac_coder", "fast"]
            continue
        limit -= got["tp"] - ceiling_db + 0.3
    coder = args[args.index("-aac_coder") + 1] if "-aac_coder" in args else ""
    return {**got, "limit_db": round(limit, 2), "input_lufs": float(m["input_i"]), "aac_coder": coder}


def _native_aac(args: list[str]) -> bool:
    """Whether ``args`` encode with ffmpeg's native AAC encoder (``-c:a aac`` / ``-acodec aac``)."""
    return any(a in ("-c:a", "-acodec", "-codec:a") and b == "aac" for a, b in zip(args, args[1:]))
