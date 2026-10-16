"""Python symbols via the standard-library ast module."""

from __future__ import annotations

import ast

from ..fsio.text import split_lines
from .model import Symbol, SymbolError

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
SIG_MAX = 100


def _signature(node: ast.AST, lines: list[str]) -> str:
    body = getattr(node, "body", None)
    first = node.lineno  # type: ignore[attr-defined]
    stop = body[0].lineno - 1 if body and body[0].lineno > first else first
    return " ".join(ln.strip() for ln in lines[first - 1 : max(stop, first)])[:SIG_MAX]


def _symbol(node: ast.AST, name: str, kind: str, lines: list[str]) -> Symbol:
    decorators = [d.lineno for d in getattr(node, "decorator_list", [])]
    start = min([node.lineno, *decorators])  # type: ignore[attr-defined]
    return Symbol(name, kind, start, node.end_lineno or start, _signature(node, lines))  # type: ignore[attr-defined]


def _const_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [t.id for t in targets if isinstance(t, ast.Name)]


def _blocks(node: ast.stmt) -> list[list[ast.stmt]]:
    """Statement lists nested in if / try / with, so definitions under `if TYPE_CHECKING:` are found."""
    if isinstance(node, ast.If):
        return [node.body, node.orelse]
    if isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
        return [node.body, *[h.body for h in node.handlers], node.orelse, node.finalbody]
    if isinstance(node, ast.With):
        return [node.body]
    return []


def _walk(body: list[ast.stmt], prefix: str, lines: list[str], out: list[Symbol]) -> None:
    for node in body:
        for block in _blocks(node):
            _walk(block, prefix, lines, out)
        if isinstance(node, _FUNCS):
            out.append(_symbol(node, prefix + node.name, "method" if prefix else "func", lines))
        elif isinstance(node, ast.ClassDef):
            out.append(_symbol(node, prefix + node.name, "class", lines))
            _walk(node.body, prefix + node.name + ".", lines, out)
        elif not prefix and isinstance(node, (ast.Assign, ast.AnnAssign)):
            for name in _const_names(node):
                out.append(_symbol(node, name, "const", lines))


def python_symbols(text: str) -> list[Symbol]:
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        raise SymbolError(f"python syntax error at line {e.lineno}: {e.msg}") from e
    out: list[Symbol] = []
    _walk(tree.body, "", split_lines(text), out)
    return sorted(out, key=lambda s: (s.start, -s.end))
