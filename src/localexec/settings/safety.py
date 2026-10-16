"""Path safety: everything must stay inside the project root."""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path


class PathError(Exception):
    pass


_DEVICE_NAME = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)


def _bad_component(part: str) -> bool:
    """Names that mean something else on Windows (streams, devices, trailing dot/space). Rejected everywhere."""
    if part in (".", ".."):
        return False
    return ":" in part or part.endswith((" ", ".")) or bool(_DEVICE_NAME.match(part))


def resolve_in_root(root: Path, rel: str) -> Path:
    """Resolve `rel` (relative or absolute) and require it to be inside `root`.

    Symlinks are followed by resolve(), so a link that escapes the root is rejected.
    `root` must already be resolved.
    """
    if not isinstance(rel, str) or not rel.strip() or "\x00" in rel:
        raise PathError("empty or invalid path")
    p = Path(rel.strip())
    if any(_bad_component(part) for part in (p.parts[1:] if p.is_absolute() else p.parts)):
        raise PathError(f"unsupported file name (stream, device name, or trailing dot/space): {rel}")
    full = p if p.is_absolute() else root / p
    resolved = full.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise PathError(f"path escapes project root: {rel}")
    if resolved == root:
        raise PathError(f"path is the project root, not a file: {rel}")
    return resolved


def rel_posix(root: Path, resolved: Path) -> str:
    return resolved.relative_to(root).as_posix()


@lru_cache(maxsize=512)
def _glob_to_regex(pat: str, any_depth: bool) -> re.Pattern[str]:
    pat = pat.replace("\\", "/")
    anchored = pat.startswith("/")
    pat = pat.lstrip("/")
    if pat.endswith("/"):
        pat += "**"
    out: list[str] = []
    i = 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    body = "".join(out)
    if any_depth and not anchored:
        body = "(?:.*/)?" + body
    flags = re.IGNORECASE if sys.platform == "win32" else 0
    return re.compile(body, flags)


def glob_match(path: str, patterns: list[str], any_depth: bool = True) -> bool:
    """True if `path` (posix, relative) or any parent directory matches a pattern."""
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    for pat in patterns:
        rx = _glob_to_regex(pat, any_depth)
        if any(rx.fullmatch(pref) for pref in prefixes):
            return True
    return False
