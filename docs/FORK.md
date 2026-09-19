# What this fork changes

Forked from [tinkerindustries/FreeCADClaude](https://github.com/tinkerindustries/FreeCADClaude)
on 2026-09-19. LGPL-2.1-or-later, same as upstream, with upstream's notices
intact. Changes below; everything else is upstream's work.

## Project mode

Upstream's contract: the live FreeCAD document is the source, and `run_python`
is the only thing that changes it. Right answer for a model built in the GUI.

Wrong answer for a repo whose Python scripts build the geometry — `cad-lab` is
one. There, `out/*.step` is output. Edit the document by hand and the change
disappears at the next build, silently, with nothing in `git diff` to show it
ever happened.

Rather than swap one rule for the other, it is a mode. Set the `ProjectDir`
preference under
`User parameter:BaseApp/Preferences/Mod/FreeCADClaude` to a checkout:

| | `ProjectDir` unset | `ProjectDir` set |
|---|---|---|
| Source of truth | the document | the project's scripts |
| Geometry changes via | `run_python` | `Edit` the script, then `reload_parts` |
| `run_python` | mutates | measures only |
| Shell | none | `Bash` |
| CLI cwd | the session folder | the project |
| System prompt | `system_prompt.md` | that, plus `project_prompt.md` |

Unset is upstream's behaviour, untouched.

## Bash

On in project mode only. A code-CAD loop is impossible without it: the part
script has to be run before its output exists. Off without a project, where
there is nothing for it to build.

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

- The addon's bundled skills are copied into the session folder, and the CLI
  discovers skills from its cwd. In project mode cwd is the project, so they
  load only if the project has its own `.claude/skills`.
- `ProjectDir` has no UI. Set it in **Tools → Edit parameters**.
- Nothing stops `run_python` editing geometry in project mode. The prompt says
  not to; it is not enforced.

## Running the tests

```bash
PYTHONPATH=/usr/lib/freecad/lib python3 eval/test_project_tools.py
for t in eval/test_*.py; do PYTHONPATH=/usr/lib/freecad/lib python3 "$t"; done
```

15 files, all passing as of 2026-09-19. Four of them need `FreeCAD` importable,
which is what the `PYTHONPATH` is for on Arch.
