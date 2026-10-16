import json

import httpx
import pytest

from conftest import FIX, PY, FakeChat, cfg, chk, git, run, write_cfg
from localexec import core
from localexec.settings.config import load_config
from localexec.tasks.ollama import OllamaError, chat

BAD = FIX.replace("a + b", "a +")  # syntax error


def test_pass_first_try(proj):
    cfg(proj)
    fc = FakeChat(FIX)
    r = run(proj, fc)
    assert r["status"] == "passed" and r["attempts"] == 1 and r["escalate"] is False
    assert "a + b" in (proj / "calc.py").read_text()
    assert (proj / r["patch"]).read_text().count("+    return a + b") == 1
    assert (proj / r["log"]).exists()
    assert r["stat"] == "+1 -1 in 1 file"
    assert len(core.to_json(r)) < 600
    assert "Use type hints." in fc.calls[0][1]["content"]  # conventions reach the model
    assert "return a - b" in fc.calls[0][1]["content"]  # current file contents


def test_not_committed(proj):
    cfg(proj)
    head = lambda: __import__("subprocess").run(["git", "rev-parse", "HEAD"], cwd=proj, capture_output=True, text=True).stdout
    before = head()
    run(proj, FakeChat(FIX))
    assert head() == before


def test_blocked_makes_no_changes(proj):
    cfg(proj)
    r = run(proj, FakeChat("BLOCKED: should add() accept floats?"))
    assert r["status"] == "blocked" and "floats" in r["question"] and r["escalate"] is False
    assert "a - b" in (proj / "calc.py").read_text() and "patch" not in r


def test_edit_error_gets_one_repair_then_fails(proj):
    cfg(proj)
    nomatch = FIX.replace("a - b", "a * zzz")
    fc = FakeChat(nomatch, nomatch)
    r = run(proj, fc)
    assert r["status"] == "edit_failed" and r["escalate"] is True
    assert len(fc.calls) == 2 and "not found" in fc.calls[1][-1]["content"]
    assert "a - b" in (proj / "calc.py").read_text()


def test_edit_error_repaired(proj):
    cfg(proj)
    r = run(proj, FakeChat("I will fix it", FIX))
    assert r["status"] == "passed"


def test_check_failure_retry_then_success(proj):
    cfg(proj)
    fc = FakeChat(BAD, FIX.replace("a - b", "a +").replace("a + b", "a + b"))
    r = run(proj, fc)
    assert r["status"] == "passed" and r["attempts"] == 2
    second = fc.calls[1][1]["content"]
    assert "Check `syn` failed" in second and "SyntaxError" in second


def test_check_failure_exhausted(proj):
    cfg(proj)
    r = run(proj, FakeChat(BAD, "FILE: calc.py\n<<<<<<< SEARCH\n    return a +\n=======\n    return a +\n>>>>>>> REPLACE\n"))
    assert r["status"] == "failed" and r["escalate"] is True and r["failed_check"] == "syn"
    assert r["output"] and len(r["output"].splitlines()) <= 30 and "patch" in r


def test_refuses_unrelated_dirty_tree(proj):
    cfg(proj)
    (proj / "util.py").write_text("X = 2\n")
    r = run(proj, FakeChat(FIX))
    assert r["status"] == "error" and "util.py" in r["error"]
    (proj / "calc.py").write_text("def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n# touched\n")
    git(proj, "checkout", "util.py")
    assert run(proj, FakeChat(FIX.replace("    return a - b", "    return a - b")))["status"] in ("passed", "edit_failed")


def test_path_traversal_and_ignored_rejected(proj):
    cfg(proj)
    assert "escapes" in run(proj, FakeChat(), files_to_edit=["../x.py"])["error"]
    assert "ignored" in run(proj, FakeChat(), files_to_edit=["node_modules/a.js"])["error"]
    assert "ignored" in run(proj, FakeChat(), files_to_edit=["uv.lock"])["error"]
    assert "escapes" in run(proj, FakeChat(), files_to_edit=["calc.py"], context_files=["../../etc/passwd"])["error"]


def test_model_cannot_edit_unlisted_file(proj):
    cfg(proj)
    evil = "FILE: util.py\n<<<<<<< FULL\nX = 99\n>>>>>>> END\n"
    r = run(proj, FakeChat(evil, evil))
    assert r["status"] == "edit_failed" and (proj / "util.py").read_text() == "X = 1\n"


def test_new_file_and_revert(proj):
    cfg(proj)
    new = "FILE: new_mod.py\n<<<<<<< FULL\nY = 2\n>>>>>>> END\n"
    r = run(proj, FakeChat(FIX + new), files_to_edit=["calc.py", "new_mod.py"])
    assert r["status"] == "passed" and (proj / "new_mod.py").read_text() == "Y = 2\n"
    dry = core.revert_task(proj, "T1", dry_run=True)
    assert dry["status"] == "dry_run" and dry["restore"] == ["calc.py"] and dry["remove"] == ["new_mod.py"]
    assert (proj / "new_mod.py").exists()
    out = core.revert_task(proj, "T1")
    assert out["status"] == "reverted"
    assert not (proj / "new_mod.py").exists() and "a - b" in (proj / "calc.py").read_text()
    assert (proj / "util.py").exists()  # nothing else touched
    assert core.revert_task(proj, "T1")["status"] == "already_reverted"
    assert run(proj, FakeChat(FIX))["status"] == "passed"  # id reusable after revert


