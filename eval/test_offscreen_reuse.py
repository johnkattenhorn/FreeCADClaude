# SPDX-License-Identifier: LGPL-2.1-or-later
"""The offscreen view is reused, not destroyed: freecad_tools/render.py.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_offscreen_reuse.py

Every capture tool renders through a throwaway 3D view, and destroying that
view segfaulted four times on 2026-09-19:

    SIGSEGV
    #1  _Py_Dealloc
    #2  Gui::View3DInventorViewer::~View3DInventorViewer()

after a cutaway twice and a capture_view twice -- so the teardown itself, not
any one tool. Two attempts to fix the ORDER of the teardown failed. The second
made it worse: it flushed the DeferredDelete so the destructor ran inside the
call, and that flush then appeared in the next crash's own stack.

So the view is now created once per document and hidden between calls. The
destructor runs at shutdown, where a viewer releasing a stale reference has
nowhere left to crash.

A real view needs a GUI, so these tests drive the caching with stand-ins. They
cover the decision -- reuse rather than recreate, hide rather than close --
which is the part that can be checked without one.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from freecad.freecadclaude.freecad_tools import render  # noqa: E402


class _Subwindow:
    def __init__(self):
        self.shown = 0
        self.hidden = 0
        self.closed = 0
        self.alive = True

    def show(self):
        if not self.alive:
            raise RuntimeError("wrapped C/C++ object has been deleted")
        self.shown += 1

    def hide(self):
        self.hidden += 1

    def close(self):
        self.closed += 1


class _View:
    def setAnimationEnabled(self, _on):
        pass


class Reuse(unittest.TestCase):
    def setUp(self):
        render._OFFSCREEN_VIEWS.clear()
        self._force = render._force_draw_style
        render._force_draw_style = lambda *a, **kw: None

    def tearDown(self):
        render._force_draw_style = self._force
        render._OFFSCREEN_VIEWS.clear()

    def test_close_hides_and_never_closes(self):
        """close() on a WA_DeleteOnClose subwindow is what schedules the
        destructor that crashes."""
        sub = _Subwindow()
        render._close_offscreen_view(sub)
        self.assertEqual(sub.hidden, 1)
        self.assertEqual(sub.closed, 0, "closing it is the crash")

    def test_a_cached_view_is_handed_back_rather_than_remade(self):
        view, sub = _View(), _Subwindow()
        render._OFFSCREEN_VIEWS["Doc"] = (view, sub)
        got_view, got_sub = render._reuse_offscreen_view("Doc")
        self.assertIs(got_view, view)
        self.assertIs(got_sub, sub)
        self.assertEqual(sub.shown, 1)

    def test_a_dead_cached_view_is_dropped_not_handed_back(self):
        """Qt can still destroy it -- closing the document, or shutdown. A
        cache entry pointing at a deleted C++ object must not be returned."""
        view, sub = _View(), _Subwindow()
        sub.alive = False
        render._OFFSCREEN_VIEWS["Doc"] = (view, sub)
        self.assertIsNone(render._reuse_offscreen_view("Doc"))
        self.assertNotIn("Doc", render._OFFSCREEN_VIEWS,
                         "a stale entry must be discarded")

    def test_views_are_kept_per_document(self):
        render._OFFSCREEN_VIEWS["A"] = (_View(), _Subwindow())
        render._OFFSCREEN_VIEWS["B"] = (_View(), _Subwindow())
        self.assertNotEqual(render._OFFSCREEN_VIEWS["A"],
                            render._OFFSCREEN_VIEWS["B"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
