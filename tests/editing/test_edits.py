import pytest

from localexec.editing.apply import EditApplyError, FileState, apply_edits, read_state, write_atomic
from localexec.editing.parse import Edit, EditParseError, is_blocked_reply, parse_edits
from pathlib import Path

SR = """FILE: a.py
<<<<<<< SEARCH
    return a - b
=======
    return a + b
>>>>>>> REPLACE
"""


def st(text, rel="a.py", existed=True):
    return {rel: FileState(rel, Path(rel), text, existed)}


ident = lambda p: p if p == "a.py" else None


def test_parse_basic_and_fences():
    e = parse_edits("```\n" + SR + "```\n")
    assert len(e) == 1 and e[0].search == ["    return a - b"] and e[0].replace == ["    return a + b"]


def test_parse_multiple_and_full():
    e = parse_edits(SR + "\nFILE: `b.py`\n<<<<<<< FULL\nX = 1\n>>>>>>> END\n")
    assert [x.kind for x in e] == ["sr", "full"] and e[1].path == "b.py"


@pytest.mark.parametrize("bad", [
    "Sure! Here you go:\n" + SR,
    "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n",
    "FILE: a.py\n<<<<<<< SEARCH\nx\n=======\ny\n",
    "nothing useful",
    "FILE: a.py\n<<<<<<< SEARCH\nx\n>>>>>>> REPLACE\n",
])
def test_parse_rejects(bad):
    with pytest.raises(EditParseError):
        parse_edits(bad)


def test_blocked():
    assert is_blocked_reply("BLOCKED: which db?") == "which db?"
    assert is_blocked_reply("```\nBLOCKED: q\n```") == "q"
    assert is_blocked_reply(SR) is None


def test_apply_exact_and_rstrip_fallback():
    out = apply_edits(st("def add(a, b):\n    return a - b  \n"), parse_edits(SR), ident)
    assert out["a.py"] == "def add(a, b):\n    return a + b\n" or "a + b" in out["a.py"]


def test_apply_no_match_and_ambiguous():
    with pytest.raises(EditApplyError) as ei:
        apply_edits(st("x = 1\n"), parse_edits(SR), ident)
    assert "not found" in str(ei.value)
    with pytest.raises(EditApplyError) as ei:
        apply_edits(st("    return a - b\n    return a - b\n"), parse_edits(SR), ident)
    assert "matches 2 places" in str(ei.value)


def test_apply_rejects_unlisted_file_and_placeholders():
    e = parse_edits("FILE: other.py\n<<<<<<< FULL\nx\n>>>>>>> END\n")
    with pytest.raises(EditApplyError) as ei:
        apply_edits(st("x\n"), e, ident)
    assert "not a file you may edit" in str(ei.value)
    e = parse_edits("FILE: a.py\n<<<<<<< FULL\n# ... rest unchanged\n>>>>>>> END\n")
    with pytest.raises(EditApplyError):
        apply_edits(st("x\n"), e, ident)


def test_full_much_shorter_rejected():
    e = parse_edits("FILE: a.py\n<<<<<<< FULL\nx\n>>>>>>> END\n")
    with pytest.raises(EditApplyError):
        apply_edits(st("line\n" * 100), e, ident)


def test_new_file_via_empty_search():
    e = parse_edits("FILE: a.py\n<<<<<<< SEARCH\n=======\nX = 1\n>>>>>>> REPLACE\n")
    assert apply_edits(st("", existed=False), e, ident) == {"a.py": "X = 1\n"}
    with pytest.raises(EditApplyError):
        apply_edits(st("data\n"), e, ident)


def test_atomic_write_preserves_crlf_and_bom(tmp_path):
    p = tmp_path / "a.py"
    p.write_bytes(b"\xef\xbb\xbfdef f():\r\n    return 1\r\n")
    s = {"a.py": read_state("a.py", p)}
    assert s["a.py"].text == "def f():\n    return 1\n"
    new = apply_edits(s, parse_edits("FILE: a.py\n<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE\n"), ident)
    write_atomic(s, new)
    assert p.read_bytes() == b"\xef\xbb\xbfdef f():\r\n    return 2\r\n"
    assert not list(tmp_path.glob(".localexec-*"))


def test_one_bad_block_changes_nothing(tmp_path):
    p = tmp_path / "a.py"
    p.write_text("x = 1\n", encoding="utf-8")
    s = {"a.py": read_state("a.py", p)}
    e = parse_edits(
        "FILE: a.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"
        "FILE: a.py\n<<<<<<< SEARCH\nzzz\n=======\ny\n>>>>>>> REPLACE\n")
    with pytest.raises(EditApplyError):
        apply_edits(s, e, ident)
    assert p.read_text() == "x = 1\n"


def test_markdown_fence_inside_full_block_is_stripped():
    text = "FILE: a.py\n<<<<<<< FULL\n```python\nx = 1\n```\n>>>>>>> END\n"
    assert parse_edits(text)[0].replace == ["x = 1"]


def test_markdown_fence_inside_search_and_replace_is_stripped():
    text = "FILE: a.py\n<<<<<<< SEARCH\n```\nx = 1\n```\n=======\n```\nx = 2\n```\n>>>>>>> REPLACE\n"
    e = parse_edits(text)[0]
    assert e.search == ["x = 1"] and e.replace == ["x = 2"]


def _apply_one(file_text: str, search: str, replace: str) -> str:
    st = FileState("a.tsx", Path("a.tsx"), file_text, True)
    e = Edit("a.tsx", "sr", search.split("\n"), replace.split("\n"))
    return apply_edits({"a.tsx": st}, [e], lambda p: p)["a.tsx"]


def test_search_ignoring_indentation_reindents_the_replacement():
    src = "f() {\n  return (\n    <button a>\n      {label}\n    </button>\n  );\n}\n"
    got = _apply_one(src, "<button a>\n      {label}\n    </button>", "<button a b>\n      {label}\n    </button>")
    assert got == "f() {\n  return (\n    <button a b>\n      {label}\n    </button>\n  );\n}\n"


def test_indentation_insensitive_match_still_requires_uniqueness():
    src = "  x = 1\n    x = 1\n"
    with pytest.raises(EditApplyError, match="matches 2 places"):
        _apply_one(src, "x = 1", "x = 2")


def test_read_state_mixed_line_endings_use_the_majority(tmp_path):
    p = tmp_path / "m.txt"
    p.write_bytes(b"a\nb\r\nc\n")
    st = read_state("m.txt", p)
    assert st.text == "a\nb\nc\n" and st.crlf is False
