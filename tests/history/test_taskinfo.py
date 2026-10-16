import json

from conftest import FIX, FakeChat, cfg, git, run
from localexec import core
from localexec.history import taskinfo


def test_list_tasks_shows_every_outcome(proj):
    cfg(proj)
    run(proj, FakeChat(FIX), task_id="T1")
    run(proj, FakeChat("BLOCKED: which rounding?"), task_id="T2", files_to_edit=["util.py"], spec="round things\nsecond line")
    core.revert_task(proj, "T1")
    out = taskinfo.list_tasks(proj)
    assert out["total"] == 2
    rows = {r.split("|")[0]: r for r in out["tasks"]}
    assert rows["T1"].startswith("T1|passed|reverted|1a|calc.py|")
    assert rows["T2"].startswith("T2|blocked|0a") or rows["T2"].startswith("T2|blocked|1a")
    assert rows["T2"].endswith("round things second line")
    assert len(json.dumps(out)) < 400
    assert taskinfo.list_tasks(proj, limit=1)["tasks"].__len__() == 1


def test_blocked_task_id_is_reusable(proj):
    cfg(proj)
    run(proj, FakeChat("BLOCKED: q"), task_id="T9")
    assert run(proj, FakeChat(FIX), task_id="T9")["status"] == "passed"


def test_show_patch_compact_and_filtered(proj):
    cfg(proj)
    big = "def long():\n" + "".join(f"    v{i} = {i}\n" for i in range(80)) + "    return 1\n"
    (proj / "big.py").write_text(big); git(proj, "add", "big.py"); git(proj, "commit", "-qm", "b")
    edit = FIX + "FILE: big.py\n<<<<<<< SEARCH\n    v40 = 40\n=======\n    v40 = 41\n>>>>>>> REPLACE\n"
    assert run(proj, FakeChat(edit), files_to_edit=["calc.py", "big.py"])["status"] == "passed"
    text = taskinfo.show_patch(proj, "T1")
    assert "+    v40 = 41" in text and "v10 = 10" not in text  # far context trimmed
    only = taskinfo.show_patch(proj, "T1", file="calc.py")
    assert "calc.py" in only and "big.py" not in only
    assert "more diff lines" in taskinfo.show_patch(proj, "T1", max_lines=5)
    assert "no patch" in taskinfo.show_patch(proj, "nope")
    assert "invalid" in taskinfo.show_patch(proj, "../x")
