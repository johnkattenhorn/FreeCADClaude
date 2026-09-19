# SPDX-License-Identifier: LGPL-2.1-or-later
"""The transcript follows FreeCAD's theme: transcript_widgets._document_style.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_transcript_theme.py

QTextBrowser paints its own Base background and Qt's Markdown renderer has its
own idea of a code block, so the panel came out as a white slab inside a dark
FreeCAD.

The first fix derived colours from QApplication.palette() and made it worse:
FreeCAD's themes are Qt STYLE SHEETS, and a stylesheet does not change the
application palette, so under FreeCAD Dark that palette is still the light
system one. The result was a light transcript carrying the theme's light text
-- white on white. Colours come from the WIDGET's palette now, which Qt has
folded the stylesheet into by the time it is polished.

These tests hold both ends of that down: the style must move with the palette
it is given, and it must not name a colour of its own. Headless on the
offscreen platform plugin.
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


def _style(base, text):
    """A style derived from a WIDGET carrying these colours.

    Deliberately set on the widget, not the application: a widget whose palette
    differs from the app's is exactly the situation a stylesheet theme creates,
    and the situation that broke this.
    """
    widget = QtWidgets.QWidget()
    pal = widget.palette()
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor(base))
    pal.setColor(QtGui.QPalette.Text, QtGui.QColor(text))
    widget.setPalette(pal)
    return tw._document_style(widget)


class DocumentStyle(unittest.TestCase):
    def test_style_changes_with_the_palette(self):
        self.assertNotEqual(_style(*DARK), _style(*LIGHT),
                            "a style that ignores the palette is a hardcoded theme")

    def test_the_widgets_palette_is_what_counts_not_the_applications(self):
        """The bug this file exists for. A stylesheet theme leaves the
        application palette light while the widget's is dark; reading the
        application's gave a light transcript under a dark FreeCAD."""
        app_pal = QtGui.QPalette()
        app_pal.setColor(QtGui.QPalette.Base, QtGui.QColor(LIGHT[0]))
        app_pal.setColor(QtGui.QPalette.Text, QtGui.QColor(LIGHT[1]))
        _app.setPalette(app_pal)
        self.assertEqual(_style(*DARK), _style(*DARK))
        self.assertNotEqual(_style(*DARK), _style(*LIGHT),
                            "the widget's palette must win over the app's")

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


class BrowserConstruction(unittest.TestCase):
    """Constructing one must not raise.

    Qt delivers changeEvent from inside QTextBrowser's own constructor, so any
    override reading an instance attribute set afterwards blows up during
    super().__init__(). That took the whole panel down at startup with
    "'_AutoHeightTextBrowser' object has no attribute '_styled'", and no
    headless test of the styling function could have seen it -- only building
    the widget does.
    """

    def test_constructs_and_styles_itself(self):
        browser = tw._AutoHeightTextBrowser()
        browser.setMarkdown("a `code` span")
        browser.show()  # showEvent is where the style is derived
        self.assertTrue(browser._styled, "should have styled itself once shown")

    def test_a_palette_change_before_show_does_not_raise(self):
        browser = tw._AutoHeightTextBrowser()
        pal = browser.palette()
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(DARK[0]))
        browser.setPalette(pal)  # delivers PaletteChange


class Blend(unittest.TestCase):
    def test_endpoints_and_midpoint(self):
        black, white = QtGui.QColor("#000000"), QtGui.QColor("#ffffff")
        self.assertEqual(tw._blend(black, white, 0.0).name(), "#000000")
        self.assertEqual(tw._blend(black, white, 1.0).name(), "#ffffff")
        self.assertEqual(tw._blend(black, white, 0.5).name(), "#7f7f7f")


if __name__ == "__main__":
    unittest.main(verbosity=2)
