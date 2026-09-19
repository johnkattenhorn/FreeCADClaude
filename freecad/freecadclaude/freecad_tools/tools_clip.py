# SPDX-License-Identifier: LGPL-2.1-or-later
"""clip_view -- cut the model open in the user's OWN view, and leave it cut.

cutaway answers "what is inside this?" with a picture: it renders through a
separate view, so the model on screen never moves and the user is looking at
something the panel cannot point at. clip_view answers the same question on the
thing they are actually looking at. The cut stays until it is turned off, so
they can orbit it, click faces on the cut surface and ask about them.

Nothing is modelled. A clip plane is a rendering property of a view -- Coin
issues glClipPlane while drawing -- so the solid is untouched, the document is
not dirtied, and there is nothing to undo.

The node's lifetime is this module's. It is ref'd on the way in and held in
_ACTIVE until it is removed: a Python-owned Coin node that gets garbage
collected while still in a live scene graph is a use-after-free, and the
segfault lands somewhere with no mention of a clip plane in it.
"""

import FreeCAD

from .tools_cutaway import _insert_clip_plane, _resolve_clip_plane

#: {document name: (clip node, the group it was inserted into)}. Holds the
#: reference that keeps the node alive while the scene graph points at it.
_ACTIVE = {}

_CLIP_VIEW_SCHEMA = {
    "name": "clip_view",
    "description": (
        "Cut the model open IN THE USER'S OWN 3D VIEW and leave it cut, so they "
        "can see inside the part on screen, orbit it and click the exposed "
        "faces. Use this when they ask to see inside something -- it is what "
        "'show me the cavity' means when they have the model in front of them. "
        "cutaway renders a picture instead, which does not move what they are "
        "looking at. Specify the plane as 'axis' (x/y/z) plus optional "
        "'position' (mm, defaults to the middle of the part) and 'keep' "
        "(low/high, which half stays drawn), or as 'point' [x,y,z] plus "
        "'normal' [x,y,z] for an arbitrary plane -- the kept half is the side "
        "the normal points toward. Pass 'off': true to remove it. The cut is a "
        "view setting, not geometry: nothing is modelled, the document is not "
        "modified, and the surface is HOLLOW -- you see the inside faces the "
        "cut exposed, not a filled section. Tell the user it is on and how to "
        "get rid of it, because it persists until someone says so."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "axis": {"type": "string", "description": "x, y or z"},
            "position": {"type": "number", "description": "mm along that axis"},
            "keep": {"type": "string", "description": "low (default) or high"},
            "point": {"type": "array", "items": {"type": "number"}},
            "normal": {"type": "array", "items": {"type": "number"}},
            "off": {"type": "boolean", "description": "Remove the clip plane"},
        },
    },
}


def _active_view():
    import FreeCADGui

    view = FreeCADGui.activeView()
    if view is None or not hasattr(view, "getSceneGraph"):
        return None
    return view


def _remove(doc_name):
    """Take the clip plane out of the graph and let go of it. Idempotent."""
    entry = _ACTIVE.pop(doc_name, None)
    if entry is None:
        return False
    clip, parent = entry
    try:
        parent.removeChild(clip)
    except Exception:  # noqa: BLE001 - graph already gone with the view
        pass
    try:
        clip.unref()
    except Exception:  # noqa: BLE001
        pass
    return True


def _run_clip_view(args):
    doc = FreeCAD.ActiveDocument
    if doc is None:
        return "No active document."

    if args.get("off"):
        return ("Clip plane removed; the model is whole again."
                if _remove(doc.Name) else "There was no clip plane on this view.")

    view = _active_view()
    if view is None:
        return ("The active tab isn't a 3D view -- click into the 3D view and "
                "try again.")

    try:
        from pivy import coin
    except Exception as exc:  # noqa: BLE001
        return f"Could not load the Coin3D scene-graph library: {exc!r}"

    plane, desc, _normal, err = _resolve_clip_plane(args, doc)
    if err:
        return err

    # One at a time: a second plane on the same view would clip against the
    # first and the result is nobody's idea of a section.
    _remove(doc.Name)

    clip = coin.SoClipPlane()
    clip.ref()
    clip.plane.setValue(plane)
    clip.on.setValue(True)
    try:
        parent = _insert_clip_plane(view, clip)
    except Exception as exc:  # noqa: BLE001
        clip.unref()
        return f"Could not apply the clip plane to the view: {exc!r}"

    _ACTIVE[doc.Name] = (clip, parent)
    return (
        f"Cut open in the user's view at {desc}. It stays until removed "
        "(clip_view with 'off': true, or View -> Clipping plane). The cut is "
        "hollow -- those are the interior surfaces it exposed, not a filled "
        "section -- and nothing was modelled, so the document is unchanged."
    )
