import pytest

from localexec.symbols import SymbolError, build_excerpt, find_symbols, list_symbols
from localexec.symbols.focus import focus_excerpts, parse_focus

PY = '''X = 1


@deco
def a(
    p, q,
):
    """doc"""
    return p


class C:
    def m(self):
        return 1

    async def n(self): pass

    def inner_holder(self):
        def hidden():
            return 2
        return hidden
'''

TSX = '''export const App = ({a}: P) => {
  return <div>{a}</div>;
};
function f(x: number): number { return x; }
export default class C { m(): void {}
  handle = () => 1; }
export interface I { a: string }
type T = string;
enum E { A }
const K = 5;
'''


def names(symbols):
    return [(s.name, s.kind) for s in symbols]


def test_python_symbols():
    syms = list_symbols("a.py", PY)
    assert names(syms) == [
        ("X", "const"), ("a", "func"), ("C", "class"), ("C.m", "method"), ("C.n", "method"),
        ("C.inner_holder", "method"),
    ]
    a = next(s for s in syms if s.name == "a")
    assert (a.start, a.end) == (4, 9)  # includes the decorator line
    assert "def a(" in a.signature


def test_python_syntax_error():
    with pytest.raises(SymbolError, match="syntax error"):
        list_symbols("a.py", "def (:\n")


def test_tsx_symbols():
    got = dict(names(list_symbols("A.tsx", TSX)))
    assert got["App"] == "func" and got["f"] == "func" and got["C"] == "class"
    assert got["C.m"] == "method" and got["C.handle"] == "method"
    assert got["I"] == "interface" and got["T"] == "type" and got["E"] == "enum" and got["K"] == "const"
    app = next(s for s in list_symbols("A.tsx", TSX) if s.name == "App")
    assert (app.start, app.end) == (1, 3) and app.signature.startswith("export const App")


def test_js_and_jsx_and_ts_generics():
    assert ("g", "func") in names(list_symbols("a.js", "function g() { return 1 }\n"))
    assert ("B", "func") in names(list_symbols("b.jsx", "export const B = () => <b/>;\n"))
    assert ("h", "func") in names(list_symbols("c.ts", "function h<T>(x: T): T { return <T>x }\n"))


def test_unsupported_extension_and_unparseable():
    with pytest.raises(SymbolError, match="not supported"):
        list_symbols("a.go", "package x")
    with pytest.raises(SymbolError, match="parse"):
        list_symbols("a.ts", "}}}} ((( !!!\n")


def test_find_symbols_resolution():
    syms = list_symbols("a.py", PY)
    found, problems = find_symbols(syms, ["m", "a", "C.n"])
    assert [s.name for s in found] == ["C.m", "a", "C.n"] and not problems
    _, problems = find_symbols(syms, ["zzz"])
    assert "not found" in problems[0]
    _, problems = find_symbols(syms, ["inner_holdr"])
    assert "did you mean: C.inner_holder" in problems[0]
    dup = list_symbols("d.py", "class A:\n    def run(self): pass\nclass B:\n    def run(self): pass\n")
    _, problems = find_symbols(dup, ["run"])
    assert "ambiguous" in problems[0]
    assert find_symbols(dup, ["A.run"])[0][0].name == "A.run"


def test_excerpt_markers_merge_and_clip():
    text = "".join(f"line{i}\n" for i in range(1, 101))
    sym = list_symbols("a.py", "".join(f"v{i} = {i}\n" for i in range(1, 101)))
    pick = [sym[9], sym[11]]  # lines 10 and 12 merge into one window
    ex = build_excerpt(text, pick, context=2)
    lines = ex.split("\n")
    assert lines[0].startswith("[... lines 1-7 omitted") and lines[1] == "line8" and lines[-2] == "line14"
    assert lines[-1].startswith("[... lines 15-100 omitted")
    whole = build_excerpt(text, [sym[0], sym[99]], context=200)
    assert "omitted" not in whole and whole.count("\n") == 99


def test_parse_focus_errors():
    resolve = lambda p: p if p == "a.py" else None
    assert parse_focus(["a.py::f", "a.py::C.m"], resolve) == {"a.py": ["f", "C.m"]}
    for bad in ("nocolons", "::f", "a.py::", "other.py::f"):
        with pytest.raises(SymbolError):
            parse_focus([bad], resolve)


def test_focus_excerpts_strict_vs_lenient():
    texts = {"a.py": PY, "new.py": None}
    assert "def m(self)" in focus_excerpts(texts, {"a.py": ["m"]})["a.py"]
    with pytest.raises(SymbolError, match="not found"):
        focus_excerpts(texts, {"a.py": ["gone"]}, strict=True)
    assert focus_excerpts(texts, {"a.py": ["gone"]}) == {}  # lenient: symbol vanished after an edit
    with pytest.raises(SymbolError, match="does not exist"):
        focus_excerpts(texts, {"new.py": ["f"]}, strict=True)
