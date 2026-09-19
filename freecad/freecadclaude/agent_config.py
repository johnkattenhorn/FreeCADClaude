# SPDX-License-Identifier: LGPL-2.1-or-later
"""Configuration for the Claude chat session.

Auth is handled by the ``claude`` CLI (the user's own account). This module
also assembles the ``--mcp-config`` that points the CLI at our MCP server
(mcp_server.py), which relays tool calls back to the FreeCAD bridge.
"""

import json
import os
import sys

import FreeCAD

from .freecad_tools import PARAM_PATH, REFS_REL

DEFAULT_MODEL = "claude-opus-5"

#: (label, model-id) pairs offered by the chat panel's model selector. The label
#: is what the user sees in the dropdown; the id is passed to the CLI's --model.
MODELS = (
    ("Opus", "claude-opus-5"),
    ("Sonnet", "claude-sonnet-5"),
)
_VALID_MODELS = {mid for _, mid in MODELS}

#: Reasoning effort passed to the CLI as --effort. Pinning it stops the addon
#: inheriting your global Claude Code effortLevel (which can be xhigh/max and
#: makes turns think for a long time). Chosen in the chat panel's effort
#: selector, same (label, id) shape as MODELS.
DEFAULT_EFFORT = "medium"
EFFORTS = (
    ("Low", "low"),
    ("Medium", "medium"),
    ("High", "high"),
    ("X-High", "xhigh"),
    ("Max", "max"),
)
_VALID_EFFORT = {eid for _, eid in EFFORTS}

