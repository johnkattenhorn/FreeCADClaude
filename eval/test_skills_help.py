# SPDX-License-Identifier: LGPL-2.1-or-later
"""/help reports what can run, not what is bundled: chat_panel.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_skills_help.py

The addon bundles three skills in its own .claude/skills. The CLI finds skills
in its WORKING DIRECTORY, and in project mode that is the user's project, not
the addon. So /help listed three skills that could not run, and invoking one
spent a turn discovering that.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import FreeCAD  # noqa: E402

from freecad.freecadclaude import agent_config, chat_panel  # noqa: E402


class _Project:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self._real = agent_config.get_project_dir
        agent_config.get_project_dir = lambda: self.path
        return self

    def __exit__(self, *exc):
        agent_config.get_project_dir = self._real


def _with_skill(root, skill_name):
    os.makedirs(os.path.join(root, ".claude", "skills", skill_name), exist_ok=True)
    return root


class SkillsHelp(unittest.TestCase):
    def setUp(self):
        self.project = tempfile.mkdtemp()
        # Keep the user's real ~/.claude/skills out of it.
        self._dirs = chat_panel._skill_search_dirs
        chat_panel._skill_search_dirs = lambda: [
            os.path.join(agent_config.get_project_dir() or "", ".claude", "skills")]

    def tearDown(self):
        chat_panel._skill_search_dirs = self._dirs

    def test_a_project_without_the_skills_says_so(self):
        with _Project(self.project):
            text = chat_panel._skills_help()
        self.assertIn("No skills are reachable", text)
        self.assertIn("NOT reachable", text)
        for name in chat_panel._SKILL_COMMANDS:
            self.assertIn("/%s" % name, text, "must still name them")

    def test_a_linked_skill_is_listed_as_available(self):
        _with_skill(self.project, "freecad-design-advisor")
        with _Project(self.project):
            text = chat_panel._skills_help()
        self.assertIn("**Available skills**", text)
        available = text.split("NOT reachable")[0]
        self.assertIn("/design-advisor", available)
        self.assertNotIn("/lofi-sketch", available, "that one is still missing")

    def test_reachability_is_per_skill(self):
        _with_skill(self.project, "freecad-hollow-text")
        with _Project(self.project):
            self.assertTrue(chat_panel._skill_is_reachable("freecad-hollow-text"))
            self.assertFalse(chat_panel._skill_is_reachable("freecad-lofi-sketch"))

    def test_every_slash_command_maps_to_a_bundled_skill(self):
        """A command whose skill directory does not exist could never work."""
        bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", ".claude", "skills")
        for _cmd, (skill_name, _blurb) in chat_panel._SKILL_COMMANDS.items():
            self.assertTrue(os.path.isdir(os.path.join(bundled, skill_name)),
                            skill_name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
