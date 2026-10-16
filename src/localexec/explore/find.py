"""find(pattern): read-only regex search over project files, in a small result."""

from __future__ import annotations

import os
import time
from pathlib import Path

import regex

from ..settings.common import err
from ..settings.config import Config, ConfigError, load_config
from ..fsio.text import TextError, decode, split_lines
from ..settings.safety import glob_match

MAX_FILE_BYTES = 1_000_000
MAX_LINE_SCAN = 2000
MAX_FILES = 5000
MAX_CHARS = 3000
TIME_BUDGET = 8.0
LINE_TIMEOUT = 0.25  # seconds per line; guards against catastrophic backtracking
SNIPPET = 120


def _child(rel_dir: str, name: str) -> str:
    return name if rel_dir == "." else f"{rel_dir}/{name}"


def _walk(root: Path, cfg: Config, glob: str | None):
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        dirnames[:] = [d for d in sorted(dirnames) if not glob_match(f"{_child(rel_dir, d)}/_", cfg.ignore)]
        for name in sorted(filenames):
            rel = _child(rel_dir, name)
            if glob_match(rel, cfg.ignore) or (glob and not glob_match(rel, [glob])):
                continue
            yield rel


def _read_lines(path: Path) -> list[str] | None:
    """Lines of a text file, or None when it is skipped (binary, too big, not UTF-8, unreadable)."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
        if b"\0" in data[:4096]:
            return None
        return split_lines(decode(data, path.name).text)
    except (OSError, TextError):
        return None


class _Search:
    """Collects matches under a result-count and total-size cap."""

    def __init__(self, rx: regex.Pattern[str], max_results: int):
        self.rx, self.max_results = rx, max_results
        self.matches: list[str] = []
        self.size = 0
        self.full = False

    def scan(self, rel: str, lines: list[str]) -> None:
        for n, line in enumerate(lines, 1):
            if self.rx.search(line[:MAX_LINE_SCAN], timeout=LINE_TIMEOUT):
                entry = f"{rel}:{n}:{line.strip()[:SNIPPET]}"
                if len(self.matches) >= self.max_results or self.size + len(entry) > MAX_CHARS:
                    self.full = True
                    return
                self.matches.append(entry)
                self.size += len(entry) + 1


def find(root: Path, pattern: str, glob: str | None = None, max_results: int = 30, ignore_case: bool = False) -> dict:
    try:
        cfg = load_config(root)
        rx = regex.compile(pattern, regex.IGNORECASE if ignore_case else 0)
    except (ConfigError, regex.error) as e:
        return err(f"bad pattern or config: {e}")
    search = _Search(rx, max(1, min(int(max_results), 100)))
    scanned = skipped = 0
    truncated, start = False, time.monotonic()
    try:
        for rel in _walk(root, cfg, glob):
            full = root / rel
            if not full.resolve().is_relative_to(root):
                continue
            if scanned >= MAX_FILES or time.monotonic() - start > TIME_BUDGET:
                truncated = True
                break
            lines = _read_lines(full)
            if lines is None:
                skipped += 1
                continue
            scanned += 1
            search.scan(rel, lines)
            if search.full:
                break
    except TimeoutError:
        return err("pattern is too slow (catastrophic backtracking); simplify it")
    out: dict = {"matches": search.matches, "scanned": scanned, "truncated": truncated or search.full}
    if skipped:
        out["skipped"] = skipped  # binary, oversize or non-UTF-8 files
    return out
