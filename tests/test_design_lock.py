"""An approved design must still render as approved (DESIGN_STAGE.md §1, DECISIONS #110).

The species-snapshot test locks the parameters; these lock the picture. The fixtures are real renders: Tembo with
the smallest edits a design pass makes (cloud CPU, 11-22) and Bibi Kobe's cloud render of her unchanged v3.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from animatica.design.lock import (
    MAX_SILHOUETTE_CHANGE,
    PLATFORM_SLACK,
    compare_locked,
    silhouette_change,
    thumb_change,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "design_lock"


def _approved() -> dict[str, str]:
    recs = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "design").glob("*/approved.json"))
    ]
    return {r["character"]: r["version"] for r in recs}


def test_every_approved_design_has_the_files_the_lock_compares():
    approved = _approved()
    assert len(approved) == 5
    for ch, v in approved.items():
        for f in ("silhouette.png", "thumb96.png"):
            assert (ROOT / "design" / ch / v / f).exists(), f"{ch} {v}: {f} missing"


def test_identical_files_are_the_same_design():
    for ch, v in _approved().items():
        d = ROOT / "design" / ch / v
        r = compare_locked(ch, v, d, d)
        assert r.ok and r.silhouette_change == 0 and r.thumb_change == 0


@pytest.mark.parametrize("edit", ["eye105", "leg103", "head103"])
def test_the_smallest_design_edits_are_caught(edit):
    r = compare_locked("tembo", "v3", ROOT / "design" / "tembo" / "v3", FIX / f"tembo_{edit}")
    assert not r.ok, r.line()
    assert r.silhouette_change > MAX_SILHOUETTE_CHANGE  # each edit moves the outline, not just the shading


def test_bibi_kobes_platform_difference_is_allowed_and_no_more():
    """Her cloud render of the unchanged v3 differs at the feet; it passes with her recorded slack, and the same
    numbers on any other character fail."""
    r = compare_locked("bibi_kobe", "v3", ROOT / "design" / "bibi_kobe" / "v3", FIX / "bibi_kobe_cloud")
    assert r.ok, r.line()
    assert r.silhouette_change > 0.002 and r.thumb_change > 0.01  # a real difference, not a copy
    assert not compare_locked("tembo", "v3", ROOT / "design" / "bibi_kobe" / "v3", FIX / "bibi_kobe_cloud").ok
    sil, thumb = PLATFORM_SLACK["bibi_kobe"]
    assert r.silhouette_change < sil and r.thumb_change < thumb


def test_mismatched_sizes_and_missing_files(tmp_path):
    Image.new("RGB", (8, 8), "white").save(tmp_path / "a.png")
    Image.new("RGB", (9, 9), "white").save(tmp_path / "b.png")
    assert silhouette_change(tmp_path / "a.png", tmp_path / "b.png") == 1.0
    assert thumb_change(tmp_path / "a.png", tmp_path / "b.png") == 1.0
    blank = np.full((8, 8), 255, np.uint8)
    Image.fromarray(blank).save(tmp_path / "c.png")
    assert silhouette_change(tmp_path / "a.png", tmp_path / "c.png") == 0.0  # two empty frames
    with pytest.raises(FileNotFoundError):
        compare_locked("tembo", "v3", ROOT / "design" / "tembo" / "v3", tmp_path)


@pytest.mark.blender
def test_tembo_still_renders_as_approved(tmp_path):
    """A fresh render of the approved Tembo matches design/tembo/v3 (~25 s on 2 CPU cores)."""
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from design_sheet import sheet_for

    from animatica.design.brief import load_brief
    from animatica.design.variants import Morph

    v = _approved()["tembo"]
    out = tmp_path / "tembo"
    sheet_for(load_brief("tembo"), Morph(), out, label="lock test")
    r = compare_locked("tembo", v, ROOT / "design" / "tembo" / v, out)
    assert r.ok, r.line()
    shutil.rmtree(out, ignore_errors=True)
