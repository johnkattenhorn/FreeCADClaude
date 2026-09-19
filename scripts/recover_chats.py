#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Rebuild chats.json from the session logs the panel already wrote.

    python3 scripts/recover_chats.py --list
    python3 scripts/recover_chats.py --key /path/to/part.step
    python3 scripts/recover_chats.py --key /path/to/part.step --session 20260919-184242-02ce6a

Conversations are filed per document in ~/FreeCADClaude/chats.json. That file
did not exist until 2026-09-19 (the key for a project document was computed
before the document had any objects, so it always came back None and nothing
was ever filed). Everything needed to rebuild it survived anyway: every turn's
raw stream is in ~/FreeCADClaude/<session>/stream.jsonl, including the CLI's
own session id.

One session is restored, not all of them merged. The stored session id is what
makes the next question CONTINUE the conversation rather than only look as if
it does, and there is exactly one of those per session. Merging four
transcripts under one id would put text on screen that the resumed session has
no memory of, which reads worse than starting clean.

Stdlib only, and it does not import FreeCAD, so it runs with FreeCAD closed --
which is how it should be run. The panel writes the whole file back when a turn
finishes, so a recovery done while it is open is liable to be overwritten.
"""

import argparse
import json
import os
import sys
import tempfile
import time

ROOT = os.path.join(os.path.expanduser("~"), "FreeCADClaude")
STORE = os.path.join(ROOT, "chats.json")

#: Matches chat_store.MAX_ENTRIES. Kept as a literal rather than imported so
#: this stays runnable without FreeCAD on the path.
MAX_ENTRIES = 64


def sessions():
    """Session folders that hold a usable transcript, oldest first."""
    found = []
    for name in sorted(os.listdir(ROOT)) if os.path.isdir(ROOT) else []:
        path = os.path.join(ROOT, name, "stream.jsonl")
        if not os.path.isfile(path):
            continue
        entries, session_id = read_stream(path)
        if entries:
            found.append((name, session_id, entries))
    return found


def read_stream(path):
    """(entries, session_id) from one stream.jsonl.

    Claude's answers only. The user's questions are NOT recoverable from these
    logs: the panel passes each one to the CLI as a `-p` argument, so it never
    appears in the CLI's output stream. What comes back is one side of the
    conversation.

    The session id is the part that matters most anyway. Restoring it means the
    next question continues the real conversation, and that session does
    remember the questions even though this file does not.

    Tool calls, their results and the reasoning are in the log, and are left
    out: the panel does not put those back on screen either, so a restored
    transcript should not carry them.
    """
    entries = []
    session_id = None
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("session_id"):
                session_id = event["session_id"]
            if event.get("type") != "assistant":
                continue
            content = (event.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            # One entry per assistant message. The CLI emits a whole message per
            # "assistant" event, with the token-by-token deltas in separate
            # "stream_event" records, so there is nothing to stitch back
            # together here.
            for block in content:
                if block.get("type") != "text":
                    continue
                text = (block.get("text") or "").strip()
                if text:
                    entries.append(("claude", text))
    return entries, session_id


def write_store(key, session_id, entries):
    """Merge one document's conversation into chats.json, 0600 and atomic."""
    docs = {}
    if os.path.isfile(STORE):
        try:
            with open(STORE, "r", encoding="utf-8") as fh:
                docs = (json.load(fh) or {}).get("docs") or {}
        except ValueError:
            print("existing chats.json is not valid JSON; it will be replaced",
                  file=sys.stderr)
    docs[key] = {
        "session_id": session_id,
        "entries": [[k, t] for k, t in entries[-MAX_ENTRIES:]],
        "used": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    os.makedirs(ROOT, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ROOT, prefix=".chats-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"docs": docs}, fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, STORE)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true",
                        help="show recoverable sessions and exit")
    parser.add_argument("--key", help="document key to file the chat under, "
                                      "usually the STEP the document was built from")
    parser.add_argument("--session", help="session folder name (default: the newest)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be written, write nothing")
    args = parser.parse_args()

    found = sessions()
    if not found:
        print("no recoverable sessions under %s" % ROOT)
        return 1

    if args.list or not args.key:
        print("%-28s %-38s %s" % ("session", "claude session id", "messages"))
        for name, session_id, entries in found:
            print("%-28s %-38s %d" % (name, session_id or "-", len(entries)))
        if not args.key:
            print("\nPass --key <document key> to restore one. For a project "
                  "document that is\nthe absolute path of the STEP it was built "
                  "from, e.g. out/part.step.")
        return 0

    chosen = found[-1]
    if args.session:
        matches = [s for s in found if s[0] == args.session]
        if not matches:
            print("no session %r; --list shows what there is" % args.session)
            return 1
        chosen = matches[0]

    name, session_id, entries = chosen
    key = os.path.abspath(os.path.expanduser(args.key))
    kept = entries[-MAX_ENTRIES:]
    print("session   %s" % name)
    print("id        %s" % (session_id or "none (a follow-up will start fresh)"))
    print("key       %s" % key)
    print("messages  %d%s" % (len(kept),
                              "" if len(kept) == len(entries)
                              else " (of %d, oldest dropped)" % len(entries)))
    print("first     %s" % kept[0][1][:70].replace("\n", " "))
    print("last      %s" % kept[-1][1][:70].replace("\n", " "))

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    write_store(key, session_id, kept)
    print("\nwritten to %s" % STORE)
    print("Start FreeCAD and open that document; the chat should be there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
