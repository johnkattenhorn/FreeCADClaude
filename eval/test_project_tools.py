# SPDX-License-Identifier: LGPL-2.1-or-later
"""reload_parts -- the project-mode import: freecad_tools/tools_project.py.

Needs a real FreeCAD, headless:

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_project_tools.py

The claim worth holding down is that a reload is keyed on the SOURCE PATH and
not on object names. FreeCAD renames on collision, so a name-keyed reload of
"cap.step" would leave the first import behind as "cap001" and the document
would fill with stale geometry that still looks plausible. Every test here
reloads at least twice for that reason -- a single import proves nothing.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import FreeCAD  # noqa: E402
import Part  # noqa: E402

from freecad.freecadclaude.freecad_tools import tools_project  # noqa: E402


class _Project:
    """Point the project dir at a throwaway folder for the duration."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self._real = tools_project._project_dir
        tools_project._project_dir = lambda: self.path
        return self

    def __exit__(self, *exc):
        tools_project._project_dir = self._real


def _write_step(path, length):
    """Export a box of a known size, the way a part script's build step would."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Part.export([Part.show(Part.makeBox(length, 10, 10), "tmp")], path)
    FreeCAD.ActiveDocument.removeObject("tmp")


class ReloadParts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.doc = FreeCAD.newDocument("T")
        FreeCAD.setActiveDocument(self.doc.Name)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def test_reload_replaces_rather_than_accumulates(self):
        step = os.path.join(self.tmp, "out", "part.step")
        _write_step(step, 20)
        with _Project(self.tmp):
            first = tools_project._run_reload_parts({"paths": ["out/part.step"]})
            self.assertIn("1 object imported", first)
            self.assertEqual(len(self.doc.Objects), 1)

            # rebuild the "part" at a different size, exactly as an edit would
            _write_step(step, 40)
            second = tools_project._run_reload_parts({"paths": ["out/part.step"]})

        self.assertIn("replaced 1", second)
        self.assertEqual(len(self.doc.Objects), 1, "a reload must not accumulate")
        self.assertAlmostEqual(self.doc.Objects[0].Shape.BoundBox.XLength, 40, places=3)

    def test_measurement_is_reported(self):
        step = os.path.join(self.tmp, "out", "part.step")
        _write_step(step, 20)
        with _Project(self.tmp):
            out = tools_project._run_reload_parts({"paths": ["out/part.step"]})
        # 20 x 10 x 10 mm = 2000 mm3 = 2 cm3
        self.assertIn("20.00 x 10.00 x 10.00 mm", out)
        self.assertIn("2.00 cm3", out)

    def test_source_tag_survives_and_is_hidden(self):
        step = os.path.join(self.tmp, "out", "part.step")
        _write_step(step, 20)
        with _Project(self.tmp):
            tools_project._run_reload_parts({"paths": ["out/part.step"]})
        obj = self.doc.Objects[0]
        self.assertEqual(getattr(obj, tools_project._SOURCE_PROP), step)
        self.assertEqual(obj.getEditorMode(tools_project._SOURCE_PROP), ["Hidden"])

    def test_untagged_objects_are_left_alone(self):
        """A reload must not touch geometry the user made by hand."""
        step = os.path.join(self.tmp, "out", "part.step")
        _write_step(step, 20)
        Part.show(Part.makeSphere(5), "handmade")
        with _Project(self.tmp):
            tools_project._run_reload_parts({"paths": ["out/part.step"]})
            _write_step(step, 40)
            tools_project._run_reload_parts({"paths": ["out/part.step"]})
        self.assertIn("handmade", [o.Name for o in self.doc.Objects])

    def test_a_second_file_does_not_displace_the_first(self):
        a = os.path.join(self.tmp, "out", "a.step")
        b = os.path.join(self.tmp, "out", "b.step")
        _write_step(a, 20)
        _write_step(b, 30)
        with _Project(self.tmp):
            tools_project._run_reload_parts({"paths": ["out/a.step", "out/b.step"]})
            _write_step(a, 25)
            tools_project._run_reload_parts({"paths": ["out/a.step"]})
        self.assertEqual(len(self.doc.Objects), 2)
        lengths = sorted(round(o.Shape.BoundBox.XLength) for o in self.doc.Objects)
        self.assertEqual(lengths, [25, 30])

    def test_bad_paths_report_rather_than_raise(self):
        with _Project(self.tmp):
            missing = tools_project._run_reload_parts({"paths": ["out/nope.step"]})
            wrong = tools_project._run_reload_parts({"paths": ["out/part.txt"]})
        self.assertIn("no such file", missing)
        self.assertIn("no such file", wrong)  # resolved before the suffix check

    def test_unsupported_suffix_is_named(self):
        junk = os.path.join(self.tmp, "out", "notes.txt")
        os.makedirs(os.path.dirname(junk), exist_ok=True)
        open(junk, "w").close()
        with _Project(self.tmp):
            out = tools_project._run_reload_parts({"paths": ["out/notes.txt"]})
        self.assertIn("not an importable geometry file", out)

    def test_deselect_is_harmless_without_a_gui(self):
        """The eval suite runs console FreeCAD, where FreeCADGui does not
        import. Deselecting must be a no-op there, not an exception that takes
        the reload with it."""
        step = os.path.join(self.tmp, "out", "part.step")
        _write_step(step, 20)
        with _Project(self.tmp):
            tools_project._drop_selection(self.doc, list(self.doc.Objects))
            out = tools_project._run_reload_parts({"paths": ["out/part.step"]})
        self.assertIn("1 object imported", out)

    def test_removal_goes_through_the_deselect_path(self):
        """The reload must deselect BEFORE removing, or Gui selection is left
        holding a reference to a deleted object -- which does not raise, it
        segfaults later from inside C++."""
        step = os.path.join(self.tmp, "out", "part.step")
        _write_step(step, 20)
        order = []
        real = tools_project._drop_selection
        tools_project._drop_selection = lambda doc, objs: order.append(
            ("deselect", [o.Name for o in objs]))
        try:
            with _Project(self.tmp):
                tools_project._run_reload_parts({"paths": ["out/part.step"]})
                imported = [o.Name for o in self.doc.Objects]
                _write_step(step, 40)
                tools_project._run_reload_parts({"paths": ["out/part.step"]})
        finally:
            tools_project._drop_selection = real
        self.assertEqual(order[-1], ("deselect", imported),
                         "the objects about to be removed must be deselected")

    def test_precheck_no_longer_refuses_without_a_project(self):
        """A document becomes a built one the FIRST time something is reloaded
        into it. Refusing until it already was made that first reload
        impossible, which is exactly the "make this reproducible" case."""
        real = tools_project._project_dir
        tools_project._project_dir = lambda: None
        try:
            self.assertIsNone(tools_project._precheck_reload_parts({"paths": ["x.step"]}))
        finally:
            tools_project._project_dir = real

    def test_an_absolute_path_works_without_a_project(self):
        step = os.path.join(self.tmp, "out", "part.step")
        _write_step(step, 20)
        real = tools_project._project_dir
        tools_project._project_dir = lambda: None
        try:
            out = tools_project._run_reload_parts({"paths": [step]})
        finally:
            tools_project._project_dir = real
        self.assertIn("1 object imported", out)

    def test_a_relative_path_still_needs_somewhere_to_resolve_against(self):
        real = tools_project._project_dir
        tools_project._project_dir = lambda: None
        try:
            out = tools_project._run_reload_parts({"paths": ["out/part.step"]})
        finally:
            tools_project._project_dir = real
        self.assertIn("nothing to resolve against", out)



class CapabilityNotice(unittest.TestCase):
    """The banner must describe the mode the conversation is actually in.

    It is the only place the user is told what a turn can reach, so a banner
    that still describes document mode while a shell is enabled is worse than
    no banner: it is a specific, reassuring, wrong answer.
    """

    def setUp(self):
        from freecad.freecadclaude import agent_config, chat_panel

        self.chat_panel = chat_panel
        self.agent_config = agent_config
        self._real = agent_config.project_root

    def tearDown(self):
        self.agent_config.project_root = self._real

    def test_a_built_drawing_names_its_checkout_and_the_shell(self):
        self.agent_config.project_root = lambda _doc: "/projects/cad-lab"
        text = self.chat_panel._capability_notice()
        self.assertIn("/projects/cad-lab", text)
        self.assertIn("shell", text)
        self.assertIn("built by a script", text)

    def test_a_hand_drawn_document_gets_the_ordinary_notice(self):
        self.agent_config.project_root = lambda _doc: None
        text = self.chat_panel._capability_notice()
        self.assertEqual(text, self.chat_panel._CAPABILITY_NOTICE)
        self.assertIn("add, edit or delete any object", text)

    def test_the_ordinary_notice_still_names_the_shell(self):
        """It is always on now, and a notice listing what a turn can reach
        cannot leave out the one tool that reaches anything."""
        self.agent_config.project_root = lambda _doc: None
        self.assertIn("shell", self.chat_panel._capability_notice())

if __name__ == "__main__":
    unittest.main(verbosity=2)
