"""The design stage (DESIGN_STAGE.md): brief -> N candidates -> design sheet -> art-director rubric -> pick.

* :mod:`.measure` reads proportions, features and materials off a :class:`~animatica.creatures.species.Species`.
* :mod:`.brief` loads ``design/<character>/brief.json`` (ranges, required features, palette, references).
* :mod:`.variants` makes parametric morphs of a species (head, eyes, ears, snout, legs, neck).
* :mod:`.image_checks` measures rendered design sheets (silhouette notch, floating parts, dark blocks).
* :mod:`.rubric` scores a candidate against its brief and turns failures into morph edits.
* :mod:`.critic` asks a vision model (or a recorded reviewer) to name the species unprompted.

Pure Python + numpy/Pillow: nothing here imports ``bpy``; rendering lives in ``scripts/design_sheet.py``.
"""
