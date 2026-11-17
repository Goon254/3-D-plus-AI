import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("ANIMATICA_LINE_CACHE", str(Path(__import__("tempfile").mkdtemp()) / "lines"))

HAS_BPY = importlib.util.find_spec("bpy") is not None or bool(os.environ.get("ANIMATICA_BLENDER_BIN"))


def pytest_collection_modifyitems(config, items):
    if HAS_BPY:
        return
    skip = pytest.mark.skip(reason="Blender (bpy) not available")
    for item in items:
        if "blender" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def engine(tmp_path_factory):
    from animatica.core.engine import BlenderSession

    s = BlenderSession(workdir=tmp_path_factory.mktemp("engine"))
    yield s
    s.close()


@pytest.fixture
def fresh(engine, tmp_path):
    engine.new_scene(workdir=tmp_path)
    return engine
