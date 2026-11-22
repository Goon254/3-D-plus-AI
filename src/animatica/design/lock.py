"""Is an owner-approved design still the design the owner approved? (DESIGN_STAGE.md §1: "production may not
alter an approved design").

``design/<char>/approved.json`` locks the species *parameters* (``species_snapshot``, checked by a unit test), but a
change to the code that turns parameters into a mesh, a rig pose, a material or the face (``creatures/build.py``,
``face.py``, the adapter) changes the character without touching a parameter. This module compares a fresh render
of the locked design with the files committed at approval: the black silhouette (shape) and the 96 px thumbnail
(shape, colour, face at reading size).

Calibrated in the cloud (CPU Cycles, 16 samples, 512 px; DECISIONS #110) against the approved files, which were
rendered on the owner's laptop: Tembo, Neema, Zuri and Kiki reproduce to the pixel (silhouette change 0 %, thumbnail
pixels changed ≤ 0.01 %). Bibi Kobe's feet differ by 1–2 px (silhouette 0.42 %, thumbnail 1.95 %), identically when
rendered from the very commit that wrote her files and run to run in the cloud, so that is the platform, not drift:
she gets a recorded slack. Small edits of the kind a design pass makes fail (Tembo, measured; the files are test
fixtures): 5 % bigger eyes (silhouette 0.07 %, thumbnail 0.78 %), 3 % longer legs (0.55 %, 1.49 %), a 3 % bigger
head (2.78 %, 5.51 %).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# silhouette change = pixels in one outline but not the other, over the pixels in either (1 − IoU)
MAX_SILHOUETTE_CHANGE = 0.0003
# thumbnail change = share of the 96 px thumbnail's pixels whose largest channel moved by more than THUMB_STEP
THUMB_STEP = 12
MAX_THUMB_CHANGE = 0.003
# measured differences between the laptop's approval render and a cloud CPU render of the same commit, which a
# check must allow (anything above them is still caught); see the module docstring
PLATFORM_SLACK: dict[str, tuple[float, float]] = {"bibi_kobe": (0.006, 0.025)}


def silhouette_mask(path: Path | str) -> np.ndarray:
    """Black-on-white silhouette (scripts/design_sheet.py ``silhouette``) → boolean mask of the figure."""
    return np.asarray(Image.open(path).convert("L")) < 128


def silhouette_change(a: Path | str, b: Path | str) -> float:
    ma, mb = silhouette_mask(a), silhouette_mask(b)
    if ma.shape != mb.shape:
        return 1.0
    union = np.logical_or(ma, mb).sum()
    if union == 0:
        return 0.0
    return float(np.logical_xor(ma, mb).sum() / union)


def thumb_change(a: Path | str, b: Path | str) -> float:
    ia = np.asarray(Image.open(a).convert("RGB"), dtype=int)
    ib = np.asarray(Image.open(b).convert("RGB"), dtype=int)
    if ia.shape != ib.shape:
        return 1.0
    return float((np.abs(ia - ib).max(axis=-1) > THUMB_STEP).mean())


@dataclass(frozen=True)
class LockResult:
    character: str
    version: str
    silhouette_change: float
    thumb_change: float

    @property
    def limits(self) -> tuple[float, float]:
        return PLATFORM_SLACK.get(self.character, (MAX_SILHOUETTE_CHANGE, MAX_THUMB_CHANGE))

    @property
    def ok(self) -> bool:
        sil, thumb = self.limits
        return self.silhouette_change <= sil and self.thumb_change <= thumb

    def as_dict(self) -> dict[str, Any]:
        return {
            "character": self.character,
            "version": self.version,
            "silhouette_change": round(self.silhouette_change, 5),
            "thumb_change": round(self.thumb_change, 5),
            "limits": [round(v, 5) for v in self.limits],
            "ok": self.ok,
        }

    def line(self) -> str:
        sil, thumb = self.limits
        verdict = "same" if self.ok else "CHANGED"
        return (
            f"{self.character} {self.version}: {verdict} (silhouette {self.silhouette_change:.2%}, limit "
            f"{sil:.2%}; thumbnail {self.thumb_change:.2%}, limit {thumb:.2%})"
        )


def compare_locked(character: str, version: str, locked_dir: Path, render_dir: Path) -> LockResult:
    """``locked_dir`` = ``design/<char>/<version>/`` (files committed at approval); ``render_dir`` = a fresh
    ``scripts/design_sheet.py`` output for the same character with no morph."""
    for d in (locked_dir, render_dir):
        for f in ("silhouette.png", "thumb96.png"):
            if not (d / f).exists():
                raise FileNotFoundError(d / f)
    return LockResult(
        character,
        version,
        silhouette_change(locked_dir / "silhouette.png", render_dir / "silhouette.png"),
        thumb_change(locked_dir / "thumb96.png", render_dir / "thumb96.png"),
    )