def test_revert_skips_files_edited_since(proj):
    cfg(proj)
    run(proj, FakeChat(FIX))
    (proj / "calc.py").write_text("# user edit\n")
    out = core.revert_task(proj, "T1")
    assert out["status"] == "partial" and out["skipped"] == ["calc.py:changed-since-task"]
    assert core.revert_task(proj, "T1", force=True)["status"] == "reverted"


def test_task_id_reuse_and_invalid(proj):
    cfg(proj)
    run(proj, FakeChat(FIX))
    assert "already used" in run(proj, FakeChat(FIX))["error"]
    assert "task_id" in run(proj, FakeChat(), task_id="../evil")["error"]


def test_context_truncation_reported_and_budget(proj):
    cfg(proj, extra=',"prompt_budget_tokens":1500')
    (proj / "big.txt").write_text("line of context\n" * 2000)
    git(proj, "add", "big.txt"); git(proj, "commit", "-qm", "big")
    fc = FakeChat(FIX)
    r = run(proj, fc, context_files=["big.txt"])
    assert r["status"] == "passed" and r["truncated"] == ["big.txt:truncated"]
    prompt = fc.calls[0][1]["content"]
    assert "TRUNCATED" in prompt and len(prompt) + 1500 < 1500 * 3.5 + 2500


def test_edit_file_too_large_blocks(proj):
    cfg(proj, extra=',"prompt_budget_tokens":1000')
    (proj / "calc.py").write_text("x = 1\n" * 3000)
    git(proj, "add", "-A"); git(proj, "commit", "-qm", "huge")
    fc = FakeChat()
    r = run(proj, fc)
    assert r["status"] == "blocked" and "split" in r["question"] and fc.calls == []


def test_output_cut_off_is_edit_error(proj):
    cfg(proj)
    fc = FakeChat(FIX, FIX, done_reason="length")
    assert run(proj, fc)["status"] == "edit_failed"


def test_checks_subset_and_unknown(proj):
    cfg(proj)
    assert "unknown check" in run(proj, FakeChat(FIX), check_names=["nope"])["error"]
    assert run(proj, FakeChat(FIX), check_names=[])["status"] == "passed"


def test_no_shell_and_timeout(proj):
    sleeper = chk("slow", PY, "-c", "import time;time.sleep(30)", timeout=1)
    cfg(proj, checks=sleeper)
    r = core.run_checks(proj)
    assert r["status"] == "failed" and "TIMEOUT" in r["output"]
    # an argv element is never interpreted by a shell
    inj = chk("inj", PY, "-c", "print(1)", "; touch pwned")
    write_cfg(proj, '{"checks":[' + inj + "]}")
    core.run_checks(proj)
    assert not (proj / "pwned").exists()


def test_run_checks_summary(proj):
    ok = chk("ok", PY, "-c", "print(1)") + "," + chk("bad", PY, "-c", "import sys;print('boom');sys.exit(3)")
    write_cfg(proj, '{"checks":[' + ok + "]}")
    r = core.run_checks(proj)
    assert r["status"] == "failed" and r["failed_check"] == "bad" and "boom" in r["output"]
    assert [x["ok"] for x in r["results"]] == [True, False]
    assert core.run_checks(proj, ["zzz"])["status"] == "error"


def test_non_git_dir(tmp_path):
    root = tmp_path.resolve()
    r = core.implement_task(root, "T", "s", ["a.py"], chat_fn=FakeChat())
    assert "not a git" in r["error"]


# ---- Ollama client against a mocked endpoint
def test_ollama_client_request_and_errors(tmp_path):
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url); seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"message": {"content": "hi"}, "prompt_eval_count": 12, "eval_count": 3, "done_reason": "stop"})

    c = load_config(tmp_path)
    r = chat(c, [{"role": "user", "content": "x"}], transport=httpx.MockTransport(handler))
    assert r.content == "hi" and r.prompt_tokens == 12
    assert seen["url"].endswith("/api/chat") and seen["body"]["stream"] is False
    assert seen["body"]["options"]["num_ctx"] == 16384 and seen["body"]["model"] == "qwen-coder-16k"
    with pytest.raises(OllamaError, match="404"):
        chat(c, [], transport=httpx.MockTransport(lambda r: httpx.Response(404, text="model not found")))

    def boom(req):
        raise httpx.ConnectError("refused")
    with pytest.raises(OllamaError, match="cannot reach"):
        chat(c, [], transport=httpx.MockTransport(boom))


def test_ollama_down_gives_error_result(proj):
    cfg(proj)
    def down(cfg_, msgs):
        raise OllamaError("cannot reach Ollama")
    r = run(proj, down)
    assert r["status"] == "error" and "ollama" in r["why"]


def test_sequential_tasks_on_different_files(proj):
    cfg(proj)
    assert run(proj, FakeChat(FIX))["status"] == "passed"  # leaves calc.py uncommitted
    other = "FILE: util.py\n<<<<<<< SEARCH\nX = 1\n=======\nX = 2\n>>>>>>> REPLACE\n"
    r = run(proj, FakeChat(other), task_id="T2", files_to_edit=["util.py"])
    assert r["status"] == "passed"
    (proj / "calc.py").write_text("# hand edit\n")  # user edits a task file afterwards -> unrelated again
    r = run(proj, FakeChat(other), task_id="T3", files_to_edit=["util.py"])
    assert r["status"] == "error" and "calc.py" in r["error"]
