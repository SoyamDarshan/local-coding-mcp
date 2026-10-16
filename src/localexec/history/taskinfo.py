"""Read-only task introspection: list_tasks, show_patch."""

from __future__ import annotations

import json
from pathlib import Path

from ..settings.config import STATE_DIR


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0  # vanished while listing


def manifests(root: Path, limit: int | None = None) -> tuple[list[dict], int]:
    """Newest manifests first (parsing stops after `limit` valid ones) and the total number of files."""
    paths = sorted((root / STATE_DIR).glob("*.json"), key=_mtime, reverse=True)
    out: list[dict] = []
    for m in paths:
        if limit is not None and len(out) >= limit:
            break
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "task_id" in data:
            out.append(data)
    return out, len(paths)


def _short_files(files: list[str]) -> str:
    shown = ",".join(files[:3])
    return shown + (f"+{len(files) - 3}" if len(files) > 3 else "")


def list_tasks(root: Path, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 50))
    ms, total = manifests(root, limit)
    rows = []
    for m in ms:
        flag = "|reverted" if m.get("reverted") else ""
        rows.append(
            f"{m['task_id']}|{m.get('status') or '?'}{flag}|{m.get('attempts', 0)}a|"
            f"{_short_files(list(m.get('files', {})))}|{m.get('summary', '')}"
        )
    return {"total": total, "tasks": rows, "format": "id|status|attempts|files|spec"}


def _is_header(lines: list[str], i: int) -> bool:
    """A real file header: `--- x`, `+++ y`, then a hunk. A removed line like `-- note` also starts `--- `."""
    return (
        lines[i].startswith("--- ") and i + 2 < len(lines)
        and lines[i + 1].startswith("+++ ") and lines[i + 2].startswith("@@")
    )


def _header_paths(sec: list[str]) -> set[str]:
    out = set()
    for ln in sec[:2]:
        name = ln[4:].split("\t")[0].strip()
        out.add(name[2:] if name[:2] in ("a/", "b/") else name)
    return out


def compact_patch(text: str, file: str | None = None, max_lines: int = 60, max_chars: int = 2500) -> str:
    """Keep headers, hunk markers and changed lines plus one context line around changes."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # artifact of the final newline
    sections: list[list[str]] = []
    for i, line in enumerate(lines):
        if _is_header(lines, i):
            sections.append([])
        if sections:
            sections[-1].append(line)
    wanted = file.replace("\\", "/").removeprefix("./") if file else None
    out: list[str] = []
    for sec in sections:
        if wanted and wanted not in _header_paths(sec):
            continue
        changed = {i for i, ln in enumerate(sec) if i >= 2 and ln[:1] in ("+", "-")}
        keep = {0, 1}
        for i in changed:
            keep.update({i - 1, i, i + 1})
        for i, ln in enumerate(sec):
            if i in keep or ln.startswith("@@"):
                out.append(ln)
    result: list[str] = []
    size = 0
    for ln in out:
        if len(result) >= max_lines or size + len(ln) > max_chars:
            result.append(f"[... {len(out) - len(result)} more diff lines; read the .patch file ...]")
            break
        result.append(ln[:200])
        size += len(ln) + 1
    return "\n".join(result) if result else "(no matching changes)"


def show_patch(root: Path, task_id: str, file: str | None = None, max_lines: int = 60) -> str:
    from ..settings.common import TaskError, check_task_id

    try:
        check_task_id(task_id)
    except TaskError:
        return json.dumps({"status": "error", "error": "invalid task_id"})
    p = root / STATE_DIR / f"{task_id}.patch"
    if not p.exists():
        return json.dumps({"status": "error", "error": f"no patch for task '{task_id}'"})
    return compact_patch(p.read_text(encoding="utf-8"), file, max(5, min(int(max_lines), 300)))
