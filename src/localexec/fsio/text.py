"""Read and write source text in one canonical form.

Everything outside this module works on normalised text: LF line endings, no BOM.
`Doc.render` restores the file's original BOM and (majority) line ending on write.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BOM = b"\xef\xbb\xbf"


class TextError(Exception):
    """The file is not valid UTF-8 text."""


@dataclass(frozen=True)
class Doc:
    text: str  # LF only, BOM stripped
    bom: bool = False
    eol: str = "\n"  # original majority line ending: "\n" or "\r\n"

    def render(self, text: str | None = None) -> bytes:
        body = self.text if text is None else text
        if self.eol != "\n":
            body = body.replace("\n", self.eol)
        data = body.encode("utf-8")
        return BOM + data if self.bom else data


def _majority_eol(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def decode(data: bytes, name: str = "file") -> Doc:
    """Bytes to Doc. Raises TextError for non-UTF-8 content."""
    bom = data.startswith(BOM)
    if bom:
        data = data[len(BOM):]
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise TextError(f"{name}: not valid UTF-8 text ({e.reason})") from e
    return Doc(raw.replace("\r\n", "\n"), bom, _majority_eol(raw))


def read_doc(path: Path, name: str | None = None) -> Doc:
    return decode(path.read_bytes(), name or path.name)


def read_text(path: Path, name: str | None = None) -> str:
    return read_doc(path, name).text


def normalize_bytes(data: bytes | None) -> str | None:
    """Lenient bytes -> normalised text for baselines and diffs (never raises; None stays None)."""
    if data is None:
        return None
    if data.startswith(BOM):
        data = data[len(BOM):]
    return data.decode("utf-8", "replace").replace("\r\n", "\n")


def split_keepends(text: str) -> list[str]:
    """Like str.splitlines(keepends=True) but splitting on LF only."""
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def split_lines(text: str) -> list[str]:
    """Lines of normalised text, split on LF only (str.splitlines also splits on \\x0c, \\u2028, ...)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines
