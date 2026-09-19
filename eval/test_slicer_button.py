# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Slicer button hands the model over: chat_panel._export_for_slicer.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_slicer_button.py

The button used to open a settings page and nothing else, which is not what a
button marked Slicer suggests: it did not slice, and it said nothing about the
part on screen. It now exports what is visible, oriented the way each part
prints, and opens the slicer on it.

Everything that can go wrong falls back to the settings page rather than
failing silently, so each of those paths is checked here.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import FreeCAD  # noqa: E402

from freecad.freecadclaude import chat_panel, slicer_runner  # noqa: E402
from freecad.freecadclaude.freecad_tools import print_export  # noqa: E402


class _Shape:
    def isNull(self):
        return False


class _ViewObject:
    def __init__(self, visible=True):
        self.Visibility = visible


class _Obj:
    def __init__(self, visible=True):
        self.Shape = _Shape()
        self.ViewObject = _ViewObject(visible)


class _Doc:
    Name = "cap"

    def __init__(self, objects):
        self.Objects = list(objects)


class _Widget:
    pass


class ExportForSlicer(unittest.TestCase):
    def setUp(self):
        self._doc = getattr(FreeCAD, "ActiveDocument", None)
        self._discover = slicer_runner.discover_binary
        self._export = print_export.oriented_export
        self._open_url = chat_panel.QtGui.QDesktopServices.openUrl
        self._handles = chat_panel._desktop_handles
        self.opened = []
        # Exports land in a throwaway folder, not the user's real session dir:
        # a test run should not leave files in their conversation history.
        from freecad.freecadclaude import freecad_tools

        self._freecad_tools = freecad_tools
        self._session_dir = freecad_tools.session_dir
        self.tmp = tempfile.mkdtemp()
        freecad_tools.session_dir = lambda: self.tmp
        print_export.oriented_export = lambda objs, path, **kw: open(path, "w").close()
        slicer_runner.discover_binary = lambda *a, **kw: {
            "path": "/usr/bin/true", "label": "Bambu Studio"}
        # No desktop association by default, so the fallback is what gets
        # exercised unless a test says otherwise.
        self._associate(False)

    def _associate(self, handled):
        chat_panel._desktop_handles = lambda _suffix: handled
        chat_panel.QtGui.QDesktopServices.openUrl = (
            lambda url: self.opened.append(url) or handled)

    def tearDown(self):
        FreeCAD.ActiveDocument = self._doc
        slicer_runner.discover_binary = self._discover
        print_export.oriented_export = self._export
        chat_panel.QtGui.QDesktopServices.openUrl = self._open_url
        chat_panel._desktop_handles = self._handles
        self._freecad_tools.session_dir = self._session_dir

    def _run(self, doc):
        FreeCAD.ActiveDocument = doc
        return chat_panel.ChatWidget._export_for_slicer(_Widget())

    def test_visible_solids_are_exported_and_the_slicer_opened(self):
        path, problem = self._run(_Doc([_Obj()]))
        self.assertIsNone(problem)
        self.assertTrue(path.endswith("cap.stl"), path)
        self.assertTrue(os.path.isfile(path), "the export must exist")

    def test_hidden_objects_are_not_sent(self):
        """What is on screen is what goes to the slicer."""
        path, problem = self._run(_Doc([_Obj(visible=False)]))
        self.assertIsNone(path)
        self.assertIn("nothing visible", problem)

    def test_an_empty_document_falls_back(self):
        path, problem = self._run(_Doc([]))
        self.assertIsNone(path)
        self.assertIn("nothing visible", problem)

    def test_the_desktop_association_is_tried_first(self):
        """Someone whose default .3mf handler is OrcaSlicer means it. A button
        that ignores the association is a button that fights the user."""
        self._associate(True)
        called = []
        slicer_runner.discover_binary = lambda *a, **kw: called.append(1) or None
        path, problem = self._run(_Doc([_Obj()]))
        self.assertIsNone(problem)
        self.assertEqual(len(self.opened), 1, "should have opened the file")
        self.assertEqual(called, [], "must not go looking for a slicer itself")

    def test_no_association_and_no_slicer_falls_back(self):
        slicer_runner.discover_binary = lambda *a, **kw: None
        path, problem = self._run(_Doc([_Obj()]))
        self.assertIsNone(path)
        self.assertIn("no slicer was found", problem)

    def test_no_association_uses_a_slicer_it_can_find(self):
        path, problem = self._run(_Doc([_Obj()]))
        self.assertIsNone(problem)
        self.assertTrue(path.endswith(".stl"))

    def test_a_failed_export_falls_back_rather_than_raising(self):
        def _boom(*_a, **_kw):
            raise RuntimeError("meshing failed")

        print_export.oriented_export = _boom
        path, problem = self._run(_Doc([_Obj()]))
        self.assertIsNone(path)
        self.assertIn("Could not export", problem)

    def test_a_slicer_that_will_not_start_falls_back(self):
        slicer_runner.discover_binary = lambda *a, **kw: {
            "path": "/nonexistent/slicer", "label": "Bambu Studio"}
        path, problem = self._run(_Doc([_Obj()]))
        self.assertIsNone(path)
        self.assertIn("Bambu Studio", problem)


