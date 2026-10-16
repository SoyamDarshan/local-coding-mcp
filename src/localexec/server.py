"""MCP stdio server. NEVER print to stdout here: stdout carries the MCP protocol."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[assignment]

from . import core
from .vcs import gitutil
from .history import taskinfo
from .tasks.status import status as status_impl
from .explore.find import find as find_impl
from .explore.outline import outline as outline_impl
from .settings.config import CONFIG_NAME, STATE_DIR

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="localexec %(levelname)s %(message)s")
log = logging.getLogger("localexec")

mcp = _Server(
    "localexec",
    instructions=(
        "Delegates code implementation to a local Ollama model. Call implement_task once per small "
        "step (1-2 files). Results are compact; read the .patch/.log files only on failure."
    ),
)


class RootError(Exception):
    """The project root cannot be determined safely."""


# Tasks and checks change files, so they run one at a time. Read-only tools do not take the lock.
_WRITE_LOCK = threading.Lock()


def project_root() -> Path:
    """LOCALEXEC_ROOT if set, else the git top-level of the working directory, else a directory that has
    a .localexec.json. Never silently fall back to an arbitrary working directory (e.g. System32)."""
    env = os.environ.get("LOCALEXEC_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if not root.is_dir():
            raise RootError(f"LOCALEXEC_ROOT is not a directory: {root}")
        return root
    cwd = Path.cwd().resolve()
    top = gitutil.toplevel(cwd)
    if top is not None:
        return top
    if (cwd / CONFIG_NAME).exists():
        return cwd
    raise RootError("cannot find the project: set LOCALEXEC_ROOT or start the server inside a git repository")


async def _call(name: str, fn: Callable[..., object], *args: object, write: bool = False) -> str:
    """Run `fn(root, *args)` in a worker thread; always return a short string, never a traceback."""

    def work() -> object:
        root = project_root()  # may run git, so it stays off the event loop
        if not write:
            return fn(root, *args)
        with _WRITE_LOCK:
            return fn(root, *args)

    try:
        res = await asyncio.to_thread(work)
    except RootError as e:
        res = core.err(str(e))
    except Exception as e:  # never leak a traceback into the context
        log.exception("%s crashed", name)
        res = core.err(f"internal error: {type(e).__name__}: {e}")
    return res if isinstance(res, str) else core.to_json(res)  # type: ignore[arg-type]


@mcp.tool(structured_output=False)
async def implement_task(
    task_id: str,
    spec: str,
    files_to_edit: list[str],
    context_files: list[str] | None = None,
    checks: list[str] | None = None,
    symbols: list[str] | None = None,
) -> str:
    """Have the local model implement ONE small step and run the project's checks.

    task_id: unique id, e.g. "T1-add-retry". spec: precise instructions (signatures, edge cases,
    acceptance). files_to_edit: 1-2 project-relative paths (may be new files). context_files:
    read-only files for reference. checks: names from .localexec.json (default: all).
    symbols: ["path::name", ...] (e.g. "src/a.py::Calc.add") to show the local model only those
    functions/classes plus nearby lines; use it for files too large to send whole (see outline).
    Returns compact JSON; full diff/logs are in .localexec/<task_id>.patch/.log. Does not commit.
    """
    return await _call(
        "implement_task", core.implement_task, task_id, spec, files_to_edit, context_files, checks, symbols,
        write=True,
    )


@mcp.tool(structured_output=False)
async def run_checks(names: list[str] | None = None, task_id: str | None = None) -> str:
    """Run configured checks (default all) and return a compact pass/fail summary.

    File-scoped checks ({files}/files_filter) run on task_id's files, or on all open tasks' files
    plus uncommitted changes when task_id is omitted. Add a check without {files} for full runs."""
    return await _call("run_checks", core.run_checks, names, task_id, write=True)


@mcp.tool(structured_output=False)
async def revert_task(task_id: str, dry_run: bool = False, force: bool = False) -> str:
    """Undo a task: restore files it changed to their starting content and remove files it created.

    dry_run=true only reports what would happen. Files edited since the task are skipped unless
    force=true.
    """
    return await _call("revert_task", core.revert_task, task_id, dry_run, force, write=True)


@mcp.tool(structured_output=False)
async def list_tasks(limit: int = 20) -> str:
    """List recent tasks, one short line each: id|status|attempts|files|spec. Use after context loss."""
    return await _call("list_tasks", taskinfo.list_tasks, limit)


@mcp.tool(structured_output=False)
async def show_patch(task_id: str, file: str | None = None, max_lines: int = 60) -> str:
    """Skim a task's diff (changed lines + 1 line context, capped). Use to review passed tasks cheaply."""
    return await _call("show_patch", taskinfo.show_patch, task_id, file, max_lines)


@mcp.tool(structured_output=False)
async def status() -> str:
    """Health check: Ollama reachable, model installed/loaded, config valid, configured checks."""
    return await _call("status", status_impl)


@mcp.tool(structured_output=False)
async def outline(path: str, max_items: int = 60) -> str:
    """Symbols of one file (functions, classes, methods, consts) with line ranges and signatures.

    Python, TypeScript/TSX and JavaScript. Use it instead of reading a whole file when planning."""
    return await _call("outline", outline_impl, path, max_items)


@mcp.tool(structured_output=False)
async def find(pattern: str, glob: str | None = None, max_results: int = 30, ignore_case: bool = False) -> str:
    """Regex search over project files (ignored paths skipped). Returns path:line:text, capped.

    Use it to look for an existing helper before asking for a new one. glob example: "src/**/*.py"."""
    return await _call("find", find_impl, pattern, glob, max_results, ignore_case)


def main() -> None:
    log.info("starting; state dir name=%s", STATE_DIR)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
