"""Review fixes for compact_patch: SQL-style `-- ` lines and exact file filtering."""

from __future__ import annotations

from localexec.history.taskinfo import compact_patch

PATCH = """--- a/db.sql
+++ b/db.sql
@@ -1,3 +1,3 @@
 select 1;
--- drop me
+-- keep me
 select 2;
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-x = 1
+x = 2
--- a/data.py
+++ b/data.py
@@ -1 +1 @@
-y = 1
+y = 2
"""


def test_removed_sql_comment_is_not_mistaken_for_a_file_header():
    out = compact_patch(PATCH, "db.sql")
    assert "--- drop me" in out and "+-- keep me" in out
    assert "a.py" not in out and "data.py" not in out


def test_file_filter_is_exact_not_a_substring():
    out = compact_patch(PATCH, "a.py")
    assert "+x = 2" in out and "data.py" not in out and "+y = 2" not in out


def test_unknown_file_reports_no_changes():
    assert compact_patch(PATCH, "nope.py") == "(no matching changes)"


def test_blank_context_lines_are_not_counted_as_changes():
    patch = "--- a/f.py\n+++ b/f.py\n@@ -1,5 +1,5 @@\n a\n\n\n\n-b\n+c\n"
    out = compact_patch(patch).split("\n")
    assert out.count("") <= 1  # only the blank line adjacent to the change is kept
