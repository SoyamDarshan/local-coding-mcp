import json
import subprocess
import sys
from pathlib import Path

import pytest

from localexec import core
from localexec.tasks.ollama import ChatResult


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    # write_bytes: keep LF on Windows too (write_text would translate to CRLF)
    (root / "calc.py").write_bytes(b"def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n")
    (root / "util.py").write_bytes(b"X = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return root.resolve()


def write_cfg(root: Path, text: str) -> None:
    (root / ".localexec.json").write_text(text, encoding="utf-8")


PY = sys.executable


def chk(name: str, *argv: str, **kw) -> str:
    """One check as JSON text. json.dumps escapes Windows backslashes in PY correctly."""
    return json.dumps({"name": name, "argv": list(argv), **kw})


class FakeChat:
    """Scripted replacement for ollama.chat; records the messages it was given."""

    def __init__(self, *replies: str, done_reason: str = "stop"):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []
        self.done_reason = done_reason

    def __call__(self, cfg, messages):
        self.calls.append(messages)
        content = self.replies.pop(0)
        return ChatResult(content, 100, 20, self.done_reason)


FIX = """FILE: calc.py
<<<<<<< SEARCH
    return a - b
=======
    return a + b
>>>>>>> REPLACE
"""
CHECK = chk("syn", PY, "-c", "import ast;ast.parse(open('calc.py', encoding='utf-8').read())")


def cfg(root, checks=CHECK, extra=""):
    write_cfg(root, '{"conventions":"Use type hints.","checks":[' + checks + "]" + extra + "}")
    git(root, "add", ".localexec.json")  # config itself is not "unrelated work"
    git(root, "commit", "-qm", "cfg")


def run(root, chat_fn, **kw):
    args = dict(task_id="T1", spec="fix add", files_to_edit=["calc.py"])
    args.update(kw)
    return core.implement_task(root, chat_fn=chat_fn, **args)
