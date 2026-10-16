from __future__ import annotations

import pytest

from localexec.fsio.text import BOM, TextError, decode, read_doc, read_text, split_lines


@pytest.mark.parametrize(
    ("raw", "bom", "eol", "text"),
    [
        (b"a\nb\n", False, "\n", "a\nb\n"),
        (b"a\r\nb\r\n", False, "\r\n", "a\nb\n"),
        (BOM + b"a\r\nb\r\n", True, "\r\n", "a\nb\n"),
        (b"a\r\nb\nc\nd\n", False, "\n", "a\nb\nc\nd\n"),  # mixed: LF majority
        (b"a\r\nb\r\nc\n", False, "\r\n", "a\nb\nc\n"),  # mixed: CRLF majority
        (b"", False, "\n", ""),
    ],
)
def test_decode_normalises_and_remembers_style(raw, bom, eol, text):
    doc = decode(raw)
    assert (doc.bom, doc.eol, doc.text) == (bom, eol, text)


@pytest.mark.parametrize("raw", [b"a\nb\n", b"a\r\nb\r\n", BOM + b"x = 1\r\n", BOM + b"x\n"])
def test_render_round_trips_uniform_files(raw):
    assert decode(raw).render() == raw


def test_render_applies_style_to_new_text():
    doc = decode(BOM + b"a\r\n")
    assert doc.render("x\ny\n") == BOM + b"x\r\ny\r\n"


def test_non_utf8_is_a_text_error_naming_the_file():
    with pytest.raises(TextError, match="legacy.py"):
        decode(b"caf\xe9\n", "legacy.py")


def test_read_helpers(tmp_path):
    p = tmp_path / "a.py"
    p.write_bytes(BOM + b"x = 1\r\n")
    assert read_text(p) == "x = 1\n"
    assert read_doc(p).bom is True


def test_split_lines_only_splits_on_lf():
    assert split_lines("a\x0cb\nc d\n") == ["a\x0cb", "c d"]
    assert split_lines("a\nb") == ["a", "b"]
    assert split_lines("") == []
