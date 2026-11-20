"""The horizon stripe, measured on rendered frames (``animatica.sets.frames``; DECISIONS #99)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from animatica.sets.frames import horizon_stripe, stripes_in_video

DATA = Path(__file__).parent / "data" / "frames"


def _scene(stripe: float = 0.0, canopy: bool = False, occluder: bool = False) -> np.ndarray:
    """A 640x360 savannah: sky gradient, grey-blue hills, grass with noise; optionally a pale band where the
    grass meets the hills, a layered canopy (sky slits between dark shelves) or an animal in front."""
    rng = np.random.default_rng(3)
    h, w = 360, 640
    img = np.zeros((h, w, 3), np.float32)
    ys = np.arange(h)[:, None]
    img[:] = (0.55 + 0.2 * (ys / h))[..., None] * np.array([0.8, 0.88, 1.0])
    img[130:170] = [0.62, 0.6, 0.6]  # hills
    grass = 0.42 + 0.12 * rng.standard_normal((h - 170, w))
    img[170:] = np.clip(grass, 0, 1)[..., None] * np.array([1.0, 0.85, 0.5])
    if stripe:
        img[168:174] = stripe  # pale, flat, straight
    if canopy:
        for top in (40, 60, 80):  # dark shelves with sky between, wavy edges
            for x in range(60, 400):
                dy = int(3 * np.sin(x / 9.0))
                img[top + dy : top + 10 + dy, x] = [0.15, 0.3, 0.12]
    if occluder:
        img[120:300, 250:380] = [0.45, 0.45, 0.48]
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def test_a_flat_pale_band_at_the_horizon_is_a_stripe_and_the_plain_set_is_not():
    plain = horizon_stripe(_scene())
    assert not plain["stripe"] and plain["span"] < 0.5
    band = horizon_stripe(_scene(stripe=0.9))
    assert band["stripe"]
    assert band["span"] > 0.95 and band["fill"] > 0.95
    assert abs(band["row"] - 170 / 360) < 0.03
    assert band["contrast"] > 0.2


def test_an_animal_in_front_cuts_the_stripe_but_does_not_hide_it():
    r = horizon_stripe(_scene(stripe=0.9, occluder=True))
    assert r["stripe"]
    assert 0.6 < r["fill"] < 0.9 and r["span"] > 0.95


def test_sky_between_canopy_shelves_is_not_a_stripe():
    r = horizon_stripe(_scene(canopy=True))
    assert not r["stripe"]


def test_a_band_no_brighter_than_its_neighbours_is_not_a_stripe():
    r = horizon_stripe(_scene(stripe=0.5))  # about the hills' and grass's brightness
    assert not r["stripe"]


@pytest.mark.parametrize(
    ("name", "stripe"),
    [
        ("set_1116_white_strip.jpg", True),  # the owner's note (11-16 set still)
        ("film_sc06_pale_band.jpg", True),  # final film 2:46, afternoon wide: toned down, still a stripe
        ("film_sc01_dawn_canopy.jpg", False),  # sky through the acacia's shelves
        ("film_sc02_canopy_slits.jpg", False),
        ("film_sc10_dusk_wide.jpg", False),
        (
            "film_sc04_band_behind_cast.jpg",
            True,
        ),  # 1:43 midday: the band runs on behind a termite mound and the cast
    ],
)
def test_calibration_frames(name: str, stripe: bool):
    assert horizon_stripe(DATA / name)["stripe"] is stripe


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_stripes_in_video_names_the_frames_with_a_stripe(tmp_path: Path):
    from PIL import Image

    for i, img in enumerate([_scene(), _scene(stripe=0.9)]):
        Image.fromarray(img).save(tmp_path / f"f{i}.png")
    video = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", str(tmp_path / "f%d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24", str(video),
        ],
        check=True,
    )  # fmt: skip
    hits = stripes_in_video(video, [0.5, 1.5], ["sc01", "sc02"])
    assert [h["label"] for h in hits] == ["sc02"]
