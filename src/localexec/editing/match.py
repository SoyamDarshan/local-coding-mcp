"""Locating SEARCH text in a file and re-indenting replacements."""

from __future__ import annotations

from typing import Callable


def find_hits(lines: list[str], search: list[str]) -> list[int]:
    n = len(search)
    if n == 0 or n > len(lines):
        return []

    def scan(eq: Callable[[str, str], bool]) -> list[int]:
        return [
            i
            for i in range(len(lines) - n + 1)
            if eq(lines[i], search[0]) and all(eq(lines[i + k], search[k]) for k in range(1, n))
        ]

    return (
        scan(lambda a, b: a == b)
        or scan(lambda a, b: a.rstrip() == b.rstrip())
        or scan(lambda a, b: a.strip() == b.strip())
    )


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _convert_lead(lead: str, tabs: bool) -> str:
    """Express extra indentation in the file's own style (tabs or spaces)."""
    if tabs and " " in lead and "\t" not in lead:
        return "\t" * (len(lead) // 4) + " " * (len(lead) % 4)
    if not tabs and "\t" in lead:
        return lead.replace("\t", "    ")
    return lead


def _shift(ln: str, have: str, want: str, tabs: bool) -> str:
    if not ln.strip() or not ln.startswith(have):
        return ln
    extra = ln[len(have):]
    body = extra.lstrip(" \t")
    return want + _convert_lead(extra[: len(extra) - len(body)], tabs) + body


def reindent(lines: list[str], search: list[str], file_lines: list[str], at: int) -> list[str]:
    """If SEARCH matched only after ignoring indentation, give the replacement the file's indentation.

    A replacement line identical to a SEARCH line is unchanged, so the file's own line is kept. New or edited
    lines get the indentation delta between the file and SEARCH, expressed in the file's tab/space style.
    """
    span = file_lines[at : at + len(search)]
    if all(f.rstrip() == q.rstrip() for f, q in zip(span, search, strict=True)):
        return lines
    first = next((k for k, ln in enumerate(search) if ln.strip()), 0)
    have, want = _indent(search[first]), _indent(span[first])
    tabs = any(_indent(f).startswith("\t") for f in span if f.strip())
    out, j = [], 0
    for ln in lines:
        k = next((k for k in range(j, len(search)) if ln.strip() and search[k].rstrip() == ln.rstrip()), None)
        if k is not None:
            out.append(span[k])
            j = k + 1
        else:
            out.append(_shift(ln, have, want, tabs))
    return out
