"""The protected_paths and allow_protected config keys."""

from __future__ import annotations

import json

import pytest
from conftest import write_cfg

from localexec.settings.config import ConfigError, load_config

KEYS = ("protected_paths", "allow_protected")


def test_keys_default_to_empty(proj):
    cfg = load_config(proj)
    assert cfg.protected_paths == [] and cfg.allow_protected == []


def test_keys_are_loaded(proj):
    write_cfg(proj, json.dumps({"protected_paths": ["secrets/**"], "allow_protected": ["package.json"]}))
    cfg = load_config(proj)
    assert cfg.protected_paths == ["secrets/**"] and cfg.allow_protected == ["package.json"]


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("bad", ["x", ["ok", 3], {"a": 1}, None])
def test_wrong_types_are_rejected(proj, key, bad):
    write_cfg(proj, json.dumps({key: bad}))
    with pytest.raises(ConfigError, match=f"{key} must be a list of strings"):
        load_config(proj)
