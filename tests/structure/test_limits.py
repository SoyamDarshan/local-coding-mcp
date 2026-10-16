from __future__ import annotations
from pathlib import Path
from localexec.structure.limits import DirReport, is_source_file, over_limit, scan_dirs

def test_is_source_file():
    assert is_source_file("a.py") is True
    assert is_source_file("B.TS") is True
    assert is_source_file("x.tsx") is True
    assert is_source_file("__init__.py") is False
    assert is_source_file("index.ts") is False
    assert is_source_file("README.md") is False
    assert is_source_file("data.json") is False

def test_scan_counts_direct_files_and_subdirs(tmp_path):
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "notes.md").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "c.py").write_text("", encoding="utf-8")
    assert scan_dirs(tmp_path, []) == [DirReport(".", 2, 1), DirReport("pkg", 1, 0)]

def test_scan_ignores_matching_dirs(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "y.py").write_text("", encoding="utf-8")
    result = scan_dirs(tmp_path, ["node_modules/**", "node_modules"])
    assert all(report.path != "node_modules" for report in result)
    assert result[0].subdirs == 1

def test_scan_missing_root_returns_empty(tmp_path):
    assert scan_dirs(tmp_path / "nope", []) == []

def test_over_limit():
    reports = [
        DirReport("a", 11, 0),
        DirReport("b", 3, 11),
        DirReport("c", 10, 10)
    ]
    assert over_limit(reports) == [DirReport("a", 11, 0), DirReport("b", 3, 11)]


def test_index_files_and_default_ignored_dirs_do_not_count(tmp_path):
    from localexec.settings.config import DEFAULT_IGNORE

    (tmp_path / "a.js").write_text("1", encoding="utf-8")
    (tmp_path / "index.js").write_text("1", encoding="utf-8")
    (tmp_path / "index.tsx").write_text("1", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__pycache__").mkdir()
    reports = {r.path: r for r in scan_dirs(tmp_path, DEFAULT_IGNORE)}
    assert reports["."].source_files == 1 and reports["."].subdirs == 1
    assert set(reports) == {".", "pkg"} and reports["pkg"].subdirs == 0
