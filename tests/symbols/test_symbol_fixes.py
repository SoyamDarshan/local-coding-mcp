"""Review fixes for symbols: setters/overloads, conditional defs, TS decorators, tolerant retries."""

from __future__ import annotations

import pytest

from localexec.explore.outline import outline
from localexec.fsio.text import BOM
from localexec.symbols import SymbolError, build_excerpt, find_symbols, list_symbols
from localexec.symbols.focus import focus_excerpts

PROP = '''class A:
    @property
    def x(self):
        return 1

    @x.setter
    def x(self, v):
        pass
'''

COND = '''from typing import TYPE_CHECKING

if TYPE_CHECKING:
    def helper(a: int) -> int: ...
else:
    def helper(a): return a

try:
    import json
except ImportError:
    def fallback(): return 1
'''

TS = '''class Cmp {
  @HostListener('click')
  @Debounce(10)
  onClick(e: Event): void {}

  over(a: string): void;
  over(a: number): void;
  over(a: any): void { }
}
function f(a: string): string;
function f(a: number): number;
function f(a: any): any { return a; }
'''


def test_property_setter_pair_is_one_selectable_symbol():
    found, problems = find_symbols(list_symbols("a.py", PROP), ["A.x"])
    assert problems == [] and (found[0].start, found[0].end) == (2, 8)


def test_definitions_under_if_and_try_are_found():
    names = {s.name for s in list_symbols("a.py", COND)}
    assert {"helper", "fallback"} <= names
    found, problems = find_symbols(list_symbols("a.py", COND), ["helper"])
    assert problems == [] and len(found) == 1


def test_ts_method_range_includes_its_decorators():
    syms = {s.name: s for s in list_symbols("a.ts", TS)}
    assert syms["Cmp.onClick"].start == 2


def test_ts_overload_signatures_are_part_of_the_symbol():
    found, problems = find_symbols(list_symbols("a.ts", TS), ["f"])
    assert problems == [] and (found[0].start, found[0].end) == (10, 12)
    found, _ = find_symbols(list_symbols("a.ts", TS), ["Cmp.over"])
    assert (found[0].start, found[0].end) == (6, 8)


def test_small_gaps_are_shown_instead_of_marked():
    text = "\n".join(f"l{i}" for i in range(1, 21)) + "\n"
    syms = list_symbols("a.py", "\n".join(["def a(): pass", "x1 = 1", "x2 = 2", "def b(): pass"]))
    assert "omitted" not in build_excerpt("def a(): pass\nx1 = 1\nx2 = 2\ndef b(): pass\n", syms, context=0)
    assert "omitted" in build_excerpt(text, [list_symbols("a.py", "def a(): pass")[0]], context=0)


def test_outline_handles_a_bom_file(tmp_path):
    (tmp_path / "b.py").write_bytes(BOM + b"def f():\n    return 1\n")
    out = outline(tmp_path, "b.py")
    assert out["items"][0].startswith("1-2|func|f|")


def test_broken_file_on_a_retry_falls_back_instead_of_crashing():
    texts = {"a.py": "def f(:\n"}
    assert focus_excerpts(texts, {"a.py": ["f"]}, strict=False) == {}
    with pytest.raises(SymbolError):
        focus_excerpts(texts, {"a.py": ["f"]}, strict=True)
