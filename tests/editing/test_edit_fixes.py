"""Regression tests for the edit-engine review findings (indentation, fences, dividers, safe writes)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from localexec.editing.apply import EditApplyError, FileState, StaleFileError, apply_edits, read_state, write_atomic
from localexec.editing.parse import Edit, EditParseError, parse_edits


def apply_one(text: str, search: list[str], replace: list[str], name: str = "a.py") -> str:
    st = FileState(name, Path(name), text, True)
    return apply_edits({name: st}, [Edit(name, "sr", search, replace)], lambda p: p)[name]


def test_wrapping_a_line_in_a_block_keeps_the_new_nesting():
    src = "class A:\n    def f(self):\n        return 1\n"
    got = apply_one(src, ["def f(self):", "    return 1"], ["def f(self):", "    if c:", "        return 1"])
    assert got == "class A:\n    def f(self):\n        if c:\n            return 1\n"


def test_spaces_from_the_model_become_tabs_in_a_tab_indented_file():
    src = "def f():\n\tx = 1\n\ty = 2\n"
    got = apply_one(src, ["def f():", "    x = 1"], ["def f():", "    x = 1", "    if x:", "        y = 3"])
    assert got == "def f():\n\tx = 1\n\tif x:\n\t\ty = 3\n\ty = 2\n"
    compile(got, "a.py", "exec")


def test_unchanged_lines_keep_the_files_own_indentation():
    src = "f() {\n  return (\n    <b a>\n      {label}\n    </b>\n  );\n}\n"
    got = apply_one(src, ["<b a>", "      {label}", "    </b>"], ["<b a d>", "      {label}", "    </b>"])
    assert got == "f() {\n  return (\n    <b a d>\n      {label}\n    </b>\n  );\n}\n"


def test_markdown_content_with_its_own_fences_is_not_stripped():
    body = "```bash\npip install x\n```\n\nText\n\n```\nend\n```"
    text = f"FILE: R.md\n<<<<<<< FULL\n{body}\n>>>>>>> END\n"
    assert parse_edits(text)[0].replace == body.split("\n")


def test_a_second_divider_in_the_replace_part_is_rejected_as_ambiguous():
    text = "FILE: d.rst\n<<<<<<< SEARCH\nTitle\n=======\n=======\nNew\n=======\n>>>>>>> REPLACE\n"
    with pytest.raises(EditParseError, match="ambiguous"):
        parse_edits(text)


def test_empty_full_cannot_wipe_a_file():
    st = FileState("a.py", Path("a.py"), "x = 1\ny = 2\n", True)
    with pytest.raises(EditApplyError, match="empty"):
        apply_edits({"a.py": st}, [Edit("a.py", "full", [], [""])], lambda p: p)


def test_full_keeps_a_missing_final_newline():
    st = FileState("a.txt", Path("a.txt"), "one", True)
    got = apply_edits({"a.txt": st}, [Edit("a.txt", "full", [], ["two"])], lambda p: p)
    assert got["a.txt"] == "two"


def test_mixed_line_endings_use_the_majority_style(tmp_path):
    p = tmp_path / "m.txt"
    p.write_bytes(b"a\r\nb\nc\nd\n")
    assert read_state("m.txt", p).crlf is False
    p.write_bytes(b"a\r\nb\r\nc\n")
    assert read_state("m.txt", p).crlf is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_write_keeps_the_file_mode(tmp_path):
    p = tmp_path / "run.sh"
    p.write_bytes(b"echo a\n")
    p.chmod(0o755)
    st = read_state("run.sh", p)
    write_atomic({"run.sh": st}, {"run.sh": "echo b\n"})
    assert p.read_bytes() == b"echo b\n" and (p.stat().st_mode & 0o777) == 0o755


def test_failed_write_rolls_back_files_and_new_directories(tmp_path):
    (tmp_path / "blocker").write_text("i am a file", encoding="utf-8")
    new = FileState("new/sub/f.py", tmp_path / "new" / "sub" / "f.py", "", False)
    bad = FileState("blocker/x.py", tmp_path / "blocker" / "x.py", "", False)
    with pytest.raises(OSError):
        write_atomic({new.rel: new, bad.rel: bad}, {new.rel: "a = 1\n", bad.rel: "b = 2\n"})
    assert not (tmp_path / "new").exists()


def test_write_refuses_when_the_file_changed_after_it_was_read(tmp_path):
    p = tmp_path / "a.py"
    p.write_bytes(b"x = 1\n")
    st = read_state("a.py", p)
    p.write_bytes(b"x = 99  # user edit\n")
    with pytest.raises(StaleFileError):
        write_atomic({"a.py": st}, {"a.py": "x = 2\n"})
    assert p.read_bytes() == b"x = 99  # user edit\n"


def test_write_refuses_when_a_new_file_appeared_meanwhile(tmp_path):
    st = read_state("n.py", tmp_path / "n.py")
    (tmp_path / "n.py").write_bytes(b"theirs\n")
    with pytest.raises(StaleFileError):
        write_atomic({"n.py": st}, {"n.py": "mine\n"})
    assert os.path.getsize(tmp_path / "n.py") == 7
