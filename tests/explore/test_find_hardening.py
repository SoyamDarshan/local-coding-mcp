"""Review fixes for find: catastrophic regexes, BOM files, output caps, skipped files."""

from __future__ import annotations

import time

from localexec.explore.find import find
from localexec.fsio.text import BOM


def test_catastrophic_pattern_returns_quickly_with_an_error(tmp_path):
    (tmp_path / "a.txt").write_text("a" * 40 + "!\n", encoding="utf-8")
    start = time.monotonic()
    out = find(tmp_path, r"^(a|aa)+$")
    assert out["status"] == "error" and "too slow" in out["error"]
    assert time.monotonic() - start < 5


def test_bom_file_matches_at_line_one_without_the_bom(tmp_path):
    (tmp_path / "b.py").write_bytes(BOM + b"import os\n")
    assert find(tmp_path, r"^import os$")["matches"] == ["b.py:1:import os"]


def test_form_feed_does_not_shift_line_numbers(tmp_path):
    (tmp_path / "f.py").write_bytes(b"a = 1\n\x0c\nneedle = 2\n")
    assert find(tmp_path, "needle")["matches"] == ["f.py:3:needle = 2"]


def test_skipped_files_are_counted(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\0\1\2")
    (tmp_path / "latin.txt").write_bytes(b"caf\xe9 needle\n")
    (tmp_path / "ok.txt").write_text("needle\n", encoding="utf-8")
    out = find(tmp_path, "needle")
    assert out["matches"] == ["ok.txt:1:needle"] and out["skipped"] == 2


def test_total_output_is_capped(tmp_path):
    (tmp_path / "many.txt").write_text(("needle " + "x" * 100 + "\n") * 100, encoding="utf-8")
    out = find(tmp_path, "needle", max_results=100)
    assert sum(len(m) for m in out["matches"]) <= 3000 and out["truncated"] is True
