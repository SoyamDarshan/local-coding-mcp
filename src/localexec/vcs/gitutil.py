"""Small, fixed git helpers (arguments are never taken from Claude)."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _run(root: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[bytes]:
    try:
        p = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, stdin=subprocess.DEVNULL, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f"git failed: {e}") from e
    if p.returncode != 0:
        raise GitError(p.stderr.decode("utf-8", "replace").strip()[:200] or "git error")
    return p


def _git(root: Path, *args: str) -> str:
    return _run(root, args).stdout.decode("utf-8", "replace")


def toplevel(cwd: Path) -> Path | None:
    try:
        return Path(_git(cwd, "rev-parse", "--show-toplevel").strip()).resolve()
    except GitError:
        return None


def head_sha(root: Path) -> str | None:
    """HEAD commit, or None for a repository without commits. Other git failures are raised."""
    try:
        return _git(root, "rev-parse", "--verify", "-q", "HEAD").strip()
    except GitError as e:
        if str(e) == "git error":  # `-q` exits 1 without a message for an unborn HEAD
            return None
        raise


def file_at_head(root: Path, rel: str) -> bytes | None:
    """Committed bytes of `rel` (posix, relative to root), or None if it is not tracked in HEAD."""
    try:
        return _run(root, ("show", f"HEAD:./{rel}")).stdout
    except GitError:
        return None


def dirty_paths(root: Path) -> list[str]:
    """Tracked files with staged or unstaged changes, relative to `root` (posix)."""
    prefix = _git(root, "rev-parse", "--show-prefix").strip()
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    parts = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:
            i += 1  # skip the original-path entry
        if prefix:
            if not path.startswith(prefix):
                continue
            path = path[len(prefix):]
        paths.append(path)
    return paths