#: The system prompt lives in system_prompt.md alongside this module so it's
#: easy to read/edit as plain text; loaded once at import time. Its {REFS_DIR}
#: placeholder becomes the references folder as the CLI sees it -- relative to
#: its cwd, which is the session folder the references are copied into. Relative
#: is what makes one substitution good for every conversation: the prompt is
#: built once per worker while the session folder changes on "New". Taken from
#: freecad_tools rather than spelt again here so the paths the prompt cites and
#: the ones the tools' just-in-time notes cite can't drift apart.
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_SYSTEM_PROMPT_PATH = os.path.join(_MODULE_DIR, "system_prompt.md")
with open(_SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as _f:
    SYSTEM_PROMPT = _f.read().strip().replace("{REFS_DIR}", REFS_REL)

#: Always appended to SYSTEM_PROMPT. Kept in its own file because it qualifies
#: the base prompt rather than extending it: the base prompt says run_python is
#: how you change the model, and for a document a script built, that is exactly
#: what must not happen.
_PROJECT_PROMPT_PATH = os.path.join(_MODULE_DIR, "project_prompt.md")
with open(_PROJECT_PROMPT_PATH, "r", encoding="utf-8") as _f:
    PROJECT_PROMPT = _f.read().strip()

#: Addon root = three levels up from this file (.../FreeCADClaude/freecad/freecadclaude).
_ADDON_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

#: A project directory whose .claude/skills hold FreeCAD skills (e.g. the
#: bundled freecad-design-advisor planning skill under this addon's .claude/skills).
#: When set, the CLI runs with this as its cwd so the project skills are
#: discovered, and the Skill + read tools are enabled. Defaults to the addon root
#: so the bundled skills work out of the box; override via the "SkillsProjectDir"
#: preference (e.g. point at an external project), or clear it to disable.
DEFAULT_SKILLS_DIR = _ADDON_ROOT

#: Task/todo tracking tools (always enabled) so the agent can plan and track
#: multi-step modeling work. "Task" is the subagent launcher (the CLI also
#: accepts "Agent" as an alias for it, and reports its use under that name);
#: the rest are the todo-list family. These have no system side effects.
#: TaskOutput is deprecated by the CLI in favour of reading the task's output
#: file with Read, so it is not enabled.
_TASK_TOOLS = [
    "Task",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskStop",
    "TaskUpdate",
]

#: Read is always on so the agent can open the SVG file produced by
#: view_sketch_svg (returned as a path, not inline -- it's text, not an
#: image) and skill reference files. capture_view returns its PNG inline, so
#: it doesn't need Read. Read-only.
_READ_TOOLS = ["Read"]

#: File-authoring tools, always on (like Read): Write creates or replaces a
#: file, Edit does an in-place string replacement in one -- e.g. iterating on
#: freecad-lofi-sketch's concept SVGs without rewriting them whole. Both run
#: inside the claude CLI process itself (not the MCP bridge/GUI thread) and
#: reach the filesystem but never the live FreeCAD document. Bash stays OFF;
#: run_python remains the only path that mutates the document.
_WRITE_TOOLS = ["Write", "Edit"]

#: File-search tools, always on so Claude can look for files on disk (find by
#: name with Glob, search contents with Grep) -- e.g. locate a STEP to import or
#: a previous export. Read-only, like Read: they discover paths but never mutate.
#: Bash stays OFF -- the only mutation path to the live document is the
#: run_python tool.
_SEARCH_TOOLS = ["Glob", "Grep"]

#: Extra built-in tool enabled only when a skills project is configured: Skill
#: loads the bundled skills (Glob/Grep it may need are already always-on above).
_SKILL_TOOLS = ["Skill"]

#: The CLI's Windows shell tool, for the odd job Python is clumsy at (invoking a
#: slicer CLI, unzipping a STEP archive). Windows-only: the name does not
#: resolve on macOS and needs a separate opt-in on Linux, and the CLI drops an
#: unrecognised --tools name silently rather than erroring, so offering it
#: elsewhere would be a no-op that reads as a live capability.
#:
#: It grants no reach run_python lacks -- that is already arbitrary Python in
#: the FreeCAD process -- and runs in the CLI subprocess, so unlike run_python
#: it cannot block the GUI thread. Bash stays off: one shell is enough, and
#: this is the one that matches the deploy target.
_SHELL_TOOLS = ["PowerShell"] if sys.platform == "win32" else []

#: Always on. A drawing built by a script needs its script RUN before the
#: result exists, and asking for a reproducible script for a drawing built by
#: hand is a normal request -- neither works without a shell.
#:
#: Upstream left it off, on the grounds that run_python was the only path to
#: the document. That reasoning does not survive its own code comment: run_python
#: is arbitrary Python inside the FreeCAD process, so it already reaches the
#: filesystem. A shell adds convenience here, not reach.
_SHELL = ["Bash"]


def get_model():
    params = FreeCAD.ParamGet(PARAM_PATH)
    model = params.GetString("Model", DEFAULT_MODEL) or DEFAULT_MODEL
    return model if model in _VALID_MODELS else DEFAULT_MODEL


def save_model(model_id):
    """Persist the selected model so it's remembered across restarts and picked
    up by build_config()/get_model() the next time a worker is created."""
    FreeCAD.ParamGet(PARAM_PATH).SetString("Model", model_id)


def get_effort():
    """Reasoning effort (low/medium/high/xhigh/max). Pinned so it doesn't
    inherit the user's global Claude Code effortLevel."""
    params = FreeCAD.ParamGet(PARAM_PATH)
    effort = (
        (params.GetString("Effort", DEFAULT_EFFORT) or DEFAULT_EFFORT).strip().lower()
    )
    return effort if effort in _VALID_EFFORT else DEFAULT_EFFORT


def save_effort(effort):
    """Persist the selected effort so it's remembered across restarts and picked
    up by build_config()/get_effort() the next time a worker is created."""
    FreeCAD.ParamGet(PARAM_PATH).SetString("Effort", effort)


def get_skills_dir():
    """Return the configured skills project dir if it has .claude/skills, else None."""
    params = FreeCAD.ParamGet(PARAM_PATH)
    path = (
        params.GetString("SkillsProjectDir", DEFAULT_SKILLS_DIR) or DEFAULT_SKILLS_DIR
    )
    if path and os.path.isdir(os.path.join(path, ".claude", "skills")):
        return path
    return None


#: The tools that render a picture for the agent to look at. Every one of them
#: goes through render._offscreen_shot.
#:
#: They are the AGENT's eyes, not the user's -- the user is already looking at
#: the screen. When the work is "change this face", measuring it with
#: run_python and acting on it is the whole job, and a screenshot is a round
#: trip that tells the user nothing they cannot see.
#:
#: capture_user_view is deliberately NOT in here: it grabs the view the user is
#: already looking at, which is what "look at this" means, and it renders
#: nothing of its own.
_SCREENSHOT_TOOLS = (
    "capture_view",
    "cutaway",
    "crop_view",
    "view_model_3d",
    "read_model_markup",
)


def screenshots_enabled():
    """Whether the agent may render pictures for itself.

    On by default, as upstream has it. Set the "Screenshots" preference to
    false for a panel that works numerically -- describe_objects, get_sketch,
    get_selection and run_python measurements -- and leaves looking to the
    person with the window open.
    """
    return FreeCAD.ParamGet(PARAM_PATH).GetBool("Screenshots", True)


#: Property reload_parts writes on every object it imports, naming the file the
#: object was built from. Spelled here as well as in tools_project so this
#: module does not import it and create a cycle.
SOURCE_PROP = "FCCSourceFile"


def source_files(document):
    """Absolute paths the open document's objects were BUILT from.

    Empty for a document somebody drew, which is the ordinary case. Non-empty
    means the geometry on screen is output: a script produced that file, and a
    change made to the document by hand disappears the next time it runs.

    This replaces a ProjectDir preference. Which kind of drawing is open is a
    fact about the drawing, not a setting, and a global preference could only
    ever be right for one document at a time.
    """
    paths = set()
    for obj in getattr(document, "Objects", None) or ():
        source = (getattr(obj, SOURCE_PROP, "") or "").strip()
        if source:
            paths.add(os.path.abspath(source))
    return sorted(paths)


def project_root(document):
    """The checkout a built document came from, or None.

    The git working tree containing its source files, because that is the unit
    the build script, its tests and its history live in. Without a repository it
    is the source file's own folder, which at least makes the script reachable.
    """
    sources = source_files(document)
    if not sources:
        return None
    folder = os.path.dirname(sources[0])
    probe = folder
    while True:
        if os.path.isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return folder
        probe = parent


def session_workspace():
    """The CLI's cwd: this conversation's session folder, with the skills and the
    scripting references copied into it.

    The session folder rather than the addon root, so the CLI's project context
    is the conversation's own artifacts (captures, exports, scripts) and not this
    repo's source. Call it again after "New" -- a fresh conversation means a
    fresh folder, and the copies are remade from the originals.
    """
    from . import freecad_tools

    return freecad_tools.prepare_session_workspace(get_skills_dir())


def _python_exe():
    """Path to FreeCAD's bundled Python (used to run the stdlib-only MCP server)."""
    home = FreeCAD.getHomePath()
    for name in ("python.exe", "python3", "python"):
        cand = os.path.join(home, "bin", name)
        if os.path.isfile(cand):
            return cand
    return "python"  # last resort: rely on PATH


def build_config(cli_path, bridge_port, bridge_token):
    """Bundle everything the worker needs, including the MCP wiring."""
    from . import freecad_tools

    mcp_config = json.dumps(
        {
            "mcpServers": {
                "freecad": {
                    "command": _python_exe(),
                    "args": [os.path.join(_ADDON_ROOT, "mcp_server.py")],
                    "env": {
                        "FREECAD_BRIDGE_PORT": str(bridge_port),
                        "FREECAD_BRIDGE_TOKEN": bridge_token,
                    },
                }
            }
        }
    )
    tool_names = list(freecad_tools.TOOLS)
    if not screenshots_enabled():
        tool_names = [n for n in tool_names if n not in _SCREENSHOT_TOOLS]
    allowed_tools = ["mcp__freecad__" + name for name in tool_names]

    skills_dir = get_skills_dir()
    builtin_tools = (
        list(_TASK_TOOLS)  # always available
        + list(_READ_TOOLS)
        + list(_WRITE_TOOLS)
        + list(_SEARCH_TOOLS)
        + list(_SHELL_TOOLS)  # Windows only; empty elsewhere
        + list(_SHELL)
    )
    if skills_dir:
        builtin_tools += _SKILL_TOOLS
    allowed_tools += builtin_tools
    # The subagent launcher is enabled via "Task" but the CLI reports its use as
    # "Agent"; allow that name too so subagents (e.g. the Plan agent) run without
    # a permission prompt in -p mode.
    allowed_tools.append("Agent")

    # cwd is always the session folder. The bundled skills are copied there and
    # the CLI discovers skills from its cwd, so this is what keeps them
    # reachable -- running in the project instead is what made /help advertise
    # three skills that could not load.
    #
    # A document built by a script brings its checkout along as an extra
    # directory, so the script, its tests and its history are all readable and
    # writable. The agent is told where it is; it cd's there when it needs to.
    cwd = session_workspace()
    extra_dirs = []
    root = project_root(FreeCAD.ActiveDocument)
    if root:
        extra_dirs.append(root)
    system = SYSTEM_PROMPT + "\n\n" + PROJECT_PROMPT

    return {
        "cli_path": cli_path,
        "model": get_model(),
        "effort": get_effort(),
        "system": system,
        "project_dir": root,
        "extra_dirs": extra_dirs,
        "mcp_config": mcp_config,
        "allowed_tools": allowed_tools,
        "builtin_tools": builtin_tools,
        "cwd": cwd,  # the project in project mode, else the session folder
        # The active chat conversation's log folder -- see freecad_tools.new_session_id.
        # Must be minted (freecad_tools.new_session_id()) before this call.
        "log_dir": freecad_tools.session_dir(),
    }
