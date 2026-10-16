"""Server wiring: root detection fails closed, errors become short JSON, mutating tools are serialised."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from localexec import server


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("LOCALEXEC_ROOT", raising=False)


def test_env_root_wins_and_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALEXEC_ROOT", str(tmp_path))
    assert server.project_root() == tmp_path.resolve()
    monkeypatch.setenv("LOCALEXEC_ROOT", str(tmp_path / "missing"))
    with pytest.raises(server.RootError):
        server.project_root()


def test_no_git_and_no_config_means_no_root(clean_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(server.RootError, match="LOCALEXEC_ROOT"):
        server.project_root()


def test_a_directory_with_a_config_is_accepted(clean_env, monkeypatch, tmp_path):
    (tmp_path / ".localexec.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert server.project_root() == tmp_path.resolve()


def test_root_error_becomes_a_short_json_error(clean_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    out = json.loads(asyncio.run(server._call("x", lambda root: {"never": "called"})))
    assert out["status"] == "error" and "LOCALEXEC_ROOT" in out["error"]


def test_crashing_tool_never_leaks_a_traceback(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALEXEC_ROOT", str(tmp_path))

    def boom(root):
        raise ValueError("secret detail")

    out = json.loads(asyncio.run(server._call("boom", boom)))
    assert out["status"] == "error" and "internal error: ValueError" in out["error"] and "Traceback" not in out["error"]


def test_write_tools_never_overlap_but_read_tools_do_not_wait(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALEXEC_ROOT", str(tmp_path))
    active, peak, lock = 0, 0, threading.Lock()

    def slow(root):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.15)
        with lock:
            active -= 1
        return {"ok": True}

    async def go():
        await asyncio.gather(*[server._call("w", slow, write=True) for _ in range(3)])

    async def go_reads():
        await asyncio.gather(*[server._call("r", slow) for _ in range(3)])

    asyncio.run(go())
    assert peak == 1
    peak = 0
    asyncio.run(go_reads())
    assert peak > 1
