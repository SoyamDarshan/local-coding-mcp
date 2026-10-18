"""Default protected paths and the matcher that applies them."""

from __future__ import annotations

import pytest

from localexec.settings.protected import DEFAULT_PROTECTED, protected_among

ROOT_HITS = [
    "conftest.py", "pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg", "setup.py", "noxfile.py",
    "sitecustomize.py", ".pytest.ini", "package.json", ".npmrc", ".yarnrc.yml", "jest.config.ts", "vitest.config.mts",
    "vite.config.js", "webpack.config.js", "babel.config.json", ".babelrc", ".babelrc.json",
    "eslint.config.mjs", ".eslintrc.cjs", "Makefile", "justfile", "Dockerfile", "Dockerfile.dev",
    "docker-compose.yml", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "Cargo.toml", "build.rs", ".github/workflows/ci.yml", ".gitlab-ci.yml", ".circleci/config.yml",
    ".husky/pre-commit", ".pre-commit-config.yaml", ".vscode/settings.json", ".scmexec.json",
    ".mcp.json", "CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude/settings.json",
]
LOOKALIKES = [
    "src/app.py", "tests/test_a.py", "README.md", "my_conftest.py", "src/package_json_helpers.py",
    "setup.py.bak", "docs/build.rs.md",
]


@pytest.mark.parametrize("rel", ROOT_HITS)
def test_default_hits_at_root_and_nested(rel):
    assert protected_among([rel]) == [rel]
    nested = f"web/app/{rel}"
    assert protected_among([nested]) == [nested]


@pytest.mark.parametrize("rel", LOOKALIKES)
def test_ordinary_and_lookalike_names_are_not_protected(rel):
    assert protected_among([rel]) == []


def test_default_patterns_are_lower_case():
    assert all(p == p.lower() for p in DEFAULT_PROTECTED)


def test_case_is_ignored_and_spelling_kept():
    paths = ["PyProject.toml", ".GitHub/Workflows/CI.yml"]
    assert protected_among(paths) == paths


def test_order_and_duplicates():
    assert protected_among(["b/conftest.py", "a/conftest.py", "b/conftest.py"]) == ["b/conftest.py", "a/conftest.py"]


def test_extra_patterns_add_and_are_case_insensitive():
    assert protected_among(["secrets/prod.yml", "src/a.py"], extra=["SECRETS/**"]) == ["secrets/prod.yml"]


def test_allow_exempts_defaults_and_extras():
    assert protected_among(["package.json", "a/package.json"], allow=["package.json"]) == []
    got = protected_among(["secrets/public.txt", "secrets/key.txt"], extra=["secrets/**"], allow=["secrets/public.txt"])
    assert got == ["secrets/key.txt"]


def test_allow_anchoring():
    paths = ["package.json", "web/package.json", "x/web/package.json"]
    assert protected_among(paths, allow=["/web/package.json"]) == ["package.json", "x/web/package.json"]
    assert protected_among(paths, allow=["web/package.json"]) == ["package.json"]


def test_allow_double_star_switches_protection_off():
    assert protected_among(["package.json"], allow=["**"]) == []
