"""TypeScript / TSX / JavaScript symbols via tree-sitter."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .model import Symbol, SymbolError

SIG_MAX = 100
_FUNC_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
_DECLS = {
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}
_parsers: dict[str, Any] = {}


def _parser(ext: str) -> Any:
    key = {".ts": "ts", ".tsx": "tsx"}.get(ext, "js")
    if key not in _parsers:
        try:
            from tree_sitter import Language, Parser
            import tree_sitter_javascript as tsj
            import tree_sitter_typescript as tsts
        except ImportError as e:
            raise SymbolError("tree-sitter packages are not installed (run: uv sync)") from e
        lang = {"ts": tsts.language_typescript, "tsx": tsts.language_tsx, "js": tsj.language}[key]
        _parsers[key] = Parser(Language(lang()))
    return _parsers[key]


def _text(node: Any) -> str:
    return node.text.decode("utf-8", "replace")


def _sym(outer: Any, name: str, kind: str) -> Symbol:
    first_line = _text(outer).splitlines()[0].strip() if _text(outer) else name
    return Symbol(name, kind, outer.start_point[0] + 1, outer.end_point[0] + 1, first_line[:SIG_MAX])


def _methods(cls: Any, cname: str) -> list[Symbol]:
    body = cls.child_by_field_name("body")
    out: list[Symbol] = []
    lead: int | None = None  # first line of decorators waiting for their member
    for member in body.children if body else []:
        if member.type == "decorator":
            lead = lead if lead is not None else member.start_point[0] + 1
            continue
        name_node = member.child_by_field_name("name")
        value = member.child_by_field_name("value")
        is_method = member.type in ("method_definition", "method_signature")
        if name_node is not None and (is_method or (value is not None and value.type in _FUNC_VALUES)):
            sym = _sym(member, f"{cname}.{_text(name_node)}", "method")
            out.append(replace(sym, start=min(sym.start, lead)) if lead else sym)
        lead = None
    return out


def _declarators(decl: Any, outer: Any) -> list[Symbol]:
    out = []
    for child in decl.children:
        if child.type != "variable_declarator":
            continue
        name_node, value = child.child_by_field_name("name"), child.child_by_field_name("value")
        if name_node is None or name_node.type != "identifier":
            continue
        is_func = value is not None and value.type in _FUNC_VALUES
        out.append(_sym(outer, _text(name_node), "func" if is_func else "const"))
    return out


def _top_level(outer: Any) -> list[Symbol]:
    decl = outer.child_by_field_name("declaration") if outer.type == "export_statement" else outer
    if decl is None:
        return []
    name_node = decl.child_by_field_name("name")
    if decl.type in ("function_declaration", "generator_function_declaration", "function_signature") and name_node:
        return [_sym(outer, _text(name_node), "func")]
    if decl.type in ("class_declaration", "abstract_class_declaration") and name_node:
        return [_sym(outer, _text(name_node), "class"), *_methods(decl, _text(name_node))]
    if decl.type in ("lexical_declaration", "variable_declaration"):
        return _declarators(decl, outer)
    if decl.type in _DECLS and name_node:
        return [_sym(outer, _text(name_node), _DECLS[decl.type])]
    return []


def ts_symbols(rel: str, text: str) -> list[Symbol]:
    ext = rel[rel.rfind(".") :].lower()
    tree = _parser(ext).parse(text.encode("utf-8"))
    out: list[Symbol] = []
    for node in tree.root_node.children:
        out.extend(_top_level(node))
    if not out and tree.root_node.has_error:
        raise SymbolError("could not parse file (syntax errors)")
    return sorted(out, key=lambda s: (s.start, -s.end))
