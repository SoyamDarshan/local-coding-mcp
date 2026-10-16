"""Shared helpers: ids, JSON results, task log, path targets."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Callable

from .config import STATE_DIR, Config
from .safety import PathError, glob_match, rel_posix, resolve_in_root

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")  # \Z: `$` would accept a trailing newline
RESERVED_STEMS = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)  # Windows device names
RESERVED_IDS = {"run_checks"}  # would collide with state-dir files

def est_tokens(text: str) -> int:
    return int(len(text) / 3.5) + 1



class TaskError(Exception):
    """Pre-flight failure; reported as a tiny error result."""


def err(message: str) -> dict:
    return {"status": "error", "error": message[:400], "escalate": False}


def to_json(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TaskLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def write(self, title: str, body: str = "") -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"\n===== {time.strftime('%H:%M:%S')} {title} =====\n{body}\n")


def state_dir(root: Path) -> Path:
    d = root / STATE_DIR
    d.mkdir(exist_ok=True)
    if not d.resolve().is_relative_to(root):
        raise TaskError(f"{STATE_DIR} resolves outside the project; remove that link")
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")
    return d


def check_task_id(task_id: str) -> None:
    if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id):
        raise TaskError("task_id must match [A-Za-z0-9._-], max 64 chars")
    if task_id.endswith(".") or RESERVED_STEMS.match(task_id.split(".")[0]) or task_id.lower() in RESERVED_IDS:
        raise TaskError(f"task_id '{task_id}' is reserved or ends with a dot; pick another")


def resolve_targets(root: Path, cfg: Config, paths: list[str], what: str) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in paths:
        try:
            full = resolve_in_root(root, p)
        except PathError as e:
            raise TaskError(f"{what}: {e}") from e
        rel = rel_posix(root, full)
        if glob_match(rel, cfg.ignore):
            raise TaskError(f"{what}: '{rel}' is ignored by config")
        if not glob_match(rel, cfg.allowed_paths, any_depth=False):
            raise TaskError(f"{what}: '{rel}' not in allowed_paths")
        out[rel] = full
    return out


def make_key_resolver(root: Path, keys: set[str]) -> Callable[[str], str | None]:
    lowered = {k.lower(): k for k in keys}

    def resolve(p: str) -> str | None:
        p = p.replace("\\", "/")
        try:
            pp = Path(p)
            if pp.is_absolute():
                p = pp.resolve(strict=False).relative_to(root).as_posix()
        except (ValueError, OSError):
            return None
        while p.startswith("./"):
            p = p[2:]
        if p in keys:
            return p
        return lowered.get(p.lower()) if len(lowered) == len(keys) else None

    return resolve

