"""Design proposals render beside a locked design and never touch it (DECISIONS #112)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from animatica.creatures.species import CAST, SPECIES, Chain
from animatica.design.brief import load_brief
from animatica.design.critic import blind_verdict, load_blind_read
from animatica.design.proposal import apply_overrides, changed_fields, load_proposal, proposal_species

ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "design" / "proposals"


def test_overrides_merge_chains_and_materials_without_touching_the_locked_species():
    sp = SPECIES["meerkat"]
    before = sp.mats["back"]["pattern_color"]
    new = apply_overrides(
        sp,
        {
            "torso": [0.088, 0.19, 0.09],
            "neck": {"tip": [0.0, -0.136, 0.07]},
            "mats": {"back": {"pattern_color": "#9E774A"}},
        },
    )
    assert new.torso == (0.088, 0.19, 0.09)
    assert isinstance(new.neck, Chain) and new.neck.tip == (0.0, -0.136, 0.07)
    assert new.neck.base == sp.neck.base and new.neck.bones == sp.neck.bones  # the rest of the chain is kept
    assert new.mats["back"]["pattern_color"] == "#9E774A"
    assert new.mats["back"]["pattern_scale"] == sp.mats["back"]["pattern_scale"]  # merged, not replaced
    assert new.mats["ear"] == sp.mats["ear"]
    assert sp.mats["back"]["pattern_color"] == before  # the locked species is untouched
    assert set(changed_fields(sp, new)) == {"torso", "neck", "mats"}


@pytest.mark.parametrize(
    "bad",
    [{"torsoo": [1, 1, 1]}, {"name": "mongoose"}, {"neck": {"tipp": [0, 0, 0]}}],
)
def test_a_typo_is_an_error_not_the_locked_design_under_a_new_name(bad):
    with pytest.raises(ValueError):
        apply_overrides(SPECIES["meerkat"], bad)


def test_every_committed_proposal_builds_and_is_marked_when_read():
    found = sorted(PROPOSALS.glob("*/proposal.json"))
    assert found, "design/proposals/ has no proposal"
    for p in found:
        doc = load_proposal(p.parent)
        assert doc["character"] in CAST
        assert (ROOT / "design" / doc["character"] / doc["base"]).is_dir(), (
            "the base must be a committed design"
        )
        sp = proposal_species(doc, SPECIES)
        assert changed_fields(SPECIES[CAST[doc["character"]]], sp), f"{p}: changes nothing"
        for f in ("sheet.jpg", "silhouette.png", "thumb96.png", "score.json"):
            assert (p.parent / f).exists(), f"{p.parent / f}: render it with scripts/design_proposal.py"
        read = load_blind_read(p.parent)
        if (p.parent / "blind_read.json").exists():
            assert read is not None, f"{p.parent}: the blind read is for other images (re-rendered since)"
            verdict = blind_verdict(load_brief(doc["character"]), read)
            assert "misread" not in verdict.values() or "status" in doc, "a misread proposal must say so"


def test_compare_board_is_drawn(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    from design_proposal import compare_board

    prop = tmp_path / "kiki-v7"
    prop.mkdir()
    for f in ("silhouette.png", "thumb96.png"):
        (prop / f).write_bytes((PROPOSALS / "kiki-v7" / f).read_bytes())
    out = compare_board(ROOT / "design" / "kiki" / "v6", prop, "kiki: v6 vs v7")
    assert out.exists() and out.stat().st_size > 1000
    # the proposal's own stress test (rig_stress_test.py --proposal, #120), never the locked design's report
    stress = json.loads((PROPOSALS / "kiki-v7" / "score.json").read_text())["rig_stress"]
    assert stress["record"] == "rig_stress.json" and stress["fresh"]


def test_a_shell_profile_domes_the_shell_and_leaves_the_locked_one_untouched():
    """Bibi Kobe's shell read as a ball (shape:shell_dome 0.53, max 0.40; DECISIONS #95). ``shell_profile``
    (#114) shapes the carapace per species; unset, it builds v3's mesh exactly and is left out of the species
    fingerprint, so the locked design and its stress report stay valid."""
    from dataclasses import replace

    from animatica.creatures.build import build_creature
    from animatica.design.fingerprint import species_hash, species_snapshot
    from animatica.design.measure import shell_shape

    sp = SPECIES["tortoise"]
    assert sp.shell_profile is None and "shell_profile" not in species_snapshot(sp)
    v3 = (0.85, -0.02, 0.72, 0.42, 2.0)  # the defaults spelt out: the same mesh
    same = replace(sp, shell_profile=v3)
    shell = [o for o in build_creature("m", sp)[0] if str(o.get("id", "")).endswith("_shell")][0]
    shell2 = [o for o in build_creature("m", same)[0] if str(o.get("id", "")).endswith("_shell")][0]
    assert shell["vertices"] == shell2["vertices"]
    assert species_hash(same) != species_hash(sp)  # set, it counts like any parameter
    locked = shell_shape(sp)
    doc = load_proposal(PROPOSALS / "bibi_kobe-v4")
    dome = shell_shape(proposal_species(doc, SPECIES))
    assert locked["shoulder"] > 0.4  # the ball fails the soft check
    assert dome["shoulder"] <= 0.4  # the proposal is a dome
    assert 0.54 <= dome["height_length"] <= 0.62  # near the species notes' 0.58
