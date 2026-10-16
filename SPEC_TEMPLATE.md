# Spec template (one per implement_task call)

Copy the fields into the tool call. Keep a task to 1-2 files.

```
task_id:        T<number>-<short-slug>        # unique, [A-Za-z0-9._-], e.g. T3-retry-backoff
files_to_edit:  [path/relative/to/project.py]  # 1-2 files; new files must be listed here too
context_files:  [path/to/read_only_reference.py]   # optional; only what the model must see
checks:         [ruff, pytest]                 # optional; default = all configured checks

spec: |
  GOAL: <one sentence>
  FILES: <each file and what changes in it>
  STEPS:
    1. <concrete change>
    2. <concrete change>
  SIGNATURES (exact):
    def fetch(url: str, *, retries: int = 3) -> bytes: ...
  EDGE CASES:
    - <input -> expected behaviour>
  DO NOT: <things to leave alone>
  ACCEPTANCE: <which checks / tests must pass, observable behaviour>
```

Tips: name the function or class to change; give exact signatures; list edge cases as
input -> output pairs; say what NOT to touch; if a test must be added, name the test file
in files_to_edit and give the test cases.
