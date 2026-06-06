"""AST-backed code model (tree-sitter). A small, language-neutral structure the collectors
query instead of line regexes — which dissolves the regex brittleness (multi-class files,
multi-line calls, comments, and crucially receiver->field-type resolution for correlation).

`parse(language, text)` returns a Module for "java" or "csharp". Only the few node shapes
the collectors need are extracted; the grammars carry the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache

import tree_sitter_c_sharp as ts_cs
import tree_sitter_java as ts_java
from tree_sitter import Language, Node, Parser


@dataclass(frozen=True)
class Call:
    receiver: str  # simple name of the call's receiver ("eventPublisher"), "" if none
    method: str  # invoked method name ("publish")
    line: int  # 1-based call-site line
    str_args: tuple[str, ...] = ()  # string-literal arguments (e.g. a kafka topic)


@dataclass
class MethodDecl:
    name: str
    annotations: dict[str, str]  # ann-name -> first string-literal arg ("" if none)
    start: int  # 1-based
    end: int
    calls: list[Call] = field(default_factory=list)


@dataclass
class TypeDecl:
    name: str
    kind: str  # class | interface | enum
    supertypes: list[str]  # extends/implements/base type names
    annotations: dict[str, str]
    fields: dict[str, str]  # field name -> declared type (for receiver resolution)
    methods: list[MethodDecl]
    start: int
    end: int


@dataclass
class Module:
    namespace: str
    types: list[TypeDecl]


@cache
def _lang(language: str) -> Language:
    return Language(ts_java.language() if language == "java" else ts_cs.language())


@cache
def _parser(language: str) -> Parser:
    return Parser(_lang(language))


def parse(language: str, text: str) -> Module:
    tree = _parser(language).parse(text.encode("utf-8"))
    src = text.encode("utf-8")
    return _MODEL[language](tree.root_node, src)


def _txt(n: Node, src: bytes) -> str:
    return src[n.start_byte : n.end_byte].decode("utf-8", "replace")


def _descend(n: Node, types: set[str]):
    if n.type in types:
        yield n
    for c in n.children:
        yield from _descend(c, types)


def _last_ident(node: Node, src: bytes) -> str:
    """Receiver name: a bare identifier, or the trailing name of `this.x` / `a.b`."""
    if node.type == "identifier":
        return _txt(node, src)
    ids = [c for c in node.children if c.type == "identifier"]
    return _txt(ids[-1], src) if ids else ""


def _str_args(args: Node | None, src: bytes, kinds: set[str]) -> tuple[str, ...]:
    if args is None:
        return ()
    out = []
    for s in _descend(args, kinds):
        out.append(_txt(s, src).strip("\"'@$"))
    return tuple(out)


# ---------------- Java ----------------

def _java_calls(body: Node | None, src: bytes) -> list[Call]:
    if body is None:
        return []
    calls = []
    for inv in _descend(body, {"method_invocation"}):
        obj = inv.child_by_field_name("object")
        name = inv.child_by_field_name("name")
        calls.append(Call(
            receiver=_last_ident(obj, src) if obj else "",
            method=_txt(name, src) if name else "",
            line=inv.start_point[0] + 1,
            str_args=_str_args(inv.child_by_field_name("arguments"), src, {"string_literal"}),
        ))
    return calls


def _java_annotations(node: Node, src: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    mods = next((c for c in node.children if c.type == "modifiers"), None)
    for a in (mods.children if mods else []):
        if a.type in ("annotation", "marker_annotation"):
            nm = a.child_by_field_name("name")
            if nm:
                args = _str_args(a.child_by_field_name("arguments"), src, {"string_literal"})
                out["@" + _txt(nm, src)] = args[0] if args else ""
    return out


def _java_fields(body: Node, src: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    for fd in (c for c in body.children if c.type == "field_declaration"):
        ftype = fd.child_by_field_name("type")
        for dec in _descend(fd, {"variable_declarator"}):
            nm = dec.child_by_field_name("name")
            if nm and ftype:
                fields[_txt(nm, src)] = _txt(ftype, src)
    return fields


def _java_supertypes(node: Node, src: bytes) -> list[str]:
    out = []
    for fname in ("superclass", "interfaces"):
        sn = node.child_by_field_name(fname)
        if sn:
            out += [_txt(t, src) for t in _descend(sn, {"type_identifier", "generic_type"})]
    return out


def _parse_java(root: Node, src: bytes) -> Module:
    pkg = ""
    for p in _descend(root, {"package_declaration"}):
        pkg = _txt(p, src).replace("package", "").strip().rstrip(";").strip()
        break
    types = []
    for t in _descend(root, {"class_declaration", "interface_declaration", "enum_declaration"}):
        name = t.child_by_field_name("name")
        body = t.child_by_field_name("body")
        methods = []
        for m in (body.children if body else []):
            if m.type == "method_declaration":
                mn = m.child_by_field_name("name")
                methods.append(MethodDecl(
                    name=_txt(mn, src) if mn else "",
                    annotations=_java_annotations(m, src),
                    start=m.start_point[0] + 1, end=m.end_point[0] + 1,
                    calls=_java_calls(m.child_by_field_name("body"), src),
                ))
        types.append(TypeDecl(
            name=_txt(name, src) if name else "?",
            kind=t.type.split("_")[0],
            supertypes=_java_supertypes(t, src),
            annotations=_java_annotations(t, src),
            fields=_java_fields(body, src) if body else {},
            methods=methods, start=t.start_point[0] + 1, end=t.end_point[0] + 1,
        ))
    return Module(pkg, types)


# ---------------- C# ----------------

def _cs_calls(body: Node | None, src: bytes) -> list[Call]:
    if body is None:
        return []
    calls = []
    for inv in _descend(body, {"invocation_expression"}):
        fn = inv.child_by_field_name("function")
        receiver, method = "", ""
        if fn and fn.type == "member_access_expression":
            expr = fn.child_by_field_name("expression")
            nm = fn.child_by_field_name("name")
            receiver = _last_ident(expr, src) if expr else ""
            method = _txt(nm, src) if nm else ""
        elif fn:
            method = _last_ident(fn, src)
        calls.append(Call(
            receiver=receiver, method=method, line=inv.start_point[0] + 1,
            str_args=_str_args(inv.child_by_field_name("arguments"), src,
                               {"string_literal", "verbatim_string_literal", "raw_string_literal"}),
        ))
    return calls


def _cs_attributes(node: Node, src: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for al in (c for c in node.children if c.type == "attribute_list"):
        for a in _descend(al, {"attribute"}):
            nm = a.child_by_field_name("name")
            if nm:
                args = _str_args(a.child_by_field_name("arguments"), src,
                                 {"string_literal", "verbatim_string_literal"})
                out["[" + _txt(nm, src) + "]"] = args[0] if args else ""
    return out


def _cs_fields(body: Node, src: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    for fd in _descend(body, {"field_declaration"}):
        vd = next((c for c in fd.children if c.type == "variable_declaration"), None)
        if not vd:
            continue
        ftype = vd.child_by_field_name("type")
        for dec in _descend(vd, {"variable_declarator"}):
            nm = dec.child_by_field_name("name") or next((c for c in dec.children if c.type == "identifier"), None)
            if nm and ftype:
                fields[_txt(nm, src)] = _txt(ftype, src)
    return fields


def _parse_csharp(root: Node, src: bytes) -> Module:
    ns = ""
    for n in _descend(root, {"namespace_declaration", "file_scoped_namespace_declaration"}):
        nm = n.child_by_field_name("name")
        if nm:
            ns = _txt(nm, src)
            break
    types = []
    for t in _descend(root, {"class_declaration", "interface_declaration"}):
        name = t.child_by_field_name("name")
        body = t.child_by_field_name("body")
        methods = []
        for m in _descend(body, {"method_declaration"}) if body else []:
            mn = m.child_by_field_name("name")
            methods.append(MethodDecl(
                name=_txt(mn, src) if mn else "",
                annotations=_cs_attributes(m, src),
                start=m.start_point[0] + 1, end=m.end_point[0] + 1,
                calls=_cs_calls(m.child_by_field_name("body"), src),
            ))
        bases = t.child_by_field_name("bases")
        types.append(TypeDecl(
            name=_txt(name, src) if name else "?",
            kind=t.type.split("_")[0],
            supertypes=[_txt(b, src) for b in _descend(bases, {"identifier", "generic_name"})] if bases else [],
            annotations=_cs_attributes(t, src),
            fields=_cs_fields(body, src) if body else {},
            methods=methods, start=t.start_point[0] + 1, end=t.end_point[0] + 1,
        ))
    return Module(ns, types)


_MODEL = {"java": _parse_java, "csharp": _parse_csharp}
