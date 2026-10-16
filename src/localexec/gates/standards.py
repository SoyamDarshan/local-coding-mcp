"""Coding-standards check: function length (Python) and file length (code files).

"Lines" means code lines: blanks, comment-only lines and docstrings are not counted.
Ratchet: legacy violations are only reported as warnings unless the change made them worse.
"""

from __future__ import annotations

import ast
import difflib
import io
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from ..fsio.text import TextError, read_text, split_lines
from ..settings.safety import glob_match
from ..settings.defaults import Standards

CODE_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".go", ".java",
    ".kt", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".sh",
}
HASH_COMMENT_EXTS = {".py", ".rb", ".sh"}
IGNORE_MARKER = "lintlen: ignore"
MAX_REPORT_LINES = 8


@dataclass
class StdResult:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fatal: bool = False  # needs a planner decision (e.g. split a file); retrying the model is pointless


@dataclass
class Func:
    name: str
    start: int
    end: int
    loc: int


# --------------------------------------------------------------------------- counting


def _python_code_lines(text: str) -> set[int] | None:
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
            tokenize.ENDMARKER, tokenize.ENCODING}
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type not in skip:
                lines.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return lines


def _slash_code_lines(text: str) -> set[int]:
    lines: set[int] = set()
    in_block = False
    for n, raw in enumerate(split_lines(text), 1):
        s = raw.strip()
        if in_block:
            if "*/" in s:
                in_block = False
                s = s.split("*/", 1)[1].strip()
            else:
                continue
        if s.startswith("/*"):
            if "*/" in s:
                s = s.split("*/", 1)[1].strip()
            else:
                in_block = True
                continue
        if s and not s.startswith("//"):
            lines.add(n)
    return lines


def _hash_code_lines(text: str) -> set[int]:
    return {n for n, raw in enumerate(split_lines(text), 1) if raw.strip() and not raw.strip().startswith("#")}


def _docstring_lines(text: str) -> set[int]:
    """Lines occupied by module, class and function docstrings (not code)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            out.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return out


def code_lines(rel: str, text: str) -> set[int]:
    ext = Path(rel).suffix.lower()
    if ext == ".py":
        got = _python_code_lines(text)
        return got - _docstring_lines(text) if got is not None else _hash_code_lines(text)
    if ext in HASH_COMMENT_EXTS:
        return _hash_code_lines(text)
    return _slash_code_lines(text)


def python_functions(text: str) -> list[Func] | None:
    """All functions/methods with their code-line counts (docstrings excluded). None on syntax error."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    code = _python_code_lines(text)
    if code is None:
        return None
    found: list[Func] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                span = set(range(child.lineno, (child.end_lineno or child.lineno) + 1)) & code
                doc = child.body[0] if child.body else None
                if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str):
                    span -= set(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
                found.append(Func(name, child.lineno, child.end_lineno or child.lineno, len(span)))
                visit(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def changed_ranges(old: str | None, new: str) -> list[tuple[int, int]] | None:
    """New-file line ranges touched by the change. None = whole file (new/unknown baseline)."""
    if old is None:
        return None
    a, b = split_lines(old), split_lines(new)
    ranges = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        # a pure deletion touches the lines on both sides of the join
        ranges.append((max(j1, 1), j1 + 1) if j1 == j2 else (j1 + 1, j2))
    return ranges


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]] | None) -> bool:
    return ranges is None or any(s <= end and e >= start for s, e in ranges)


# --------------------------------------------------------------------------- the check


def _check_file_length(rel: str, text: str, base: str | None, std: Standards, res: StdResult) -> None:
    loc = len(code_lines(rel, text))
    old_loc = len(code_lines(rel, base)) if base is not None else None
    if loc > std.max_file_lines:
        if old_loc is not None and loc <= old_loc:
            res.warnings.append(f"{rel}: {loc} code lines, legacy file over {std.max_file_lines}; plan a split")
        else:
            res.failures.append(
                f"{rel}: {loc} code lines (max {std.max_file_lines}). Too long: needs a split into "
                "another file (planner decision)."
            )
            res.fatal = True
    elif loc > std.warn_file_lines:
        res.warnings.append(f"{rel}: {loc} code lines (soft limit {std.warn_file_lines}); consider splitting")


def _has_marker(lines: list[str], f: Func) -> bool:
    """`# lintlen: ignore` anywhere on the (possibly multi-line) signature."""
    for ln in lines[f.start - 1 : f.end]:
        if IGNORE_MARKER in ln:
            return True
        if ln.split("#")[0].rstrip().endswith(":"):
            break
    return False


def _check_functions(rel: str, text: str, base: str | None, std: Standards, res: StdResult) -> None:
    funcs = python_functions(text)
    if funcs is None:
        res.failures.append(f"{rel}: cannot be parsed as Python (syntax error); fix it first")
        return
    old = {f.name: f.loc for f in (python_functions(base) or [])} if base is not None else {}
    ranges = changed_ranges(base, text)
    lines = split_lines(text)
    for f in funcs:
        if f.loc <= std.max_function_lines or not _overlaps(f.start, f.end, ranges):
            continue
        if _has_marker(lines, f):
            continue
        msg = f"{rel}::{f.name} (lines {f.start}-{f.end}): {f.loc} code lines, max {std.max_function_lines}"
        if f.name in old and f.loc <= old[f.name]:
            res.warnings.append(msg + " (legacy, not made worse)")
        else:
            res.failures.append(msg + ". Extract helper functions; reuse existing ones instead of duplicating.")


def check_files(
    root: Path, std: Standards, files: list[str], baselines: dict[str, str | None] | None = None
) -> StdResult:
    res = StdResult()
    baselines = baselines or {}
    for rel in files:
        if Path(rel).suffix.lower() not in CODE_EXTS or glob_match(rel, std.exempt):
            continue
        try:
            text = read_text(root / rel, rel)
        except OSError:
            continue  # deleted or unreadable
        except TextError as e:
            res.warnings.append(f"{e}; not checked")
            continue
        base = baselines.get(rel)
        _check_file_length(rel, text, base, std, res)
        if Path(rel).suffix.lower() == ".py":
            _check_functions(rel, text, base, std, res)
    res.failures = res.failures[:MAX_REPORT_LINES]
    res.warnings = res.warnings[:MAX_REPORT_LINES]
    return res
