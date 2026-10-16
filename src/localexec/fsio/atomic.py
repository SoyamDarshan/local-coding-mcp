"""Atomic file replacement that keeps permissions, plus directory bookkeeping for rollbacks."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory and os.replace; keeps the old file's mode."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".localexec-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def missing_dirs(parent: Path) -> list[Path]:
    """Directories above (and including) `parent` that do not exist yet, shallowest first."""
    out: list[Path] = []
    cur = parent
    while not cur.exists() and cur != cur.parent:
        out.append(cur)
        cur = cur.parent
    return out[::-1]
