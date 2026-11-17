"""Design stage: briefs, measurements, morphs, rubric, image checks and the species-read critic."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from animatica.creatures.species import SPECIES
from animatica.design.brief import Brief, BriefError, all_briefs, load_brief
from animatica.design.critic import critique_for, load_recorded, reads_as, record
from animatica.design.image_checks import dark_blob, floating_parts, neck_notch, sheet_metrics
from animatica.design.measure import contrast_ratio, features, materials, proportions
from animatica.design.rubric import edit_morph, score
from animatica.design.variants import Morph, apply_morph, candidates


def test_every_cast_member_has_a_valid_brief():
    briefs = all_briefs()
    assert set(briefs) == {"tembo", "zuri", "kiki", "neema", "bibi_kobe"}
    for b in briefs.values():
        assert b.species in SPECIES
        assert b.names and b.confusions, b.character
        assert b.species in b.names


def test_brief_rejects_unknown_metrics_inverted_ranges_and_unlicensed_references():
    base = load_brief("kiki").raw
    with pytest.raises(BriefError):
        Brief.from_dict({**base, "ranges": {"cuteness": [0, 1]}})
    with pytest.raises(BriefError):
        Brief.from_dict({**base, "ranges": {"eye_head": [0.6, 0.3]}})
    with pytest.raises(BriefError):
        Brief.from_dict({**base, "references": [{"url": "https://example.org/a.jpg"}]})


def test_measurements_match_the_designs():
    p = proportions(SPECIES["elephant"])
    assert 0.7 < p["head_body"] < 0.9  # a calf: big head
    assert p["neck_head"] < 0.75  # the neck is narrower than the head (no melting)
    assert "trunk" in features(SPECIES["elephant"]) and "big_ears" in features(SPECIES["elephant"])
    assert "pattern:stripes" in features(SPECIES["zebra"])
    assert materials(SPECIES["zebra"])["pattern_contrast"]["coat"] > 10
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)


def test_meerkat_black_legs_are_flagged_and_the_lift_fixes_them():
    """The reviewer's 'very thin black legs' note (11-17 03:36) as an automatic check."""
    brief = load_brief("kiki")
    r = score(brief, SPECIES["meerkat"])
    assert "materials:flat_black" in r.hard_failures
    assert r.edit.get("lift_dark", 0) > 0
    fixed = apply_morph(SPECIES["meerkat"], Morph(lift_dark=0.7), brief.dark_ok)
    assert "materials:flat_black" not in score(brief, fixed).hard_failures
    # the intended dark tail tip is kept
    assert fixed.mats["tailtip"] == SPECIES["meerkat"].mats["tailtip"]


def test_morph_scales_the_head_and_keeps_the_trunk_on_the_face():
    sp = SPECIES["elephant"]
    big = apply_morph(sp, Morph(head=1.1, eye=1.1))
    assert big.head_size[1] == pytest.approx(sp.head_size[1] * 1.1, rel=1e-3)
    assert big.eye[3] == pytest.approx(sp.eye[3] * 1.21, rel=1e-3)
    front = big.head_at[1] - big.head_size[1] / 2
    assert big.trunk.base[1] - front == pytest.approx(
        sp.trunk.base[1] - (sp.head_at[1] - sp.head_size[1] / 2), abs=1e-3
    )
    assert apply_morph(sp, Morph()) is sp


def test_candidates_are_distinct_and_start_from_the_base():
    cs = candidates(SPECIES["meerkat"], 6)
    assert len(cs) == 6 and cs[0][0] == Morph()
    assert len({json.dumps(m.as_dict(), sort_keys=True) for m, _ in cs}) == 6


def test_rubric_turns_range_misses_into_bounded_edits_and_the_loop_converges():
    brief = load_brief("kiki")
    sp, morph = SPECIES["meerkat"], Morph()
    r0 = score(brief, sp)
    assert "head" in r0.edit and 1.0 < r0.edit["head"] <= 1.2
    assert "neck" in r0.edit and 0.85 <= r0.edit["neck"] < 1.0
    for _ in range(5):
        r = score(brief, apply_morph(sp, morph, brief.dark_ok))
        if not r.edit:
            break
        morph = edit_morph(morph, r.edit)
    final = score(brief, apply_morph(sp, morph, brief.dark_ok))
    assert final.score > r0.score
    assert not [c for c in final.checks if c.group == "proportions" and not c.passed and c.fix]
    assert final.pending == ["silhouette", "species read"] and not final.ready


