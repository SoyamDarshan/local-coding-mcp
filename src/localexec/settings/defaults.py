"""Shared defaults: the coding-standards limits.

Lives in settings so config can use it without importing the gates package.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Standards:
    max_function_lines: int = 50
    max_file_lines: int = 500
    warn_file_lines: int = 300
    exempt: list[str] = field(
        default_factory=lambda: ["migrations/**", "generated/**", "*.min.js", "*.d.ts", "*.generated.*"]
    )
