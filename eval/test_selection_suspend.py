# SPDX-License-Identifier: LGPL-2.1-or-later
"""Suspending the selection for a capture: freecad_tools/visibility.py.

    python3 eval/test_selection_suspend.py

Every capture clears the 3D selection so nothing renders in the highlight
colour, then puts it back. It used to keep the SelectionObjects that
getSelectionEx returned and re-add those.

A SelectionObject is a view onto a live selection entry. clearSelection() takes
that entry away, so what is being held afterwards points at something that has
gone -- and reading .Object off it, or handing it back to addSelection, is a
dangling reference. Nothing raises. It crashes later, somewhere unrelated:

    SIGSEGV
    #1  _Py_Dealloc
    #2  Gui::View3DInventorViewer::~View3DInventorViewer()

Four times on 2026-09-19, and every one of them had something selected -- twice
after the user selected a face, once after the agent was asked to highlight
three. The last was 1.7 seconds after Gui.Selection.addSelection.

So names are copied out before the clear, and names are what goes back. These
tests hold that down with a stand-in for FreeCADGui: the point is not that
restoring works, it is that nothing object-shaped survives the clear.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


class _FakeSelectionObject:
    """What getSelectionEx returns -- and what must NOT be held onto.

    Touching it after the clear raises here. A real one does something worse.
    """

    def __init__(self, obj_name, subs, owner):
        self._obj_name = obj_name
        self._subs = subs
        self._owner = owner

    def _check(self):
        if self._owner.cleared:
            raise RuntimeError("SelectionObject used after clearSelection()")

    @property
    def ObjectName(self):
        self._check()
        return self._obj_name

    @property
    def SubElementNames(self):
        self._check()
        return list(self._subs)

    @property
    def Object(self):
        self._check()
        raise AssertionError("nothing should reach for .Object any more")


class _FakeSelection:
    def __init__(self, entries):
        self.entries = entries          # [(obj_name, [subs])]
        self.cleared = False
        self.added = []

    def getSelectionEx(self, _doc_name=None):
        return [_FakeSelectionObject(n, s, self) for n, s in self.entries]

    def clearSelection(self, _doc_name=None):
        self.cleared = True

    def addSelection(self, *args):
        self.added.append(args)


class _Doc:
    Name = "TheDoc"


def _install(selection):
    module = types.ModuleType("FreeCADGui")
    module.Selection = selection
    sys.modules["FreeCADGui"] = module


class SuspendAndRestore(unittest.TestCase):
    def setUp(self):
        self.sel = _FakeSelection([("Part__Feature", ["Face11", "Face6", "Face17"])])
        _install(self.sel)
        from freecad.freecadclaude.freecad_tools import visibility

        self.visibility = visibility

    def tearDown(self):
        sys.modules.pop("FreeCADGui", None)

    def test_saved_state_holds_no_selection_objects(self):
        saved = self.visibility._suspend_selection(_Doc())
        self.assertTrue(self.sel.cleared)
        for entry in saved:
            for part in entry:
                self.assertIsInstance(part, (str, tuple),
                                      "only names may survive the clear")

    def test_restore_reads_nothing_from_the_old_selection(self):
        """The regression. If anything held a SelectionObject, touching it
        after the clear raises -- which is the stand-in for the real crash."""
        saved = self.visibility._suspend_selection(_Doc())
        self.visibility._restore_selection(saved)  # must not raise
        self.assertEqual(self.sel.added, [
            ("TheDoc", "Part__Feature", "Face11"),
            ("TheDoc", "Part__Feature", "Face6"),
            ("TheDoc", "Part__Feature", "Face17"),
        ])

    def test_whole_object_selection_round_trips(self):
        self.sel.entries = [("Box", [])]
        saved = self.visibility._suspend_selection(_Doc())
        self.visibility._restore_selection(saved)
        self.assertEqual(self.sel.added, [("TheDoc", "Box")])

    def test_nothing_selected_clears_nothing(self):
        self.sel.entries = []
        self.assertEqual(self.visibility._suspend_selection(_Doc()), [])
        self.assertFalse(self.sel.cleared, "no selection, nothing to clear")

    def test_an_object_that_vanished_does_not_take_the_restore_down(self):
        saved = self.visibility._suspend_selection(_Doc())

        def _boom(*_args):
            raise RuntimeError("no such object")

        self.sel.addSelection = _boom
        self.visibility._restore_selection(saved)  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
