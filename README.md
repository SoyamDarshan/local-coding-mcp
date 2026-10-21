# localexec-mcp

A local MCP server that lets Claude Code hand small, well-specified coding tasks to a model running in Ollama on your own machine, then verifies the result with your own tests and linters.

Claude plans the work and writes a spec. A local model writes the code. Your checks decide whether it passed. Claude gets back a short verdict instead of a diff, so a long coding session spends fewer tokens on writing code. No API key is needed, and the server only talks to your Ollama instance.

```
Claude Code ──spec──▶ localexec ──prompt──▶ Ollama (local model)
     ▲                    │                        │
     │                    ◀─────── edit blocks ────┘
     │                    │
     └─ short verdict ◀── apply edits, run your checks, retry on failure
```

## Features

- **Local inference.** The model runs in Ollama on your machine. localexec makes no other network calls.
- **Your checks decide.** Tests, linters and type checks from `.localexec.json` run after every task. Failures go back to the model.
- **Short results.** Each result is a few lines of JSON. Full diffs and logs are written to `.localexec/` in your project.
- **Atomic and reversible.** Every edit block must apply or nothing is written. `revert_task` restores files exactly.
- **Size limits.** Optional standards fail functions over 50 code lines and files over 500, so generated code stays reviewable.
- **Safe by default.** Paths stay inside the project, no shell is involved, nothing is deleted except files a task created, and it never commits.

## Requirements

- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/)
- git (projects must be git repositories)
- [Ollama](https://ollama.com) with a code model. The defaults expect `qwen-coder-16k`: `qwen2.5-coder:14b` with a 16,384-token context window
- Claude Code, or any MCP client that can start a stdio server

## Quick start

Install the server and create the model:

```bash
uv sync
printf 'FROM qwen2.5-coder:14b\nPARAMETER num_ctx 16384\n' > Modelfile
ollama create qwen-coder-16k -f Modelfile
```

Configure a project. Copy the example config into it and edit `checks` to the commands that should pass after every change:

```bash
cp <install-dir>/.localexec.example.json <your-project>/.localexec.json
cat <install-dir>/CLAUDE.snippet.md >> <your-project>/CLAUDE.md
```

Register the server with Claude Code:

```bash
claude mcp add --scope user localexec -- uv run --project <install-dir> localexec-mcp
claude mcp list
```

Use `--project`, not `--directory`: the server finds your project from the directory Claude Code launches it in. Windows PowerShell users can use `Copy-Item` and `Get-Content ... | Add-Content` in place of `cp` and `cat`. The [getting started guide](docs/getting-started.html) covers each step in detail.

## Tools

| Tool | What it does |
|---|---|
| `implement_task` | Gives one small task to the local model, applies its edits, runs your checks and retries on failure |
| `run_checks` | Runs the configured checks and returns pass or fail per check |
| `revert_task` | Undoes a task: restores changed files and removes files it created |
| `list_tasks` | Lists recent tasks, one short line each |
| `show_patch` | Skims a task's diff cheaply |
| `status` | Checks Ollama, the model and the config |
| `outline` | Lists a file's functions, classes and methods with line ranges |
| `find` | Regular-expression search over the project |

A task result looks like this:

```json
{"status":"passed","attempts":1,"files":["calc.py"],"stat":"+1 -1 in 1 file","patch":".localexec/T1.patch","log":".localexec/T1.log","escalate":false,"why":"all checks passed"}
```

`status` is `passed`, `failed`, `blocked`, `edit_failed` or `error`. When `escalate` is true, Claude should look at the problem rather than retry.

## Configuration

Each project has a `.localexec.json` in its root. Every key is optional:

```json
{
  "ollama_model": "qwen-coder-16k",
  "num_ctx": 16384,
  "max_attempts": 2,
  "standards": true,
  "checks": [
    { "name": "ruff", "argv": ["uv", "run", "ruff", "check", "{files}"], "files_filter": ["*.py"] },
    { "name": "pytest", "argv": ["uv", "run", "pytest", "-x", "-q"], "timeout": 600 }
  ],
  "conventions": "Python 3.12, type hints on all functions, no new dependencies.",
  "allowed_paths": ["src/**", "tests/**"]
}
```

`"{files}"` expands to the files a task changed, so a linter can run on only those. See `.localexec.example.json` for a fuller example and the [configuration reference](docs/configuration.html) for every key.

Environment variables: `LOCALEXEC_ROOT` sets the project root explicitly, and `LOCALEXEC_OLLAMA_URL` points at an Ollama server other than this machine.

## Documentation

The `docs/` folder is a static documentation site with a landing page, a getting started guide, the workflow for Claude, a tool and configuration reference, and troubleshooting. Open `docs/index.html` in a browser, or publish it with GitHub Pages: in the repository settings, choose **Deploy from a branch**, then the `main` branch and the `/docs` folder.

`CLAUDE.snippet.md` holds the workflow as instructions for your project's `CLAUDE.md`, and `SPEC_TEMPLATE.md` is the spec format.

## Development

```bash
uv sync
uv run pytest -q                       # unit tests with a mocked Ollama, no GPU needed
uv run python scripts/smoke_client.py  # real MCP stdio against a fake Ollama endpoint
uv run python scripts/live_check.py    # eight realistic tasks against your real Ollama
```

`live_check.py` builds a throwaway git repository and writes `live_check_report.md` and `live_check_results.json` in the current directory. Both are git-ignored.

The source is organised so that each package under `src/localexec/` groups one kind of problem, with at most ten source files per directory:

| Package | Concern |
|---|---|
| `server.py`, `core.py` | MCP entry point and task orchestration |
| `settings/` | config, path safety, task ids, standards defaults |
| `fsio/` | safe text reads and atomic writes |
| `editing/` | edit-block parsing, matching and application |
| `tasks/` | the implement-and-retry loop, prompts, Ollama client, status |
| `history/` | manifests, revert, task listing and patches |
| `gates/` | configured checks and the standards check |
| `vcs/` | git queries |
| `explore/`, `symbols/`, `structure/` | `outline` and `find`, symbol ranges, directory limits |

Dependencies point one way: `settings`, `fsio` and `vcs` are leaves, and `tasks` builds on everything below it. `tests/` mirrors the packages.

## License

MIT. See [LICENSE](LICENSE).
