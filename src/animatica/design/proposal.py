"""Design proposals: a next version of a locked character, built beside it, never over it.

DESIGN_STAGE.md §1 forbids production from altering an approved design, and §6 says only the owner moves a
design into the library. A proposal is how the pipeline offers a better version anyway: a JSON file of field
overrides on top of the *locked* species parameters, rendered to its own folder
(``design/proposals/<char>-<version>/``) with the standard sheet, scored by the same rubric and read blind
(DECISIONS #111). The locked species in ``creatures.species`` stays untouched until the owner approves.

``proposal.json``::

    {"character": "kiki", "version": "v7", "base": "v6",
     "why": ["the reviewer / blind reader notes it answers"],
     "overrides": {"torso": [0.09, 0.172, 0.1], "neck": {"tip": [0, -0.13, 0.07]}}}

Overrides name :class:`~animatica.creatures.species.Species` fields. Tuples are given as lists; a ``Chain``
field (neck, tail, trunk) takes a partial dict; ``mats`` and ``coat`` are merged one level deep (a material's
keys replace the locked ones, other materials stay). Unknown fields are an error, so a typo can't silently
render the locked design under a new name.
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

from animatica.creatures.species import Chain, Extra, Species

CHAIN_FIELDS = ("neck", "tail", "trunk")
MERGE_FIELDS = ("coat", "mats", "part_mats")


def _tuplify(v: Any) -> Any:
    if isinstance(v, list):
        return tuple(_tuplify(x) for x in v)
    return v


def _chain(old: Chain | None, new: dict[str, Any]) -> Chain:
    base = (
        {}
        if old is None
        else {"base": old.base, "tip": old.tip, "bones": old.bones, "r0": old.r0, "r1": old.r1}
    )
    unknown = set(new) - {"base", "tip", "bones", "r0", "r1"}
    if unknown:
        raise ValueError(f"chain override: unknown keys {sorted(unknown)}")
    base.update({k: _tuplify(v) for k, v in new.items()})
    return Chain(**base)


def apply_overrides(sp: Species, overrides: dict[str, Any]) -> Species:
    """The locked species with ``overrides`` applied (see the module doc)."""
    names = {f.name for f in fields(Species)}
    unknown = set(overrides) - names
    if unknown:
        raise ValueError(f"unknown Species fields: {sorted(unknown)}")
    if "name" in overrides:
        raise ValueError("a proposal keeps the species name (face rigs and gaits are keyed by it)")
    kw: dict[str, Any] = {}
    for k, v in overrides.items():
        old = getattr(sp, k)
        if k in CHAIN_FIELDS and isinstance(v, dict):
            kw[k] = _chain(old, v)
        elif k == "mats":
            merged = {m: dict(d) for m, d in old.items()}
            for m, d in v.items():
                merged[m] = {**merged.get(m, {}), **d}
            kw[k] = merged
        elif k in MERGE_FIELDS:
            kw[k] = {**old, **v}
        elif k == "extras":
            kw[k] = tuple(Extra(**{kk: _tuplify(vv) for kk, vv in e.items()}) for e in v)
        else:
            kw[k] = _tuplify(v)
    return replace(sp, **kw)


def load_proposal(path: Path) -> dict[str, Any]:
    """Read a ``proposal.json`` (a file, or the folder holding one) and check its shape."""
    p = path / "proposal.json" if path.is_dir() else path
    doc = json.loads(p.read_text(encoding="utf-8"))
    for key in ("character", "version", "base", "overrides"):
        if key not in doc:
            raise ValueError(f"{p}: missing {key!r}")
    doc["dir"] = str(p.parent)
    return doc


def proposal_species(doc: dict[str, Any], species: dict[str, Species]) -> Species:
    """The proposal's species, built on the locked one."""
    from animatica.creatures.species import CAST

    return apply_overrides(species[CAST[doc["character"]]], doc["overrides"])


def changed_fields(sp: Species, proposed: Species) -> dict[str, tuple[Any, Any]]:
    """Fields whose value differs: name -> (locked, proposed). For the packet's change list."""
    return {
        f.name: (getattr(sp, f.name), getattr(proposed, f.name))
        for f in fields(Species)
        if getattr(sp, f.name) != getattr(proposed, f.name)
    }


def stress_summary(report: dict[str, Any], proposed: Species) -> dict[str, Any]:
    """What a proposal's ``score.json`` says about its rig stress test (``scripts/rig_stress_test.py
    --proposal``): passed or not, the hard and soft checks that failed, and whether the report measured *these*
    parameters (a report about another version of the proposal must not count; DECISIONS #68)."""
    from animatica.design.fingerprint import staleness

    st = staleness(report, proposed)
    checks = report.get("checks", [])
    return {
        "passed": bool(report.get("passed")) and st["species_ok"],
        "fresh": st["species_ok"],
        "failed": sorted(c["id"] for c in checks if c.get("hard", True) and not c["passed"]),
        "soft_failed": sorted(c["id"] for c in checks if not c.get("hard", True) and not c["passed"]),
        "checks": len(checks),
        "record": "rig_stress.json",
    }
