"""Dark faces in close and medium shots, measured on rendered frames (``animatica.production.exposure``;
DECISIONS #102)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from animatica.production.exposure import (
    DARK_MEDIAN,
    MIN_RADIUS,
    dark_faces_in_report,
    face_exposure,
    face_targets,
    head_box,
    inside,
    scene_cameras,
)
from animatica.production.scene import load_scenes

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "frames"
FILM = ROOT / "films" / "savannah" / "07_scenes.json"
BOXES = json.loads((DATA / "face_boxes.json").read_text(encoding="utf-8"))["frames"]


@pytest.mark.parametrize("name", sorted(BOXES))
def test_calibration_frames(name: str):
    """The film's SC 8 tortoise MCU (3:50) is dark; the darkest other faces (dusk, night) are not. Boxes and
    verdicts checked by eye on the final film (cloud review 11-20 15:36)."""
    want = BOXES[name]
    got = face_exposure(DATA / name, tuple(want["box"]))
    assert got["dark"] is want["dark"] and want["dark"] is name.startswith("film_sc08_dark")
    if not got["dark"]:
        assert got["median"] >= 1.5 * DARK_MEDIAN  # a margin, not a coin toss


def test_head_box_is_the_heads_size_on_the_film_and_inside_measures_the_frame():
    cam = {"location": [0.0, -5.0, 1.0], "aim": [0.0, 0.0, 1.0], "lens": 50.0}
    box, r = head_box(cam, (0.0, 0.0, 1.0), 0.5)
    assert abs((box[0] + box[2]) / 2 - 0.5) < 1e-9 and abs((box[1] + box[3]) / 2 - 0.5) < 1e-9
    assert abs((box[3] - box[1]) - 2 * r) < 1e-9
    near, r2 = head_box({**cam, "location": [0.0, -2.5, 1.0]}, (0.0, 0.0, 1.0), 0.5)
    assert abs(r2 / r - 2.0) < 1e-6  # half the distance, twice the size
    assert head_box(cam, (0.0, -6.0, 1.0), 0.5) is None  # behind the camera
    assert inside((0.25, 0.25, 0.75, 0.75)) == 1.0 and abs(inside((0.5, 0.0, 1.5, 1.0)) - 0.5) < 1e-9


def test_a_black_head_box_is_dark_and_a_dim_one_is_not():
    img = np.full((180, 320, 3), 40, np.uint8)  # a dim night frame (luminance ~0.16)
    img[60:120, 140:200] = 3  # a near-black head
    box = (140 / 320, 60 / 180, 200 / 320, 120 / 180)
    assert face_exposure(img, box)["dark"]
    assert not face_exposure(np.full((180, 320, 3), 40, np.uint8), box)["dark"]
    assert face_exposure(img, (1.2, 0.2, 1.4, 0.4))["median"] is None  # off the frame: nothing to judge


def test_face_targets_take_the_face_shots_subjects_at_a_readable_size():
    """Only close and medium shots with cameras, only subjects on stage, heads big enough and in frame."""
    spec = load_scenes(FILM)["sc08"]
    shots, poses, secs, approx = scene_cameras(spec, None)
    assert approx
    tg = face_targets(spec, shots, poses, 24)
    types = {sh["shot"]: sh["type"] for sh in shots}
    assert tg and all(types[t["shot"]] in ("cu", "mcu", "ms") for t in tg)
    assert all(t["radius"] >= MIN_RADIUS for t in tg)
    assert ("bibi_kobe", 1) in {(t["who"], t["shot"]) for t in tg}
    bare = [{k: v for k, v in s.items() if k != "aim"} for s in shots]
    assert face_targets(spec, bare, poses, 24) == []


def _video(path: Path, tmp: Path, value: int, seconds: float) -> None:
    Image.fromarray(np.full((180, 320, 3), value, np.uint8)).save(tmp / "frame.png")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "4", "-t", f"{seconds:.2f}",
         "-i", str(tmp / "frame.png"), "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_the_animatic_lists_dark_faces_from_the_scene_report_and_its_render(tmp_path: Path):
    """``savannah_animatic.py``'s path: a scene's render and its ``report.json`` cameras. A black render
    gives a row per face target; a lit one none; a report without cameras nothing (it does not guess)."""
    spec = load_scenes(FILM)["sc08"]
    shots, poses, secs, _ = scene_cameras(spec, None)
    rep = {"seconds": secs, "shots": shots, "lines": []}
    n = len(face_targets(spec, shots, poses, 24))
    black, lit = tmp_path / "black.mp4", tmp_path / "lit.mp4"
    _video(black, tmp_path, 2, secs + 1)
    _video(lit, tmp_path, 110, secs + 1)
    rows = dark_faces_in_report(load_scenes(FILM)["sc08"], rep, black)
    assert len(rows) == n and rows[0]["scene"] == "sc08" and rows[0]["median"] < DARK_MEDIAN
    assert dark_faces_in_report(load_scenes(FILM)["sc08"], rep, lit) == []
    bare = {**rep, "shots": [{k: v for k, v in s.items() if k != "location"} for s in shots]}
    assert dark_faces_in_report(load_scenes(FILM)["sc08"], bare, black) == []
