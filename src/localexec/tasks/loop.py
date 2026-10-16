"""The attempt loop: prompt -> model -> apply -> checks -> retry."""

from __future__ import annotations

from typing import Callable

from ..gates import checks as checks_mod
from ..settings.common import err, est_tokens, make_key_resolver
from ..settings.config import Config
from ..editing.apply import EditApplyError, FileState, apply_edits, read_state, write_atomic
from ..editing.parse import EditParseError, is_blocked_reply, parse_edits
from ..history.manifest import Ctx, backup, baselines, finish, save_manifest
from .ollama import ChatResult, OllamaError
from .preflight import Prepared
from .prompting import FORMAT_PROMPT, SYSTEM_PROMPT, build_prompt
from ..symbols.focus import focus_excerpts

EXCERPT_LINES = 30
EXCERPT_CHARS = 900
ChatFn = Callable[[Config, list[dict[str, str]]], ChatResult]


def generate_edits(
    c: Ctx,
    chat_fn: ChatFn,
    messages: list[dict[str, str]],
    states: dict[str, FileState],
    resolver: Callable[[str], str | None],
    tag: str,
    partial: set[str] | None = None,
) -> tuple[str, object]:
    """One model call plus at most one repair round for edit parse/apply errors.

    Returns ("blocked", question) | ("edits", new_text_dict) | ("edit_error", message).
    """
    last_err = ""
    for repair in (0, 1):
        reply = chat_fn(c.cfg, messages)
        c.log.write(
            f"{tag} model reply{' (repair)' if repair else ''} "
            f"[prompt_tokens={reply.prompt_tokens} out={reply.output_tokens} done={reply.done_reason}]",
            reply.content,
        )
        if reply.prompt_tokens and reply.prompt_tokens >= 0.98 * c.cfg.num_ctx:
            note = "prompt filled the context window; Ollama may have cut it (raise num_ctx or lower prompt_budget_tokens)"
            if note not in c.warnings:
                c.warnings.append(note)
        q = is_blocked_reply(reply.content)
        if q is not None:
            return "blocked", q
        try:
            if reply.done_reason == "length":
                raise EditParseError("output was cut off (token limit); produce smaller, focused edits")
            edits = parse_edits(reply.content)
            return "edits", apply_edits(states, edits, resolver, partial)
        except EditParseError as e:
            last_err = f"parse error: {e}"
        except EditApplyError as e:
            last_err = "; ".join(e.messages)
        c.log.write(f"{tag} edit error", last_err)
        if repair == 0:
            messages = messages + [
                {"role": "assistant", "content": reply.content[:6000]},
                {
                    "role": "user",
                    "content": "Your edit blocks could not be applied. NOTHING was changed. Problems:\n"
                    + last_err[:2500]
                    + "\nResend corrected edit blocks only (all of them), same format.",
                },
            ]
    return "edit_error", last_err


