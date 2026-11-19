"""Design stage: briefs, measurements, morphs, rubric, image checks and the species-read critic."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from animatica.creatures.species import SPECIES, Extra
from animatica.design.brief import Brief, BriefError, all_briefs, load_brief
from animatica.design.critic import critique_for, load_recorded, reads_as, record
from animatica.design.image_checks import dark_blob, floating_parts, neck_notch, sheet_metrics
from animatica.design.measure import contrast_ratio, features, hoof_shape, mane_shape, materials, proportions
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
    # v2 (11-17 09:36) paints the lower legs a darker shade of the coat: no black boots, the dark ears allowed
    assert "materials:flat_black" not in score(brief, SPECIES["meerkat"]).hard_failures
    sp = SPECIES["meerkat"]
    booted = replace(sp, mats={**sp.mats, "paw": {**sp.mats["paw"], "base_color": "#24180F"}})  # v1's legs
    r = score(brief, booted)
    assert "materials:flat_black" in r.hard_failures
    assert r.edit.get("lift_dark", 0) > 0
    fixed = apply_morph(booted, Morph(lift_dark=0.7), brief.dark_ok)
    assert "materials:flat_black" not in score(brief, fixed).hard_failures
    # the intended dark tail tip and ears are kept
    assert fixed.mats["tailtip"] == sp.mats["tailtip"] and fixed.mats["ear"] == sp.mats["ear"]


def test_a_near_black_paw_mark_is_flagged_and_the_lift_fixes_it():
    """A black mark over a leg region is a black boot too (review 11-17 15:36), not only a black base colour."""
    brief = load_brief("kiki")
    sp = SPECIES["meerkat"]
    paw = sp.mats["paw"]
    booted = replace(sp, mats={**sp.mats, "paw": {**paw, "marks": [{**paw["marks"][0], "color": "#0A0806"}]}})
    r = score(brief, booted)
    assert "materials:flat_black" in r.hard_failures
    fixed = apply_morph(booted, Morph(lift_dark=0.7), brief.dark_ok)
    assert "materials:flat_black" not in score(brief, fixed).hard_failures
    assert fixed.mats["paw"]["base_color"] == paw["base_color"]  # only the mark is lifted


def test_the_meerkat_paw_shade_sits_at_the_ground():
    """The paw mark is painted at root z = -body_z; a change to body_z must move it too."""
    sp = SPECIES["meerkat"]
    assert sp.mats["paw"]["marks"][0]["at"][2] == pytest.approx(-sp.body_z)


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
    v2 = SPECIES["meerkat"]
    # a small head on a thick neck (head_body and neck_head out of range, as in v1); v2 fixed both in the base
    sp, morph = replace(v2, head_size=(0.052, 0.072, 0.05), neck=replace(v2.neck, r1=0.024)), Morph()
    assert not score(brief, v2).edit
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


def test_a_head_carried_high_on_a_sloping_neck_counts_as_separate():
    """Kiki v2 on all fours: the head rides well above the back on a neck that widens into the chest, so
    there is no dip and no throat, but the head is clearly its own mass. A level head still melts."""
    legs = [(130, 150, 6, 40), (190, 150, 6, 40)]
    neck = [(85 + 6 * k, 62 + 5 * k, 14 + 1.2 * k, 14 + 1.2 * k) for k in range(8)]
    high = _blob(200, 260, [(160, 100, 60, 28), (50, 40, 26, 22), *neck, *legs])
    level = _blob(200, 260, [(160, 100, 60, 28), (60, 90, 26, 22), (100, 95, 30, 26), *legs])
    got = neck_notch(high)
    assert got["lift"] >= 0.5 and got["neck_notch"] >= 0.15
    assert neck_notch(level)["neck_notch"] < 0.15


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
    no_mane = replace(SPECIES["zebra"], extras=(), mane=None)
    assert "feature:mane" in score(b, no_mane, img, crit).hard_failures


def test_expression_change_and_the_face_check(tmp_path):
    from animatica.design.image_checks import expression_change

    a = np.zeros((64, 64, 4), np.uint8)
    a[8:56, 8:56] = (150, 150, 150, 255)
    b = a.copy()
    b[20:24, 20:44] = (40, 30, 30, 255)  # a brow moves: 96 of 2304 figure pixels
    Image.fromarray(a).save(tmp_path / "n.png")
    Image.fromarray(b).save(tmp_path / "h.png")
    v = expression_change(tmp_path / "n.png", tmp_path / "h.png")
    assert v == pytest.approx(96 / 2304, abs=1e-3)
    assert expression_change(tmp_path / "n.png", tmp_path / "n.png") == 0.0
    r = score(load_brief("zuri"), SPECIES["zebra"], {"expression_happy": 0.01, "expression_surprised": 0.05})
    face = {c.id: c for c in r.checks if c.group == "face"}
    assert not face["face:happy"].passed and face["face:surprised"].passed
    assert "face:happy" not in r.hard_failures and any("happy" in m for m in r.manual)


def test_low_critic_appeal_blocks_ready():
    b = load_brief("zuri")
    img = {"neck_notch": 0.4, "floating_parts": 0, "dark_blob": 0.02}
    crit = {"silhouette_species": "zebra", "thumbnail_species": "zebra"}
    assert score(b, SPECIES["zebra"], img, {**crit, "appeal": 9}).ready
    low = score(b, SPECIES["zebra"], img, {**crit, "appeal": 6})
    assert not low.ready and not low.hard_failures


def test_a_detached_tail_in_the_signature_pose_is_a_floating_part():
    """Kiki v2-v3's sentinel tail hung below the rump, detached; the floating check only looked at the side
    view. design_sheet now runs it on the signature-pose silhouette too (v4 fixed the rump weights)."""
    from animatica.design.image_checks import floating_parts, load_mask

    root = Path(__file__).resolve().parents[1] / "design" / "kiki"
    assert floating_parts(load_mask(root / "v3" / "silhouette.png")) == 1
    assert floating_parts(load_mask(root / "v4" / "silhouette.png")) == 0


def test_rig_stress_checks_join_the_rubric_and_a_hard_motion_failure_blocks_ready():
    from animatica.design.rubric import score

    brief = load_brief("tembo")
    sp = SPECIES[brief.species]
    from animatica.design.fingerprint import fingerprint

    fp = fingerprint(sp)
    ok = {"checks": [{"id": "foot_slide", "passed": True, "hard": True, "message": "ok"}], "fingerprint": fp}
    bad = {
        "checks": [{"id": "foot_slide", "passed": False, "hard": True, "message": "65 mm"}],
        "fingerprint": fp,
    }
    base = score(brief, sp)
    good = score(brief, sp, stress=ok)
    worse = score(brief, sp, stress=bad)
    assert any(c.id == "motion:foot_slide" and c.group == "motion" for c in good.checks)
    assert "motion:foot_slide" not in base.hard_failures and "motion:foot_slide" in worse.hard_failures
    assert worse.score < good.score and not worse.ready


def test_a_stress_report_about_other_parameters_blocks_ready():
    """Review 11-18 03:36: the owner's brow notes (#65) changed three species and nothing re-ran the stress test,
    so the reports described the old faces. A report carries fingerprints; another species' parameters (or none)
    is a hard failure, changed rig code a soft one."""
    from animatica.design.fingerprint import fingerprint, rig_code_hash, species_hash

    brief = load_brief("tembo")
    sp = SPECIES[brief.species]
    checks = [{"id": "foot_slide", "passed": True, "hard": True, "message": "ok"}]
    fresh = score(brief, sp, stress={"checks": checks, "fingerprint": fingerprint(sp)})
    assert "motion:fresh" not in fresh.hard_failures
    assert all(c.passed for c in fresh.checks if c.id.startswith("motion:fresh"))
    none = score(brief, sp, stress={"checks": checks})
    assert "motion:fresh" in none.hard_failures and not none.ready
    moved = replace(sp, brow_size=(sp.brow_size[0] * 1.2, sp.brow_size[1]))
    assert species_hash(moved) != species_hash(sp)
    other = score(brief, moved, stress={"checks": checks, "fingerprint": fingerprint(sp)})
    assert "motion:fresh" in other.hard_failures
    old_code = {"species": species_hash(sp), "rig_code": "0" * 16}
    code = score(brief, sp, stress={"checks": checks, "fingerprint": old_code})
    stale = next(c for c in code.checks if c.id == "motion:fresh_code")
    assert not stale.passed and not stale.hard and "motion:fresh" not in code.hard_failures
    assert code.score < fresh.score
    assert len(rig_code_hash()) == 16


def test_rig_code_hash_ignores_line_endings(tmp_path):
    """The laptop is Windows: a CRLF checkout must fingerprint the same as the Linux one."""
    from animatica.design.fingerprint import _CREATURES, RIG_MODULES, rig_code_hash

    for name in RIG_MODULES:
        src = (_CREATURES / f"{name}.py").read_bytes().replace(b"\r\n", b"\n")
        (tmp_path / f"{name}.py").write_bytes(src.replace(b"\n", b"\r\n"))
    assert rig_code_hash(tmp_path) == rig_code_hash()


def test_every_rig_stress_report_on_main_measured_the_current_design():
    """design/<char>/rig_stress.json must be about the species parameters on main: change a species, re-run
    ``scripts/rig_stress_test.py <char> --no-render`` (CPU, ~30 s) in the same commit."""
    from animatica.design.fingerprint import staleness

    root = Path(__file__).resolve().parents[1] / "design"
    reports = sorted(root.glob("*/rig_stress.json"))
    assert len(reports) == 5
    for p in reports:
        sp = SPECIES[load_brief(p.parent.name).species]
        st = staleness(json.loads(p.read_text(encoding="utf-8")), sp)
        assert st["species_ok"], (
            f"{p.parent.name}: rig_stress.json is stale; re-run scripts/rig_stress_test.py"
        )


def test_approved_designs_are_locked_to_their_species_snapshot():
    """An owner-approved design (design/<char>/approved.json) must not drift: changing an approved species'
    parameters needs a new approval (update the snapshot only with the owner's sign-off)."""
    from dataclasses import MISSING, asdict, fields

    root = Path(__file__).resolve().parents[1] / "design"
    locked = sorted(root.glob("*/approved.json"))
    assert locked, "no approved designs found"
    for p in locked:
        rec = json.loads(p.read_text(encoding="utf-8"))
        sp = SPECIES[load_brief(rec["character"]).species]
        now = json.loads(json.dumps(asdict(sp), default=str))
        snap = rec["species_snapshot"]
        # a field added after the approval counts only if it moved off its default (which changes nothing)
        default = {f.name: f.default for f in fields(sp) if f.default is not MISSING}
        new_ok = {
            k for k in now if k not in snap and now[k] == json.loads(json.dumps(default.get(k), default=str))
        }
        drift = sorted(k for k in now if k not in new_ok and now[k] != snap.get(k))
        assert not drift, f"{rec['character']} is approved as {rec['version']} but changed: {drift}"
        assert (p.parent / rec["version"] / "sheet.jpg").exists()


def test_the_packet_index_is_written_from_the_packets_and_matches_main(tmp_path):
    """The packets' index README said Kiki v4 / Zuri v2 for a day after both moved on (review 11-18 06:36): it was
    hand-written. It is now generated from each packet's scores.json and approved.json; this test fails when the
    committed index differs from what the packets on main would write."""
    import importlib.util
    import shutil

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("design_packet", root / "scripts" / "design_packet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    committed = (root / "design" / "packets" / "README.md").read_text(encoding="utf-8")
    tmp = tmp_path
    for p in (root / "design").glob("*/approved.json"):
        (tmp / "design" / p.parent.name).mkdir(parents=True, exist_ok=True)
        shutil.copy(p, tmp / "design" / p.parent.name / "approved.json")
    for p in (root / "design" / "packets").glob("*/scores.json"):
        (tmp / "design" / "packets" / p.parent.name).mkdir(parents=True, exist_ok=True)
        shutil.copy(p, tmp / "design" / "packets" / p.parent.name / "scores.json")
    shutil.copy(root / "design" / "packets" / "notes.json", tmp / "design" / "packets" / "notes.json")
    text = mod.index(tmp)
    assert text.replace("\r\n", "\n") == committed.replace("\r\n", "\n"), (
        "run scripts/design_packet.py --index"
    )
    for char in ("kiki", "zuri", "tembo"):
        sc = json.loads((root / "design" / "packets" / char / "scores.json").read_text(encoding="utf-8"))
        assert f"({char}/README.md) | {sc['version']} |" in text


def _hard(r) -> set[str]:
    return set(r.hard_failures)


def test_a_board_mane_is_caught_and_the_ridge_passes():
    """Zuri v2's mane was an ellipsoid board on one neck bone; only the reviewer's eye caught it (11-17 15:36)."""
    brief, z = load_brief("zuri"), SPECIES["zebra"]
    board = Extra("mane", "uv_sphere", (0.085, 0.28, 0.66), (0.0, 0.07, 0.19), "neck_1", "mane", (25, 0, 0))
    v2 = replace(z, mane=None, extras=(*z.extras, board))
    m = mane_shape(v2)
    assert m is not None and not m["follows_neck"] and m["stand"] > 1.0
    assert {"shape:mane_follows_neck", "shape:mane_fin"} <= _hard(score(brief, v2))
    # the v3 ridge follows the neck and stands about half the neck's depth: no hard failure
    assert not {"shape:mane_follows_neck", "shape:mane_fin"} & _hard(score(brief, z))
    # a ridge stood up as a fin is caught too
    assert "shape:mane_fin" in _hard(score(brief, replace(z, mane=(0.25, 0.06, 0))))
    assert mane_shape(SPECIES["giraffe"]) is None


def test_a_saw_tooth_crest_is_a_soft_failure_and_a_smooth_one_passes(monkeypatch):
    """The reviewer's v3 note (11-18 03:36) and the owner's (11-18): soften the saw-tooth mane into a brush.
    v3's +-22 % alternating teeth are caught; the brush (a gentle 5 % ripple over the tufts) passes."""
    from animatica.creatures import parts

    brief, z = load_brief("zuri"), SPECIES["zebra"]
    brush = {c.id: c for c in score(brief, z).checks}["shape:mane_brush"]
    assert brush.passed and brush.value < 0.15
    monkeypatch.setattr(parts, "TUFT", 0.6)  # a coarse, deep-toothed crest
    saw = {c.id: c for c in score(brief, z).checks}["shape:mane_brush"]
    assert not saw.passed and not saw.hard and saw.value > 0.2
    smooth = {c.id: c for c in score(brief, replace(z, mane=(0.11, 0.06, 0))).checks}["shape:mane_brush"]
    assert smooth.passed


def test_puck_hooves_are_caught_and_the_hoof_mesh_passes(monkeypatch):
    """Zuri v2's hooves were flat cylinders under the striped leg tube (review 11-17 15:36)."""
    brief = load_brief("zuri")
    for name in ("zebra", "giraffe"):
        h = hoof_shape(SPECIES[name])
        assert h is not None and h["taper"] < 0.8 and 55 < h["wall_deg"] < 70, (name, h)
        assert "shape:hoof_puck" not in _hard(
            score(load_brief("neema" if name == "giraffe" else "zuri"), SPECIES[name])
        )
    assert hoof_shape(SPECIES["elephant"]) is None

    import math

    from animatica.creatures import build

    def puck(r: float, h: float, seg: int = 32):  # what v2 rendered: a straight-walled cylinder
        ring = [
            (math.sin(2 * math.pi * k / seg) * r, -math.cos(2 * math.pi * k / seg) * r) for k in range(seg)
        ]
        verts = [[x, y, z] for z in (0.0, h) for x, y in ring]
        faces = [[k, (k + 1) % seg, seg + (k + 1) % seg, seg + k] for k in range(seg)]
        return verts, faces

    monkeypatch.setattr(build, "hoof_mesh", puck)
    h = hoof_shape(SPECIES["zebra"])
    assert h["taper"] == pytest.approx(1.0) and h["wall_deg"] == pytest.approx(90.0)
    assert "shape:hoof_puck" in _hard(score(brief, SPECIES["zebra"]))


def test_a_mane_that_stops_short_of_the_poll_is_a_soft_failure():
    """Review 11-18 18:36: Zuri's mane runs from the withers to mid-neck; a zebra's runs to the poll."""
    brief, z = load_brief("zuri"), SPECIES["zebra"]
    short = {c.id: c for c in score(brief, z).checks}["shape:mane_reach"]
    assert not short.passed and not short.hard and 0.6 < short.value < 0.85
    # a mane whose crest meets the back of the head (here: a head that reaches back over the crest's end) passes
    full = replace(z, head_size=(0.24, 0.95, 0.5))
    assert {c.id: c for c in score(brief, full).checks}["shape:mane_reach"].passed


def test_eye_and_brow_outline_checks_pick_the_near_eye_and_the_worst_brow():
    """Googly eyes and floating brow dashes (cloud reviews 11-18): the near eye is the smaller share of the pair
    (in a 3/4 view the far eye peeking past the far cheek is a drawing convention), a brow counts at its worst."""
    from animatica.creatures.qa import outline_summary
    from animatica.design.rubric import BROW_OUTLINE_MAX, EYE_OUTLINE_MAX

    rep = {
        "frames": {
            "8": {
                "outline": {
                    "eye_L": {"views": [0.0, 0.0, 0.0]},
                    "eye_R": {"views": [0.0, 0.45, 0.0]},  # the far eye in the 3/4 view: ignored
                    "brow_L": {"views": [0.0, 0.0, 0.0]},
                    "brow_R": {"views": [0.0, 0.9, 0.0]},  # the far brow drawn against the backdrop
                }
            }
        }
    }
    ol = outline_summary(rep, ["front", "three_quarter", "back"], ["eye_L", "eye_R"], ["brow_L", "brow_R"])
    assert ol["eye"] == 0.0 and ol["brow"] == 0.9 and ol["brow_view"] == "three_quarter"
    b, sp = load_brief("tembo"), SPECIES["elephant"]
    checks = {c.id: c for c in score(b, sp, {"outline": ol}).checks}
    assert checks["face:eye_outline"].passed and not checks["face:brow_outline"].passed
    assert not checks["face:brow_outline"].hard and "floats" in checks["face:brow_outline"].message
    # a bug-eyed front view (both eyes outside the outline) fails the eye check
    bug = {"eye": EYE_OUTLINE_MAX + 0.1, "eye_view": "front", "brow": BROW_OUTLINE_MAX, "brow_view": "front"}
    checks = {c.id: c for c in score(b, sp, {"outline": bug}).checks}
    assert not checks["face:eye_outline"].passed and checks["face:brow_outline"].passed
    # a render made before the check has no outline: not scored
    assert not any(c.id.endswith("_outline") for c in score(b, sp, {"floating_parts": 0}).checks)


def test_a_ball_shell_is_a_soft_failure_and_a_dome_passes(monkeypatch):
    """Bibi Kobe's shell read as a ball in every cloud review from 11-17 06:36 while every check passed."""
    import math

    from animatica.creatures import shell as shell_mod
    from animatica.design.measure import dome_shoulder, shell_shape

    def sphere(rows: int) -> list[list[float]]:  # rows = 60: a whole ball; 30: its top half on a flat plate
        return [
            [math.sin(t) * math.cos(p), math.sin(t) * math.sin(p), math.cos(t)]
            for t in (i * math.pi / 60 for i in range(rows + 1))
            for p in (j * math.pi / 30 for j in range(60))
        ]

    assert dome_shoulder(sphere(60)) == pytest.approx(0.65)
    assert dome_shoulder(sphere(30)) == pytest.approx(0.3)
    assert dome_shoulder([[x, y, 1.7 * z] for x, y, z in sphere(30)]) == pytest.approx(
        0.3
    )  # taller, same dome
    assert shell_shape(SPECIES["zebra"]) is None

    brief, t = load_brief("bibi_kobe"), SPECIES["tortoise"]
    ball = {c.id: c for c in score(brief, t).checks}["shape:shell_dome"]
    assert not ball.passed and not ball.hard and ball.value["shoulder"] > 0.5
    monkeypatch.setattr(shell_mod, "DOME", 1.6)  # gentler sides, a rounder top
    dome = {c.id: c for c in score(brief, replace(t, shell=((0.46, 0.58, 0.38), (0.0, 0.0, 0.07)))).checks}
    assert dome["shape:shell_dome"].passed, dome["shape:shell_dome"].message


def _coat(kind: str, n: int = 240) -> tuple[np.ndarray, np.ndarray]:
    """A pale oval figure with dark marking: concentric rings (a bullseye) or chevrons that run off its edge."""
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    cx = cy = n / 2
    fig = ((xx - cx) / 90) ** 2 + ((yy - cy) / 110) ** 2 <= 1
    if kind == "rings":
        s = np.hypot(xx - cx, yy - cy)
    else:
        s = yy + 1.4 * np.abs(xx - cx)
    dark = fig & (np.sin(s / 9.0) > 0.1)
    rgb = np.full((n, n, 3), 240, np.uint8)
    rgb[dark] = 25
    rgb[~fig] = (222, 219, 212)
    return rgb, fig


def test_stripe_rings_find_a_bullseye_and_pass_chevrons():
    from animatica.design.image_checks import fill_roundness, stripe_rings

    rings = stripe_rings(*_coat("rings"))
    assert rings["largest"] > 0.015 and rings["count"] >= 1  # the pale annulus between two dark rings
    assert stripe_rings(*_coat("chevrons"))["largest"] == 0.0
    # a thin strip shut in between features is closed but not a ring
    strip = np.zeros((60, 60), bool)
    strip[5:55, 28:32] = True
    assert fill_roundness(strip) < 0.35
    annulus = np.zeros((60, 60), bool)
    yy, xx = np.mgrid[0:60, 0:60]
    r = np.hypot(yy - 30, xx - 30)
    annulus[(r > 18) & (r < 26)] = True
    assert fill_roundness(annulus) > 0.7


def test_zuris_baseline_bullseyes_fail_and_her_chevrons_pass():
    """The owner's catch (cloud review 11-17 06:36): Zuri's baseline sheet rings her chest and rump; v2-v4's
    chevrons close nothing. Measured on the committed sheets."""
    from animatica.design.image_checks import sheet_views, stripe_rings
    from animatica.design.rubric import STRIPE_RING_MAX

    root = Path(__file__).resolve().parents[1] / "design"
    base = sheet_views(root / "baseline" / "zuri_sheet.jpg")
    assert stripe_rings(*base["front"])["largest"] > STRIPE_RING_MAX
    assert stripe_rings(*base["back"])["largest"] > 5 * STRIPE_RING_MAX
    for v in ("v2", "v3", "v4"):
        views = sheet_views(root / "zuri" / v / "sheet.jpg")
        assert all(stripe_rings(*views[t])["largest"] <= STRIPE_RING_MAX for t in ("front", "back")), v


def test_the_stripe_ring_check_is_hard():
    b = load_brief("zuri")
    img = {"neck_notch": 0.4, "floating_parts": 0, "dark_blob": 0.02}
    bad = score(b, SPECIES["zebra"], {**img, "stripe_rings": {"largest": 0.15, "view": "back"}}).as_dict()
    good = score(b, SPECIES["zebra"], {**img, "stripe_rings": {"largest": 0.007, "view": "back"}}).as_dict()
    c_bad = next(c for c in bad["checks"] if c["id"] == "materials:stripe_rings")
    c_good = next(c for c in good["checks"] if c["id"] == "materials:stripe_rings")
    assert c_bad["hard"] and not c_bad["passed"] and "bullseye" in c_bad["message"]
    assert c_good["passed"]
    assert not bad["ready"]
