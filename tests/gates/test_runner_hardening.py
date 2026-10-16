"""Review fixes for the check runner: bounded output, tail kept, cmd.exe and command-line guards."""

from __future__ import annotations

from conftest import PY

from localexec.gates import checks
from localexec.settings.config import Check


def test_huge_output_is_bounded_but_keeps_start_and_end(tmp_path):
    code = "import sys; sys.stdout.write('START' + 'x' * 2_000_000 + 'END')"
    r = checks.run_check(Check("big", [PY, "-c", code]), tmp_path)
    assert r.ok and len(r.output) < checks.MAX_CAPTURE + 200
    assert r.output.startswith("START") and r.output.endswith("END") and "characters truncated" in r.output


def test_small_output_is_untouched(tmp_path):
    r = checks.run_check(Check("small", [PY, "-c", "print('hello')"]), tmp_path)
    assert r.output.strip() == "hello" and "truncated" not in r.output


def test_timeout_keeps_partial_output(tmp_path):
    code = "import sys, time; print('partial', flush=True); time.sleep(30)"
    r = checks.run_check(Check("slow", [PY, "-c", code], timeout=1), tmp_path)
    assert r.timed_out and "partial" in r.output and "TIMEOUT" in r.output


def test_excerpt_keeps_the_tail_where_summaries_live():
    output = "\n".join([f"line {i}" for i in range(100)] + ["== 3 failed, 5 passed =="])
    text = checks.excerpt(output, 30, 2000)
    assert "line 0" in text and "== 3 failed, 5 passed ==" in text and "[...]" in text
    assert len(text.splitlines()) <= 30


def test_cmd_shims_reject_shell_metacharacters_in_arguments():
    assert checks._argv_problem("C:/x/eslint.cmd", ["C:/x/eslint.cmd", "a&b.ts"]) is not None
    assert checks._argv_problem("C:/x/eslint.CMD", ["C:/x/eslint.CMD", "100%.ts"]) is not None
    assert checks._argv_problem("C:/x/eslint.cmd", ["C:/x/eslint.cmd", "src/a.ts"]) is None
    assert checks._argv_problem("/usr/bin/tool", ["/usr/bin/tool", "a&b.ts"]) is None  # real executables are fine


def test_overlong_command_lines_are_refused_with_a_clear_message():
    argv = ["tool", *["x" * 100 for _ in range(400)]]
    assert "too many files" in (checks._argv_problem("tool", argv) or "")
