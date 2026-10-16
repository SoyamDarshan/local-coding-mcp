"""Symbol extraction: outline entries and focused prompt excerpts."""

from __future__ import annotations

from pathlib import Path

from .excerpt import build_excerpt, find_symbols
from .model import Symbol, SymbolError
from .python_lang import python_symbols
from .ts_lang import ts_symbols

SUPPORTED_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}

__all__ = ["Symbol", "SymbolError", "SUPPORTED_EXTS", "build_excerpt", "find_symbols", "list_symbols"]


def list_symbols(rel: str, text: str) -> list[Symbol]:
    ext = Path(rel).suffix.lower()
    if ext == ".py":
        return python_symbols(text)
    if ext in SUPPORTED_EXTS:
        return ts_symbols(rel, text)
    raise SymbolError(f"symbols are not supported for '{ext or rel}' files (supported: {', '.join(sorted(SUPPORTED_EXTS))})")
