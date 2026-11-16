"""--device auto|cpu|cuda|optix: pure selection logic, protocol, CLI plumbing, and a real Cycles render."""

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from animatica.core.protocol import Batch

ROOT = Path(__file__).resolve().parents[1]


def _devices():
    # devices.py has no top-level bpy import, so the pure helpers load without Blender
    spec = importlib.util.spec_from_file_location(
        "animatica_devices_under_test", ROOT / "adapters/blender/animatica_blender/devices.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RTX = {"OPTIX": ["RTX"], "CUDA": ["RTX"]}
OLD_NVIDIA = {"CUDA": ["GTX 1060"]}  # pre-RTX cards: CUDA only


@pytest.mark.parametrize(
    "requested, available, backend, warns",
    [
        ("auto", RTX, "OPTIX", False),
        ("auto", OLD_NVIDIA, "CUDA", False),
        ("auto", {}, "CPU", False),  # GPU-less machine: silent CPU fallback
        ("optix", RTX, "OPTIX", False),
        ("optix", OLD_NVIDIA, "CPU", True),  # explicit request that cannot be met: CPU + warning
        ("optix", {}, "CPU", True),
        ("cuda", RTX, "CUDA", False),
        ("cuda", {}, "CPU", True),
        ("cpu", RTX, "CPU", False),  # CPU forced even with a GPU present
        ("OptiX", RTX, "OPTIX", False),  # case-insensitive
    ],
)
def test_choose_backend(requested, available, backend, warns):
    got, warning = _devices().choose_backend(requested, available)
    assert got == backend
    assert bool(warning) == warns


def test_device_env_default_and_bad_values(monkeypatch):
    d = _devices()
    monkeypatch.delenv("ANIMATICA_RENDER_DEVICE", raising=False)
    assert d.requested_device(None) == "auto"
    monkeypatch.setenv("ANIMATICA_RENDER_DEVICE", "cpu")
    assert d.requested_device(None) == "cpu"
    assert d.requested_device("optix") == "optix"  # explicit op value beats the env
    with pytest.raises(ValueError):
        d.requested_device("metal")


def test_protocol_accepts_only_known_devices():
    for op in ("set_render", "render_preview"):
        Batch.model_validate({"batch_id": "b", "ops": [{"op": op, "device": "optix"}]})
    Batch.model_validate(
        {"batch_id": "b", "ops": [{"op": "render_final", "output_dir": "x", "device": "cpu"}]}
    )
    with pytest.raises(ValidationError):
        Batch.model_validate({"batch_id": "b", "ops": [{"op": "set_render", "device": "metal"}]})


def test_cli_device_flag_reaches_the_studio(monkeypatch):
    from animatica.cli.main import _studio, build_parser

    monkeypatch.delenv("ANIMATICA_RENDER_DEVICE", raising=False)
    p = build_parser()
    assert p.parse_args(["film", "x"]).device == "auto"
    assert p.parse_args(["render", "proj", "--device", "cpu"]).device == "cpu"
    args = p.parse_args(["demo", "--device", "optix", "--llm", "scripted"])
    assert _studio(args).options["device"] == "optix"
    with pytest.raises(SystemExit):
        p.parse_args(["film", "x", "--device", "metal"])


@pytest.mark.blender
def test_cycles_render_reports_device_and_falls_back(fresh, tmp_path):
    ops = [
        {"op": "create_primitive", "id": "c", "shape": "cube"},
        {"op": "set_world", "zenith": "#6080C0", "horizon": "#F2B880", "strength": 1.0},
        {"op": "set_render", "engine": "cycles", "samples": 2, "device": "cpu"},
        {
            "op": "render_preview",
            "path": str(tmp_path / "cpu.png"),
            "engine": "cycles",
            "resolution": [64, 36],
        },
    ]
    r = fresh.run_batch({"batch_id": "dev-cpu", "ops": ops})
    assert r.ok, r.errors
    assert r.data["device"] == "CPU" and (tmp_path / "cpu.png").exists()
    cpu_mean = r.data["preview_stats"]["mean"]
    assert cpu_mean > 0.05

    # auto: OptiX/CUDA when the machine has one, CPU otherwise; never an error
    r = fresh.run_batch(
        {
            "batch_id": "dev-auto",
            "ops": [
                {
                    "op": "render_preview",
                    "path": str(tmp_path / "auto.png"),
                    "engine": "cycles",
                    "resolution": [64, 36],
                    "device": "auto",
                    "frame": 1,
                }
            ],
        }
    )
    assert r.ok, r.errors
    assert r.data["device"].split(":")[0] in {"OPTIX", "CUDA", "CPU"}
    # same picture whatever the device (a broken GPU kernel shows up as a black frame)
    assert r.data["preview_stats"]["mean"] == pytest.approx(cpu_mean, abs=0.05)

    # an explicit GPU request either uses that GPU or renders on CPU with a warning
    r = fresh.run_batch(
        {
            "batch_id": "dev-optix",
            "ops": [
                {
                    "op": "render_preview",
                    "path": str(tmp_path / "optix.png"),
                    "engine": "cycles",
                    "resolution": [64, 36],
                    "device": "optix",
                }
            ],
        }
    )
    assert r.ok, r.errors
    if r.data["device"] == "CPU":
        assert any("optix" in w for w in r.warnings)
    else:
        assert r.data["device"].startswith("OPTIX")
