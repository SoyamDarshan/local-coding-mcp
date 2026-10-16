"""Project configuration (<project>/.localexec.json)."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .defaults import Standards

REPAIR_RESERVE_TOKENS = 2500  # room for the assistant reply + error message of one repair round
CONFIG_NAME = ".localexec.json"
STATE_DIR = ".localexec"

DEFAULT_IGNORE = [
    ".git/**",
    ".localexec/**",
    CONFIG_NAME,
    "node_modules/**",
    ".venv/**",
    "venv/**",
    "__pycache__/**",
    "/dist/**",  # anchored: a package named src/build or app/data is source, not output
    "/build/**",
    "/data/**",
    "*.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    ".env",
    ".env.*",
]


class ConfigError(Exception):
    pass


@dataclass
class Check:
    name: str
    argv: list[str]
    cwd: str = "."
    timeout: int = 300
    files_filter: list[str] = field(default_factory=list)  # run only if a changed file matches


@dataclass
class Config:
    ollama_model: str = "qwen-coder-16k"
    ollama_url: str = "http://localhost:11434"
    num_ctx: int = 16384
    temperature: float = 0.1
    max_attempts: int = 2
    max_output_tokens: int = 4096
    prompt_budget_tokens: int = 8000
    keep_alive: str = "10m"
    request_timeout: int = 600
    checks: list[Check] = field(default_factory=list)
    conventions: str = ""
    allowed_paths: list[str] = field(default_factory=lambda: ["**"])
    ignore: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE))
    standards: Standards | None = None  # enabled by a "standards" block in the config

    @property
    def prompt_budget_chars(self) -> int:
        budget = min(self.prompt_budget_tokens, self.num_ctx - self.max_output_tokens - REPAIR_RESERVE_TOKENS)
        return max(1000, int(budget * 3.5))


_SCALARS = {
    "ollama_model": str,
    "ollama_url": str,
    "num_ctx": int,
    "temperature": (int, float),
    "max_attempts": int,
    "max_output_tokens": int,
    "prompt_budget_tokens": int,
    "keep_alive": str,
    "request_timeout": int,
    "conventions": str,
}


STANDARDS_ARGV0 = "builtin:standards"


def _parse_standards(raw: Any) -> Standards | None:
    if raw in (None, False):
        return None
    std = Standards()
    if raw is True:
        return std
    if not isinstance(raw, dict):
        raise ConfigError("standards must be true or an object")
    bad = set(raw) - {"max_function_lines", "max_file_lines", "warn_file_lines", "exempt"}
    if bad:
        raise ConfigError(f"unknown key(s) in standards: {', '.join(sorted(bad))}")
    for key in ("max_function_lines", "max_file_lines", "warn_file_lines"):
        if key in raw:
            if isinstance(raw[key], bool) or not isinstance(raw[key], int) or raw[key] < 1:
                raise ConfigError(f"standards.{key} must be a positive integer")
            setattr(std, key, raw[key])
    if "exempt" in raw:
        if not isinstance(raw["exempt"], list) or not all(isinstance(x, str) for x in raw["exempt"]):
            raise ConfigError("standards.exempt must be a list of strings")
        std.exempt = list(dict.fromkeys(std.exempt + raw["exempt"]))
    if std.warn_file_lines > std.max_file_lines:
        raise ConfigError("standards.warn_file_lines must be <= max_file_lines")
    return std


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _check_url(url: str, loopback_only: bool) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError("ollama_url must be an http(s) URL")
    if loopback_only and parts.hostname.lower() not in LOOPBACK_HOSTS:
        raise ConfigError(
            "ollama_url in the project config must point to this machine (localhost); "
            "set the LOCALEXEC_OLLAMA_URL environment variable to use another server"
        )


def _read_raw(root: Path) -> dict[str, Any]:
    path = root / CONFIG_NAME
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"cannot read {CONFIG_NAME}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{CONFIG_NAME} must be a JSON object")
    unknown = set(raw) - (set(_SCALARS) | {"checks", "allowed_paths", "ignore", "standards"})
    if unknown:
        raise ConfigError(f"unknown key(s) in {CONFIG_NAME}: {', '.join(sorted(unknown))}")
    return raw


def _apply_scalars(cfg: Config, raw: dict[str, Any]) -> None:
    for key, typ in _SCALARS.items():
        if key in raw:
            if isinstance(raw[key], bool) or not isinstance(raw[key], typ):
                raise ConfigError(f"{key} has the wrong type")
            setattr(cfg, key, raw[key])
    if cfg.max_attempts < 1:
        raise ConfigError("max_attempts must be >= 1")
    for key in ("num_ctx", "max_output_tokens", "prompt_budget_tokens", "request_timeout"):
        if getattr(cfg, key) < 1:
            raise ConfigError(f"{key} must be a positive integer")
    if not (isinstance(cfg.temperature, (int, float)) and math.isfinite(cfg.temperature) and 0 <= cfg.temperature <= 2):
        raise ConfigError("temperature must be a number between 0 and 2")


def _apply_globs(cfg: Config, raw: dict[str, Any]) -> None:
    for key in ("allowed_paths", "ignore"):
        if key not in raw:
            continue
        v = raw[key]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ConfigError(f"{key} must be a list of strings")
        if key == "ignore":
            cfg.ignore = list(dict.fromkeys(DEFAULT_IGNORE + v))
        else:
            if not v:
                raise ConfigError("allowed_paths must not be empty (omit it to allow every path)")
            cfg.allowed_paths = v


def _parse_check(item: Any, seen: set[str]) -> Check:
    if not isinstance(item, dict):
        raise ConfigError("each check must be an object")
    bad = set(item) - {"name", "argv", "cwd", "timeout", "files_filter"}
    if bad:
        raise ConfigError(f"unknown key(s) in check: {', '.join(sorted(bad))}")
    name, argv = item.get("name"), item.get("argv")
    if not isinstance(name, str) or not name:
        raise ConfigError("check needs a 'name'")
    if name in seen:
        raise ConfigError(f"duplicate check name: {name}")
    seen.add(name)
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ConfigError(f"check '{name}': argv must be a non-empty list of strings")
    timeout = item.get("timeout", 300)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise ConfigError(f"check '{name}': timeout must be a positive integer (seconds)")
    cwd = item.get("cwd", ".")
    if not isinstance(cwd, str):
        raise ConfigError(f"check '{name}': cwd must be a string")
    if [a for a in argv if "{files}" in a] not in ([], ["{files}"]):
        raise ConfigError(f"check '{name}': '{{files}}' must be a whole argv element, used once")
    ff = item.get("files_filter", [])
    if not isinstance(ff, list) or not all(isinstance(x, str) for x in ff):
        raise ConfigError(f"check '{name}': files_filter must be a list of glob strings")
    return Check(name=name, argv=argv, cwd=cwd, timeout=timeout, files_filter=ff)


def load_config(root: Path) -> Config:
    cfg = Config()
    raw = _read_raw(root)
    _apply_scalars(cfg, raw)
    _apply_globs(cfg, raw)
    seen: set[str] = set()
    cfg.checks = [_parse_check(item, seen) for item in raw.get("checks", [])]
    cfg.standards = _parse_standards(raw.get("standards"))
    if cfg.standards is not None:
        if "standards" in seen:
            raise ConfigError("check name 'standards' is reserved when a standards block is present")
        cfg.checks.insert(0, Check(name="standards", argv=[STANDARDS_ARGV0], timeout=60))
    _check_url(cfg.ollama_url, loopback_only=True)  # the project file is untrusted input
    env_url = os.environ.get("LOCALEXEC_OLLAMA_URL")
    if env_url:
        _check_url(env_url, loopback_only=False)
        cfg.ollama_url = env_url
    return cfg
