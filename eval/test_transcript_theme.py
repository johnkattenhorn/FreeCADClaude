# SPDX-License-Identifier: LGPL-2.1-or-later
"""The transcript follows FreeCAD's theme: transcript_widgets._document_style.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_transcript_theme.py

QTextBrowser paints its own Base background and Qt's Markdown renderer has its
own idea of a code block, so the panel came out as a white slab inside a dark
FreeCAD. The fix is to name no colours of our own: the browsers are painted
transparent and everything else is derived from QApplication.palette().

That is only true for as long as nobody puts a literal back, which is what
these tests are for. Runs headless on the offscreen platform plugin.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# The addon imports Qt as `PySide`, FreeCAD's own alias for its bundled binding.
# That name lives in FreeCAD's Ext directory, which the GUI puts on sys.path at
# startup and a plain python3 does not -- so add it here rather than importing
# PySide6 directly, which would test a different module from the one that ships.
sys.path.insert(0, "/usr/lib/freecad/Ext")

from PySide import QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from freecad.freecadclaude import transcript_widgets as tw  # noqa: E402

DARK = ("#1e1e1e", "#e0e0e0")
LIGHT = ("#ffffff", "#000000")


def _style(window, window_text):
    pal = QtGui.QPalette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(window))
    pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor(window_text))
    _app.setPalette(pal)
    return tw._document_style()


class DocumentStyle(unittest.TestCase):
    def test_style_changes_with_the_palette(self):
        self.assertNotEqual(_style(*DARK), _style(*LIGHT),
                            "a style that ignores the palette is a hardcoded theme")

    def test_code_block_is_inset_in_whichever_direction_the_theme_runs(self):
        """Lighter than a dark surface, darker than a light one -- a fixed
        colour can only be right for one of them."""
        for (window, text), lighter in ((DARK, True), (LIGHT, False)):
            with self.subTest(window=window):
                style = _style(window, text)
                code = QtGui.QColor(style.split("background-color: ")[1].split(";")[0])
                surface = QtGui.QColor(window)
                if lighter:
                    self.assertGreater(code.lightness(), surface.lightness())
                else:
                    self.assertLess(code.lightness(), surface.lightness())

    def test_no_literal_white_or_black_in_the_style(self):
        for window, text in (DARK, LIGHT):
            with self.subTest(window=window):
                style = _style(window, text).lower()
                self.assertNotIn("#ffffff", style)
                self.assertNotIn("#000000", style)
                self.assertNotIn("white", style)


class Blend(unittest.TestCase):
    def test_endpoints_and_midpoint(self):
        black, white = QtGui.QColor("#000000"), QtGui.QColor("#ffffff")
        self.assertEqual(tw._blend(black, white, 0.0).name(), "#000000")
        self.assertEqual(tw._blend(black, white, 1.0).name(), "#ffffff")
        self.assertEqual(tw._blend(black, white, 0.5).name(), "#7f7f7f")


if __name__ == "__main__":
    unittest.main(verbosity=2)
