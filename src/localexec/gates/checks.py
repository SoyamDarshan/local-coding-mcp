"""Run only the check commands defined in the project config (never shell strings)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import standards as std_mod
from ..settings.config import STANDARDS_ARGV0, Check
from ..settings.safety import PathError, glob_match, resolve_in_root

MAX_CAPTURE = 400_000  # chars kept per check (half from the start, half from the end)
MAX_CMDLINE = 30_000  # Windows allows about 32k characters per command line
CMD_META = set('&|<>^%"\n\r')  # cmd.exe interprets these in arguments of .cmd/.bat shims


@dataclass
class CheckResult:
    name: str
    ok: bool
    returncode: int | None
    output: str
    seconds: float
    timed_out: bool = False
    skipped: bool = False
    warnings: list[str] = field(default_factory=list)
    retry: bool = True  # False: the model cannot fix this (planner decision needed)


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        else:
            import signal

            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _skip(check: Check, why: str) -> CheckResult:
    return CheckResult(check.name, True, 0, f"skipped: {why}", 0.0, skipped=True)


def _scoped_files(check: Check, files: list[str] | None, root: Path, cwd: Path) -> list[str] | None:
    """Changed files this check applies to, relative to its cwd. None = check is not file-scoped."""
    if not check.files_filter and "{files}" not in check.argv:
        return None
    out = []
    for rel in files or []:
        if check.files_filter and not glob_match(rel, check.files_filter):
            continue
        full = root / rel
        if not full.is_file() or not full.resolve().is_relative_to(cwd):
            continue
        arg = full.resolve().relative_to(cwd).as_posix()
        out.append("./" + arg if arg.startswith("-") else arg)
    return out


def _run_standards(check: Check, root: Path, files: list[str] | None, baselines, std) -> CheckResult:
    if std is None:
        return CheckResult(check.name, False, None, "standards not configured", 0.0)
    res = std_mod.check_files(root, std, files or [], baselines)
    lines = [f"FAIL {m}" for m in res.failures] + [f"WARN {m}" for m in res.warnings]
    return CheckResult(
        check.name, not res.failures, 1 if res.failures else 0, "\n".join(lines), 0.0,
        warnings=res.warnings, retry=not res.fatal,
    )


def _spawn(argv: list[str], cwd: Path) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "CI": "1"}
    kwargs: dict = {} if sys.platform == "win32" else {"start_new_session": True}
    return subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,  # never touch the MCP stdio pipe
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        shell=False,
        **kwargs,
    )


class _Capture(threading.Thread):
    """Drains a process's output while it runs, keeping only the first and last MAX_CAPTURE/2 characters."""

    def __init__(self, stream) -> None:
        super().__init__(daemon=True)
        self.stream, self.head, self.tail, self.total = stream, "", "", 0

    def run(self) -> None:
        half = MAX_CAPTURE // 2
        try:
            while chunk := self.stream.read(8192):
                self.total += len(chunk)
                room = half - len(self.head)
                self.head += chunk[:room]
                self.tail = (self.tail + chunk[room:])[-half:]
        except (OSError, ValueError):
            pass  # pipe closed under us

    def text(self) -> str:
        cut = self.total - len(self.head) - len(self.tail)
        return self.head + (f"\n[... {cut} characters truncated ...]\n" if cut > 0 else "") + self.tail


def _collect(proc: subprocess.Popen[str], timeout: int) -> tuple[str, bool]:
    """Wait for the process; kill its whole tree on timeout. Returns (output, timed_out)."""
    cap = _Capture(proc.stdout)
    cap.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        try:
            proc.wait(timeout=10)  # reap it so no zombie is left
        except subprocess.TimeoutExpired:
            pass
    cap.join(5)  # a surviving grandchild may hold the pipe open; we keep what we have
    out = cap.text()
    if timed_out:
        out += f"\n[localexec] TIMEOUT after {timeout}s, process killed"
    return out, timed_out


def _fail(check: Check, message: str) -> CheckResult:
    return CheckResult(check.name, False, None, message, 0.0)


def _argv_problem(exe: str, argv: list[str]) -> str | None:
    if sum(len(a) + 1 for a in argv) > MAX_CMDLINE:
        return "too many files for one command line; split the task into smaller steps"
    if exe.lower().endswith((".cmd", ".bat")) and any(CMD_META & set(a) for a in argv[1:]):
        return "a file name contains characters that cmd.exe would interpret (& | < > ^ % \"); rename it"
    return None


def run_check(
    check: Check,
    root: Path,
    files: list[str] | None = None,
    baselines: dict[str, str | None] | None = None,
    std: std_mod.Standards | None = None,
) -> CheckResult:
    if check.argv[0] == STANDARDS_ARGV0:
        return _run_standards(check, root, files, baselines, std)
    start = time.monotonic()
    try:
        cwd = resolve_in_root(root, check.cwd) if check.cwd not in (".", "") else root
    except PathError as e:
        return _fail(check, f"bad cwd: {e}")
    scoped = _scoped_files(check, files, root, cwd.resolve())
    if scoped is not None and not scoped:
        return _skip(check, "no matching changed files")
    exe = shutil.which(check.argv[0], path=os.environ.get("PATH"))
    if exe is None:
        return _fail(check, f"command not found: {check.argv[0]}")
    argv = [exe]
    for a in check.argv[1:]:
        argv.extend((scoped or []) if a == "{files}" else [a])
    problem = _argv_problem(exe, argv)
    if problem:
        return _fail(check, problem)
    try:
        proc = _spawn(argv, cwd)
    except OSError as e:
        return _fail(check, f"failed to start: {e}")
    out, timed_out = _collect(proc, check.timeout)
    ok = (not timed_out) and proc.returncode == 0
    return CheckResult(check.name, ok, proc.returncode, out, time.monotonic() - start, timed_out)


def excerpt(output: str, max_lines: int, max_chars: int) -> str:
    """First lines plus the last few (test summaries and tracebacks end at the tail)."""
    lines = output.strip().splitlines()
    if len(lines) > max_lines:
        tail = max(3, max_lines // 3)
        lines = lines[: max_lines - tail - 1] + ["[...]"] + lines[-tail:]
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + " [...]"


def trim_for_model(output: str, max_chars: int = 3500, head: int = 40, tail: int = 40) -> str:
    lines = output.strip().splitlines()
    if len(lines) > head + tail:
        lines = lines[:head] + [f"[... {len(lines) - head - tail} lines omitted ...]"] + lines[-tail:]
    text = "\n".join(lines)
    if len(text) > max_chars:
        half = max_chars // 2
        text = text[:half] + "\n[... trimmed ...]\n" + text[-half:]
    return text
