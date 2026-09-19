# SPDX-License-Identifier: LGPL-2.1-or-later
"""clip_view -- cut the model open in the user's OWN view, and leave it cut.

cutaway answers "what is inside this?" with a picture rendered through a
separate view, so the model on screen never moves and the panel cannot point at
what it just described. clip_view answers it on the thing the user is actually
looking at. The cut stays until it is turned off, so they can orbit it, click
faces on the cut surface and ask about them.

This drives FreeCAD's OWN global clipping plane, through
View3DInventorPy.toggleClippingPlane, rather than pushing an SoClipPlane into
the scene graph by hand. Three things follow from that, and all of them are
reasons the hand-rolled version was wrong:

  it is the same plane the View -> Clipping View dialog controls, so a clip set
  from here shows up ticked there and its offset slider moves it -- two
  mechanisms in one scene graph clip against each other and the result is a
  mess;

  noManip=False asks for a drag manipulator, so the user can walk the section
  through the model with the mouse;

  the node belongs to FreeCAD. Nothing Python owns is left in a live scene
  graph, which is where a garbage collection at the wrong moment becomes a
  segfault with no clip plane named anywhere in the traceback.

Nothing is modelled either way. A clip plane is a rendering property of a view,
so the solid is untouched, the document is not dirtied, and there is nothing to
undo.
"""

import FreeCAD

from .render import _apply_camera_orientation, _orbit_rotation
from .tools_cutaway import _resolve_clip_plane

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
        "the normal points toward. Pass 'off': true to remove it, or 'handle': "
        "true for a drag manipulator the user can pull to walk the cut through "
        "the model. This is FreeCAD's own clipping plane, so it also appears in "
        "View -> Clipping View, where its offset slider moves it. The camera is "
        "swung round to face the cut unless 'look' is false -- a clip applied "
        "while looking at the outer surface of the half that stays looks like "
        "nothing happened. The cut is HOLLOW: you see the inside faces it "
        "exposed, not a filled section. Nothing is modelled and the document is "
        "not modified. Tell the user it is on and how to get rid of it, because "
        "it persists until someone says so."
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
            "handle": {
                "type": "boolean",
                "description": "Show a drag manipulator (default false)",
            },
            "look": {
                "type": "boolean",
                "description": "Face the camera at the cut (default true)",
            },
        },
    },
}


def _active_view():
    import FreeCADGui

    view = FreeCADGui.activeView()
    return view if view is not None and hasattr(view, "toggleClippingPlane") else None


def _placement_for(plane):
    """An App.Placement describing `plane` (a Coin SbPlane) for FreeCAD.

    FreeCAD's clipping plane keeps the half its placement's +Z points AWAY from,
    and SbPlane keeps the half its normal points TOWARD, so the rotation maps
    +Z onto the plane's normal and the two conventions agree.
    """
    normal = plane.getNormal()
    distance = plane.getDistanceFromOrigin()
    n = FreeCAD.Vector(normal[0], normal[1], normal[2])
    return FreeCAD.Placement(
        FreeCAD.Vector(n.x * distance, n.y * distance, n.z * distance),
        FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), n),
    )


def _face_the_cut(view, normal):
    """Point the camera INTO the half that stays, so the cut is what you see.

    A clip keeps the side its normal points toward. Sitting on that side and
    looking further into it shows the kept half's intact outer surface: the
    model looks exactly as it did before, and the clip reads as if it did
    nothing. That is the usual first experience of this tool, and it is what
    happened the first time it was used.

    So the camera wants its view direction running WITH the normal -- on the
    removed side, looking into the opened cavity. Left alone when it already
    is, and reported either way, because a view that moves without being asked
    deserves a sentence.
    """
    try:
        d = view.getViewDirection()
        dot = d.x * normal[0] + d.y * normal[1] + d.z * normal[2]
    except Exception:  # noqa: BLE001 - cannot tell; leave the camera alone
        return False
    if dot > 0.35:
        return False  # already looking into the cut

    import math

    # Azimuth/elevation in the convention _orbit_rotation takes: azimuth 0
    # looks along +Y (front), elevation +90 looks straight down. The eye sits
    # opposite the direction we want to look in.
    nx, ny, nz = normal
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    nx, ny, nz = nx / length, ny / length, nz / length
    azimuth = math.degrees(math.atan2(-nx, ny))
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, -nz))))
    try:
        return bool(_apply_camera_orientation(view, _orbit_rotation(azimuth, elevation)))
    except Exception:  # noqa: BLE001
        return False


def _run_clip_view(args):
    doc = FreeCAD.ActiveDocument
    if doc is None:
        return "No active document."

    view = _active_view()
    if view is None:
        return ("The active tab isn't a 3D view -- click into the 3D view and "
                "try again.")

    if args.get("off"):
        if not view.hasClippingPlane():
            return "There was no clip plane on this view."
        view.toggleClippingPlane(0)
        return "Clip plane removed; the model is whole again."

    plane, desc, normal, err = _resolve_clip_plane(args, doc)
    if err:
        return err

    # Off first: toggling on over an existing plane leaves the old placement in
    # force and the new one silently ignored.
    if view.hasClippingPlane():
        view.toggleClippingPlane(0)

    try:
        view.toggleClippingPlane(
            1, False, not args.get("handle", False), _placement_for(plane))
    except Exception as exc:  # noqa: BLE001
        return f"Could not apply the clip plane to the view: {exc!r}"

    moved = _face_the_cut(view, normal) if args.get("look", True) else False

    return (
        f"Cut open in the user's view at {desc}."
        + (" Swung the camera round to face the cut." if moved else "")
        + (" Drag the handle to walk the cut through the model."
           if args.get("handle") else "")
        + " This is FreeCAD's own clipping plane, so View -> Clipping View "
        "shows it ticked and its offset slider moves it. It stays until removed "
        "(clip_view with 'off': true, or untick it there). The cut is hollow -- "
        "those are the interior surfaces it exposed, not a filled section -- "
        "and nothing was modelled, so the document is unchanged."
    )
