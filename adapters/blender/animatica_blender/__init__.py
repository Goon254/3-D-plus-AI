# SPDX-License-Identifier: GPL-3.0-or-later
"""Animatica Blender adapter.

Usable two ways:
  * headless: ``python -m animatica_blender.server --stdio`` (bpy module) or via ``blender -b``
  * live add-on: install this folder as a Blender add-on; it starts a local socket server inside the
    running Blender UI (default port 9876) speaking the same JSON protocol, executed on the main
    thread via ``bpy.app.timers`` so artists can watch agents work.
"""

bl_info = {
    "name": "Animatica Live Bridge",
    "author": "Animatica contributors",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Animatica",
    "description": "Lets Animatica agents drive this Blender session through batched operations",
    "category": "Interface",
}

_live = None


def register():  # pragma: no cover - requires the Blender UI
    import bpy

    from .live import LiveServer

    global _live
    _live = LiveServer(port=int(bpy.app.driver_namespace.get("animatica_port", 9876)))
    _live.start()


def unregister():  # pragma: no cover
    global _live
    if _live is not None:
        _live.stop()
        _live = None
