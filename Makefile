PY ?= python

.PHONY: setup test test-all lint demo demo-preview game

setup:
	pip install -e ".[dev]" bpy==5.3.0 kokoro-onnx soundfile mcp
	scripts/setup_assets.sh --godot

test:
	pytest -q -m "not blender"

test-all:
	pytest -q

lint:
	ruff check src tests adapters

demo-preview:
	animatica demo --quality preview

demo:
	animatica demo --quality final

game:
	animatica game "a 2D platformer where a robot collects flowers"
