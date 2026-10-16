"""Applying parsed edit blocks: in-memory edits and atomic, rollback-safe writes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..fsio.atomic import missing_dirs, write_bytes_atomic
from ..fsio.text import Doc, TextError, decode
from .match import find_hits, reindent
from .parse import Edit


_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:#|//|/\*|<!--|--)?\s*(?:\.\.\.|…)\s*(?:rest|existing|unchanged|remaining|other|same)\b",
    re.IGNORECASE,
)


class EditApplyError(Exception):
    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


@dataclass
class FileState:
    rel: str
    path: Path
    text: str  # normalised to \n, BOM stripped
    existed: bool
    crlf: bool = False
    bom: bool = False
    raw: bytes | None = None  # bytes as read; write_atomic refuses to overwrite a file that changed since

    def render(self, text: str) -> bytes:
        return Doc(text, self.bom, "\r\n" if self.crlf else "\n").render()


def read_state(rel: str, path: Path) -> FileState:
    if not path.exists():
        return FileState(rel, path, "", existed=False)
    if not path.is_file():
        raise EditApplyError([f"{rel}: not a regular file"])
    raw = path.read_bytes()
    try:
        doc = decode(raw, rel)
    except TextError as e:
        raise EditApplyError([str(e)]) from e
    return FileState(rel, path, doc.text, True, doc.eol == "\r\n", doc.bom, raw)


def _join_full(buf: list[str]) -> str:
    return ("\n".join(buf) + "\n") if buf else ""


def _placeholder_error(n: int, key: str, lines: list[str]) -> str | None:
    for line in lines:
        if _PLACEHOLDER_RE.match(line):
            return f"block {n} ({key}): contains a placeholder line like {line.strip()[:50]!r}; write the real code"
    return None


def _apply_full(n: int, key: str, st: FileState, replace: list[str]) -> tuple[str | None, str | None]:
    if not st.existed:
        return _join_full(replace), None
    if st.text.strip() and not any(ln.strip() for ln in replace):
        return None, f"block {n} ({key}): FULL output is empty; this would wipe the file"
    orig_lines = st.text.count("\n")
    if orig_lines > 40 and len(replace) < orig_lines * 0.3:
        return None, (
            f"block {n} ({key}): FULL output is far shorter than the existing file; "
            "use SEARCH/REPLACE blocks for large files"
        )
    text = _join_full(replace)
    return (text if st.text.endswith("\n") or not st.text else text.rstrip("\n")), None


def _not_found_message(n: int, key: str, search: list[str], lines: list[str]) -> str:
    first = search[0].strip()[:60]
    anywhere = any(first and first in ln for ln in lines)
    hint = (
        "the first line exists elsewhere, so a later line differs"
        if anywhere
        else "the first line does not appear in the file"
    )
    return (
        f"block {n} ({key}): SEARCH text not found ({hint}; starts with {first!r}). "
        "Copy the lines exactly as they are in the file"
    )


def _apply_search_replace(n: int, key: str, cur: str, e: Edit) -> tuple[str | None, str | None]:
    if not e.search or all(not x.strip() for x in e.search):
        if cur.strip() == "":
            return _join_full(e.replace), None
        return None, f"block {n} ({key}): empty SEARCH is only allowed for a new or empty file"
    lines = cur.split("\n")
    hits = find_hits(lines, e.search)
    if not hits:
        return None, _not_found_message(n, key, e.search, lines)
    if len(hits) > 1:
        return None, (
            f"block {n} ({key}): SEARCH text matches {len(hits)} places "
            f"(lines {', '.join(str(h + 1) for h in hits[:5])}); include more surrounding lines"
        )
    lines[hits[0] : hits[0] + len(e.search)] = reindent(e.replace, e.search, lines, hits[0])
    return "\n".join(lines), None


def apply_edits(
    states: dict[str, FileState],
    edits: list[Edit],
    resolve_key: Callable[[str], str | None],
    partial: set[str] | None = None,
) -> dict[str, str]:
    """Apply edits in memory. Returns {rel: new_text} for changed files.

    Raises EditApplyError listing every problem found; nothing is written here.
    """
    new_text = {rel: st.text for rel, st in states.items()}
    touched: set[str] = set()
    errors: list[str] = []
    for n, e in enumerate(edits, 1):
        key = resolve_key(e.path)
        if key is None or key not in states:
            allowed = ", ".join(sorted(states))
            errors.append(f"block {n}: '{e.path}' is not a file you may edit (allowed: {allowed})")
            continue
        placeholder = _placeholder_error(n, key, e.replace)
        if placeholder:
            errors.append(placeholder)
        if e.kind == "full" and key in (partial or ()):
            errors.append(f"block {n} ({key}): only an excerpt of this file was shown; use SEARCH/REPLACE, not FULL")
            continue
        if e.kind == "full":
            text, msg = _apply_full(n, key, states[key], e.replace)
        else:
            text, msg = _apply_search_replace(n, key, new_text[key], e)
        if msg:
            errors.append(msg)
        elif text is not None:
            new_text[key] = text
            touched.add(key)
    if errors:
        raise EditApplyError(errors)
    return {k: v for k, v in new_text.items() if k in touched and (v != states[k].text or not states[k].existed)}


class StaleFileError(OSError):
    """A file changed on disk between reading it and writing the model's edit."""


def _ensure_unchanged(states: dict[str, FileState], new_text: dict[str, str]) -> None:
    stale = []
    for rel in new_text:
        st = states[rel]
        now = st.path.read_bytes() if st.path.exists() else None
        if now != st.raw:
            stale.append(rel)
    if stale:
        raise StaleFileError(f"changed on disk while the model was working: {', '.join(stale)}; nothing written")


def _rollback(done: list[tuple[FileState, bytes | None]], created: list[Path]) -> list[str]:
    """Undo writes. Returns descriptions of anything that could not be restored."""
    failed = []
    for st, old in reversed(done):
        try:
            if old is None:
                st.path.unlink(missing_ok=True)
            else:
                write_bytes_atomic(st.path, old)
        except OSError as e:
            failed.append(f"{st.rel}: {e}")
    for d in reversed(created):
        try:
            d.rmdir()
        except OSError:
            pass  # not empty (someone else uses it): leave it
    return failed


def write_atomic(states: dict[str, FileState], new_text: dict[str, str]) -> None:
    """Write all files; if any write fails, restore the ones already written (and remove new directories)."""
    _ensure_unchanged(states, new_text)
    done: list[tuple[FileState, bytes | None]] = []
    created: list[Path] = []
    try:
        for rel, text in new_text.items():
            st = states[rel]
            old = st.path.read_bytes() if st.path.exists() else None
            made = missing_dirs(st.path.parent)
            st.path.parent.mkdir(parents=True, exist_ok=True)
            created.extend(made)
            write_bytes_atomic(st.path, st.render(text))
            done.append((st, old))
    except BaseException as e:
        failed = _rollback(done, created)
        if failed:
            raise OSError("write failed and could not restore: " + "; ".join(failed)) from e
        raise
