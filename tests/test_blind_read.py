"""Blind species reads: recorded per exact image, judged against the brief (DECISIONS #111)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from animatica.design.brief import load_brief
from animatica.design.critic import blind_verdict, load_blind_read, record_blind_read

ROOT = Path(__file__).resolve().parents[1]


def _images(d: Path) -> None:
    Image.new("L", (8, 8), 255).save(d / "silhouette.png")
    Image.new("RGB", (8, 8), "tan").save(d / "thumb96.png")


def test_a_blind_read_is_clear_weak_or_misread(tmp_path):
    _images(tmp_path)
    b = load_brief("kiki")
    rec = record_blind_read(
        tmp_path,
        "test",
        silhouette={"animal": "meerkat", "confidence": 90, "alternatives": ["prairie dog"]},
        thumbnail={"animal": "Meerkat", "confidence": 60, "alternatives": ["mongoose"]},
    )
    assert blind_verdict(b, rec) == {"silhouette": "clear", "thumbnail": "weak"}
    rec["thumbnail"]["animal"] = "mongoose"
    assert blind_verdict(b, rec)["thumbnail"] == "misread"


def test_a_blind_read_is_void_once_either_image_is_re_rendered(tmp_path):
    _images(tmp_path)
    ans = {"animal": "zebra", "confidence": 80}
    record_blind_read(tmp_path, "test", silhouette=ans, thumbnail=ans)
    assert load_blind_read(tmp_path) is not None
    Image.new("RGB", (8, 8), "grey").save(tmp_path / "thumb96.png")
    assert load_blind_read(tmp_path) is None


def test_a_blind_read_needs_both_views_and_a_sane_confidence(tmp_path):
    _images(tmp_path)
    with pytest.raises(ValueError):
        record_blind_read(tmp_path, "t", silhouette={"animal": "zebra", "confidence": 80})
    with pytest.raises(ValueError):
        bad = {"animal": "zebra", "confidence": 0.8e3}
        record_blind_read(tmp_path, "t", silhouette=bad, thumbnail=bad)


def test_every_locked_design_has_a_current_blind_read_and_none_misreads():
    for p in sorted((ROOT / "design").glob("*/approved.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        d = p.parent / rec["version"]
        read = load_blind_read(d)
        assert read is not None, f"{rec['character']} {rec['version']}: no blind read of these images"
        assert "misread" not in blind_verdict(load_brief(rec["character"]), read).values()
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "blind_read.py")], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "weak: zebra" in out.stdout  # Zuri's silhouette: horse-like (the open design note)
