# SPDX-License-Identifier: LGPL-2.1-or-later
"""Captures borrow the active view; they never create one: render.py.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_capture_borrows_view.py

capture_view, cutaway and view_model_3d used to open a throwaway
Gui::View3DInventor per call and destroy it afterwards, so a screenshot never
disturbed the user's camera. Destroying it segfaulted five times on
2026-09-19:

    SIGSEGV
    #1  _Py_Dealloc
    #2  Gui::View3DInventorViewer::~View3DInventorViewer()

every one of them on a capture tool. Four attempts to make the teardown safe
failed; keeping the view alive instead left a second document tab and a modal
save prompt. So no view is created, and the borrowed camera goes back.

These tests hold the decision, not the rendering: nothing calls createView, and
the camera is restored.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from freecad.freecadclaude.freecad_tools import render  # noqa: E402


class _View:
    def __init__(self, camera="CAM-ORIGINAL"):
        self.camera = camera
        self.restored = []
        self.animation = None

    def saveImage(self, *_a, **_kw):
        pass

    def getCamera(self):
        return self.camera

    def setCamera(self, cam):
        self.restored.append(cam)

    def setAnimationEnabled(self, on):
        self.animation = on


class _GuiDoc:
    def __init__(self, views=()):
        self._views = list(views)

    def mdiViewsOfType(self, _kind):
        return list(self._views)

    def createView(self, _kind):
        raise AssertionError("a capture must never create a view")


class _Doc:
    Name = "TheDoc"


def _install(active, gui_doc):
    module = types.ModuleType("FreeCADGui")
    module.activeView = lambda: active
    module.getDocument = lambda _n: gui_doc
    module.getMainWindow = lambda: None
    sys.modules["FreeCADGui"] = module


class BorrowsTheActiveView(unittest.TestCase):
    def setUp(self):
        self._force = render._force_draw_style
        render._force_draw_style = lambda *a, **kw: None

    def tearDown(self):
        render._force_draw_style = self._force
        sys.modules.pop("FreeCADGui", None)

    def test_uses_the_active_view_and_creates_nothing(self):
        view = _View()
        _install(view, _GuiDoc([view]))
        got, camera, prev = render._offscreen_view(_Doc())
        self.assertIs(got, view)
        self.assertEqual(camera, "CAM-ORIGINAL")
        self.assertIs(prev, view)
        self.assertIs(view.animation, False, "animation must be off for a capture")

    def test_falls_back_to_a_3d_view_when_the_active_tab_is_not_one(self):
        """A spreadsheet or TechDraw tab must not make a capture give up."""
        view = _View()
        _install(object(), _GuiDoc([view]))  # active tab has no saveImage
        got, _camera, _prev = render._offscreen_view(_Doc())
        self.assertIs(got, view)

    def test_no_3d_view_at_all_bails_rather_than_creating_one(self):
        _install(object(), _GuiDoc([]))
        self.assertEqual(render._offscreen_view(_Doc()), (None, None, None))

    def test_camera_is_put_back(self):
        view = _View()
        render._close_offscreen_view("CAM-ORIGINAL", view)
        self.assertEqual(view.restored, ["CAM-ORIGINAL"],
                         "the user's camera must come back exactly")

    def test_restore_without_a_camera_is_a_no_op(self):
        view = _View()
        render._close_offscreen_view(None, view)
        self.assertEqual(view.restored, [])


class NoViewCreationAnywhere(unittest.TestCase):
    def test_the_module_does_not_call_createview(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "freecad", "freecadclaude", "freecad_tools",
                            "render.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("createView", source,
                         "creating a 3D view is the crash this file removed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
