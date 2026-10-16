"""Pick symbols by name and render a prompt excerpt around them."""

from __future__ import annotations

import difflib

from dataclasses import replace

from .model import Symbol

GAP_MERGE = 2  # gaps of up to this many lines are shown instead of replaced by a marker


def find_symbols(symbols: list[Symbol], wanted: list[str]) -> tuple[list[Symbol], list[str]]:
    """Resolve names to symbols. Returns (found, problems)."""
    found: list[Symbol] = []
    problems: list[str] = []
    names = [s.name for s in symbols]
    for w in dict.fromkeys(wanted):
        exact = [s for s in symbols if s.name == w]
        loose = [s for s in symbols if s.name.endswith("." + w)]
        hits = exact or loose
        if hits and len({s.name for s in hits}) == 1:
            found.append(_combine(hits))  # property setters, overloads, if/else definitions
        elif hits:
            problems.append(f"'{w}' is ambiguous ({', '.join(s.name for s in hits[:4])}); use the qualified name")
        else:
            close = difflib.get_close_matches(w, names, n=3, cutoff=0.5)
            hint = f" (did you mean: {', '.join(close)})" if close else ""
            problems.append(f"symbol '{w}' not found{hint}")
    return found, problems


def _combine(hits: list[Symbol]) -> Symbol:
    """One symbol spanning all same-named definitions."""
    if len(hits) == 1:
        return hits[0]
    return replace(hits[0], start=min(s.start for s in hits), end=max(s.end for s in hits))


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for a, b in sorted(ranges):
        if merged and a <= merged[-1][1] + 1 + GAP_MERGE:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def build_excerpt(text: str, symbols: list[Symbol], context: int = 5) -> str:
    """The chosen symbols with `context` lines around them; gaps become explicit markers."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    total = len(lines)
    spans = _merge([(max(1, s.start - context), min(total, s.end + context)) for s in symbols])
    out: list[str] = []
    cursor = 1
    for a, b in spans:
        if a > cursor:
            out.append(f"[... lines {cursor}-{a - 1} omitted (not part of the file text) ...]")
        out.extend(lines[a - 1 : b])
        cursor = b + 1
    if cursor <= total:
        out.append(f"[... lines {cursor}-{total} omitted (not part of the file text) ...]")
    return "\n".join(out)
