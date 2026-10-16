"""Review fixes: task ids, Windows-style names, ignore anchoring, config validation, Ollama replies."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import write_cfg

from localexec.tasks import ollama
from localexec.settings.common import TaskError, check_task_id, state_dir
from localexec.settings.config import Config, ConfigError, load_config
from localexec.settings.safety import PathError, glob_match, resolve_in_root


@pytest.mark.parametrize("bad", ["a\n", "NUL", "nul.txt", "Com1", "a.", "run_checks", "RUN_CHECKS", "", "-x", "a/b"])
def test_bad_task_ids_are_rejected(bad):
    with pytest.raises(TaskError):
        check_task_id(bad)


@pytest.mark.parametrize("good", ["T1", "T3-retry-backoff", "a.b_c", "D1b-dir-report", "console"])
def test_good_task_ids_pass(good):
    check_task_id(good)


@pytest.mark.parametrize("bad", ["a.py::$DATA", "src/NUL", "src/nul.txt", "x.py.", "dir /f.py", "C:evil.py", "a:b.py"])
def test_windows_style_names_are_rejected_on_every_os(tmp_path, bad):
    with pytest.raises(PathError):
        resolve_in_root(tmp_path.resolve(), bad)


def test_normal_nested_paths_still_resolve(tmp_path):
    root = tmp_path.resolve()
    assert resolve_in_root(root, "src/pkg/mod.py") == root / "src" / "pkg" / "mod.py"
    assert resolve_in_root(root, "./a/../b.py") == root / "b.py"


def test_default_ignores_are_anchored_to_the_project_root():
    ig = Config().ignore
    assert glob_match("build/out.js", ig) and glob_match("data/x.csv", ig) and glob_match("dist/a.js", ig)
    assert not glob_match("src/build/tool.py", ig) and not glob_match("app/data/models.py", ig)
    assert glob_match("pkg/node_modules/x.js", ig) and glob_match("a/__pycache__/m.pyc", ig)


def test_remote_ollama_url_in_project_config_is_refused(proj):
    write_cfg(proj, json.dumps({"ollama_url": "http://evil.example:11434"}))
    with pytest.raises(ConfigError, match="localhost"):
        load_config(proj)
    write_cfg(proj, json.dumps({"ollama_url": "http://localhost:11434"}))
    assert load_config(proj).ollama_url == "http://localhost:11434"


def test_env_override_may_point_elsewhere_but_must_be_http(proj, monkeypatch):
    monkeypatch.setenv("LOCALEXEC_OLLAMA_URL", "http://gpu-box:11434")
    assert load_config(proj).ollama_url == "http://gpu-box:11434"
    monkeypatch.setenv("LOCALEXEC_OLLAMA_URL", "file:///etc/passwd")
    with pytest.raises(ConfigError, match="http"):
        load_config(proj)


@pytest.mark.parametrize(
    "raw", ['{"num_ctx": 0}', '{"request_timeout": -5}', '{"temperature": NaN}', '{"temperature": 9}', '{"allowed_paths": []}']
)
def test_nonsense_config_values_are_rejected(proj, raw):
    write_cfg(proj, raw)
    with pytest.raises(ConfigError):
        load_config(proj)


def test_state_dir_must_stay_inside_the_project(proj, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    try:
        (proj / ".localexec").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted here")
    with pytest.raises(TaskError, match="outside"):
        state_dir(proj)


def handler(payload, status=200):
    return httpx.MockTransport(lambda request: httpx.Response(status, json=payload))


def test_ollama_null_content_is_an_error():
    with pytest.raises(ollama.OllamaError, match="no text"):
        ollama.chat(Config(), [], transport=handler({"message": {"content": None}}))


def test_ollama_model_lists_tolerate_odd_shapes():
    assert ollama.installed_models(Config(), handler({"models": [None, {"name": "m:latest"}, {"x": 1}]})) == {"m:latest", "m"}
    with pytest.raises(ollama.OllamaError):
        ollama.installed_models(Config(), handler(["not", "an", "object"]))
    assert ollama.loaded_models(Config(), handler({"models": "oops"})) == set()