class TaskRunner:
    """Runs up to max_attempts generations for one prepared task and builds the final result."""

    def __init__(self, c: Ctx, prep: Prepared, spec: str, chat_fn: ChatFn, check_runner: Callable[..., checks_mod.CheckResult]):
        self.c, self.prep, self.spec = c, prep, spec
        self.chat_fn, self.check_runner = chat_fn, check_runner
        self.resolver = make_key_resolver(c.root, set(prep.targets))
        self.failure: str | None = None
        self.notes: list[str] = []
        self.warnings: list[str] = []
        self.failed: tuple[str, str] = ("", "")
        self.no_retry = False
        self.attempts = 0

    def run(self) -> dict:
        try:
            for attempt in range(1, self.c.cfg.max_attempts + 1):
                self.attempts = attempt
                result = self._attempt(attempt)
                if result is not None:
                    return result
                if self.no_retry:
                    break
            return self._give_up()
        except Exception as e:  # never leave a task without a final status
            self.c.log.write("INTERNAL ERROR", repr(e))
            return self._finish("error", True, "internal error", {"error": f"{type(e).__name__}: {e}"[:300]})

    def _finish(self, status: str, escalate: bool, why: str, extra: dict | None = None) -> dict:
        """finish() plus the reminder that edits from an earlier attempt are still in the tree."""
        extra = {**self._extra(), **(extra or {})}
        if self.c.originals and "note" not in extra:
            extra["note"] = "earlier attempt's changes remain in the tree"
        return finish(self.c, status, self.attempts, escalate, why, extra)

    def _extra(self) -> dict:
        extra: dict = {}
        if self.notes:
            extra["truncated"] = self.notes
        warnings = [*self.warnings, *self.c.warnings]
        if warnings:
            extra["warnings"] = [w[:160] for w in warnings[:5]]
        return extra

    def _attempt(self, attempt: int) -> dict | None:
        """Final result dict, or None to continue with the next attempt."""
        c = self.c
        try:
            states = {rel: read_state(rel, p) for rel, p in self.prep.targets.items()}
        except EditApplyError as e:
            return self._finish("error", False, "cannot read a file to edit", {"error": str(e)[:300]})
        texts = {rel: (st.text if st.existed else None) for rel, st in states.items()}
        excerpts = focus_excerpts(texts, self.prep.focus)
        prompt, notes, too_big = build_prompt(c.cfg, self.spec, states, self.prep.context, self.failure, excerpts)
        self.notes = notes or self.notes
        if too_big:
            c.log.write("BLOCKED (budget)", too_big)
            return self._finish("blocked", False, "prompt over budget", {"question": too_big})
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + FORMAT_PROMPT},
            {"role": "user", "content": prompt},
        ]
        c.log.write(f"attempt {attempt} prompt (~{est_tokens(prompt)} tokens)", prompt)
        try:
            kind, payload = generate_edits(
                c, self.chat_fn, messages, states, self.resolver, f"attempt {attempt}", set(excerpts)
            )
        except OllamaError as e:
            c.log.write("OLLAMA ERROR", str(e))
            return self._finish("error", False, "ollama unavailable", {"error": str(e)[:300]})
        if kind != "edits":
            return self._model_gave_up(kind, payload)
        if not payload:
            self.failure = ((self.failure or "") + "\n(your last reply made no changes)").strip()
            c.log.write("no-op edits")
            return None
        return self._apply_and_check(attempt, states, payload)  # type: ignore[arg-type]

    def _model_gave_up(self, kind: str, payload: object) -> dict:
        if kind == "blocked":
            return self._finish("blocked", False, "local model needs a spec clarification", {"question": payload})
        return self._finish("edit_failed", True, "local model could not produce applicable edits", {"error": str(payload)[:400]})

    def _apply_and_check(self, attempt: int, states: dict[str, FileState], new_text: dict[str, str]) -> dict | None:
        c = self.c
        for rel in new_text:
            p = self.prep.targets[rel]
            backup(c, rel, p.read_bytes() if p.exists() else None)
        c.status = "running"
        save_manifest(c)  # provisional: lets revert_task recover if the process dies mid-write
        try:
            write_atomic(states, new_text)
        except OSError as e:
            return self._finish("error", False, "write failed", {"error": str(e)[:300]})
        save_manifest(c)
        c.log.write(f"attempt {attempt} applied", ", ".join(new_text))
        failing = self._run_checks()
        if failing is None:
            selected = self.prep.selected
            why = "all checks passed" if selected else "applied; no checks configured"
            return finish(c, "passed", attempt, False, why, self._extra())
        self.failed = (failing.name, checks_mod.excerpt(failing.output, EXCERPT_LINES, EXCERPT_CHARS))
        self.failure = f"Check `{failing.name}` failed:\n" + checks_mod.trim_for_model(failing.output)
        self.no_retry = not failing.retry
        return None

    def _run_checks(self) -> checks_mod.CheckResult | None:
        c = self.c
        changed, bl = sorted(c.originals), baselines(c)
        for ch in self.prep.selected:
            r = self.check_runner(ch, c.root, files=changed, baselines=bl, std=c.cfg.standards)
            c.log.write(f"check {ch.name} -> {'OK' if r.ok else 'FAIL'} rc={r.returncode} {r.seconds:.1f}s", r.output)
            self.warnings.extend(w for w in r.warnings if w not in self.warnings)
            if not r.ok:
                return r
        return None

    def _give_up(self) -> dict:
        name, output = self.failed
        extra = self._extra()
        if name:
            extra.update({"failed_check": name, "output": output})
            why = (
                f"'{name}' needs a planner decision (not retried)"
                if self.no_retry
                else f"check '{name}' still failing after {self.attempts} attempt(s)"
            )
        else:
            why = f"no usable change after {self.attempts} attempt(s)"
        return finish(self.c, "failed", self.attempts, True, why, extra)  # tree state is in the patch
