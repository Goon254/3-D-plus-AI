"""Fingerprints that tie a rig stress report to the design it measured (REVIEW_QUEUE, review 11-18 03:36).

The owner's brow notes (DECISIONS #65) changed three species, and nothing re-ran the stress test, so the reports
on main described the old faces: the slimmer v3 brows floated off the skin in motion and every "ready" still
stood. ``scripts/rig_stress_test.py`` now stores both fingerprints in ``rig_stress.json``; the rubric fails a
report whose species fingerprint doesn't match (hard: it measured another design) and flags one whose rig-code
fingerprint doesn't (soft: the shared rig or face code changed since, so re-run it before the owner sees it).

* :func:`species_hash`: the species parameters (the same snapshot ``approved.json`` locks).
* :func:`rig_code_hash`: the source of the modules that build, skin, pose and animate a creature. Line endings
  are normalised, so a Windows checkout hashes the same as Linux.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from animatica.creatures.species import Species

# every module whose code changes what the stress test measures (species.py is covered by species_hash)
RIG_MODULES = (
    "build",
    "ear",
    "eyes",
    "face",
    "gait",
    "gesture",
    "organic",
    "parts",
    "perform",
    "qa",
    "shell",
)

_CREATURES = Path(__file__).resolve().parents[1] / "creatures"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def species_snapshot(sp: Species) -> dict[str, Any]:
    """The species parameters as plain JSON (as ``approved.json`` stores them)."""
    return json.loads(json.dumps(asdict(sp), default=str))


def species_hash(sp: Species) -> str:
    return _digest(json.dumps(species_snapshot(sp), sort_keys=True, separators=(",", ":")).encode())


def rig_code_hash(root: Path | None = None) -> str:
    base = root or _CREATURES
    h = hashlib.sha256()
    for name in RIG_MODULES:
        p = base / f"{name}.py"
        h.update(name.encode() + b"\0")
        if p.exists():
            h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def fingerprint(sp: Species) -> dict[str, str]:
    return {"species": species_hash(sp), "rig_code": rig_code_hash()}


def staleness(stress: dict[str, Any], sp: Species) -> dict[str, Any]:
    """Compare a stress report with the current design: ``species_ok`` (False when the report has no
    fingerprint, or measured other parameters) and ``code_ok`` (False when the rig code changed since)."""
    fp = stress.get("fingerprint") or {}
    return {
        "species_ok": fp.get("species") == species_hash(sp),
        "code_ok": fp.get("rig_code") == rig_code_hash(),
        "recorded": bool(fp),
    }
