"""Minimal Ollama /api/chat client (non-streaming). Talks only to the local Ollama server."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..settings.config import Config


class OllamaError(Exception):
    pass


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int | None
    output_tokens: int | None
    done_reason: str | None


def chat(
    cfg: Config,
    messages: list[dict[str, str]],
    transport: httpx.BaseTransport | None = None,
) -> ChatResult:
    body = {
        "model": cfg.ollama_model,
        "messages": messages,
        "stream": False,
        "keep_alive": cfg.keep_alive,
        "options": {
            "num_ctx": cfg.num_ctx,
            "temperature": cfg.temperature,
            "num_predict": cfg.max_output_tokens,
        },
    }
    url = cfg.ollama_url.rstrip("/") + "/api/chat"
    try:
        with httpx.Client(timeout=cfg.request_timeout, transport=transport, trust_env=False) as client:
            resp = client.post(url, json=body)
    except httpx.ConnectError as e:
        raise OllamaError(f"cannot reach Ollama at {cfg.ollama_url} (is it running?): {e}") from e
    except httpx.TimeoutException as e:
        raise OllamaError(f"Ollama request timed out after {cfg.request_timeout}s") from e
    except httpx.HTTPError as e:
        raise OllamaError(f"Ollama request failed: {e}") from e
    if resp.status_code != 200:
        raise OllamaError(f"Ollama HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        content = data["message"]["content"]
    except (ValueError, KeyError, TypeError) as e:
        raise OllamaError(f"unexpected Ollama response: {resp.text[:300]}") from e
    if not isinstance(content, str):
        raise OllamaError(f"unexpected Ollama response (no text content): {resp.text[:300]}")
    return ChatResult(
        content=content,
        prompt_tokens=data.get("prompt_eval_count"),
        output_tokens=data.get("eval_count"),
        done_reason=data.get("done_reason"),
    )


def _get(cfg: Config, path: str, transport: httpx.BaseTransport | None) -> dict:
    url = cfg.ollama_url.rstrip("/") + path
    try:
        with httpx.Client(timeout=10, transport=transport, trust_env=False) as client:
            resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data
    except httpx.ConnectError as e:
        raise OllamaError(f"cannot reach Ollama at {cfg.ollama_url} (is it running?)") from e
    except (httpx.HTTPError, ValueError) as e:
        raise OllamaError(f"Ollama {path} failed: {e}") from e


def _names(data: dict) -> set[str]:
    models = data.get("models")
    names = {m["name"] for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)} if isinstance(models, list) else set()
    return names | {n.removesuffix(":latest") for n in names}


def installed_models(cfg: Config, transport: httpx.BaseTransport | None = None) -> set[str]:
    return _names(_get(cfg, "/api/tags", transport))


def loaded_models(cfg: Config, transport: httpx.BaseTransport | None = None) -> set[str]:
    return _names(_get(cfg, "/api/ps", transport))
