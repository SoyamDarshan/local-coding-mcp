"""Run realistic tasks against your real Ollama and print a one-page report.

Usage (from the localexec-mcp folder):
    uv run python scripts/live_check.py [--model qwen-coder-16k] [--only fix-bug,add-method] [--keep]
Writes live_check_report.md next to where you run it. Nothing touches your real projects:
it works in a temporary git repo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from live_fixtures import CASES, Case, files  # noqa: E402

from localexec import core  # noqa: E402
from localexec.tasks.status import status as model_status  # noqa: E402
from localexec.settings.config import load_config  # noqa: E402
from localexec.tasks.ollama import ChatResult, chat  # noqa: E402

PY = sys.executable


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def write_config(root: Path, model: str, budget: int | None) -> None:
    cfg = {
        "ollama_model": model,
        "standards": True,
        "conventions": "Python 3.11, type hints on every function, keep functions short, no new dependencies.",
        "checks": [
            {"name": "compile", "argv": [PY, "-m", "compileall", "-q", "shop", "tests"], "timeout": 60},
            {"name": "pytest", "argv": [PY, "-m", "pytest", "-q", "-x", "{files}"],
             "files_filter": ["tests/test_*.py"], "timeout": 180},
        ],
    }
    if budget:
        cfg["prompt_budget_tokens"] = budget
    (root / ".localexec.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")


def make_repo(model: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="localexec-live-")).resolve()
    git(root, "init", "-q")
    git(root, "config", "user.email", "live@check")
    git(root, "config", "user.name", "live check")
    for rel, text in files().items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode("utf-8"))
    (root / ".gitignore").write_text(".localexec/\n__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    write_config(root, model, None)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "baseline")
    return root.resolve()


class Recorder:
    """Wraps the real chat function and records tokens and time per call."""

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.output_tokens = 0
        self.seconds = 0.0
        self.replies: list[str] = []

    def __call__(self, cfg, messages) -> ChatResult:
        start = time.monotonic()
        res = chat(cfg, messages)
        self.seconds += time.monotonic() - start
        self.calls += 1
        self.replies.append(res.content)
        self.prompt_tokens += res.prompt_tokens or 0
        self.output_tokens += res.output_tokens or 0
        return res


def verify(root: Path, code: str) -> tuple[bool, str]:
    p = subprocess.run([PY, "-c", code], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode == 0, (p.stderr.strip().splitlines() or [""])[-1][:120]


def run_case(root: Path, case: Case, model: str) -> dict:
    write_config(root, model, case.budget)
    git(root, "add", "-A")
    subprocess.run(["git", "commit", "-qm", f"cfg {case.id}"], cwd=root, capture_output=True)
    rec = Recorder()
    res = core.implement_task(
        root, f"L-{case.id}", case.spec, case.files_to_edit, None, case.checks, case.symbols, chat_fn=rec
    )
    got = res.get("status")
    ok_verify, why = verify(root, case.verify) if got == "passed" else (got == case.expect, "")
    row = {
        "id": case.id, "title": case.title, "expected": case.expect, "status": got,
        "attempts": res.get("attempts"), "model_calls": rec.calls, "prompt_tokens": rec.prompt_tokens,
        "output_tokens": rec.output_tokens, "seconds": round(rec.seconds, 1),
        "result_ok": (got == case.expect) and ok_verify, "detail": why or res.get("why") or res.get("error", ""),
        "warnings": res.get("warnings", []),
        "question": res.get("question"), "raw": res,
        "replies": [r[:1500] for r in rec.replies],
    }
    if res.get("files"):
        # always leave a clean tree for the next case, whatever the outcome
        core.revert_task(root, f"L-{case.id}")
    git(root, "add", "-A")
    subprocess.run(["git", "commit", "-qm", f"done {case.id}"], cwd=root, capture_output=True)
    return row


def report(rows: list[dict], model: str, total_s: float) -> str:
    passed = sum(r["result_ok"] for r in rows)
    out = [f"# live_check report: {model}", "", f"{passed}/{len(rows)} cases correct, {total_s:.0f}s total", "",
           "| case | expected | status | attempts | calls | prompt tok | out tok | sec | ok | note |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(
            f"| {r['id']} | {r['expected']} | {r['status']} | {r['attempts']} | {r['model_calls']} | "
            f"{r['prompt_tokens']} | {r['output_tokens']} | {r['seconds']} | {'yes' if r['result_ok'] else 'NO'} | "
            f"{str(r['detail'])[:70]} |"
        )
    extra = sum(max(0, r["model_calls"] - (r["attempts"] or 0)) for r in rows)
    out += ["", f"Extra model calls beyond one per attempt (edit-format repairs): {extra}"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", default="")
    ap.add_argument("--keep", action="store_true", help="print the temp repo path and keep it")
    args = ap.parse_args()
    cfg0 = load_config(Path(tempfile.gettempdir()))
    model = args.model or cfg0.ollama_model
    root = make_repo(model)
    st = model_status(root)
    print("status:", json.dumps(st))
    if st.get("status") != "ok":
        print("Ollama/model not ready; fix that first.")
        return 2
    wanted = {x for x in args.only.split(",") if x}
    start = time.monotonic()
    rows = []
    for case in (c for c in CASES if not wanted or c.id in wanted):
        print(f"running {case.id} ...", flush=True)
        rows.append(run_case(root, case, model))
        print(f"  -> {rows[-1]['status']} ok={rows[-1]['result_ok']} {rows[-1]['seconds']}s", flush=True)
    text = report(rows, model, time.monotonic() - start)
    Path("live_check_report.md").write_text(text, encoding="utf-8")
    Path("live_check_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("\n" + text)
    print(f"\nrepo kept at: {root}" if args.keep else "")
    return 0 if all(r["result_ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
