"""Prompt text and prompt assembly under a token budget."""

from __future__ import annotations

from pathlib import Path

from ..settings.common import est_tokens
from ..settings.config import Config
from ..editing.apply import FileState
from ..fsio.text import TextError, read_text

SYSTEM_PROMPT = (
    "You are a precise code implementation assistant. Modify only the code named in the spec. "
    "Do not refactor, rename, or improve anything else. Follow the conventions exactly. "
    "If the spec is ambiguous or missing information, reply `BLOCKED: <specific question>` "
    "instead of guessing. Output only edit blocks in the required format, no explanations. "
    "Do not add dependencies unless the spec lists them."
)

FORMAT_PROMPT = """
REQUIRED OUTPUT FORMAT (strict). For each change write:

FILE: relative/path/to/file
<<<<<<< SEARCH
existing lines copied exactly from the file (enough lines to be unique)
=======
the replacement lines
>>>>>>> REPLACE

To create a NEW file, or fully rewrite a SMALL file, write:

FILE: relative/path/to/file
<<<<<<< FULL
the complete file content
>>>>>>> END

Rules: only edit files listed under "Files to edit". SEARCH text must match the file exactly,
including indentation, and must match exactly one place. Never use placeholders such as
"... rest unchanged". Several blocks per file are fine. No text outside the blocks, no markdown.
""".strip()



def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text[: max(0, limit)]
    return cut + f"\n[... TRUNCATED: {len(text) - len(cut)} more characters omitted ...]", True


def _head_text(cfg: Config, spec: str, failure: str | None) -> str:
    head = []
    if cfg.conventions.strip():
        head.append("## Conventions\n" + cfg.conventions.strip())
    head.append("## Task spec\n" + spec.strip())
    if failure and "Check `" in failure:
        head.append(
            "## Previous attempt\nYour previous edits were applied (see current files below) but "
            "these checks failed. Fix them with new edit blocks for the files shown; do not reply BLOCKED "
            "for check errors (BLOCKED is only for an ambiguous spec).\n" + failure
        )
    elif failure:
        head.append("## Previous attempt\n" + failure)
    return "\n\n".join(head)


EXCERPT_NOTE = (
    "Some files below are EXCERPTS: only the symbols you must change (plus nearby lines) are shown. "
    "Lines like `[... lines 3-40 omitted ...]` are NOT in the file: never put them in SEARCH, and "
    "do not use FULL for an excerpted file."
)


def _edit_text(edit_states: dict[str, FileState], excerpts: dict[str, str]) -> str:
    parts = ["## Files to edit (current contents)"]
    if excerpts:
        parts.append(EXCERPT_NOTE)
    for rel, st in edit_states.items():
        if rel in excerpts:
            parts.append(f"=== {rel} (EXCERPT) ===\n{excerpts[rel]}\n=== end {rel} ===")
        elif st.existed:
            parts.append(f"=== {rel} ===\n{st.text}\n=== end {rel} ===")
        else:
            parts.append(f"=== {rel} (NEW FILE, does not exist yet) ===\n=== end {rel} ===")
    return "\n".join(parts)


def _context_text(context: dict[str, Path], remaining: int) -> tuple[str, list[str]]:
    notes: list[str] = []
    parts: list[str] = []
    for rel, path in context.items():
        if remaining < 400:
            notes.append(f"{rel}:omitted")
            continue
        try:
            raw = read_text(path, rel)
        except (OSError, TextError):
            notes.append(f"{rel}:unreadable")
            continue
        body, cut = _truncate(raw, remaining - 80)
        if cut:
            notes.append(f"{rel}:truncated")
        part = f"=== {rel} (read-only context) ===\n{body}\n=== end {rel} ==="
        parts.append(part)
        remaining -= len(part)
    text = ("\n\n## Context files (read-only, do not edit)\n" + "\n".join(parts)) if parts else ""
    return text, notes


def build_prompt(
    cfg: Config,
    spec: str,
    edit_states: dict[str, FileState],
    context: dict[str, Path],
    failure: str | None,
    excerpts: dict[str, str] | None = None,
) -> tuple[str, list[str], str | None]:
    """Return (prompt, truncated_notes, blocked_reason)."""
    head_text = _head_text(cfg, spec, failure)
    edit_text = _edit_text(edit_states, excerpts or {})
    tail = "\n\nReply with edit blocks only, or `BLOCKED: <question>`."
    fixed = len(SYSTEM_PROMPT) + len(FORMAT_PROMPT) + len(head_text) + len(edit_text) + len(tail) + 200
    remaining = cfg.prompt_budget_chars - fixed
    if remaining < 0:
        return "", [], (
            f"prompt too large for the local model (~{est_tokens('x' * fixed)} tokens vs budget "
            f"~{int(cfg.prompt_budget_chars / 3.5)}): split the task or shrink files_to_edit"
        )
    ctx_text, notes = _context_text(context, remaining)
    return f"{head_text}\n\n{edit_text}{ctx_text}{tail}", notes, None
