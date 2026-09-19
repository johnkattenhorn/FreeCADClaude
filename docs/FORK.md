# What this fork changes

Forked from [tinkerindustries/FreeCADClaude](https://github.com/tinkerindustries/FreeCADClaude)
on 2026-09-19. LGPL-2.1-or-later, same as upstream, with upstream's notices
intact. Changes below; everything else is upstream's work.

## One mode, and it works out which kind of drawing this is

Upstream's contract: the live FreeCAD document is the source, and `run_python`
is the only thing that changes it. Right for a model built in the GUI.

Wrong for a document a script produced, where `out/*.step` is output. Edit it by
hand and the change disappears at the next build, silently, with nothing in
`git diff` to show it happened.

The first attempt at this was a `ProjectDir` preference selecting a mode. That
was the wrong shape: which kind of drawing is open is a **fact about the
drawing**, not a setting, and one global value could only ever be right for one
document at a time.

So there is no mode. `reload_parts` records the file every object was built
from in an `FCCSourceFile` property, and `agent_config.source_files` reads it
back:

| the open document | what it means |
|---|---|
| no `FCCSourceFile` on its objects | somebody drew it. `run_python` changes it, save it as a `.FCStd` |
| objects carry `FCCSourceFile` | a script built it. Geometry changes go in the script, then `reload_parts` |

`project_root` walks up from the source file to the enclosing git working tree,
which is passed to the CLI with `--add-dir`.

"Give me a script that rebuilds this" is a request, not a setting. The agent
writes the script, runs it and reloads the result; from then on the objects
carry their source and the document is a built one.

## `Bash`

Always on. A drawing built by a script needs its script run, and making a
hand-drawn one reproducible needs the same.

Upstream left it off on the grounds that `run_python` was the only path to the
document. That reasoning does not survive its own code comment: `run_python` is
arbitrary Python inside the FreeCAD process, so it already reaches the
filesystem. A shell adds convenience, not reach.

The CLI's cwd is the session folder, not the project. The bundled skills are
copied there and the CLI discovers skills from its cwd, so running in the
project is what made `/help` advertise three skills that could not load.

## `reload_parts`

`freecad_tools/tools_project.py`. Imports the files a build produced, replacing
what a previous reload of the same paths left, keeping the camera.

It does **not** build anything. The agent runs the build itself with `Bash`,
which is where a traceback belongs — in the turn, streamed, next to the code
that caused it. That split keeps seconds of build off the GUI thread, and means
the tool does not care whether the project builds with a venv, make, or a shell
script.

Re-import is keyed on the **source path**, recorded on each imported object in
a hidden `FCCSourceFile` property. Not on names: an import can produce several
objects and FreeCAD renames on collision, so a name-keyed reload of `cap.step`
leaves the first import behind as `cap001` and the document fills with stale
geometry that still looks plausible. `eval/test_project_tools.py` reloads twice
in every test for that reason, and the keying was mutation-checked to confirm
the tests bite.

## Known gaps

- Nothing stops `run_python` editing the geometry of a document a script built.
  The prompt says not to; it is not enforced.
- The project root is detected from the FIRST source file when a document holds
  parts from more than one checkout. Rare, and it picks one rather than failing.
- A document built before this addon tagged its imports carries no
  `FCCSourceFile`, so it reads as hand-drawn until something is reloaded into
  it.

## Running the tests

```bash
PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_project_tools.py
for t in eval/test_*.py; do PYTHONPATH=/usr/lib/freecad/lib python3 "$t"; done
```

15 files, all passing as of 2026-09-19. Four of them need `FreeCAD` importable,
which is what the `PYTHONPATH` is for on Arch.
