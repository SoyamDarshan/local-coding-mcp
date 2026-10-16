"""revert_task: restore a task's files from backups; remove only files it created."""

from __future__ import annotations

import json
from pathlib import Path

from ..settings.common import TaskError, check_task_id, err, sha
from ..settings.config import STATE_DIR
from ..fsio.atomic import write_bytes_atomic
from ..settings.safety import PathError, resolve_in_root


def _plan(root: Path, sdir: Path, task_id: str, m: dict, force: bool) -> tuple[list[str], list[str], list[str]]:
    """Decide per file: restore from backup, remove (task-created), or skip with a reason."""
    restore: list[str] = []
    remove: list[str] = []
    skipped: list[str] = []
    running = m.get("status") == "running"  # interrupted run: files are either original or ours, restore both
    for rel, info in m["files"].items():
        try:
            p = resolve_in_root(root, rel)
        except PathError:
            skipped.append(f"{rel}:unsafe")
            continue
        cur_sha = sha(p.read_bytes()) if p.exists() else None
        if cur_sha == info["orig_sha"]:
            continue  # already at starting state
        if cur_sha != info["post_sha"] and not (force or running):
            skipped.append(f"{rel}:changed-since-task")
        elif not info["existed"]:
            remove.append(rel)
        elif (sdir / f"{task_id}.orig" / rel).exists():
            restore.append(rel)
        else:
            skipped.append(f"{rel}:backup-missing")
    return restore, remove, skipped


def _execute(root: Path, sdir: Path, task_id: str, restore: list[str], remove: list[str]) -> None:
    for rel in restore:
        write_bytes_atomic(resolve_in_root(root, rel), (sdir / f"{task_id}.orig" / rel).read_bytes())
    for rel in remove:
        resolve_in_root(root, rel).unlink(missing_ok=True)  # only files this task created


def revert_task(root: Path, task_id: str, dry_run: bool = False, force: bool = False) -> dict:
    try:
        check_task_id(task_id)
    except TaskError as e:
        return err(str(e))
    sdir = root / STATE_DIR
    mpath = sdir / f"{task_id}.json"
    if not mpath.exists():
        return err(f"no recorded changes for task '{task_id}'")
    try:
        m = json.loads(mpath.read_text(encoding="utf-8"))
    except ValueError:
        return err("task manifest is corrupt")
    if m.get("reverted"):
        return {"status": "already_reverted", "task_id": task_id}
    restore, remove, skipped = _plan(root, sdir, task_id, m, force)
    if not dry_run:
        _execute(root, sdir, task_id, restore, remove)
        if not skipped:
            m["reverted"] = True
            write_bytes_atomic(mpath, json.dumps(m, indent=1).encode("utf-8"))
    status = "dry_run" if dry_run else ("reverted" if not skipped else "partial")
    out: dict = {"status": status, "restore": restore, "remove": remove}
    if skipped:
        out["skipped"] = skipped
    return out
