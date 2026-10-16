"""Strict parsing of SEARCH/REPLACE and FULL edit blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass


SEARCH_START = "<<<<<<< SEARCH"
FULL_START = "<<<<<<< FULL"
DIVIDER = "======="
REPLACE_END = ">>>>>>> REPLACE"
FULL_END = ">>>>>>> END"

_FILE_RE = re.compile(r"^FILE:\s*(.+?)\s*$")


class EditParseError(Exception):
    pass


@dataclass
class Edit:
    path: str
    kind: str  # "sr" (search/replace) or "full"
    search: list[str]
    replace: list[str]


def is_blocked_reply(text: str) -> str | None:
    """Return the question if the model replied BLOCKED: ..., else None."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
    if t[:8].upper().startswith("BLOCKED:"):
        return t[8:].strip()[:1500] or "(no question given)"
    return None


def _clean_path(p: str) -> str:
    return p.strip().strip("`'\"").strip()


_FORBIDDEN = {
    "search": (REPLACE_END, FULL_END, SEARCH_START, FULL_START),
    "replace": (SEARCH_START, FULL_START, FULL_END),
    "full": (SEARCH_START, FULL_START, REPLACE_END),
}

_FENCE_OPEN_RE = re.compile(r"^\s*```[\w+.-]*\s*$")


def strip_fence(lines: list[str]) -> list[str]:
    """Drop a markdown code fence the model wrapped around a whole section.

    Only when the fence is the sole fence pair: content that itself contains fences (Markdown files) is kept.
    """
    idx = [i for i, ln in enumerate(lines) if ln.strip()]
    if len(idx) < 2 or not _FENCE_OPEN_RE.match(lines[idx[0]]) or lines[idx[-1]].strip() != "```":
        return lines
    inner = lines[idx[0] + 1 : idx[-1]]
    if any(ln.lstrip().startswith("```") for ln in inner):
        return lines
    return inner


class _Parser:
    """Line-by-line state machine: idle -> search -> replace, or idle -> full."""

    def __init__(self) -> None:
        self.edits: list[Edit] = []
        self.state = "idle"
        self.path: str | None = None
        self.buf: list[str] = []
        self.search: list[str] = []

    def feed(self, i: int, raw: str) -> None:
        s = raw.rstrip()
        if self.state == "idle":
            self._idle(i, s)
        else:
            self._block(i, s, raw)

    def _idle(self, i: int, s: str) -> None:
        if not s.strip() or s.lstrip().startswith("```"):
            return
        m = _FILE_RE.match(s.strip())
        if m:
            self.path = _clean_path(m.group(1))
        elif s in (SEARCH_START, FULL_START):
            if not self.path:
                raise EditParseError(f"line {i}: edit block without a preceding 'FILE: path' line")
            self.state = "search" if s == SEARCH_START else "full"
            self.buf = []
        else:
            raise EditParseError(f"line {i}: text outside an edit block: {s.strip()[:60]!r}")

    def _block(self, i: int, s: str, raw: str) -> None:
        if s in _FORBIDDEN[self.state]:
            raise EditParseError(f"line {i}: unexpected marker {s!r} inside {self.state.upper()} section")
        if self.state == "replace" and s == DIVIDER:
            raise EditParseError(
                f"line {i}: a second '{DIVIDER}' line is ambiguous; add surrounding lines to SEARCH or use FULL"
            )
        if self.state == "search" and s == DIVIDER:
            self.search, self.buf, self.state = strip_fence(self.buf), [], "replace"
        elif self.state == "replace" and s == REPLACE_END:
            self._emit("sr")
        elif self.state == "full" and s == FULL_END:
            self._emit("full")
        else:
            self.buf.append(raw)

    def _emit(self, kind: str) -> None:
        assert self.path is not None
        self.edits.append(Edit(self.path, kind, self.search if kind == "sr" else [], strip_fence(self.buf)))
        self.state, self.buf = "idle", []


def parse_edits(text: str) -> list[Edit]:
    parser = _Parser()
    for i, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        parser.feed(i, raw)
    if parser.state != "idle":
        raise EditParseError("output ended inside an unterminated edit block (possibly cut off)")
    if not parser.edits:
        raise EditParseError("no edit blocks found; reply with edit blocks or 'BLOCKED: <question>'")
    return parser.edits
