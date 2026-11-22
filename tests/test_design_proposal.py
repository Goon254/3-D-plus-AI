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
    assert json.loads((PROPOSALS / "kiki-v7" / "score.json").read_text())["rig_stress"].startswith("not run")
