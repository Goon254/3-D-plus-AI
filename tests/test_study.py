import numpy as np
import pytest
from PIL import Image

from animatica.knowledge import study as st


def test_refuses_urls():
    with pytest.raises(ValueError):
        st.study(["https://www.youtube.com/watch?v=x"], "x", "none")


def test_study_images(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STYLES_DIR", tmp_path / "styles")
    paths = []
    for i, col in enumerate([(240, 140, 60), (40, 50, 110)]):
        p = tmp_path / f"r{i}.png"
        a = np.zeros((40, 60, 3), np.uint8)
        a[:20] = col
        a[20:] = (90, 70, 50)
        Image.fromarray(a).save(p)
        paths.append(str(p))
    notes = st.study(paths, "test", "generated in test")
    assert notes["frames_analysed"] == 2 and len(notes["palette"]) == 6
    assert notes["director_hints"]["mood"] in ("warm", "wonder", "mysterious", "playful")
    assert st.STYLES_DIR.joinpath("test.json").exists()
