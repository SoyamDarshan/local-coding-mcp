"""Paths the local model may not edit: files that decide what runs or how Claude is configured."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .safety import glob_match

# Lower-case on purpose: matching folds case so the result is the same on every operating system.
DEFAULT_PROTECTED: tuple[str, ...] = (
    # Python test and build config
    "conftest.py", "pyproject.toml", "pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg", "setup.py", "noxfile.py",
    "sitecustomize.py",
    # Node tooling
    "package.json", ".npmrc", ".yarnrc*", "jest.config.*", "vitest.config.*", "vite.config.*",
    "webpack.config.*", "babel.config.*", ".babelrc*", "eslint.config.*", ".eslintrc*",
    # Build and container
    "makefile", "justfile", "dockerfile*", "docker-compose*", "pom.xml", "build.gradle*",
    "settings.gradle*", "cargo.toml", "build.rs",
    # CI and hooks
    ".github/**", ".gitlab-ci.yml", ".circleci/**", ".husky/**", ".pre-commit-config.yaml", ".vscode/**",
    # Control plane around Claude (push/merge switches, registered programs, standing instructions)
    ".scmexec.json", ".mcp.json", "claude.md", "claude.local.md", "agents.md", ".claude/**",
)


def protected_among(paths: Iterable[str], extra: Sequence[str] = (), allow: Sequence[str] = ()) -> list[str]:
    """The protected subset of `paths` (project-relative, posix): input order, de-duplicated, spelling kept.

    A path is protected when it matches a default or `extra` pattern and no `allow` pattern. Patterns
    apply at any depth unless they start with `/`.
    """
    patterns = [p.lower() for p in (*DEFAULT_PROTECTED, *extra)]
    exempt = [p.lower() for p in allow]
    out: list[str] = []
    for path in paths:
        low = path.lower()
        if path not in out and glob_match(low, patterns) and not glob_match(low, exempt):
            out.append(path)
    return out
