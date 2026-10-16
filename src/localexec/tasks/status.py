"""Backend health: project config, Ollama model state and recorded task count."""

from __future__ import annotations

from pathlib import Path

import httpx

from . import ollama
from ..settings.config import ConfigError, load_config
from ..history.taskinfo import manifests


def status(root: Path, transport: httpx.BaseTransport | None = None) -> dict:
    try:
        cfg = load_config(root)
    except ConfigError as e:
        return {"status": "error", "config": str(e)[:200]}
    out: dict = {"status": "ok", "project": root.name, "model": cfg.ollama_model, "checks": [c.name for c in cfg.checks]}
    try:
        installed = ollama.installed_models(cfg, transport)
        out["model_installed"] = cfg.ollama_model in installed
        out["model_loaded"] = cfg.ollama_model in ollama.loaded_models(cfg, transport)
        if not out["model_installed"]:
            out["status"] = "error"
            out["hint"] = f"run: ollama list  (model '{cfg.ollama_model}' not found)"
    except ollama.OllamaError as e:
        out["status"] = "error"
        out["ollama"] = str(e)[:200]
    out["tasks"] = len(manifests(root))
    return out
