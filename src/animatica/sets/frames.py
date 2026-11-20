"""Set problems measured on rendered frames (numpy + Pillow; DESIGN_STAGE §8: a human catch becomes a check).

:func:`horizon_stripe` — the owner's "horizon stripe" (11-16 set still): a thin, pale, featureless band laid
straight across the frame where the ground meets the far hills, brighter than both what is above it (hills or
sky) and the grass below. It reads as a painted line, not as distance.

How it is measured, on the frame scaled to 320 px wide (luminance, Rec. 709):

1. Per column, every thin band (1 to ``BAND_MAX`` of the frame height) is compared with the rows just above and
   just below it (one row of slack for JPEG blur). The band's *contrast* is the smaller of the two steps up; a
   column holds a band when it is ≥ ``CONTRAST_MIN``.
2. The row where most columns hold a band (± ``ROW_TOL`` of the height) is the candidate line.
3. Along that row, columns with a band are joined into runs across gaps of up to ``GAP_MAX`` of the width. A
   run counts only if it is a *line*: at least ``RUN_MIN`` of the width, straight (the band's row wanders
   ≤ ``WANDER_MAX`` of the height round a fitted line) and even (the band's thickness varies ≤ ``THICK_SD``
   rows). Sky seen through a layered acacia, a gap between two animals, or a caption wobble in row or
   thickness and drop out here.
4. ``span``: from the left end of the first line run to the right end of the last, over the frame width; ``fill``:
   the runs' total width over the frame width. A stripe has ``span`` ≥ ``SPAN_MIN`` and ``fill`` ≥ ``FILL_MIN``
   (animals and trunks in front may cut it).

Calibration (DECISIONS #99, frames in ``tests/data/frames``): the 11-16 set still (a white strip) and every
committed set still but the night one fail; on the final film the dawn, dusk and night scenes pass (sky seen between
the acacias' shelves is rejected as a wavy, uneven run), and 19 of 317 frames sampled every second fail: the
midday and afternoon wides of SC 4-6 (1:41-3:02), where a pale bare-ground band lies under the hills. The stripe was
toned down after 11-16, not removed. The check is conservative: a band cut to under half the width by the cast is
missed.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

WIDTH = 320  # measuring width (px)
BAND_MAX = 0.04  # thickest band, fraction of the frame height
CONTRAST_MIN = 0.08  # luminance step up from both neighbours
ROW_TOL = 0.012  # rows within this fraction of the height count as the same line
GAP_MAX = 0.03  # gaps in a run bridged up to this fraction of the width
RUN_MIN = 0.10  # a line run is at least this wide
WANDER_MAX = 0.006  # a line's row wanders at most this fraction of the height round its fit
THICK_SD = 1.5  # rows (at the measuring scale): a line's thickness is even
SPAN_MIN = 0.80  # a stripe spans at least this share of the frame width ...
FILL_MIN = 0.50  # ... and is drawn along at least this share of it

_LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def luminance(image: str | Path | Image.Image | np.ndarray, width: int = WIDTH) -> np.ndarray:
    """Luminance 0-1 of a frame (path, PIL image or RGB array), scaled to ``width`` px wide."""
    if isinstance(image, np.ndarray):
        im = Image.fromarray(image.astype(np.uint8)) if image.dtype != np.uint8 else Image.fromarray(image)
    elif isinstance(image, Image.Image):
        im = image
    else:
        im = Image.open(image)
    im = im.convert("RGB")
    w, h = im.size
    height = max(16, round(width * h / w))
    a = np.asarray(im.resize((width, height), Image.BILINEAR), np.float32) / 255.0
    return a @ _LUMA


def band_contrast(lum: np.ndarray, band_max: float = BAND_MAX) -> tuple[np.ndarray, np.ndarray]:
    """Per pixel (band top row, column): the best contrast of a thin bright band starting there, and its
    thickness in rows; only each column's local peak (within ``band_max``) is kept, the rest is -1."""
    h, w = lum.shape
    best = np.full((h, w), -1.0, np.float32)
    thick = np.zeros((h, w), np.int32)
    cs = np.vstack([np.zeros((1, w), np.float32), np.cumsum(lum, 0, dtype=np.float32)])
    gap = 1
    for t in range(1, max(1, round(band_max * h)) + 1):
        k = max(2, t)
        ys = np.arange(k + gap, h - t - gap - k)
        if len(ys) == 0:
            continue
        band = (cs[ys + t] - cs[ys]) / t
        above = (cs[ys - gap] - cs[ys - gap - k]) / k
        below = (cs[ys + t + gap + k] - cs[ys + t + gap]) / k
        c = np.minimum(band - above, band - below)
        cur = best[ys]
        better = c > cur
        best[ys] = np.where(better, c, cur)
        thick[ys] = np.where(better, t, thick[ys])
    # keep each column's peak only: a thicker band that merely contains a bright line is the same line
    hmax = max(1, round(band_max * h))
    peak = best.copy()
    for d in range(1, hmax + 1):
        peak[d:] = np.maximum(peak[d:], best[:-d])
        peak[:-d] = np.maximum(peak[:-d], best[d:])
    best = np.where(best >= peak, best, -1.0).astype(np.float32)
    return best, thick