class ChoosingTheFormat(unittest.TestCase):
    """STL for one part, 3MF for several.

    FreeCAD writes a 3MF's geometry but none of the print project a slicer
    expects, so Bambu Studio says "invalid config, load geometry data only"
    every time. True, and noise for a file whose job is to be looked at. An STL
    is expected to be geometry alone.

    It costs object separation, so a plate of several parts still goes as 3MF:
    arriving as one merged mesh cannot be arranged, which is worse than a
    dialog.
    """

    def setUp(self):
        self._doc = getattr(FreeCAD, "ActiveDocument", None)
        self._export = print_export.oriented_export
        self._handles = chat_panel._desktop_handles
        self._session = None
        print_export.oriented_export = lambda objs, path, **kw: open(path, "w").close()
        chat_panel._desktop_handles = lambda _suffix: True
        chat_panel.QtGui.QDesktopServices.openUrl = lambda _url: True
        from freecad.freecadclaude import freecad_tools

        self._freecad_tools = freecad_tools
        self._session_dir = freecad_tools.session_dir
        self.tmp = tempfile.mkdtemp()
        freecad_tools.session_dir = lambda: self.tmp

    def tearDown(self):
        FreeCAD.ActiveDocument = self._doc
        print_export.oriented_export = self._export
        chat_panel._desktop_handles = self._handles
        self._freecad_tools.session_dir = self._session_dir

    def _run(self, count):
        FreeCAD.ActiveDocument = _Doc([_Obj() for _ in range(count)])
        return chat_panel.ChatWidget._export_for_slicer(_Widget())[0]

    def test_one_part_goes_as_stl(self):
        self.assertTrue(self._run(1).endswith(".stl"))

    def test_several_parts_go_as_3mf(self):
        self.assertTrue(self._run(3).endswith(".3mf"))


class DesktopAssociation(unittest.TestCase):
    """A 3MF is a zip, which is what made this go wrong.

    `xdg-mime query filetype` sniffs the contents and calls a 3MF
    application/zip, so the "association" it reports is the user's archive
    manager. openUrl then opens the containing folder and returns success, and
    the button that trusted it opened a file manager instead of a slicer.

    So the question is asked BY NAME, per format.
    """

    def test_it_asks_about_the_format_not_about_zip(self):
        every = [t for types in chat_panel._MIME_TYPES.values() for t in types]
        self.assertIn("model/3mf", every)
        self.assertIn("model/stl", every)
        self.assertNotIn("application/zip", every)

    def test_the_vendor_spelling_is_covered_too(self):
        self.assertTrue(any("3dmanufacturing" in t
                            for t in chat_panel._MIME_TYPES[".3mf"]))

    def test_both_formats_are_known(self):
        self.assertEqual(set(chat_panel._MIME_TYPES), {".3mf", ".stl"})

    def test_it_does_not_sniff_the_file(self):
        """Sniffing is the bug. The source must not query filetype."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "freecad", "freecadclaude", "chat_panel.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn('"filetype"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
