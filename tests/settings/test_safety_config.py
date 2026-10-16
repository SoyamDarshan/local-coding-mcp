import os
import pytest

from localexec.settings.config import ConfigError, load_config
from localexec.settings.safety import PathError, glob_match, resolve_in_root
from conftest import write_cfg


def test_traversal_and_absolute(tmp_path):
    root = (tmp_path / "r").resolve(); root.mkdir()
    (tmp_path / "secret.txt").write_text("s")
    with pytest.raises(PathError):
        resolve_in_root(root, "../secret.txt")
    with pytest.raises(PathError):
        resolve_in_root(root, str(tmp_path / "secret.txt"))
    assert resolve_in_root(root, "a/b.py") == root / "a" / "b.py"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlink_escape(tmp_path):
    root = (tmp_path / "r").resolve(); root.mkdir()
    outside = tmp_path / "out"; outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathError):
        resolve_in_root(root, "link/x.py")


def test_globs():
    ig = ["node_modules/**", "*.lock", "data/**", ".env.*"]
    assert glob_match("node_modules/a/b.js", ig)
    assert glob_match("web/node_modules/a.js", ig)
    assert glob_match("uv.lock", ig) and glob_match("web/yarn.lock", ig)
    assert glob_match(".env.local", ig)
    assert not glob_match("src/app.py", ig)
    assert glob_match("src/a/b.py", ["src/**"], any_depth=False)
    assert not glob_match("web/src/a.py", ["src/**"], any_depth=False)


def test_config_defaults_and_errors(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.temperature == 0.1 and cfg.max_attempts == 2 and ".git/**" in cfg.ignore
    write_cfg(tmp_path, '{"ignore":["gen/**"],"checks":[{"name":"x","argv":["echo"]}]}')
    cfg = load_config(tmp_path)
    assert "gen/**" in cfg.ignore and "node_modules/**" in cfg.ignore and cfg.checks[0].timeout == 300
    for bad in ['{"typo":1}', '{"max_attempts":0}', '{"checks":[{"name":"x"}]}', "not json"]:
        write_cfg(tmp_path, bad)
        with pytest.raises(ConfigError):
            load_config(tmp_path)