def _runs(cols: np.ndarray, gap: int) -> list[tuple[int, int]]:
    xs = np.flatnonzero(cols)
    out: list[tuple[int, int]] = []
    if len(xs) == 0:
        return out
    s = p = int(xs[0])
    for x in [int(v) for v in xs[1:]] + [10**9]:
        if x - p > gap + 1:
            out.append((s, p))
            s = x
        p = x
    return out


def horizon_stripe(image: str | Path | Image.Image | np.ndarray) -> dict[str, Any]:
    """Measure a horizon stripe in one frame. Returns ``stripe`` (bool), ``row`` (the line's height from the
    top, fraction), ``span``, ``fill``, ``contrast`` (median along the line runs) and ``runs`` (each line run's
    ``x0``, ``x1``, ``wander``, ``thick_sd``, ``line``)."""
    lum = luminance(image)
    h, w = lum.shape
    best, thick = band_contrast(lum)
    hit = best >= CONTRAST_MIN
    tol = max(1, round(ROW_TOL * h))
    near = np.zeros_like(hit)
    for d in range(-tol, tol + 1):
        near |= np.roll(hit, d, 0)
    near[:tol] = near[-tol:] = False
    cover = near.mean(1)
    y = int(cover.argmax())
    rows = slice(max(0, y - tol), min(h, y + tol + 1))
    cols = hit[rows].any(0)
    runs = []
    for x0, x1 in _runs(cols, round(GAP_MAX * w)):
        xs = np.arange(x0, x1 + 1)
        xs = xs[cols[xs]]
        yb = rows.start + np.argmax(np.where(hit[rows][:, xs], best[rows][:, xs], -9), 0)
        tb = thick[yb, xs]
        if len(xs) >= 3:
            fit = np.polyval(np.polyfit(xs, yb, 1), xs)
            wander = float(np.sqrt(np.mean((yb - fit) ** 2)) / h)
        else:
            wander = 1.0
        width = (x1 - x0 + 1) / w
        line = width >= RUN_MIN and wander <= WANDER_MAX and float(tb.std()) <= THICK_SD
        runs.append(
            {
                "x0": round(x0 / w, 3),
                "x1": round((x1 + 1) / w, 3),
                "wander": round(wander, 4),
                "thick_sd": round(float(tb.std()), 2),
                "contrast": float(np.median(best[yb, xs])),
                "line": bool(line),
            }
        )
    lines = [r for r in runs if r["line"]]
    span = (lines[-1]["x1"] - lines[0]["x0"]) if lines else 0.0
    fill = sum(r["x1"] - r["x0"] for r in lines)
    contrast = float(np.median([r["contrast"] for r in lines])) if lines else 0.0
    return {
        "stripe": bool(span >= SPAN_MIN and fill >= FILL_MIN),
        "row": round(y / h, 3),
        "span": round(float(span), 3),
        "fill": round(float(fill), 3),
        "contrast": round(contrast, 3),
        "runs": runs,
    }


def grab(video: str | Path, t: float, width: int = WIDTH) -> np.ndarray | None:
    """One frame of ``video`` at ``t`` seconds as an RGB array ``width`` px wide (ffmpeg), or None past the end."""
    r = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{max(0.0, t):.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if r.returncode or not r.stdout:
        return None
    return np.asarray(Image.open(io.BytesIO(r.stdout)).convert("RGB"))


def stripes_in_video(
    video: str | Path, times: list[float], labels: list[str] | None = None
) -> list[dict[str, Any]]:
    """:func:`horizon_stripe` on the frames of ``video`` at ``times``; one entry per frame with a stripe
    (``t``, ``label``, ``row``, ``span``, ``fill``, ``contrast``)."""
    out = []
    for i, t in enumerate(times):
        rgb = grab(video, t)
        if rgb is None:
            continue
        r = horizon_stripe(rgb)
        if r["stripe"]:
            out.append(
                {
                    "t": round(t, 2),
                    "label": labels[i] if labels else "",
                    **{k: r[k] for k in ("row", "span", "fill", "contrast")},
                }
            )
    return out
