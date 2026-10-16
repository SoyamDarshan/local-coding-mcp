import json
import os

import pytest

from conftest import write_cfg
from localexec.explore.find import find
from localexec.explore.outline import outline


@pytest.fixture
def repo(tmp_path):
    root = tmp_path.resolve()
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("import os\n\n\ndef alpha():\n    return 'needle'\n", encoding="utf-8")
    (root / "src" / "b.ts").write_text("export const beta = () => 1;\n// Needle here\n", encoding="utf-8")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "x.js").write_text("needle\n", encoding="utf-8")
    (root / "bin.dat").write_bytes(b"needle\0\0binary")
    (root / ".env").write_text("needle=secret\n", encoding="utf-8")
    return root


def test_outline_python_and_ts(repo):
    r = outline(repo, "src/a.py")
    assert r["items"] == ["4-5|func|alpha|def alpha():"] and r["total"] == 1 and r["lines"] == 5
    assert outline(repo, "src/b.ts")["items"][0].startswith("1-1|func|beta|")
    assert len(json.dumps(r)) < 400


def test_outline_truncates_and_reports_more(repo):
    (repo / "big.py").write_text("".join(f"def f{i}():\n    pass\n\n" for i in range(200)), encoding="utf-8")
    r = outline(repo, "big.py", max_items=10)
    assert len(r["items"]) == 10 and r["more"] == 190 and r["total"] == 200
    assert len(json.dumps(outline(repo, "big.py", max_items=200))) < 4000


def test_outline_rejects_bad_paths(repo):
    assert "escapes" in outline(repo, "../x.py")["error"]
    assert "ignored" in outline(repo, "node_modules/pkg/x.js")["error"]
    assert "not supported" in outline(repo, "bin.dat")["error"] or "readable" in outline(repo, "bin.dat")["error"]
    assert "not a readable file" in outline(repo, "nope.py")["error"]
    (repo / "bad.py").write_text("def (:\n", encoding="utf-8")
    assert "syntax error" in outline(repo, "bad.py")["error"]


def test_find_basic_glob_and_skips(repo):
    r = find(repo, "needle")
    assert r["matches"] == ["src/a.py:5:return 'needle'"] and r["truncated"] is False
    both = find(repo, "needle", ignore_case=True)["matches"]
    assert sorted(m.split(":")[0] for m in both) == ["src/a.py", "src/b.ts"]
    assert find(repo, "needle", glob="*.ts", ignore_case=True)["matches"] == ["src/b.ts:2:// Needle here"]
    joined = " ".join(find(repo, "needle|secret", ignore_case=True)["matches"])
    assert "node_modules" not in joined and ".env" not in joined and "bin.dat" not in joined


def test_find_limits_and_errors(repo):
    for i in range(50):
        (repo / f"m{i}.txt").write_text("hit\n", encoding="utf-8")
    r = find(repo, "hit", max_results=7)
    assert len(r["matches"]) == 7 and r["truncated"] is True
    assert "bad pattern" in find(repo, "(unclosed")["error"]
    (repo / "long.txt").write_text("x" * 5000 + "TAIL\n", encoding="utf-8")
    assert find(repo, "TAIL")["matches"] == []  # beyond the scan window, and never dumped whole
    snippet = find(repo, "x{10}", glob="long.txt")["matches"][0]
    assert len(snippet) < 160


def test_find_uses_config_ignore(repo):
    write_cfg(repo, '{"ignore": ["src/**"]}')
    assert find(repo, "needle")["matches"] == []


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_find_skips_symlink_escape(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("out") / "secret.txt"
    outside.write_text("needle outside\n")
    (repo / "link.txt").symlink_to(outside)
    assert all("link.txt" not in m for m in find(repo, "needle")["matches"])
