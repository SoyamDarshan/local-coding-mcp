import pytest

from conftest import FIX, PY, FakeChat, git, run, write_cfg
from localexec import core
from localexec.settings.config import ConfigError, load_config

STD = ',"standards":{"max_function_lines":5,"max_file_lines":40,"warn_file_lines":20}'


def setup(proj, checks="", extra=""):
    write_cfg(proj, '{"checks":[' + checks + "]" + extra + "}")
    git(proj, "add", ".localexec.json"); git(proj, "commit", "-qm", "cfg")



def scoped_check(expected, filt=""):
    code = f"import sys; sys.exit(0 if sys.argv[1:]=={expected!r} else 7)"
    import json
    d = {"name": "scoped", "argv": [PY, "-c", code, "{files}"]}
    if filt:
        d["files_filter"] = filt
    return json.dumps(d)


def test_files_placeholder_gets_changed_files_only(proj):
    setup(proj, scoped_check(["calc.py"]))
    assert run(proj, FakeChat(FIX))["status"] == "passed"


def test_files_filter_skips_and_run_checks_reports_skipped(proj):
    setup(proj, scoped_check(["x"], ["*.ts"]))
    assert run(proj, FakeChat(FIX))["status"] == "passed"  # skipped, not failed
    r = core.run_checks(proj)
    assert r["status"] == "passed" and r["results"][0]["skipped"] is True


def test_leading_dash_filename_cannot_become_an_option(proj):
    setup(proj, scoped_check(["./-x.py"]))
    new = "FILE: -x.py\n<<<<<<< FULL\nA = 1\n>>>>>>> END\n"
    assert run(proj, FakeChat(new), files_to_edit=["-x.py"])["status"] == "passed"


def test_files_relative_to_check_cwd(proj):
    (proj / "sub").mkdir(); (proj / "sub" / "m.py").write_text("A = 1\n")
    git(proj, "add", "-A"); git(proj, "commit", "-qm", "sub")
    import json
    d = {"name": "insub", "cwd": "sub", "argv": [PY, "-c", "import sys; sys.exit(0 if sys.argv[1:]==['m.py'] else 7)", "{files}"]}
    setup(proj, json.dumps(d))
    edit = "FILE: sub/m.py\n<<<<<<< SEARCH\nA = 1\n=======\nA = 2\n>>>>>>> REPLACE\n"
    assert run(proj, FakeChat(edit), files_to_edit=["sub/m.py"])["status"] == "passed"


def test_files_placeholder_validation(tmp_path):
    for argv in ('["x","a{files}"]', '["x","{files}","{files}"]'):
        write_cfg(tmp_path, '{"checks":[{"name":"c","argv":' + argv + "}]}")
        with pytest.raises(ConfigError):
            load_config(tmp_path)


def long_fn(n):
    return "".join(f"    v{i} = {i}\n" for i in range(n))


def test_standards_feedback_loop_then_pass(proj):
    setup(proj, extra=STD)
    bad = "FILE: calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n" + long_fn(8) + "    return a + b\n>>>>>>> REPLACE\n"
    good = "FILE: calc.py\n<<<<<<< SEARCH\n" + long_fn(8) + "    return a + b\n=======\n    return _s(a, b)\n>>>>>>> REPLACE\n"
    good += "FILE: calc.py\n<<<<<<< SEARCH\ndef mul(a, b):\n=======\ndef _s(a, b):\n    return a + b\n\n\ndef mul(a, b):\n>>>>>>> REPLACE\n"
    fc = FakeChat(bad, good)
    r = run(proj, fc)
    assert r["status"] == "passed" and r["attempts"] == 2, r
    assert "calc.py::add" in fc.calls[1][1]["content"] and "Extract helper" in fc.calls[1][1]["content"]


def test_file_too_long_is_not_retried(proj):
    setup(proj, extra=STD)
    new = "FILE: calc.py\n<<<<<<< FULL\n" + "".join(f"v{i} = {i}\n" for i in range(50)) + ">>>>>>> END\n"
    fc = FakeChat(new, new)
    r = run(proj, fc, files_to_edit=["calc.py"])
    assert r["status"] == "failed" and r["attempts"] == 1 and r["escalate"] is True
    assert "planner decision" in r["why"] and len(fc.calls) == 1 and r["failed_check"] == "standards"


def test_soft_limit_warning_in_passed_result(proj):
    setup(proj, extra=STD)
    new = "FILE: calc.py\n<<<<<<< FULL\n" + "".join(f"v{i} = {i}\n" for i in range(25)) + ">>>>>>> END\n"
    r = run(proj, FakeChat(new))
    assert r["status"] == "passed" and "soft limit" in r["warnings"][0]


def test_standards_runs_even_when_checks_subset_requested(proj):
    setup(proj, scoped_check(["calc.py"]), extra=STD)
    new = "FILE: calc.py\n<<<<<<< FULL\n" + "".join(f"v{i} = {i}\n" for i in range(50)) + ">>>>>>> END\n"
    r = run(proj, FakeChat(new), check_names=["scoped"])
    assert r["failed_check"] == "standards"


def test_run_checks_scope_by_task(proj):
    setup(proj, scoped_check(["calc.py"]))
    run(proj, FakeChat(FIX), task_id="T1")
    assert core.run_checks(proj, task_id="T1")["status"] == "passed"
    assert "no recorded" in core.run_checks(proj, task_id="T7")["error"]
    (proj / "util.py").write_text("X = 5\n")  # dirty file joins the default scope -> scoped check now fails
    assert core.run_checks(proj)["status"] == "failed"
    assert core.run_checks(proj, task_id="T1")["status"] == "passed"
