"""`symbols=["path::name", ...]` handling for implement_task."""

from __future__ import annotations

from typing import Callable

from .excerpt import build_excerpt, find_symbols
from .model import SymbolError
from . import list_symbols


def parse_focus(args: list[str], resolve_path: Callable[[str], str | None]) -> dict[str, list[str]]:
    """Group 'path::name' entries by file. `resolve_path` maps a path to an editable file key."""
    focus: dict[str, list[str]] = {}
    for arg in args:
        path, sep, name = arg.rpartition("::")
        if not sep or not path.strip() or not name.strip():
            raise SymbolError(f"symbols entry '{arg}' must look like 'path/to/file.py::function_name'")
        key = resolve_path(path.strip())
        if key is None:
            raise SymbolError(f"symbols: '{path}' is not listed in files_to_edit")
        focus.setdefault(key, []).append(name.strip())
    return focus


def focus_excerpts(
    texts: dict[str, str | None], focus: dict[str, list[str]], strict: bool = False, context: int = 5
) -> dict[str, str]:
    """Excerpt per focused file. strict: any unresolved name raises; otherwise it is skipped
    (a symbol may legitimately vanish after the model's first attempt)."""
    out: dict[str, str] = {}
    problems: list[str] = []
    for rel, names in focus.items():
        text = texts.get(rel)
        if text is None:
            problems.append(f"{rel}: file does not exist yet, so symbols cannot be used")
            continue
        try:
            symbols = list_symbols(rel, text)
        except SymbolError as e:
            problems.append(f"{rel}: {e}")  # e.g. a syntax error left by an earlier attempt
            continue
        found, probs = find_symbols(symbols, names)
        problems.extend(f"{rel}: {p}" for p in probs)
        if found:
            out[rel] = build_excerpt(text, found, context)
    if strict and problems:
        raise SymbolError("; ".join(problems)[:600])
    return out
