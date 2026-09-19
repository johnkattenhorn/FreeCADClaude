# SPDX-License-Identifier: LGPL-2.1-or-later
"""Per-document conversation storage: freecad/freecadclaude/chat_store.py.

    PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_chat_store.py

The store's whole job is to still be right after a restart, so every test here
reads back through a fresh call rather than trusting what it just passed in.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from freecad.freecadclaude import chat_store  # noqa: E402


class _Store:
    """Point the store at a throwaway file for the duration."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self._real = chat_store._store_path
        chat_store._store_path = lambda: self.path
        return self

    def __exit__(self, *exc):
        chat_store._store_path = self._real


class _Obj:
    """A document object carrying the source tag reload_parts writes."""

    def __init__(self, source):
        setattr(self, "FCCSourceFile", source)


class _Doc:
    def __init__(self, filename, objects=()):
        self.FileName = filename
        self.Objects = list(objects)


class DocKey(unittest.TestCase):
    def test_saved_document_keys_on_its_path(self):
        self.assertEqual(chat_store.doc_key(_Doc("/tmp/a.FCStd")), "/tmp/a.FCStd")

    def test_unsaved_and_empty_has_no_key(self):
        """A document with nothing in it has no identity: Unnamed today and
        Unnamed after a restart are the same string and mean different files."""
        self.assertIsNone(chat_store.doc_key(_Doc("")))
        self.assertIsNone(chat_store.doc_key(None))

    def test_an_unsaved_project_document_keys_on_what_built_it(self):
        """The regression this fallback exists for. view.FCMacro opens a fresh
        document and imports a STEP, so FileName is always empty -- and a rule
        that stores nothing for unsaved documents stored nothing at all for the
        one workflow project mode is for."""
        doc = _Doc("", [_Obj("/home/j/cad/out/cap.step")])
        self.assertEqual(chat_store.doc_key(doc), "/home/j/cad/out/cap.step")

    def test_a_saved_path_still_wins_over_the_source(self):
        doc = _Doc("/home/j/cad/real.FCStd", [_Obj("/home/j/cad/out/cap.step")])
        self.assertEqual(chat_store.doc_key(doc), "/home/j/cad/real.FCStd")

    def test_two_parts_share_one_key_rather_than_flipping(self):
        doc = _Doc("", [_Obj("/p/b.step"), _Obj("/p/a.step")])
        self.assertEqual(chat_store.doc_key(doc), "/p/a.step|/p/b.step")
        reordered = _Doc("", [_Obj("/p/a.step"), _Obj("/p/b.step")])
        self.assertEqual(chat_store.doc_key(reordered), chat_store.doc_key(doc),
                         "object order must not change the key")

    def test_untagged_objects_do_not_make_a_key(self):
        doc = _Doc("", [_Obj("")])
        self.assertIsNone(chat_store.doc_key(doc))

    def test_key_is_absolute(self):
        self.assertTrue(os.path.isabs(chat_store.doc_key(_Doc("rel/b.FCStd"))))
        self.assertTrue(os.path.isabs(
            chat_store.doc_key(_Doc("", [_Obj("rel/out/c.step")]))))


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "chats.json")

    def test_session_id_and_entries_survive(self):
        with _Store(self.path):
            chat_store.save("/d/a.FCStd", "sess-abc",
                            [("you", "why 1.6mm?"), ("claude", "it flexes")])
            sid, entries = chat_store.load("/d/a.FCStd")
        self.assertEqual(sid, "sess-abc")
        self.assertEqual(entries, [("you", "why 1.6mm?"), ("claude", "it flexes")])

    def test_unknown_document_is_empty_not_an_error(self):
        with _Store(self.path):
            self.assertEqual(chat_store.load("/d/never.FCStd"), (None, []))

    def test_unsaved_document_stores_nothing(self):
        with _Store(self.path):
            chat_store.save(None, "sess", [("you", "hi")])
            self.assertFalse(os.path.exists(self.path), "no key means no file")
            self.assertEqual(chat_store.load(None), (None, []))

    def test_documents_do_not_bleed_into_each_other(self):
        with _Store(self.path):
            chat_store.save("/d/a.FCStd", "sess-a", [("you", "about A")])
            chat_store.save("/d/b.FCStd", "sess-b", [("you", "about B")])
            self.assertEqual(chat_store.load("/d/a.FCStd"), ("sess-a", [("you", "about A")]))
            self.assertEqual(chat_store.load("/d/b.FCStd"), ("sess-b", [("you", "about B")]))

    def test_forget_removes_only_that_document(self):
        with _Store(self.path):
            chat_store.save("/d/a.FCStd", "sess-a", [("you", "a")])
            chat_store.save("/d/b.FCStd", "sess-b", [("you", "b")])
            chat_store.forget("/d/a.FCStd")
            self.assertEqual(chat_store.load("/d/a.FCStd"), (None, []))
            self.assertEqual(chat_store.load("/d/b.FCStd")[0], "sess-b")

    def test_file_is_written_0600(self):
        """Questions and answers about the user's own drawings."""
        with _Store(self.path):
            chat_store.save("/d/a.FCStd", "s", [("you", "x")])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_a_corrupt_store_reads_as_empty(self):
        """A half-written file must not crash the panel's constructor."""
        with open(self.path, "w") as fh:
            fh.write("{not json")
        with _Store(self.path):
            self.assertEqual(chat_store.load("/d/a.FCStd"), (None, []))


class Caps(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "chats.json")

    def test_entries_are_trimmed_keeping_the_newest(self):
        many = [("you", "q%d" % i) for i in range(chat_store.MAX_ENTRIES + 10)]
        with _Store(self.path):
            chat_store.save("/d/a.FCStd", "s", many)
            _, entries = chat_store.load("/d/a.FCStd")
        self.assertEqual(len(entries), chat_store.MAX_ENTRIES)
        self.assertEqual(entries[-1], ("you", "q%d" % (chat_store.MAX_ENTRIES + 9)))

    def test_a_huge_entry_is_truncated(self):
        with _Store(self.path):
            chat_store.save("/d/a.FCStd", "s", [("claude", "x" * (chat_store.MAX_ENTRY_CHARS * 2))])
            _, entries = chat_store.load("/d/a.FCStd")
        self.assertEqual(len(entries[0][1]), chat_store.MAX_ENTRY_CHARS)

    def test_oldest_document_is_dropped_past_the_cap(self):
        with _Store(self.path):
            for i in range(chat_store.MAX_DOCS + 5):
                chat_store.save("/d/%03d.FCStd" % i, "s%d" % i, [("you", "q")])
                # distinct 'used' stamps, without sleeping a second per document
                docs = chat_store._read()
                docs["/d/%03d.FCStd" % i]["used"] = "2026-09-19T00:%02d:00" % i
                chat_store._write(docs)
            kept = chat_store._read()
        self.assertEqual(len(kept), chat_store.MAX_DOCS)
        self.assertNotIn("/d/000.FCStd", kept, "oldest should have gone")
        self.assertIn("/d/%03d.FCStd" % (chat_store.MAX_DOCS + 4), kept)

    def test_write_is_atomic_leaving_no_temp_files(self):
        with _Store(self.path):
            chat_store.save("/d/a.FCStd", "s", [("you", "x")])
        leftovers = [f for f in os.listdir(os.path.dirname(self.path)) if f.startswith(".chats-")]
        self.assertEqual(leftovers, [])
        with open(self.path) as fh:
            json.load(fh)  # parses


if __name__ == "__main__":
    unittest.main(verbosity=2)
