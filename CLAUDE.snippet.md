## Local implementation delegate (localexec MCP)

Workflow for any code change:

1. **Plan first.** Explore, then write a short plan split into tasks of 1-2 files each.
2. **Write a spec per task** in this fixed format and pass it as `spec`:
   `GOAL / FILES / STEPS / SIGNATURES (exact) / EDGE CASES / DO NOT / ACCEPTANCE (checks)`.
   Use a unique `task_id` such as `T3-retry-backoff`. List only the 1-2 files to change in
   `files_to_edit` and only the files the local model must see in `context_files`.
3. **Delegate every implementation step** with the `implement_task` tool. Do NOT write
   implementation code yourself, and do not re-read files after a `passed` result: the compact
   result is the source of truth.
4. **Read the result:**
   - `passed` -> move to the next task.
   - `blocked` -> the local model asked a question (`question`); answer it by improving the spec
     and call again.
   - `failed` or `escalate: true` -> only now read `.localexec/<task_id>.patch` (and the log if
     needed), then either fix the spec and retry with a new `task_id`, or implement it yourself.
   - `edit_failed` -> shrink the task or make the spec more precise; retry with a new task_id.
5. **Write code yourself only if** `escalate` is true, or the task is security-sensitive (auth,
   permissions, migrations, concurrency, secrets, crypto).
6. Call `status` once at the start of a session (Ollama up, model installed). After context loss call
   `list_tasks` instead of guessing what is done. Review a `passed` task cheaply with `show_patch`.
7. **Coding standards** (enforced by the `standards` check): functions <= 50 code lines, files <= 500
   (aim for 200-300). Before writing a spec, look for an existing helper to reuse (`find` for
   names/patterns, `outline` for a file's symbols) and name it in the spec; never ask for duplicated logic. Specify
   new helpers by name and signature so functions stay small. If a task would push a file past ~300
   lines, plan the split first (new file as its own task).
   A result with `warnings` is a hint to plan a split soon; `failed_check: standards` with
   `escalate: true` means a file is over the limit: split it, do not retry.
8. **Big files:** instead of passing a whole file to the local model, pass
   `symbols=["path/file.py::func", "path/file.ts::Class.method"]` (use `outline` to get exact names).
   The model then sees only those symbols plus a few context lines. Edits to other parts of the
   file are still located by SEARCH text. Whole-file rewrites are refused for excerpted files.
9. Use `run_checks` for a final full check and `revert_task` to undo a bad task. Never commit;
   leave changes in the working tree for the user to review.
10. **Protected files:** if `implement_task` returns "protected file(s)", edit that file yourself;
    do not retry or look for a way around it.
