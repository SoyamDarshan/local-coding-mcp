"""Public orchestration entry points: implement_task and run_checks (revert lives in history/revert.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .gates import checks as checks_mod
from .vcs import gitutil
from .settings.common import (  # noqa: F401  (re-exported for callers and tests)
    TASK_ID_RE, TaskError, TaskLog, check_task_id, err, est_tokens, make_key_resolver,
    resolve_targets, sha, state_dir, to_json,
)
from .settings.config import STATE_DIR, ConfigError, load_config
from .tasks.loop import EXCERPT_CHARS, EXCERPT_LINES, ChatFn, TaskRunner
from .history.manifest import Ctx, clear_task_artifacts, task_scope
from .tasks.ollama import chat as ollama_chat
from .tasks.preflight import prepare, select_checks
from .history.revert import revert_task  # noqa: F401
from .settings.safety import PathError, glob_match


def implement_task(
    root: Path,
    task_id: str,
    spec: str,
    files_to_edit: list[str],
    context_files: list[str] | None = None,
    check_names: list[str] | None = None,
    symbols: list[str] | None = None,
    chat_fn: ChatFn = ollama_chat,
    check_runner: Callable[..., checks_mod.CheckResult] = checks_mod.run_check,
) -> dict:
    try:
        prep = prepare(root, task_id, spec, files_to_edit, context_files, check_names, symbols)
    except (TaskError, PathError, ConfigError) as e:
        return err(str(e))
    clear_task_artifacts(prep.sdir, task_id)
    log = TaskLog(prep.sdir / f"{task_id}.log")
    c = Ctx(root, prep.cfg, task_id, prep.sdir, log, prep.start_sha, {}, dict(prep.targets))
    c.summary = " ".join(spec.split())[:60]
    log.write(
        "START",
        f"task={task_id} start_sha={prep.start_sha}\nfiles={list(prep.targets)}\n"
        f"context={list(prep.context)}\nspec:\n{spec}",
    )
    return TaskRunner(c, prep, spec, chat_fn, check_runner).run()


# --------------------------------------------------------------------------- run_checks


def run_checks(root: Path, names: list[str] | None = None, task_id: str | None = None) -> dict:
    """Run checks. File-scoped checks see the files of task_id, or of all open tasks + dirty files."""
    try:
        cfg = load_config(root)
        selected = select_checks(cfg, names)
        if task_id is not None:
            check_task_id(task_id)
    except (ConfigError, TaskError) as e:
        return err(str(e))
    if not selected:
        return err("no checks configured in .localexec.json")
    files, bl = task_scope(root, task_id, extra=gitutil_dirty(root) if task_id is None else ())
    if task_id is not None and not files and not (root / STATE_DIR / f"{task_id}.json").exists():
        return err(f"no recorded task '{task_id}'")
    sdir = state_dir(root)
    log_lines: list[str] = []
    results = []
    first_fail = None
    warnings: list[str] = []
    for ch in selected:
        r = checks_mod.run_check(ch, root, files=files, baselines=bl, std=cfg.standards)
        log_lines.append(f"===== {ch.name} rc={r.returncode} {r.seconds:.1f}s =====\n{r.output}\n")
        results.append({"name": ch.name, "ok": r.ok, **({"skipped": True} if r.skipped else {}), "secs": round(r.seconds, 1)})
        warnings.extend(w for w in r.warnings if w not in warnings)
        if not r.ok and first_fail is None:
            first_fail = r
    (sdir / "run_checks.log").write_text("\n".join(log_lines), encoding="utf-8")
    out: dict = {"status": "passed" if first_fail is None else "failed", "results": results, "log": f"{STATE_DIR}/run_checks.log"}
    if warnings:
        out["warnings"] = [w[:160] for w in warnings[:5]]
    if first_fail is not None:
        out["failed_check"] = first_fail.name
        out["output"] = checks_mod.excerpt(first_fail.output, EXCERPT_LINES, EXCERPT_CHARS)
    return out


def gitutil_dirty(root: Path) -> list[str]:
    try:
        return [p for p in gitutil.dirty_paths(root) if not glob_match(p, [STATE_DIR + "/**"])]
    except gitutil.GitError:
        return []