def _blob(h: int, w: int, ellipses: list[tuple[float, float, float, float]]) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    m = np.zeros((h, w), bool)
    for cx, cy, rx, ry in ellipses:
        m |= ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1
    return m


def test_neck_notch_separates_a_clear_head_from_a_melted_one():
    legs = [(110, 150, 6, 40), (170, 150, 6, 40)]
    clear = _blob(200, 240, [(140, 100, 60, 30), (50, 60, 22, 20), (80, 80, 18, 8), *legs])
    melted = _blob(200, 240, [(130, 95, 75, 38), (60, 78, 30, 30), *legs])
    assert neck_notch(clear)["neck_notch"] > 0.3
    assert neck_notch(melted)["neck_notch"] < 0.15


def test_floating_parts_and_dark_blobs(tmp_path):
    body = _blob(100, 100, [(50, 50, 30, 20)])
    assert floating_parts(body) == 0
    assert floating_parts(body | _blob(100, 100, [(90, 10, 4, 4)])) == 1
    rgb = np.full((100, 100, 3), 200, np.uint8)
    rgb[50:70, 25:75] = 8  # a black block on the lower half of the figure
    Image.fromarray(rgb).save(tmp_path / "side.png")
    assert dark_blob(tmp_path / "side.png", body) > 0.2


def test_sheet_metrics_reads_a_silhouette_png(tmp_path):
    m = _blob(200, 240, [(140, 100, 60, 30), (50, 60, 22, 20), (80, 80, 18, 8)])
    Image.fromarray(np.where(m, 0, 255).astype(np.uint8)).convert("RGB").save(tmp_path / "s.png")
    got = sheet_metrics(tmp_path / "s.png")
    assert got["floating_parts"] == 0 and got["neck_notch"] > 0.3


def test_species_read_needs_the_name_without_a_confusion():
    b = load_brief("kiki")
    assert reads_as(b, "Meerkat")[0]
    assert reads_as(b, "a meerkat standing guard")[0]
    assert not reads_as(b, "weasel")[0]
    assert not reads_as(b, "meerkat or maybe a weasel")[0]
    assert not reads_as(b, "some small mammal")[0]
    assert reads_as(load_brief("bibi_kobe"), "leopard tortoise")[0]


def test_recorded_critique_only_applies_to_the_sheet_it_was_written_for(tmp_path):
    sheet = tmp_path / "sheet.png"
    Image.new("RGB", (8, 8), "white").save(sheet)
    record(
        tmp_path / "critique.json",
        sheet,
        "reviewer",
        silhouette_species="weasel",
        thumbnail_species="meerkat",
    )
    b = load_brief("kiki")
    crit = critique_for(b, tmp_path)
    assert crit and crit["silhouette_species"] == "weasel"
    r = score(b, SPECIES["meerkat"], {"neck_notch": 0.4, "floating_parts": 0, "dark_blob": 0.0}, crit)
    assert "read:silhouette" in r.hard_failures and "read:thumbnail" not in r.hard_failures
    Image.new("RGB", (8, 8), "black").save(sheet)  # re-rendered: the old critique no longer applies
    assert load_recorded(tmp_path / "critique.json", sheet) is None


def test_a_design_is_ready_only_with_every_check_passing():
    b = load_brief("zuri")
    img = {"neck_notch": 0.4, "floating_parts": 0, "dark_blob": 0.02}
    crit = {"silhouette_species": "zebra", "thumbnail_species": "zebra"}
    assert score(b, SPECIES["zebra"], img, crit).ready
    assert not score(b, SPECIES["zebra"], {**img, "floating_parts": 1}, crit).ready
    no_mane = replace(SPECIES["zebra"], extras=())
    assert "feature:mane" in score(b, no_mane, img, crit).hard_failures
