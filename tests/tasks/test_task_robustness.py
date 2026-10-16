"""Review fixes for the task pipeline: crash recovery, stale writes, retry state, budget headroom."""

from __future__ import annotations

import json

import pytest
from conftest import PY, FakeChat, chk, git, write_cfg

from localexec import core
from localexec.tasks import loop
from localexec.settings.config import Config
from localexec.tasks.ollama import ChatResult

FIX = "FILE: calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"
NOOP = "FILE: calc.py\n<<<<<<< SEARCH\n    return a * b\n=======\n    return a * b\n>>>>>>> REPLACE\n"
FAILING = chk("bad", PY, "-c", "raise SystemExit('boom')")
OK = chk("ok", PY, "-c", "pass")


def setup(root, checks, extra=""):
    write_cfg(root, '{"checks":[' + checks + "]" + extra + "}")
    git(root, "add", ".localexec.json")
    git(root, "commit", "-qm", "cfg")


def run(root, chat_fn, task_id="T1", **kw):
    return core.implement_task(root, task_id, "fix add", ["calc.py"], chat_fn=chat_fn, **kw)


def manifest(root, task_id="T1"):
    return json.loads((root / ".localexec" / f"{task_id}.json").read_text(encoding="utf-8"))


def test_unexpected_exception_still_produces_a_final_result(proj):
    setup(proj, OK)

    def exploding_runner(*a, **k):
        raise RuntimeError("runner bug")

    r = run(proj, FakeChat(FIX), check_runner=exploding_runner)
    assert r["status"] == "error" and "RuntimeError" in r["error"] and r["escalate"] is True
    assert r["note"] and manifest(proj)["status"] == "error"  # never left as "running"


def test_file_edited_by_the_user_while_the_model_works_is_not_overwritten(proj):
    setup(proj, OK)

    class UserEdits(FakeChat):
        def __call__(self, cfg, messages):
            (proj / "calc.py").write_bytes(b"# user edit\n")
            return super().__call__(cfg, messages)

    r = run(proj, UserEdits(FIX))
    assert r["status"] == "error" and "changed on disk" in r["error"]
    assert (proj / "calc.py").read_bytes() == b"# user edit\n"
    assert manifest(proj)["files"] == {}  # nothing changed, so the task id is not burned
    assert run(proj, FakeChat("BLOCKED: q"))["status"] == "blocked"  # same id usable again


def test_interrupted_run_can_be_reverted(proj, monkeypatch):
    setup(proj, OK)
    real = loop.write_atomic

    def write_then_die(states, new_text):
        real(states, new_text)
        raise SystemExit  # simulates the process dying after the write, before the final manifest

    monkeypatch.setattr(loop, "write_atomic", write_then_die)
    with pytest.raises(SystemExit):
        run(proj, FakeChat(FIX))
    assert manifest(proj)["status"] == "running" and b"a + b" in (proj / "calc.py").read_bytes()
    assert core.revert_task(proj, "T1")["status"] == "reverted"
    assert b"a - b" in (proj / "calc.py").read_bytes()


def test_noop_retry_keeps_the_check_failure_for_the_next_attempt(proj):
    setup(proj, FAILING, ', "max_attempts": 3')
    fc = FakeChat(FIX, NOOP, "BLOCKED: stuck")
    r = run(proj, fc)
    assert r["status"] == "blocked" and r["note"]
    last = fc.calls[2][1]["content"]
    assert "Check `bad` failed" in last and "made no changes" in last


def test_errors_after_an_applied_attempt_mention_the_remaining_changes(proj):
    setup(proj, FAILING, ', "max_attempts": 2')

    def second_call_fails(cfg, messages):
        from localexec.tasks.ollama import OllamaError
        raise OllamaError("connection refused")

    class Seq(FakeChat):
        def __call__(self, cfg, messages):
            return super().__call__(cfg, messages) if self.replies else second_call_fails(cfg, messages)

    r = run(proj, Seq(FIX))
    assert r["status"] == "error" and "remain in the tree" in r["note"]


class FullContext(FakeChat):
    def __call__(self, cfg, messages):
        res = super().__call__(cfg, messages)
        return ChatResult(res.content, cfg.num_ctx, 20, "stop")


def test_prompt_that_fills_the_context_window_adds_a_warning(proj):
    setup(proj, OK)
    r = run(proj, FullContext(FIX))
    assert r["status"] == "passed" and any("context window" in w for w in r["warnings"])


def test_prompt_budget_leaves_room_for_a_repair_round():
    cfg = Config(num_ctx=16384, max_output_tokens=4096, prompt_budget_tokens=12000)
    assert cfg.prompt_budget_chars == int((16384 - 4096 - 2500) * 3.5)
    assert Config().prompt_budget_chars == int(8000 * 3.5)


def test_reusing_a_reverted_task_id_clears_its_old_patch_and_backups(proj):
    setup(proj, OK)
    assert run(proj, FakeChat(FIX))["status"] == "passed"
    assert (proj / ".localexec" / "T1.patch").exists() and (proj / ".localexec" / "T1.orig").exists()
    assert core.revert_task(proj, "T1")["status"] == "reverted"
    run(proj, FakeChat("BLOCKED: q"))
    assert not (proj / ".localexec" / "T1.patch").exists() and not (proj / ".localexec" / "T1.orig").exists()
