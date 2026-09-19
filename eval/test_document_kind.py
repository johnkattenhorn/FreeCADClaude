# SPDX-License-Identifier: LGPL-2.1-or-later
"""Telling a built drawing from a drawn one: agent_config.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_document_kind.py

There used to be a ProjectDir preference deciding whether the document or a
script was the source of the geometry. That was the wrong shape: it is a fact
about the drawing in front of you, not a setting, and one global value can only
ever be right for one document at a time.

reload_parts already records the file every object was built from, so the
question answers itself per document.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import FreeCAD  # noqa: E402

from freecad.freecadclaude import agent_config  # noqa: E402


class _Obj:
    def __init__(self, source=None):
        if source is not None:
            setattr(self, agent_config.SOURCE_PROP, source)


class _Doc:
    def __init__(self, objects=()):
        self.Objects = list(objects)


class SourceFiles(unittest.TestCase):
    def test_a_hand_drawn_document_has_none(self):
        self.assertEqual(agent_config.source_files(_Doc([_Obj(), _Obj()])), [])

    def test_a_built_document_reports_what_built_it(self):
        doc = _Doc([_Obj("/p/out/cap.step")])
        self.assertEqual(agent_config.source_files(doc), ["/p/out/cap.step"])

    def test_paths_are_absolute_and_deduplicated(self):
        doc = _Doc([_Obj("/p/out/a.step"), _Obj("/p/out/a.step"), _Obj("/p/out/b.step")])
        self.assertEqual(agent_config.source_files(doc),
                         ["/p/out/a.step", "/p/out/b.step"])

    def test_a_missing_document_is_not_an_error(self):
        self.assertEqual(agent_config.source_files(None), [])


class ProjectRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())

    def test_a_hand_drawn_document_has_no_root(self):
        self.assertIsNone(agent_config.project_root(_Doc([_Obj()])))

    def test_the_git_working_tree_is_the_root(self):
        """The repository is the unit the build script, its tests and its
        history live in, so that is what gets handed to the agent."""
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "out"))
        subprocess.run(["git", "init", "-q", repo], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        step = os.path.join(repo, "out", "cap.step")
        open(step, "w").close()
        self.assertEqual(agent_config.project_root(_Doc([_Obj(step)])), repo)

    def test_without_a_repository_the_source_folder_is_used(self):
        """Not the whole filesystem. At least the script stays reachable."""
        folder = os.path.join(self.tmp, "loose")
        os.makedirs(folder)
        step = os.path.join(folder, "cap.step")
        open(step, "w").close()
        self.assertEqual(agent_config.project_root(_Doc([_Obj(step)])), folder)


class ShellIsAlwaysOn(unittest.TestCase):
    def test_bash_is_in_the_tool_list(self):
        """A drawing built by a script needs its script run; asking for a
        reproducible script for a hand-drawn one needs the same. Neither works
        without a shell."""
        config = agent_config.build_config("/usr/bin/true", 9999, "tok")
        self.assertIn("Bash", config["builtin_tools"])

    def test_the_cli_starts_in_the_session_folder(self):
        """Not the project. The bundled skills are copied here and the CLI
        finds skills in its cwd, which is what running in the project broke."""
        config = agent_config.build_config("/usr/bin/true", 9999, "tok")
        self.assertIn("FreeCADClaude", config["cwd"])


class ModelPicker(unittest.TestCase):
    """The dropdown's ids go straight to the CLI's --model."""

    def test_the_default_is_offered(self):
        self.assertIn(agent_config.DEFAULT_MODEL,
                      [mid for _label, mid in agent_config.MODELS])

    def test_no_id_carries_a_date_suffix(self):
        """Model ids are complete as they stand. A remembered date suffix is a
        different string and the CLI will not know it."""
        import re

        for _label, mid in agent_config.MODELS:
            self.assertIsNone(re.search(r"-\d{8}$", mid), mid)

    def test_labels_and_ids_are_unique(self):
        labels = [label for label, _ in agent_config.MODELS]
        ids = [mid for _, mid in agent_config.MODELS]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(len(ids), len(set(ids)))

    def test_an_unknown_id_falls_back_to_the_default(self):
        """A model dropped from the list must not leave a stored preference
        pointing at something the CLI will reject."""
        self.assertNotIn("claude-made-up-9", agent_config._VALID_MODELS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
