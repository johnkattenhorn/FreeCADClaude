# SPDX-License-Identifier: LGPL-2.1-or-later
"""When a conversation acquires a document to live under: chat_panel.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_chat_key_transition.py

chats.json was never written. The panel files a conversation under the active
document's key, and for a project document that key comes from the source file
recorded on its objects, because such a document is never saved and has no
FileName.

slotActivateDocument fires when App.newDocument() is called, before anything is
in the document. So the key came back None, nothing was filed, and nothing
re-ran once the import arrived a moment later.

Two cases have to stay apart once it does arrive:

  a document that has just GAINED a key is the same conversation, now with
  somewhere to live -- adopt the key and file what is on screen;

  a switch from one document to another is a different conversation -- save the
  old one and load the new one's.

Getting that backwards either loses the conversation or shows the wrong one.
These call the method against a stand-in, so no Qt widget is needed.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, "/usr/lib/freecad/Ext")

import FreeCAD  # noqa: E402

from freecad.freecadclaude import chat_panel, chat_store  # noqa: E402


class _Transcript:
    def __init__(self, entries=()):
        self._entries = list(entries)

    def entries(self):
        return list(self._entries)


class _Widget:
    """Only what _on_document_activated touches."""

    def __init__(self, key=None, entries=()):
        self._chat_key = key
        self._restored_session_id = None
        self.transcript_view = _Transcript(entries)
        self.persisted = 0
        self.loaded = []

    def _persist_chat(self):
        self.persisted += 1

    def _load_chat(self, key):
        self.loaded.append(key)
        self._chat_key = key


class _Doc:
    def __init__(self, filename="", objects=()):
        self.FileName = filename
        self.Objects = list(objects)


class _Obj:
    def __init__(self, source):
        setattr(self, "FCCSourceFile", source)


KEY = os.path.abspath("/p/out/cap.step")
OTHER = os.path.abspath("/p/out/other.step")


class KeyTransition(unittest.TestCase):
    def setUp(self):
        self._doc = getattr(FreeCAD, "ActiveDocument", None)
        self._load = chat_store.load
        chat_store.load = lambda key: (None, [])

    def tearDown(self):
        FreeCAD.ActiveDocument = self._doc
        chat_store.load = self._load

    def _run(self, widget, doc):
        FreeCAD.ActiveDocument = doc
        chat_panel.ChatWidget._on_document_activated(widget)

    def test_a_document_gaining_a_key_keeps_the_conversation(self):
        """The regression. The panel opens before the STEP is imported; when it
        lands, the chat on screen must be adopted, not wiped."""
        widget = _Widget(key=None, entries=[("you", "why 1.6mm?")])
        self._run(widget, _Doc("", [_Obj(KEY)]))
        self.assertEqual(widget._chat_key, KEY)
        self.assertEqual(widget.loaded, [], "must not clear what is on screen")
        self.assertEqual(widget.persisted, 1, "and must file it under the new key")

    def test_gaining_a_key_with_a_stored_chat_and_an_empty_screen_restores_it(self):
        """Restart: panel opens empty, document arrives, the stored chat is
        this document's and should come back."""
        chat_store.load = lambda key: ("sess-old", [("you", "earlier")])
        widget = _Widget(key=None, entries=[])
        self._run(widget, _Doc("", [_Obj(KEY)]))
        self.assertEqual(widget.loaded, [KEY], "should load the stored chat")

    def test_switching_documents_saves_and_swaps(self):
        widget = _Widget(key=KEY, entries=[("you", "about the cap")])
        self._run(widget, _Doc("", [_Obj(OTHER)]))
        self.assertEqual(widget.persisted, 1)
        self.assertEqual(widget.loaded, [OTHER])

    def test_the_same_document_again_does_nothing(self):
        widget = _Widget(key=KEY)
        self._run(widget, _Doc("", [_Obj(KEY)]))
        self.assertEqual((widget.persisted, widget.loaded), (0, []))

    def test_no_key_either_side_leaves_the_transcript_alone(self):
        """An unsaved, empty document's chat lives only on screen."""
        widget = _Widget(key=None, entries=[("you", "hello")])
        self._run(widget, _Doc("", []))
        self.assertEqual((widget.persisted, widget.loaded), (0, []))
        self.assertIsNone(widget._chat_key)

    def test_a_restored_session_id_is_kept_when_adopting(self):
        chat_store.load = lambda key: ("sess-stored", [])
        widget = _Widget(key=None, entries=[("you", "mid-conversation")])
        self._run(widget, _Doc("", [_Obj(KEY)]))
        self.assertEqual(widget._restored_session_id, "sess-stored")


if __name__ == "__main__":
    unittest.main(verbosity=2)
