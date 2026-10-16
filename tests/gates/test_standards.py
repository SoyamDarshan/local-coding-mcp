import pytest

from localexec.gates import standards as st
from localexec.settings.config import ConfigError, load_config
from conftest import write_cfg

STD = st.Standards(max_function_lines=5, max_file_lines=40, warn_file_lines=20)


def fn(name, n, doc=True):
    body = ('    """doc\n    more doc\n    """\n' if doc else "") + "".join(f"    x{i} = {i}\n" for i in range(n))
    return f"def {name}():\n{body}    return 1\n"


def test_function_loc_excludes_docstring_comments_blanks():
    text = "def f():\n    \"\"\"d\n    d\n    \"\"\"\n\n    # comment\n    a = 1  # trailing\n    return a\n"
    (f,) = st.python_functions(text)
    assert f.loc == 3  # def line, a = 1, return a
    assert st.python_functions("def (:") is None


def test_methods_and_nested_get_qualified_names():
    text = "class A:\n    def m(self):\n        def inner():\n            return 1\n        return inner\n"
    assert [f.name for f in st.python_functions(text)] == ["A.m", "A.m.inner"]


def test_changed_ranges():
    assert st.changed_ranges(None, "a\n") is None
    assert st.changed_ranges("a\nb\nc\n", "a\nB\nc\n") == [(2, 2)]
    assert st.changed_ranges("a\nb\n", "a\n") == [(1, 2)]  # deletion marks the join line


def check(tmp_path, rel, new, old="<same>", std=STD):
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(new, encoding="utf-8")
    base = {rel: new if old == "<same>" else old}
    return st.check_files(tmp_path, std, [rel], base)


def test_new_long_function_fails(tmp_path):
    r = check(tmp_path, "a.py", fn("big", 10), old=None)
    assert r.failures and "a.py::big" in r.failures[0] and not r.fatal


def test_ratchet_untouched_legacy_function_is_ignored(tmp_path):
    old = fn("legacy", 10) + "\n\n" + fn("small", 1)
    new = old[: -len("    return 1\n")] + "    y = 1\n    return 1\n"  # small() grows by one line
    r = check(tmp_path, "a.py", new, old=old)
    assert not r.failures and not any("legacy" in w for w in r.warnings)


def test_ratchet_touched_legacy_not_worse_warns_worse_fails(tmp_path):
    old = fn("legacy", 10)
    same_size = old.replace("x3 = 3", "x3 = 33")
    r = check(tmp_path, "a.py", same_size, old=old)
    assert not r.failures and "legacy" in r.warnings[0]
    r = check(tmp_path, "a.py", old.replace("    return 1\n", "    z = 2\n    return 1\n"), old=old)
    assert r.failures


def test_ignore_marker(tmp_path):
    text = fn("big", 10).replace("def big():", "def big():  # lintlen: ignore")
    assert not check(tmp_path, "a.py", text, old=None).failures


def test_file_length_rules(tmp_path):
    big = "".join(f"v{i} = {i}\n" for i in range(45))
    r = check(tmp_path, "a.py", big, old=None)
    assert r.fatal and "split" in r.failures[0]
    legacy = check(tmp_path, "a.py", big, old=big + "w = 1\n")  # shrank: not worse
    assert not legacy.failures and "legacy" in legacy.warnings[0]
    grown = check(tmp_path, "a.py", big + "q = 1\n", old=big)
    assert grown.fatal
    soft = check(tmp_path, "a.py", "".join(f"v{i} = {i}\n" for i in range(25)), old=None)
    assert not soft.failures and "soft limit" in soft.warnings[0]


def test_exempt_and_non_code(tmp_path):
    big = "".join(f"v{i} = {i}\n" for i in range(60))
    assert not check(tmp_path, "migrations/001.py", big, old=None).failures
    assert not check(tmp_path, "notes.md", big, old=None).failures


def test_slash_languages_skip_comments(tmp_path):
    text = "// c\n/* a\n b */\nconst a = 1;\n\n/* x */ const b = 2;\n"
    assert len(st.code_lines("x.ts", text)) == 2


def test_config_standards_block(tmp_path):
    assert load_config(tmp_path).standards is None
    write_cfg(tmp_path, '{"standards": true}')
    c = load_config(tmp_path)
    assert c.standards.max_file_lines == 500 and c.checks[0].name == "standards"
    write_cfg(tmp_path, '{"standards": {"max_file_lines": 400, "warn_file_lines": 200, "exempt": ["gen/**"]}}')
    c = load_config(tmp_path)
    assert c.standards.max_file_lines == 400 and "gen/**" in c.standards.exempt and "migrations/**" in c.standards.exempt
    for bad in ['{"standards": {"x": 1}}', '{"standards": {"max_file_lines": 0}}',
                '{"standards": {"warn_file_lines": 900}}', '{"standards": 5}',
                '{"standards": true, "checks":[{"name":"standards","argv":["x"]}]}']:
        write_cfg(tmp_path, bad)
        with pytest.raises(ConfigError):
            load_config(tmp_path)
