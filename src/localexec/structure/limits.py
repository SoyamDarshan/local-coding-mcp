"""Directory structure scan: count direct source files and subdirectories per directory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..settings.safety import glob_match

SOURCE_EXTS = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".java", ".kt", ".rs", ".cs", ".rb", ".php", ".swift", ".c", ".h", ".cpp", ".hpp"})
SKIP_NAMES = frozenset({"__init__.py", "index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"})


@dataclass
class DirReport:
    path: str
    source_files: int
    subdirs: int


def is_source_file(name: str) -> bool:
    return Path(name).suffix.lower() in SOURCE_EXTS and name not in SKIP_NAMES


def _child(rel: str, name: str) -> str:
    return name if rel == "." else f"{rel}/{name}"


def scan_dirs(root: Path, ignore: list[str]) -> list[DirReport]:
    if not root.is_dir():
        return []
    reports = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = Path(dirpath).relative_to(root).as_posix() or "."
        dirnames[:] = [d for d in dirnames if not glob_match(f"{_child(rel, d)}/_", ignore)]
        reports.append(DirReport(rel, sum(is_source_file(name) for name in filenames), len(dirnames)))
    return sorted(reports, key=lambda r: r.path)


def over_limit(reports: list[DirReport], max_files: int = 10, max_subdirs: int = 10) -> list[DirReport]:
    return [r for r in reports if r.source_files > max_files or r.subdirs > max_subdirs]
