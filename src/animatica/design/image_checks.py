"""Measure rendered design-sheet views (numpy + Pillow): the hard checks a human caught too late before.

* :func:`neck_notch` — in the side silhouette (facing left), how clearly the head separates from the body:
  the larger of the dip in the top contour behind the head (forehead/poll above the neck) and the narrowing
  of the figure's upper outline between the head and the shoulders (throat), both as a fraction of the head's
  height in the image, or a head carried at least half a head above the back (``lift``, weighted 0.3).
  ~0 means the head melts into the body.
* :func:`floating_parts` — silhouette pieces not connected to the main figure (a floating brow, ear or paw).
* :func:`dark_blob` — the largest connected near-black area inside the figure in a colour view, as a fraction
  of the figure: the "flat black block" class (black legs, sunglasses patches).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def load_mask(path: str | Path) -> np.ndarray:
    """Figure mask from a silhouette PNG: alpha if present, else dark-on-light."""
    im = Image.open(path)
    if im.mode in ("RGBA", "LA"):
        return np.asarray(im.getchannel("A")) > 127
    g = np.asarray(im.convert("L"), dtype=np.float32)
    return g < 128


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return list(zip(starts.tolist(), ends.tolist()))


def components(mask: np.ndarray) -> list[int]:
    """Sizes (pixels) of the 8-connected components of ``mask``, largest first (run-based union-find)."""
    parent: list[int] = []
    size: list[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    prev: list[tuple[int, int, int]] = []
    for row in mask:
        cur = []
        for s, e in _runs(row):
            i = len(parent)
            parent.append(i)
            size.append(e - s)
            for ps, pe, pi in prev:
                if ps <= e and pe >= s:  # touching or diagonal (8-connected)
                    a, b = find(i), find(pi)
                    if a != b:
                        parent[b] = a
                        size[a] += size[b]
            cur.append((s, e, i))
        prev = cur
    roots = {find(i) for i in range(len(parent))}
    return sorted((size[r] for r in roots), reverse=True)


def floating_parts(mask: np.ndarray, min_frac: float = 0.002) -> int:
    """Pieces apart from the main figure, ignoring specks below ``min_frac`` of the figure."""
    comp = components(mask)
    if not comp:
        return 0
    return sum(1 for c in comp[1:] if c >= min_frac * comp[0])


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())


LIFT_MIN = 0.5  # head top above the back's highest point, in head heights, before the lift counts
LIFT_WEIGHT = 0.3


def neck_notch(mask: np.ndarray, head_zone: float = 0.32) -> dict[str, float]:
    """Head/body separation in a side silhouette with the animal facing left (see module doc)."""
    x0, x1, y0, y1 = _bbox(mask)
    w = x1 - x0 + 1
    cols = range(x0, x1 + 1)
    top = np.full(w, np.nan)
    for i, x in enumerate(cols):
        ys = np.flatnonzero(mask[:, x])
        if ys.size:
            top[i] = ys[0]
    height = y1 - top  # contour height above the figure's lowest point, in pixels
    hz = max(2, int(w * head_zone))
    body_from = int(w * 0.45)
    body_i = body_from + int(np.nanargmax(height[body_from:]))
    # belly line: median bottom of the top run across the body zone (legs hang below it)
    bottoms = []
    for x in range(x0 + body_from, x1 + 1):
        rr = _runs(mask[:, x])
        if rr:
            bottoms.append(rr[0][1])
    belly = int(np.median(bottoms)) if bottoms else y1

    def thickness(i: int) -> float:  # the top run (clipped at the belly line): head/neck/back, not legs
        rr = _runs(mask[:, x0 + i])
        return float(max(0, min(rr[0][1], belly) - rr[0][0])) if rr else 0.0

    # the head column: the thickest column among the high ones in the front zone (not an ear tip, ossicone
    # or the hanging trunk)
    hmax = float(np.nanmax(height[:hz]))
    high = [i for i in range(hz) if height[i] >= hmax - 0.6 * (hmax - float(np.nanmin(height[:hz])) + 1)]
    head_i = max(high, key=thickness)
    head_t = max(1.0, thickness(head_i))
    lo, hi = sorted((head_i, body_i))
    seg = height[lo : hi + 1]
    top_dip = float(min(height[head_i], height[body_i]) - np.nanmin(seg)) if seg.size else 0.0
    # throat: the top run narrows between the head and the shoulders
    th = np.asarray([thickness(i) for i in range(lo, hi + 1)])
    throat = float((head_t - th.min()) / head_t) if th.size else 0.0
    head_h = head_t
    # a head carried well above the back line on a sloping neck (a meerkat or a dog on all fours) is separate
    # even without a dip or a throat; a melted head sits level with the back. Counts only from half a head up.
    lift = float(height[head_i] - height[body_i]) / head_h
    raised = LIFT_WEIGHT * lift if lift >= LIFT_MIN else 0.0
    return {
        "neck_notch": round(max(top_dip / head_h, throat, raised), 4),
        "top_dip": round(top_dip / head_h, 4),
        "throat": round(throat, 4),
        "lift": round(lift, 4),
    }


def dark_blob(rgb_path: str | Path, mask: np.ndarray, threshold: float = 0.05) -> float:
    """Largest connected near-black region inside the figure / figure area (linear luminance < threshold)."""
    im = np.asarray(Image.open(rgb_path).convert("RGB"), dtype=np.float32) / 255.0
    lin = np.where(im <= 0.04045, im / 12.92, ((im + 0.055) / 1.055) ** 2.4)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    if lum.shape != mask.shape:
        return 0.0
    dark = (lum < threshold) & mask
    comp = components(dark)
    area = int(mask.sum())
    return round(comp[0] / area, 4) if comp and area else 0.0


def sheet_metrics(silhouette: str | Path, side_rgb: str | Path | None = None) -> dict[str, Any]:
    mask = load_mask(silhouette)
    out: dict[str, Any] = {"floating_parts": floating_parts(mask), **neck_notch(mask)}
    if side_rgb is not None:
        out["dark_blob"] = dark_blob(side_rgb, mask)
    return out


def expression_change(neutral: str | Path, other: str | Path, delta: float = 0.08) -> float:
    """Share of the figure's pixels in a face close-up that visibly change between two expressions.

    Both renders come from the same camera and frame size; a pixel counts when any channel moves by more than
    ``delta``. Brows that barely lift and a smile one pixel wide score ~0.01: the expression doesn't read.
    """
    a = np.asarray(Image.open(neutral).convert("RGBA"), dtype=np.float32) / 255.0
    b = np.asarray(Image.open(other).convert("RGBA"), dtype=np.float32) / 255.0
    if a.shape != b.shape:
        return 0.0
    fig = (a[..., 3] > 0.5) | (b[..., 3] > 0.5)
    if not fig.any():
        return 0.0
    diff = np.abs(a - b).max(axis=-1)
    return round(float((diff[fig] > delta).mean()), 4)
