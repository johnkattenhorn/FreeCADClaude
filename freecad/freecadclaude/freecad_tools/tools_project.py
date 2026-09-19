# SPDX-License-Identifier: LGPL-2.1-or-later
"""reload_parts -- bring a code-CAD build's output back into the view.

Project mode's other half. The agent edits the part script and runs the build
itself with Bash, which is where a traceback belongs: in the turn, streamed,
next to the code that caused it. This tool does only the part that has to
happen inside FreeCAD -- drop what the last build left, import what this one
made, and leave the camera where the user had it.

Splitting it that way keeps the build off the GUI thread. A build123d part with
a headless render takes seconds, and seconds of a frozen window each iteration
is how a loop stops being worth using. It also means the tool doesn't care what
the build command is: a venv, make, uv run, a shell script. It only handles
files that already exist.

Re-import is keyed on the SOURCE PATH, recorded on each imported object in a
hidden property. Name-matching would be wrong twice over: an import can produce
several objects, and FreeCAD renames on collision, so the second reload of
"cap.step" leaves "cap001" behind and the view slowly fills with corpses.
"""

import os

import FreeCAD

#: Set on every object this tool imports, holding the absolute source path.
#: Hidden, so it doesn't clutter the property editor, and it survives a save --
#: which is what lets a reload after a restart still find the last import.
_SOURCE_PROP = "FCCSourceFile"

_SUPPORTED = (".step", ".stp", ".brep", ".brp", ".iges", ".igs", ".stl", ".obj")

_RELOAD_PARTS_SCHEMA = {
    "name": "reload_parts",
    "description": (
        "Project mode. Import the files a build just produced, replacing what a "
        "previous reload of the SAME paths put in the document, and keep the "
        "camera where it is. Use it after you have edited a part script and run "
        "the project's build yourself with Bash -- this tool does not build "
        "anything, it only imports files that already exist. Pass 'paths': a "
        "list of STEP/BREP/IGES/STL files, absolute or relative to the project "
        "directory. Returns, per file, what it replaced and the imported solid's "
        "bounding box and volume, so you can check the geometry changed the way "
        "you intended without a screenshot. Set 'fit' to true only when the part "
        "has moved or resized enough to leave the view -- the default keeps the "
        "camera, because the user is usually looking at the exact feature they "
        "asked you to change."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to import, e.g. ['out/bath_overflow_cap.step']",
            },
            "fit": {
                "type": "boolean",
                "description": "View-fit after importing (default false: keep the camera)",
            },
        },
        "required": ["paths"],
    },
}


def _project_dir():
    """The configured project, or None. Imported lazily: agent_config imports
    this package, so a module-level import here would be circular."""
    from .. import agent_config

    return agent_config.get_project_dir()


def _resolve(raw, project):
    """Absolute path for a tool argument, relative paths taken against the project."""
    path = os.path.expanduser(str(raw).strip())
    if not os.path.isabs(path):
        if not project:
            return None, "no project directory is set, so a relative path has nothing to resolve against"
        path = os.path.join(project, path)
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        return None, "no such file"
    if os.path.splitext(path)[1].lower() not in _SUPPORTED:
        return None, "not an importable geometry file (%s)" % ", ".join(_SUPPORTED)
    return path, None


def _tag(obj, path):
    """Record where an object came from, so the next reload can find it."""
    if not hasattr(obj, _SOURCE_PROP):
        try:
            obj.addProperty("App::PropertyString", _SOURCE_PROP, "FreeCADClaude",
                            "Source file this object was imported from")
            obj.setEditorMode(_SOURCE_PROP, 2)  # hidden
        except Exception:  # noqa: BLE001 - a type that refuses properties still imports fine
            return
    setattr(obj, _SOURCE_PROP, path)


def _previous(doc, path):
    """Objects a previous reload imported from `path`."""
    return [o for o in doc.Objects if getattr(o, _SOURCE_PROP, None) == path]


