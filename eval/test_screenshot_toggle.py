# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Screenshots preference: agent_config + freecad_tools.list_schemas.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_screenshot_toggle.py

Rendering a picture is for the AGENT to look at. The user is already looking at
the screen, so when the work is "change this face" a screenshot is a round trip
that shows them nothing new -- and every one of the five segfaults on
2026-09-19 happened on one of these tools.

Off, they must be absent from the advertised tool list, not merely refused by
the allowlist: an agent that can see a tool reaches for it, and in -p mode a
refused call ends the turn instead of prompting.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import FreeCAD  # noqa: E402

from freecad.freecadclaude import agent_config, freecad_tools  # noqa: E402


class ScreenshotToggle(unittest.TestCase):
    def setUp(self):
        self.params = FreeCAD.ParamGet(freecad_tools.PARAM_PATH)
        self.previous = self.params.GetBool("Screenshots", True)

    def tearDown(self):
        self.params.SetBool("Screenshots", self.previous)

    def _names(self):
        return {s["name"] for s in freecad_tools.list_schemas()}

    def test_on_by_default_matching_upstream(self):
        """Read against a group that has never held the key, so the default is
        what is being tested rather than a value left behind."""
        unset = FreeCAD.ParamGet(freecad_tools.PARAM_PATH + "/NoSuchGroup")
        self.assertTrue(unset.GetBool("Screenshots", True))

    def test_off_hides_every_rendering_tool(self):
        self.params.SetBool("Screenshots", False)
        names = self._names()
        for tool in agent_config._SCREENSHOT_TOOLS:
            self.assertNotIn(tool, names, tool)

    def test_off_keeps_the_tools_that_do_the_work(self):
        """Measuring and acting are the point; only looking goes away."""
        self.params.SetBool("Screenshots", False)
        names = self._names()
        for tool in ("run_python", "reload_parts", "describe_objects",
                     "get_selection", "get_sketch", "export"):
            self.assertIn(tool, names, tool)

    def test_off_keeps_capture_user_view(self):
        """It grabs the view the user is already looking at and renders nothing
        of its own -- which is what 'look at this' means."""
        self.params.SetBool("Screenshots", False)
        self.assertIn("capture_user_view", self._names())

    def test_on_advertises_everything(self):
        self.params.SetBool("Screenshots", True)
        self.assertEqual(self._names(), set(freecad_tools.TOOLS))

    def test_the_allowlist_agrees_with_what_is_advertised(self):
        """Advertised but not allowed is a dead turn; allowed but not
        advertised is a tool nobody can reach."""
        self.params.SetBool("Screenshots", False)
        config = agent_config.build_config("/usr/bin/true", 9999, "tok")
        allowed = {t.rsplit("__", 1)[-1]
                   for t in config["allowed_tools"] if t.startswith("mcp__freecad__")}
        self.assertEqual(allowed, self._names())


if __name__ == "__main__":
    unittest.main(verbosity=2)
