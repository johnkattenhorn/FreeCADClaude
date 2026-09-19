# SPDX-License-Identifier: LGPL-2.1-or-later
"""clip_view -- clipping the user's own view: freecad_tools/tools_clip.py.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_clip_view.py

The first version pushed an SoClipPlane into the scene graph by hand. That was
wrong twice over: it left a Python-owned Coin node in a live graph, and it
fought with the plane View -> Clipping View manages, so the dialog's checkboxes
would not tick while a clip from the panel was in place.

It drives FreeCAD's own View3DInventorPy.toggleClippingPlane now, so there is
one plane and the dialog and the panel agree about it.

A real view needs a GUI. These use a stand-in to check the decisions: clear an
existing plane before setting a new one, ask for a manipulator only when
requested, and turn a plane into the placement FreeCAD wants.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import FreeCAD  # noqa: E402

from freecad.freecadclaude.freecad_tools import tools_clip  # noqa: E402


class _StubView:
    """Records what clip_view asks of the viewer."""

    def __init__(self, has=False, direction=(0, 1, 0)):
        self.has = has
        self.calls = []
        self._dir = direction

    def toggleClippingPlane(self, *args):
        self.calls.append(args)
        self.has = bool(args[0]) if args else not self.has

    def hasClippingPlane(self):
        return self.has

    def getViewDirection(self):
        class _D:
            pass

        d = _D()
        d.x, d.y, d.z = self._dir
        return d


class _Doc:
    Name = "TheDoc"


class ClipViaFreeCADsOwnPlane(unittest.TestCase):
    def setUp(self):
        self._view = tools_clip._active_view
        self._doc = FreeCAD.ActiveDocument if hasattr(FreeCAD, "ActiveDocument") else None
        self._resolve = tools_clip._resolve_clip_plane
        self._face = tools_clip._face_the_cut
        self._place = tools_clip._placement_for
        tools_clip._face_the_cut = lambda v, n: False
        tools_clip._placement_for = lambda p: "PLACEMENT"
        tools_clip._resolve_clip_plane = lambda a, d: ("PLANE", "x = 0 mm", (1, 0, 0), None)

    def tearDown(self):
        tools_clip._active_view = self._view
        tools_clip._resolve_clip_plane = self._resolve
        tools_clip._face_the_cut = self._face
        tools_clip._placement_for = self._place

    def _run(self, view, args):
        tools_clip._active_view = lambda: view
        FreeCAD.ActiveDocument = _Doc()
        try:
            return tools_clip._run_clip_view(args)
        finally:
            FreeCAD.ActiveDocument = self._doc

    def test_it_uses_freecads_own_plane(self):
        """Not a hand-inserted SoClipPlane. One plane, shared with the dialog."""
        view = _StubView()
        self._run(view, {"axis": "x"})
        self.assertEqual(view.calls, [(1, False, True, "PLACEMENT")])

    def test_an_existing_plane_is_cleared_first(self):
        """Toggling on over an existing plane leaves the old placement in force
        and silently ignores the new one."""
        view = _StubView(has=True)
        self._run(view, {"axis": "x"})
        self.assertEqual(view.calls[0], (0,), "must turn the old one off first")
        self.assertEqual(view.calls[1][0], 1)

    def test_handle_asks_for_a_manipulator(self):
        view = _StubView()
        self._run(view, {"axis": "x", "handle": True})
        self.assertIs(view.calls[0][2], False, "noManip false means show the handle")

    def test_no_handle_by_default(self):
        view = _StubView()
        self._run(view, {"axis": "x"})
        self.assertIs(view.calls[0][2], True)

    def test_off_removes_it(self):
        view = _StubView(has=True)
        out = self._run(view, {"off": True})
        self.assertEqual(view.calls, [(0,)])
        self.assertIn("removed", out)

    def test_off_with_nothing_set_says_so(self):
        view = _StubView(has=False)
        out = self._run(view, {"off": True})
        self.assertEqual(view.calls, [])
        self.assertIn("no clip plane", out)

    def test_it_points_at_the_dialog(self):
        """The user needs to know where else this plane lives."""
        out = self._run(_StubView(), {"axis": "x"})
        self.assertIn("Clipping View", out)


class _Dir:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _CamView:
    def __init__(self, direction):
        self._dir = direction
        self.oriented = []

    def getViewDirection(self):
        return self._dir


class FaceTheCut(unittest.TestCase):
    """SoClipPlane keeps the side its normal points toward. A camera sitting on
    that side and looking further into it sees the kept half's intact outer
    surface -- the model looks untouched and the clip reads as a no-op. That is
    what happened the first time this tool was used.
    """

    def setUp(self):
        self._apply = tools_clip._apply_camera_orientation
        self._rot = tools_clip._orbit_rotation
        self.applied = []
        tools_clip._apply_camera_orientation = lambda v, r: self.applied.append(r) or True
        tools_clip._orbit_rotation = lambda az, el: ("rot", round(az, 3), round(el, 3))

    def tearDown(self):
        tools_clip._apply_camera_orientation = self._apply
        tools_clip._orbit_rotation = self._rot

    def test_camera_already_looking_into_the_cut_is_left_alone(self):
        view = _CamView(_Dir(0, 1, 0))
        self.assertFalse(tools_clip._face_the_cut(view, (0, 1, 0)))
        self.assertEqual(self.applied, [], "an unnecessary move is still a move")

    def test_camera_on_the_wrong_side_is_swung_round(self):
        view = _CamView(_Dir(0, -1, 0))   # looking away from the kept half
        self.assertTrue(tools_clip._face_the_cut(view, (0, 1, 0)))
        self.assertEqual(len(self.applied), 1)

    def test_it_ends_up_looking_along_the_normal(self):
        """+X normal: the eye goes to -X, so azimuth is -90 and level."""
        view = _CamView(_Dir(-1, 0, 0))
        tools_clip._face_the_cut(view, (1, 0, 0))
        self.assertEqual(self.applied, [("rot", -90.0, 0.0)])

    def test_a_z_normal_gives_a_straight_down_look(self):
        view = _CamView(_Dir(0, 0, 1))
        tools_clip._face_the_cut(view, (0, 0, -1))
        _tag, _az, elevation = self.applied[0]
        self.assertAlmostEqual(elevation, 90.0, places=3)

    def test_an_unreadable_view_direction_leaves_the_camera_alone(self):
        class _Broken:
            def getViewDirection(self):
                raise RuntimeError("no camera")

        self.assertFalse(tools_clip._face_the_cut(_Broken(), (0, 1, 0)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
