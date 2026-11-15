"""Reference study (Milestone 8): learn style notes from *legally usable* media.

Input: local files only — user-supplied clips/images, Blender Studio open movies (CC-BY), CC0/CC-BY media,
or our own renders. URLs are refused on purpose: nothing is downloaded, and never from YouTube or other
sites against their terms. Record the source and license of each reference.

Extracted (offline, numpy + ffmpeg): cut points and average shot length, a 6-colour palette, brightness,
contrast, warmth, saturation and motion energy. With a vision-capable LLM, a few keyframes are also
described (timing, poses, camera language, colour). Results go to ``knowledge/styles/<name>.json`` and
can steer the Director (``animatica film --style <name>``).
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

STYLES_DIR = Path(__file__).parent / "styles"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _refuse_remote(src: str) -> None:
    if re.match(r"^[a-z]+://", src, re.I):
        raise ValueError(
            "reference study only accepts local files you have the right to use (no URLs, no downloading)"
        )


def extract_frames(video: Path, out_dir: Path, every_s: float = 0.5, width: int = 320) -> list[Path]:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"fps={1 / every_s},scale={width}:-1",
            str(out_dir / "f_%05d.png"),
        ],
        check=True,
        timeout=1800,
    )
    return sorted(out_dir.glob("f_*.png"))


def detect_cuts(video: Path, threshold: float = 0.3) -> list[float]:
    p = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(video),
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", p.stderr)]


def duration(video: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def palette(pixels: np.ndarray, k: int = 6, iters: int = 12, seed: int = 0) -> list[tuple[str, float]]:
    rng = np.random.default_rng(seed)
    px = pixels[rng.choice(len(pixels), size=min(len(pixels), 20000), replace=False)].astype(np.float32)
    centers = px[rng.choice(len(px), size=k, replace=False)]
    for _ in range(iters):
        labels = ((px[:, None, :] - centers[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            sel = px[labels == j]
            if len(sel):
                centers[j] = sel.mean(0)
    counts = np.bincount(labels, minlength=k) / len(labels)
    order = np.argsort(-counts)
    return [
        ("#{:02X}{:02X}{:02X}".format(*(int(c) for c in centers[j])), round(float(counts[j]), 3))
        for j in order
    ]


def analyse_frames(frames: list[Path]) -> dict[str, Any]:
    arrs = [np.asarray(Image.open(f).convert("RGB"), dtype=np.float32) for f in frames]
    allpx = np.concatenate([a.reshape(-1, 3) for a in arrs])
    lum = 0.2126 * allpx[:, 0] + 0.7152 * allpx[:, 1] + 0.0722 * allpx[:, 2]
    mx, mn = allpx.max(1), allpx.min(1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    warmth = float((allpx[:, 0] - allpx[:, 2]).mean() / 255)
    motion = [float(np.abs(a - b).mean() / 255) for a, b in zip(arrs, arrs[1:]) if a.shape == b.shape]
    return {
        "frames_analysed": len(frames),
        "palette": palette(allpx),
        "brightness": round(float(lum.mean() / 255), 3),
        "contrast": round(float(lum.std() / 255), 3),
        "saturation": round(float(sat.mean()), 3),
        "warmth": round(warmth, 3),
        "motion_energy": round(float(np.mean(motion)) if motion else 0.0, 4),
    }


def study(sources: list[str], name: str, license_note: str, provider=None) -> dict[str, Any]:
    """Analyse local reference media and store a style note."""
    frames: list[Path] = []
    cuts_total, dur_total, n_videos = 0, 0.0, 0
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        for i, src in enumerate(sources):
            _refuse_remote(src)
            p = Path(src)
            if not p.exists():
                raise FileNotFoundError(src)
            if p.suffix.lower() in IMAGE_EXT:
                frames.append(p)
                continue
            sub = tdir / f"v{i}"
            sub.mkdir()
            frames += extract_frames(p, sub)
            cuts = detect_cuts(p)
            cuts_total += len(cuts)
            dur_total += duration(p)
            n_videos += 1
        if not frames:
            raise ValueError("no frames to analyse")
        notes = analyse_frames(frames)
        if n_videos:
            notes["cuts"] = cuts_total
            notes["average_shot_length_s"] = round(dur_total / (cuts_total + n_videos), 2)
        if provider is not None and getattr(provider, "supports_vision", False):
            picks = [frames[int(j)] for j in np.linspace(0, len(frames) - 1, num=min(4, len(frames)))]
            try:
                notes["vision"] = provider.complete_json(
                    "study.describe",
                    "You are an animation supervisor. Describe the timing, posing, camera language and "
                    'colour of these reference frames as reusable style notes. JSON: {"notes": [str]}',
                    {"name": name},
                    images=picks,
                ).get("notes", [])
            except Exception as e:  # noqa: BLE001
                notes["vision_error"] = str(e)[:200]
    notes.update({"name": name, "sources": [Path(s).name for s in sources], "license": license_note})
    notes["director_hints"] = style_hints(notes)
    STYLES_DIR.mkdir(exist_ok=True)
    (STYLES_DIR / f"{name}.json").write_text(json.dumps(notes, indent=1))
    return notes


def style_hints(notes: dict[str, Any]) -> dict[str, Any]:
    """Translate measurements into Director parameters (palette roles, mood, pacing)."""
    pal = [c for c, _ in notes["palette"]]
    mood = "warm" if notes["warmth"] > 0.08 else "mysterious" if notes["brightness"] < 0.25 else "wonder"
    if notes["motion_energy"] > 0.08:
        mood = "playful"
    lum = lambda h: sum(int(h[i : i + 2], 16) for i in (1, 3, 5))  # noqa: E731
    by_l = sorted(pal, key=lum)
    return {
        "mood": mood,
        "sky_zenith": by_l[0],
        "ground": by_l[1],
        "sky_horizon": by_l[-1],
        "shot_length_s": notes.get("average_shot_length_s"),
    }


def load_style(name: str) -> dict[str, Any] | None:
    p = STYLES_DIR / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None
