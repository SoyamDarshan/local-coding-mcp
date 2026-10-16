"""Review fixes: the standards gate must not silently pass files it cannot read or parse."""

from __future__ import annotations

import json

from conftest import git, write_cfg

from localexec import core
from localexec.gates import standards as st
from localexec.fsio.text import BOM

STD = st.Standards(max_function_lines=5, max_file_lines=40, warn_file_lines=20)
LONG_FN = "def f():\n" + "".join(f"    x{i} = {i}\n" for i in range(10)) + "    return 1\n"


def run(tmp_path, rel, data: bytes, base=None):
    (tmp_path / rel).write_bytes(data)
    return st.check_files(tmp_path, STD, [rel], {rel: base})


def test_bom_does_not_hide_a_long_function(tmp_path):
    res = run(tmp_path, "b.py", BOM + LONG_FN.encode())
    assert any("b.py::f" in m for m in res.failures)


def test_crlf_file_is_counted_like_an_lf_file(tmp_path):
    res = run(tmp_path, "c.py", LONG_FN.replace("\n", "\r\n").encode())
    assert any("c.py::f" in m for m in res.failures)


def test_syntax_error_in_a_changed_python_file_fails(tmp_path):
    res = run(tmp_path, "bad.py", b"def f(:\n    pass\n")
    assert any("cannot be parsed" in m for m in res.failures)


def test_non_utf8_file_is_reported_not_silently_skipped(tmp_path):
    res = run(tmp_path, "latin.py", b"x = 'caf\xe9'\n")
    assert res.failures == [] and any("not valid UTF-8" in m for m in res.warnings)


def test_docstrings_do_not_count_towards_file_length(tmp_path):
    doc = '"""' + "\n".join(f"line {i}" for i in range(100)) + '\n"""\n'
    res = run(tmp_path, "d.py", (doc + "X = 1\n").encode())
    assert res.failures == [] and res.warnings == []


def test_run_checks_uses_head_as_baseline_for_dirty_legacy_files(proj):
    legacy = "def old():\n" + "".join(f"    x{i} = {i}\n" for i in range(60)) + "    return 1\n"
    (proj / "legacy.py").write_bytes(legacy.encode())
    git(proj, "add", "-A")
    git(proj, "commit", "-qm", "legacy")
    (proj / "legacy.py").write_bytes((legacy + "\nY = 2\n").encode())  # unrelated edit, function untouched
    write_cfg(proj, json.dumps({"standards": True}))
    out = core.run_checks(proj)
    assert out["status"] == "passed", out


def test_ignore_marker_works_on_any_line_of_a_multiline_signature(tmp_path):
    body = "".join(f"    x{i} = {i}\n" for i in range(10))
    src = f"def f(\n    a,\n):  # lintlen: ignore\n{body}    return 1\n"
    res = run(tmp_path, "m.py", src.encode())
    assert res.failures == []
