# SPDX-License-Identifier: LGPL-2.1-or-later
"""_insert_clip_plane's contract: freecad_tools/tools_cutaway.py.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_cutaway_clip.py

Background. cutaway renders through a throwaway offscreen view, and
_close_offscreen_view closes a WA_DeleteOnClose subwindow -- so Qt DEFERS
destroying the inner View3DInventorViewer to a posted event, after cutaway's
frame has returned. If the SoClipPlane is still a child of that view's scene
graph, the teardown unrefs it to zero and Coin deletes the node, and the Python
wrapper is deallocated afterwards onto freed memory. It lands as

    SIGSEGV
    #1  _Py_Dealloc
    #2  Gui::View3DInventorViewer::~View3DInventorViewer()

with nothing in the traceback naming a clip plane. Observed 2026-09-19.

The fix keeps the node's whole lifetime in cutaway's own frame: ref it, and
detach it in a finally before the view can go. That needs _insert_clip_plane to
say WHERE it put the node, which is what these tests hold down -- it has two
insertion paths and the wrong parent means removeChild silently does nothing
and the crash comes back.

The full sequence needs a real offscreen view, so it is not reproduced here.
This covers the part that can be tested without a GUI.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pivy import coin  # noqa: E402

from freecad.freecadclaude.freecad_tools.tools_cutaway import _insert_clip_plane  # noqa: E402


class _FakeView:
    """Just enough of a view for _insert_clip_plane: it wants a scene graph."""

    def __init__(self, sg):
        self._sg = sg

    def getSceneGraph(self):
        return self._sg


def _graph(with_camera):
    sg = coin.SoSeparator()
    sg.ref()
    if with_camera:
        sg.addChild(coin.SoOrthographicCamera())
    sg.addChild(coin.SoSeparator())  # stand-in for the geometry
    return sg


class InsertClipPlane(unittest.TestCase):
    def setUp(self):
        self.clip = coin.SoClipPlane()
        self.clip.ref()

    def tearDown(self):
        self.clip.unref()

    # Note: pivy hands back a fresh Python proxy for the same C++ node, so the
    # returned parent is never `is` the graph you passed in. Identity is the
    # wrong question -- what matters is that removeChild on it detaches.

    def test_camera_present_goes_after_the_camera(self):
        """Coin issues glClipPlane under the viewing matrix, so a plane placed
        BEFORE the camera clips in the wrong space and the cut lands somewhere
        that looks arbitrary."""
        sg = _graph(with_camera=True)
        _insert_clip_plane(_FakeView(sg), self.clip)
        self.assertEqual(sg.findChild(self.clip), 1)  # index 0 is the camera
        sg.unref()

    def test_no_camera_goes_first(self):
        sg = _graph(with_camera=False)
        _insert_clip_plane(_FakeView(sg), self.clip)
        self.assertEqual(sg.findChild(self.clip), 0)
        sg.unref()

    def test_returned_parent_is_the_one_that_can_remove_it(self):
        """The whole point of the return value. A parent that cannot remove the
        node leaves it attached, and the deferred teardown crashes again."""
        for with_camera in (True, False):
            with self.subTest(camera=with_camera):
                clip = coin.SoClipPlane()
                clip.ref()
                sg = _graph(with_camera)
                parent = _insert_clip_plane(_FakeView(sg), clip)
                self.assertIsNotNone(parent, "must say where it put the node")
                parent.removeChild(clip)
                self.assertEqual(sg.findChild(clip), -1, "node still attached")
                clip.unref()
                sg.unref()


if __name__ == "__main__":
    unittest.main(verbosity=2)
