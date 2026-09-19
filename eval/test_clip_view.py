# SPDX-License-Identifier: LGPL-2.1-or-later
"""clip_view -- clipping the user's own view: freecad_tools/tools_clip.py.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_clip_view.py

The node's lifetime is the thing to get right. A Python-owned Coin node left in
a live scene graph and then garbage collected is a use-after-free, and the
segfault that follows names no clip plane anywhere in it -- which is exactly
how five crashes on 2026-09-19 stayed unexplained for so long. So the plane is
ref'd on the way in, held while it is in the graph, and removed and unref'd
together.

A real scene graph needs a GUI. These drive the lifetime with stand-ins, which
is the part that can be checked without one.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from freecad.freecadclaude.freecad_tools import tools_clip  # noqa: E402


class _Clip:
    def __init__(self):
        self.refs = 0

    def ref(self):
        self.refs += 1

    def unref(self):
        self.refs -= 1


class _Parent:
    def __init__(self):
        self.removed = []

    def removeChild(self, node):
        self.removed.append(node)


class ClipLifetime(unittest.TestCase):
    def setUp(self):
        tools_clip._ACTIVE.clear()

    def tearDown(self):
        tools_clip._ACTIVE.clear()

    def test_remove_detaches_and_releases_together(self):
        clip, parent = _Clip(), _Parent()
        clip.ref()
        tools_clip._ACTIVE["Doc"] = (clip, parent)

        self.assertTrue(tools_clip._remove("Doc"))
        self.assertEqual(parent.removed, [clip], "must come out of the graph")
        self.assertEqual(clip.refs, 0, "and the reference must be given up")
        self.assertNotIn("Doc", tools_clip._ACTIVE)

    def test_remove_is_idempotent(self):
        self.assertFalse(tools_clip._remove("Doc"))
        clip, parent = _Clip(), _Parent()
        tools_clip._ACTIVE["Doc"] = (clip, parent)
        self.assertTrue(tools_clip._remove("Doc"))
        self.assertFalse(tools_clip._remove("Doc"), "second removal is a no-op")

    def test_a_detach_that_fails_still_releases(self):
        """The view can be gone already -- closing the document does it. The
        entry must still be dropped, or the next clip stacks on a dead one."""
        class _DeadParent:
            def removeChild(self, _node):
                raise RuntimeError("wrapped C/C++ object has been deleted")

        clip = _Clip()
        clip.ref()
        tools_clip._ACTIVE["Doc"] = (clip, _DeadParent())
        self.assertTrue(tools_clip._remove("Doc"))
        self.assertEqual(clip.refs, 0)
        self.assertNotIn("Doc", tools_clip._ACTIVE)

    def test_planes_are_tracked_per_document(self):
        a, b = (_Clip(), _Parent()), (_Clip(), _Parent())
        tools_clip._ACTIVE["A"] = a
        tools_clip._ACTIVE["B"] = b
        tools_clip._remove("A")
        self.assertNotIn("A", tools_clip._ACTIVE)
        self.assertIn("B", tools_clip._ACTIVE, "one document must not clear another")


class OffWithNoDocument(unittest.TestCase):
    def test_off_without_a_document_says_so(self):
        module = types.ModuleType("FreeCAD")
        module.ActiveDocument = None
        saved = sys.modules.get("FreeCAD")
        sys.modules["FreeCAD"] = module
        try:
            import importlib

            importlib.reload(tools_clip)
            self.assertIn("No active document", tools_clip._run_clip_view({"off": True}))
        finally:
            if saved is not None:
                sys.modules["FreeCAD"] = saved
            import importlib

            importlib.reload(tools_clip)


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
