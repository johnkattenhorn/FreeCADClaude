# SPDX-License-Identifier: LGPL-2.1-or-later
"""Conversations that outlive the window, filed under the document they are about.

A conversation belongs to a drawing, not to a session of FreeCAD. Ask about the
flange on Monday, reopen the file on Friday, and the questions you already asked
should still be there -- losing them to a restart is how you find out you were
relying on them.

Two things are kept per document:

  session_id   Claude's own id. Restoring it means a question after a restart
               CONTINUES the conversation rather than only looking as if it
               does. Without it the transcript reads like a chat the model has
               no memory of, which is worse than an empty panel.
  entries      what was on screen: (kind, text) pairs, replayed through the
               transcript's own add_entry.

Keyed on the document's saved path. A document that has never been saved has
nowhere to file anything under, so its conversation stays in memory and dies
with the window -- the same rule Omawrite settled on, for the same reason.

Everything lives in one JSON file written 0600: your questions and Claude's
answers about your own drawings.
"""

import json
import os
import tempfile
import time

#: Most recently used documents to keep. The oldest goes when a further one
#: arrives. Generous: the file holds text, and 40 drawings is a long way past
#: what anyone has open in a week.
MAX_DOCS = 40

#: Entries kept per document. Enough to hold a working session; a transcript
#: long past this is scrollback, not context -- the session_id carries the
#: actual continuity.
MAX_ENTRIES = 64

#: Cap on any single entry. A tool result can be enormous and a transcript is
#: not an archive of them.
MAX_ENTRY_CHARS = 64 * 1024


def _store_path():
    """Where the file lives. Under the addon's own folder, beside the sessions."""
    from .freecad_tools import artifacts_dir

    return os.path.join(artifacts_dir(), "chats.json")


def doc_key(document):
    """The key a document files its conversation under, or None for unsaved.

    FileName is empty until a document has been saved, and an unsaved document
    has no stable identity to key on -- Unnamed, Unnamed001 and the next one
    after a restart are all the same string and none of them mean anything.
    """
    if document is None:
        return None
    name = (getattr(document, "FileName", "") or "").strip()
    return os.path.abspath(name) if name else None


def _read():
    try:
        with open(_store_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    docs = data.get("docs")
    return docs if isinstance(docs, dict) else {}


def _write(docs):
    """Replace the file atomically, 0600.

    Atomically because a half-written store read at the next startup is a
    crash in the panel's constructor, which is a much worse failure than a
    lost conversation.
    """
    path = _store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".chats-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"docs": docs}, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - a store we cannot write is not worth a crash
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _prune(docs):
    """Keep the MAX_DOCS most recently used."""
    if len(docs) <= MAX_DOCS:
        return docs
    ranked = sorted(docs.items(), key=lambda kv: kv[1].get("used", ""), reverse=True)
    return dict(ranked[:MAX_DOCS])


def load(key):
    """Return (session_id, entries) for `key`. Empty for an unknown or unsaved one."""
    if not key:
        return None, []
    record = _read().get(key)
    if not isinstance(record, dict):
        return None, []
    entries = [
        (str(e[0]), str(e[1]))
        for e in record.get("entries", [])
        if isinstance(e, (list, tuple)) and len(e) == 2
    ]
    return record.get("session_id") or None, entries


def save(key, session_id, entries):
    """Write this document's conversation, trimming to the caps. No-op if unsaved."""
    if not key:
        return
    trimmed = [
        [str(kind), str(text)[:MAX_ENTRY_CHARS]]
        for kind, text in list(entries)[-MAX_ENTRIES:]
    ]
    docs = _read()
    docs[key] = {
        "session_id": session_id or None,
        "entries": trimmed,
        "used": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write(_prune(docs))


def forget(key):
    """Drop this document's conversation. What "New" means: do not bring it back."""
    if not key:
        return
    docs = _read()
    if docs.pop(key, None) is not None:
        _write(docs)
