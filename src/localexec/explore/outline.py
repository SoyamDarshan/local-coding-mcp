"""outline(path): symbols of one file with line ranges, in a small result."""

from __future__ import annotations

from pathlib import Path

from ..settings.common import err
from ..settings.config import ConfigError, load_config
from ..fsio.text import TextError, read_text, split_lines
from ..settings.safety import PathError, glob_match, rel_posix, resolve_in_root
from ..symbols import SymbolError, list_symbols

MAX_FILE_BYTES = 1_000_000
MAX_CHARS = 3000


def outline(root: Path, path: str, max_items: int = 60) -> dict:
    try:
        cfg = load_config(root)
        full = resolve_in_root(root, path)
    except (ConfigError, PathError) as e:
        return err(str(e))
    rel = rel_posix(root, full)
    if glob_match(rel, cfg.ignore):
        return err(f"'{rel}' is ignored by config")
    if not full.is_file() or full.stat().st_size > MAX_FILE_BYTES:
        return err(f"'{rel}' is not a readable file under {MAX_FILE_BYTES // 1000} KB")
    try:
        text = read_text(full, rel)
        symbols = list_symbols(rel, text)
    except (SymbolError, TextError, OSError) as e:
        return err(str(e))
    items: list[str] = []
    size = 0
    for s in symbols[: max(1, max_items)]:
        line = f"{s.start}-{s.end}|{s.kind}|{s.name}|{s.signature}"
        if size + len(line) > MAX_CHARS:
            break
        items.append(line)
        size += len(line) + 1
    out: dict = {"path": rel, "lines": len(split_lines(text)), "total": len(symbols), "items": items}
    if len(items) < len(symbols):
        out["more"] = len(symbols) - len(items)
    out["format"] = "lines|kind|name|signature"
    return out
