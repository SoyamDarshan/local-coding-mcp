"""Per-task state: manifest, backups, patch/diff and the final compact result."""

from __future__ import annotations

import difflib
import json
import time
from collections.abc import Iterable
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..settings.common import TaskLog, sha, to_json
from ..vcs import gitutil
from ..settings.config import STATE_DIR, Config
from ..fsio.atomic import write_bytes_atomic
from ..fsio.text import normalize_bytes, split_keepends

def known_task_files(root: Path) -> set[str]:
    """Files changed by earlier, non-reverted tasks and untouched since (so not 'unrelated')."""
    known: set[str] = set()
    for m in (root / STATE_DIR).glob("*.json"):
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("reverted"):
            continue
        for rel, info in data.get("files", {}).items():
            p = root / rel
            cur = sha(p.read_bytes()) if p.exists() else None
            if cur == info.get("post_sha"):
                known.add(rel)
    return known



def make_diff(rel: str, before: str | None, after: str | None) -> tuple[str, int, int]:
    a = split_keepends(before or "")
    b = split_keepends(after or "")
    d = list(
        difflib.unified_diff(
            a, b,
            fromfile="/dev/null" if before is None else f"a/{rel}",
            tofile="/dev/null" if after is None else f"b/{rel}",
        )
    )
    add = sum(1 for x in d if x.startswith("+") and not x.startswith("+++"))
    dele = sum(1 for x in d if x.startswith("-") and not x.startswith("---"))
    text = "".join(x if x.endswith("\n") else x + "\n\\ No newline at end of file\n" for x in d)
    return text, add, dele



@dataclass
class Ctx:
    root: Path
    cfg: Config
    task_id: str
    sdir: Path
    log: TaskLog
    start_sha: str | None
    originals: dict[str, bytes | None]  # rel -> original bytes (None = did not exist)
    paths: dict[str, Path]
    status: str = ""
    attempts: int = 0
    summary: str = ""
    warnings: list[str] = field(default_factory=list)  # run-level warnings (e.g. possible prompt truncation)


def save_manifest(c: Ctx, reverted: bool = False) -> None:
    """Atomically write the task manifest. Files the task did not actually change are left out, unless the
    task is `running` (provisional manifest written before the files, so a crash can still be reverted)."""
    files = {}
    for rel, orig in c.originals.items():
        p = c.paths[rel]
        cur = p.read_bytes() if p.exists() else None
        if cur == orig and c.status != "running":
            continue
        files[rel] = {
            "existed": orig is not None,
            "orig_sha": sha(orig) if orig is not None else None,
            "post_sha": sha(cur) if cur is not None else None,
        }
    payload = {
        "task_id": c.task_id, "start_sha": c.start_sha, "reverted": reverted,
        "status": c.status, "attempts": c.attempts, "summary": c.summary,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files,
    }
    write_bytes_atomic(c.sdir / f"{c.task_id}.json", json.dumps(payload, indent=1).encode("utf-8"))


def clear_task_artifacts(sdir: Path, task_id: str) -> None:
    """Remove the previous run's patch and backups when a task id is reused (they are our own state files)."""
    (sdir / f"{task_id}.patch").unlink(missing_ok=True)
    shutil.rmtree(sdir / f"{task_id}.orig", ignore_errors=True)


def backup(c: Ctx, rel: str, data: bytes | None) -> None:
    if rel in c.originals:
        return
    c.originals[rel] = data
    if data is not None:
        dst = c.sdir / f"{c.task_id}.orig" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)


def finish(c: Ctx, status: str, attempts: int, escalate: bool, why: str, extra: dict | None = None) -> dict:
    c.status, c.attempts = status, attempts
    patch_parts, add, dele = [], 0, 0
    changed = []
    for rel, orig in c.originals.items():
        p = c.paths[rel]
        cur = p.read_bytes() if p.exists() else None
        if cur == orig:
            continue
        before, after = normalize_bytes(orig), normalize_bytes(cur)
        text, a, d = make_diff(rel, before, after)
        patch_parts.append(text)
        add, dele = add + a, dele + d
        changed.append(rel)
    res: dict = {"status": status, "attempts": attempts, "files": changed}
    if changed:
        patch = c.sdir / f"{c.task_id}.patch"
        patch.write_text("".join(patch_parts), encoding="utf-8", newline="\n")
        res["stat"] = f"+{add} -{dele} in {len(changed)} file{'s' if len(changed) != 1 else ''}"
        res["patch"] = f"{STATE_DIR}/{c.task_id}.patch"
    save_manifest(c)  # always: list_tasks needs the status even when nothing changed
    res["log"] = f"{STATE_DIR}/{c.task_id}.log"
    res["escalate"] = escalate
    res["why"] = why
    if extra:
        res.update(extra)
    c.log.write("RESULT", to_json(res))
    return res



def baselines(c: Ctx) -> dict[str, str | None]:
    """Starting text of every file the task touched (None = the task created it)."""
    return {rel: normalize_bytes(orig) for rel, orig in c.originals.items()}


def _head_text(root: Path, rel: str) -> str | None:
    """Committed text of a dirty tracked file: the baseline that keeps legacy code from failing the ratchet."""
    try:
        return normalize_bytes(gitutil.file_at_head(root, rel))
    except gitutil.GitError:
        return None


def task_scope(
    root: Path, task_id: str | None = None, extra: Iterable[str] = ()
) -> tuple[list[str], dict[str, str | None]]:
    """Files (and their pre-task text) for run_checks: one task, or all open tasks plus `extra`."""
    sdir = root / STATE_DIR
    files: dict[str, str | None] = {}
    manifests = []
    for m in sdir.glob("*.json"):
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "files" in data and not data.get("reverted"):
            if task_id is None or data.get("task_id") == task_id:
                manifests.append(data)
    for data in sorted(manifests, key=lambda d: d.get("time", "")):  # earliest baseline wins
        for rel, info in data["files"].items():
            if rel in files:
                continue
            orig = sdir / f"{data['task_id']}.orig" / rel
            files[rel] = normalize_bytes(orig.read_bytes()) if info.get("existed") and orig.exists() else None
    for rel in extra:
        if rel not in files:
            files[rel] = _head_text(root, rel)
    return sorted(files), files
