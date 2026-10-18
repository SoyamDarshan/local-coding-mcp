"""implement_task pre-flight: validate inputs, resolve paths, guard the git tree."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..vcs import gitutil
from ..settings.common import TaskError, check_task_id, make_key_resolver, resolve_targets, state_dir
from ..settings.config import STATE_DIR, Check, Config, load_config
from ..fsio.text import TextError, read_text
from ..history.manifest import known_task_files
from ..settings.protected import protected_among
from ..settings.safety import glob_match
from ..symbols import SymbolError
from ..symbols.focus import focus_excerpts, parse_focus


@dataclass
class Prepared:
    cfg: Config
    targets: dict[str, Path]
    context: dict[str, Path]
    selected: list[Check]
    start_sha: str | None
    sdir: Path
    focus: dict[str, list[str]] = field(default_factory=dict)


def select_checks(cfg: Config, names: list[str] | None) -> list[Check]:
    """Requested checks; the standards check always runs first when it is enabled."""
    by_name = {ch.name: ch for ch in cfg.checks}
    if names is None:
        return list(cfg.checks)
    missing = [n for n in names if n not in by_name]
    if missing:
        raise TaskError(f"unknown check(s): {', '.join(missing)}; configured: {', '.join(by_name) or 'none'}")
    chosen = [by_name[n] for n in dict.fromkeys(names) if n != "standards"]
    return ([by_name["standards"]] if "standards" in by_name else []) + chosen


def _guard_git_tree(root: Path, targets: dict[str, Path]) -> None:
    if gitutil.toplevel(root) is None:
        raise TaskError("project is not a git repository")
    try:
        known = known_task_files(root)
        dirty = [
            p for p in gitutil.dirty_paths(root)
            if p not in targets and p not in known and not glob_match(p, [STATE_DIR + "/**"])
        ]
    except gitutil.GitError as e:
        raise TaskError(f"git status failed: {e}") from e
    if dirty:
        more = f" (+{len(dirty) - 4} more)" if len(dirty) > 4 else ""
        raise TaskError(
            f"{len(dirty)} unrelated uncommitted file(s): {', '.join(dirty[:4])}{more}. "
            "Commit/stash them or include them in files_to_edit."
        )


def _guard_task_id_unused(sdir: Path, task_id: str) -> None:
    manifest = sdir / f"{task_id}.json"
    if not manifest.exists():
        return
    try:
        prev = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        raise TaskError(f"task_id '{task_id}' already used; pick a new id") from None
    if prev.get("files") and not prev.get("reverted"):
        raise TaskError(f"task_id '{task_id}' already used; revert_task it or pick a new id")


def _validate_focus(root: Path, targets: dict[str, Path], symbols: list[str] | None) -> dict[str, list[str]]:
    if not symbols:
        return {}
    try:
        focus = parse_focus(symbols, make_key_resolver(root, set(targets)))
        texts = {rel: (read_text(p, rel) if p.exists() else None) for rel, p in targets.items()}
        focus_excerpts(texts, focus, strict=True)
    except (SymbolError, OSError, TextError) as e:
        raise TaskError(str(e)) from e
    return focus


def _requested_rel(root: Path, name: str) -> str | None:
    """The path as the caller wrote it: project-relative, forward slashes, `.`/`..` collapsed, links not followed."""
    path = Path(name.strip().replace("\\", "/"))
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            return None
    return Path(os.path.normpath(path.as_posix())).as_posix()


def _guard_protected(root: Path, cfg: Config, requested: list[str], targets: dict[str, Path]) -> None:
    """Refuse files that decide what runs or how Claude is configured; the planner edits those itself.

    Both the requested spelling and the symlink-resolved path are checked."""
    forms = [rel for name in requested if (rel := _requested_rel(root, name)) is not None]
    hit = protected_among([*forms, *targets], cfg.protected_paths, cfg.allow_protected)
    if hit:
        more = f" (+{len(hit) - 3} more)" if len(hit) > 3 else ""
        raise TaskError(
            f"protected file(s): {', '.join(hit[:3])}{more}. "
            "They control what runs or how Claude is configured; edit them yourself."
        )


def prepare(
    root: Path,
    task_id: str,
    spec: str,
    files_to_edit: list[str],
    context_files: list[str] | None,
    check_names: list[str] | None,
    symbols: list[str] | None = None,
) -> Prepared:
    """Raises TaskError / PathError / ConfigError with a short, user-facing message."""
    check_task_id(task_id)
    cfg = load_config(root)
    if not spec or not spec.strip():
        raise TaskError("spec is empty")
    if not files_to_edit:
        raise TaskError("files_to_edit is empty")
    targets = resolve_targets(root, cfg, files_to_edit, "files_to_edit")
    context = resolve_targets(root, cfg, context_files or [], "context_files")
    context = {rel: p for rel, p in context.items() if rel not in targets}
    _guard_protected(root, cfg, files_to_edit, targets)
    selected = select_checks(cfg, check_names)
    _guard_git_tree(root, targets)
    sdir = state_dir(root)
    _guard_task_id_unused(sdir, task_id)
    focus = _validate_focus(root, targets, symbols)
    try:
        head = gitutil.head_sha(root)
    except gitutil.GitError as e:
        raise TaskError(f"git failed: {e}") from e
    return Prepared(cfg, targets, context, selected, head, sdir, focus)
