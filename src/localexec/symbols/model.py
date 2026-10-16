"""Shared symbol types."""

from __future__ import annotations

from dataclasses import dataclass


class SymbolError(Exception):
    """Short, user-facing problem (unsupported language, parse failure, missing dependency)."""


@dataclass(frozen=True)
class Symbol:
    name: str  # qualified for methods: "Class.method"
    kind: str  # func | method | class | const | interface | type | enum
    start: int  # 1-based, inclusive (includes decorators / the `export` keyword)
    end: int
    signature: str  # first line(s) of the definition, trimmed
