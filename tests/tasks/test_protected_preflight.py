"""implement_task refuses to edit files that control execution or Claude's configuration."""

from __future__ import annotations

import os

import pytest
from conftest import FIX, FakeChat, cfg, run

CREATE_PYPROJECT = "FILE: pyproject.toml\n<<<<<<< FULL\n[tool]\n>>>>>>> END\n"


def new_file_reply(name: str) -> str:
    return f"FILE: {name}\n<<<<<<< FULL\nX = 1\n>>>>>>> END\n"


def assert_refused(proj, chat, r):
    assert r["status"] == "error" and r["escalate"] is False
    assert "protected file" in r["error"] and "allow_protected" not in r["error"]
    assert chat.calls == []  # no model call
    assert not (proj / ".localexec" / "T1.json").exists()  # no state written


@pytest.mark.parametrize(
    "name",
    ["pyproject.toml", "tests/new/conftest.py", ".github/workflows/ci.yml", "CLAUDE.md", ".scmexec.json", ".mcp.json"],
)
def test_protected_targets_are_refused(proj, name):
    cfg(proj)
    chat = FakeChat(FIX)
    assert_refused(proj, chat, run(proj, chat, files_to_edit=[name]))


def test_absolute_path_is_refused(proj):
    cfg(proj)
    chat = FakeChat(FIX)
    assert_refused(proj, chat, run(proj, chat, files_to_edit=[str(proj / "pyproject.toml")]))


@pytest.mark.parametrize(
    "name", ["./PyProject.toml", "sub/../pyproject.toml", ".github\\workflows\\ci.yml", ".GITHUB/workflows/ci.yml"]
)
def test_odd_spellings_are_refused(proj, name):
    cfg(proj)
    chat = FakeChat(FIX)
    assert_refused(proj, chat, run(proj, chat, files_to_edit=[name]))


def test_one_protected_file_refuses_the_whole_call(proj):
    cfg(proj)
    before = (proj / "calc.py").read_bytes()
    chat = FakeChat(FIX)
    assert_refused(proj, chat, run(proj, chat, files_to_edit=["calc.py", "pyproject.toml"]))
    assert (proj / "calc.py").read_bytes() == before


def test_message_names_at_most_three_paths(proj):
    cfg(proj)
    names = ["pyproject.toml", "setup.py", "tox.ini", "Makefile", "CLAUDE.md"]
    chat = FakeChat(FIX)
    r = run(proj, chat, files_to_edit=names)
    assert_refused(proj, chat, r)
    assert "(+2 more)" in r["error"]
    assert all(n in r["error"] for n in names[:3]) and not any(n in r["error"] for n in names[3:])


def test_protected_file_as_context_is_accepted(proj):
    cfg(proj)
    (proj / "pyproject.toml").write_bytes(b"[tool]\n")
    chat = FakeChat(FIX)
    r = run(proj, chat, context_files=["pyproject.toml"])
    assert r["status"] == "passed"
    assert "pyproject.toml" in chat.calls[0][1]["content"]


@pytest.mark.parametrize("name", ["my_conftest.py", "src/package_json_helpers.py"])
def test_lookalike_new_files_are_accepted(proj, name):
    cfg(proj)
    r = run(proj, FakeChat(new_file_reply(name)), files_to_edit=[name])
    assert r["status"] == "passed"


def test_symlink_to_protected_file_is_refused(proj):
    cfg(proj)
    (proj / "pyproject.toml").write_bytes(b"[tool]\n")
    try:
        os.symlink(proj / "pyproject.toml", proj / "alias.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    chat = FakeChat(FIX)
    assert_refused(proj, chat, run(proj, chat, files_to_edit=["alias.py"]))


def test_allow_protected_lets_a_file_through(proj):
    cfg(proj, extra=',"allow_protected":["pyproject.toml"]')
    r = run(proj, FakeChat(CREATE_PYPROJECT), files_to_edit=["pyproject.toml"])
    assert r["status"] == "passed"


def test_protected_paths_adds_a_pattern(proj):
    cfg(proj, extra=',"protected_paths":["util.py"]')
    chat = FakeChat(FIX)
    assert_refused(proj, chat, run(proj, chat, files_to_edit=["util.py"]))
