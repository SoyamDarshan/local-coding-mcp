from conftest import FakeChat, cfg, git, run
from localexec import core

BIG = "".join(f"def func_{i}(x):\n    return x + {i}\n\n\n" for i in range(120))  # ~480 lines


def big_repo(proj, budget=1200):
    (proj / "big.py").write_text(BIG, encoding="utf-8")
    git(proj, "add", "big.py"); git(proj, "commit", "-qm", "big")
    cfg(proj, extra=f',"prompt_budget_tokens":{budget}')


EDIT = "FILE: big.py\n<<<<<<< SEARCH\ndef func_7(x):\n    return x + 7\n=======\ndef func_7(x):\n    return x * 7\n>>>>>>> REPLACE\n"


def test_large_file_edited_through_symbols(proj):
    big_repo(proj)
    blocked = run(proj, FakeChat(EDIT), files_to_edit=["big.py"], task_id="Tb")
    assert blocked["status"] == "blocked" and "split" in blocked["question"]  # too big without symbols
    fc = FakeChat(EDIT)
    r = run(proj, fc, files_to_edit=["big.py"], symbols=["big.py::func_7"])
    assert r["status"] == "passed", r
    prompt = fc.calls[0][1]["content"]
    assert "(EXCERPT)" in prompt and "def func_7(x):" in prompt and "def func_90(x):" not in prompt
    assert "omitted" in prompt
    assert "return x * 7" in (proj / "big.py").read_text() and "func_90" in (proj / "big.py").read_text()


def test_full_rewrite_of_excerpted_file_is_rejected(proj):
    big_repo(proj)
    full = "FILE: big.py\n<<<<<<< FULL\nx = 1\n>>>>>>> END\n"
    fc = FakeChat(full, EDIT)
    r = run(proj, fc, files_to_edit=["big.py"], symbols=["big.py::func_7"])
    assert r["status"] == "passed" and "use SEARCH/REPLACE" in fc.calls[1][-1]["content"]
    assert "func_90" in (proj / "big.py").read_text()


def test_symbol_problems_stop_before_the_model(proj):
    big_repo(proj)
    fc = FakeChat()
    r = run(proj, fc, files_to_edit=["big.py"], symbols=["big.py::func_999"])
    assert r["status"] == "error" and "not found" in r["error"] and fc.calls == []
    assert "not listed in files_to_edit" in run(proj, fc, files_to_edit=["big.py"], symbols=["calc.py::add"])["error"]
    assert "must look like" in run(proj, fc, files_to_edit=["big.py"], symbols=["big.py"])["error"]
    assert "does not exist" in run(proj, fc, files_to_edit=["fresh.py"], symbols=["fresh.py::f"])["error"]


def test_symbols_in_small_file_and_vanished_symbol(proj):
    cfg(proj)
    rename = "FILE: calc.py\n<<<<<<< SEARCH\ndef add(a, b):\n    return a - b\n=======\ndef plus(a, b):\n    return a + b\n>>>>>>> REPLACE\n"
    fc = FakeChat(rename, "BLOCKED: nothing more")
    r = run(proj, fc, symbols=["calc.py::add"])
    assert r["status"] == "passed"  # edit applied and checks passed
    r2 = core.implement_task(proj, "T2", "again", ["calc.py"], symbols=["calc.py::add"], chat_fn=FakeChat())
    assert r2["status"] == "error" and "not found" in r2["error"]
