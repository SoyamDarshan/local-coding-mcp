from __future__ import annotations

import subprocess

from conftest import git

from localexec.vcs import gitutil


def test_unborn_head_is_none(tmp_path):
    git(tmp_path, "init", "-q")
    assert gitutil.head_sha(tmp_path) is None


def test_file_at_head_returns_committed_bytes_even_when_dirty(proj):
    (proj / "util.py").write_bytes(b"X = 2\n")
    assert gitutil.file_at_head(proj, "util.py") == b"X = 1\n"
    assert gitutil.file_at_head(proj, "missing.py") is None


def test_file_at_head_works_from_a_subdirectory_root(proj):
    sub = proj / "pkg"
    sub.mkdir()
    (sub / "m.py").write_bytes(b"A = 1\n")
    git(proj, "add", "-A")
    subprocess.run(["git", "commit", "-qm", "sub"], cwd=proj, check=True, capture_output=True)
    assert gitutil.file_at_head(sub, "m.py") == b"A = 1\n"