def _drop_selection(doc, objs):
    """Deselect `objs` before they are removed.

    A reload replaces the very geometry the user is most likely to have clicked
    on -- "change this face" ends with that face's object being deleted. Gui
    selection is not a document property and is not cleaned up by removeObject,
    so it is left holding a reference to an object that has gone. Nothing
    complains at the time; the next thing to walk the selection does, from
    inside C++, as a segfault with no Python traceback.

    Scoped to the objects actually going, so a selection elsewhere in the
    document survives a reload.
    """
    if not objs:
        return
    try:
        import FreeCADGui
    except ImportError:  # console FreeCAD (the eval suite): no selection to hold
        return
    names = {o.Name for o in objs}
    try:
        for sel in list(FreeCADGui.Selection.getSelectionEx(doc.Name)):
            if getattr(sel, "ObjectName", None) in names:
                FreeCADGui.Selection.removeSelection(doc.Name, sel.ObjectName)
    except Exception:  # noqa: BLE001 - clearing the lot beats leaving it dangling
        try:
            FreeCADGui.Selection.clearSelection(doc.Name)
        except Exception:  # noqa: BLE001
            pass


def _measure(objs):
    """Bounding box and volume across the imported objects, or None if shapeless."""
    shapes = [o.Shape for o in objs if getattr(o, "Shape", None) and not o.Shape.isNull()]
    if not shapes:
        return None
    bb = shapes[0].BoundBox
    for s in shapes[1:]:
        bb.add(s.BoundBox)
    volume = sum(s.Volume for s in shapes)
    return "%.2f x %.2f x %.2f mm, %.2f cm3" % (
        bb.XLength, bb.YLength, bb.ZLength, volume / 1000.0)


def _insert(path, doc_name):
    """Import a file, preferring the Gui importer for the colours it carries.

    ImportGui refuses to load in a console FreeCAD ("Cannot load Gui module in
    console application"), which is exactly how the eval suite runs, so fall
    back to the headless importer rather than making this tool untestable.
    """
    try:
        import ImportGui

        ImportGui.insert(path, doc_name)
        return
    except ImportError:
        pass
    if os.path.splitext(path)[1].lower() in (".stl", ".obj"):
        import Mesh

        Mesh.insert(path, doc_name)
    else:
        import Import

        Import.insert(path, doc_name)


def _run_reload_parts(args):
    paths = args.get("paths")
    if isinstance(paths, str):
        paths = [paths]
    if not paths:
        return "Pass 'paths': a list of files the build produced, e.g. ['out/part.step']."

    project = _project_dir()
    doc = FreeCAD.ActiveDocument
    if doc is None:
        doc = FreeCAD.newDocument("Project")

    # Hold the camera across the whole call. Import replaces objects, and
    # FreeCAD will happily re-frame the view underneath the user while it does.
    view = None
    camera = None
    try:
        import FreeCADGui as Gui

        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        camera = view.getCamera() if view else None
    except Exception:  # noqa: BLE001 - no GUI view (eval harness); nothing to preserve
        pass

    lines = []
    for raw in paths:
        path, problem = _resolve(raw, project)
        if problem:
            lines.append("%s: %s" % (raw, problem))
            continue

        stale = _previous(doc, path)
        _drop_selection(doc, stale)
        for obj in stale:
            try:
                doc.removeObject(obj.Name)
            except Exception:  # noqa: BLE001 - already gone with its parent
                pass

        before = set(o.Name for o in doc.Objects)
        try:
            _insert(path, doc.Name)
        except Exception as exc:  # noqa: BLE001 - a malformed export is the user's answer, not a crash
            lines.append("%s: import failed -- %r" % (raw, exc))
            continue

        fresh = [o for o in doc.Objects if o.Name not in before]
        for obj in fresh:
            _tag(obj, path)

        measured = _measure(fresh)
        lines.append("%s: %d object%s imported%s%s" % (
            os.path.relpath(path, project) if project else path,
            len(fresh), "" if len(fresh) == 1 else "s",
            ", replaced %d" % len(stale) if stale else "",
            "  (%s)" % measured if measured else ""))

    doc.recompute()

    if view is not None:
        if args.get("fit"):
            try:
                view.fitAll()
            except Exception:  # noqa: BLE001
                pass
        elif camera:
            try:
                view.setCamera(camera)
            except Exception:  # noqa: BLE001
                pass

    return "\n".join(lines) if lines else "Nothing to import."


def _precheck_reload_parts(args):
    """Refuse outside project mode, where there is no build to reload."""
    if _project_dir() is None:
        return ("reload_parts is project mode only, and no project directory is "
                "set. In this conversation the document is the source, so there "
                "is no build output to bring back -- use run_python.")
    return None
