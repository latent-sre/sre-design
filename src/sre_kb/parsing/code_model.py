"""AST-backed code model (tree-sitter). A small, language-neutral structure the collectors
query instead of line regexes — which dissolves the regex brittleness (multi-class files,
multi-line calls/annotations, comments, receiver->field-type resolution, real try/catch).

`parse(language, text)` returns a Module for "java" or "csharp". Only the node shapes the
collectors need are extracted; the grammars carry the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache

import tree_sitter_c_sharp as ts_cs
import tree_sitter_java as ts_java
from tree_sitter import Language, Node, Parser

_STR_KINDS = {"string_literal", "verbatim_string_literal", "raw_string_literal", "interpolated_string_expression"}
_THROW = {"throw_statement", "throw_expression"}
_INVOKE = {"method_invocation", "invocation_expression"}


@dataclass(frozen=True)
class Swallow:
    log_method: str  # the catch's log call ("error" / "LogError")
    message: str  # the logged string literal
    start: int  # 1-based catch span
    end: int


@dataclass(frozen=True)
class Call:
    receiver: str  # simple name of the call's receiver ("eventPublisher"), "" if none
    method: str  # invoked method name ("publish")
    line: int  # 1-based call-site line
    str_args: tuple[str, ...] = ()  # string-literal arguments (e.g. a kafka topic)
    swallow: Swallow | None = None  # set when the call sits in a try whose catch logs + no rethrow


@dataclass
class MethodDecl:
    name: str
    annotations: dict[str, dict[str, str]]  # ann-name -> args ({"": positional, "name": ...})
    start: int  # 1-based (first modifier/annotation)
    name_line: int  # 1-based line of the method name (for precise evidence)
    end: int
    calls: list[Call] = field(default_factory=list)


@dataclass
class TypeDecl:
    name: str
    kind: str  # class | interface | enum
    supertypes: list[str]
    annotations: dict[str, dict[str, str]]
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
    src = text.encode("utf-8")
    root = _parser(language).parse(src).root_node
    return (_parse_java if language == "java" else _parse_csharp)(root, src)


# ---------------- shared traversal ----------------

def _txt(n: Node, src: bytes) -> str:
    return src[n.start_byte : n.end_byte].decode("utf-8", "replace")


def _descend(n: Node | None, types: set[str]):
    if n is None:
        return
    if n.type in types:
        yield n
    for c in n.children:
        yield from _descend(c, types)


def _last_ident(node: Node, src: bytes) -> str:
    if node.type == "identifier":
        return _txt(node, src)
    ids = [c for c in node.children if c.type == "identifier"]
    return _txt(ids[-1], src) if ids else ""


def _str_args(args: Node | None, src: bytes) -> tuple[str, ...]:
    return tuple(_txt(s, src).strip("\"'@$") for s in _descend(args, _STR_KINDS)) if args else ()


def _call_rm(inv: Node, src: bytes) -> tuple[str, str]:
    if inv.type == "method_invocation":  # Java
        obj, name = inv.child_by_field_name("object"), inv.child_by_field_name("name")
        return (_last_ident(obj, src) if obj else "", _txt(name, src) if name else "")
    fn = inv.child_by_field_name("function")  # C# invocation_expression
    if fn and fn.type == "member_access_expression":
        expr, nm = fn.child_by_field_name("expression"), fn.child_by_field_name("name")
        return (_last_ident(expr, src) if expr else "", _txt(nm, src) if nm else "")
    return ("", _last_ident(fn, src) if fn else "")


def _enclosing_swallow(inv: Node, src: bytes) -> Swallow | None:
    """A try whose body holds this call and whose catch logs but does not rethrow."""
    node = inv.parent
    while node is not None:
        if node.type == "try_statement":
            body = node.child_by_field_name("body") or next((c for c in node.children if c.type == "block"), None)
            if body and body.start_byte <= inv.start_byte < body.end_byte:
                catch = next((c for c in node.children if c.type == "catch_clause"), None)
                if catch is None:
                    return None
                cbody = catch.child_by_field_name("body") or next(
                    (c for c in catch.children if c.type == "block"), catch
                )
                if next(_descend(cbody, _THROW), None) is not None:
                    return None
                for c in _descend(cbody, _INVOKE):
                    recv, meth = _call_rm(c, src)
                    if "log" in (recv + meth).lower():
                        a = _str_args(c.child_by_field_name("arguments"), src)
                        return Swallow(meth, a[0] if a else "", catch.start_point[0] + 1, catch.end_point[0] + 1)
                return None
        node = node.parent
    return None


def _calls(body: Node | None, src: bytes) -> list[Call]:
    out = []
    for inv in _descend(body, _INVOKE):
        recv, meth = _call_rm(inv, src)
        out.append(Call(recv, meth, inv.start_point[0] + 1,
                        _str_args(inv.child_by_field_name("arguments"), src), _enclosing_swallow(inv, src)))
    return out


def _method(m: Node, src: bytes, anns) -> MethodDecl:
    nm = m.child_by_field_name("name")
    return MethodDecl(
        name=_txt(nm, src) if nm else "",
        annotations=anns(m, src),
        start=m.start_point[0] + 1,
        name_line=(nm.start_point[0] + 1) if nm else m.start_point[0] + 1,
        end=m.end_point[0] + 1,
        calls=_calls(m.child_by_field_name("body"), src),
    )


# ---------------- Java ----------------

def _java_anns(node: Node, src: bytes) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    mods = next((c for c in node.children if c.type == "modifiers"), None)
    for a in (mods.children if mods else []):
        if a.type == "marker_annotation":
            nm = a.child_by_field_name("name")
            if nm:
                out["@" + _txt(nm, src)] = {}
        elif a.type == "annotation":
            nm = a.child_by_field_name("name")
            if not nm:
                continue
            args: dict[str, str] = {}
            al = a.child_by_field_name("arguments") or next(
                (c for c in a.children if c.type == "annotation_argument_list"), None
            )
            for ch in (al.children if al else []):
                if ch.type == "element_value_pair":
                    k, v = ch.child_by_field_name("key"), ch.child_by_field_name("value")
                    if k and v:
                        s = _str_args(v, src)
                        args[_txt(k, src)] = s[0] if s else _txt(v, src)
                elif ch.type in _STR_KINDS:
                    args[""] = _txt(ch, src).strip('"')
            out["@" + _txt(nm, src)] = args
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


def _parse_java(root: Node, src: bytes) -> Module:
    pkg = ""
    for p in _descend(root, {"package_declaration"}):
        pkg = _txt(p, src).replace("package", "").strip().rstrip(";").strip()
        break
    types = []
    for t in _descend(root, {"class_declaration", "interface_declaration", "enum_declaration"}):
        name, body = t.child_by_field_name("name"), t.child_by_field_name("body")
        supers = []
        for clause in t.children:  # superclass / implements / interface-extends
            if clause.type in ("superclass", "interfaces", "super_interfaces", "extends_interfaces"):
                supers += [_txt(x, src) for x in _descend(clause, {"generic_type", "type_identifier", "scoped_type_identifier"})]
        types.append(TypeDecl(
            name=_txt(name, src) if name else "?", kind=t.type.split("_")[0], supertypes=supers,
            annotations=_java_anns(t, src), fields=_java_fields(body, src) if body else {},
            methods=[_method(m, src, _java_anns) for m in (body.children if body else []) if m.type == "method_declaration"],
            start=t.start_point[0] + 1, end=t.end_point[0] + 1,
        ))
    return Module(pkg, types)


# ---------------- C# ----------------

def _cs_anns(node: Node, src: bytes) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for al in (c for c in node.children if c.type == "attribute_list"):
        for a in _descend(al, {"attribute"}):
            nm = a.child_by_field_name("name") or next(
                (c for c in a.children if c.type in ("identifier", "qualified_name")), None
            )
            if not nm:
                continue
            args: dict[str, str] = {}
            aal = a.child_by_field_name("arguments") or next(
                (c for c in a.children if c.type == "attribute_argument_list"), None
            )
            for arg in _descend(aal, {"attribute_argument"}):
                ne = next((c for c in arg.children if c.type in ("name_equals", "name_colon")), None)
                s = _str_args(arg, src)
                val = s[0] if s else ""
                key = next((_txt(c, src) for c in (ne.children if ne else []) if c.type == "identifier"), "")
                args[key] = val
            out["[" + _txt(nm, src) + "]"] = args
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
        name, body = t.child_by_field_name("name"), t.child_by_field_name("body")
        bases = t.child_by_field_name("bases")
        types.append(TypeDecl(
            name=_txt(name, src) if name else "?", kind=t.type.split("_")[0],
            supertypes=[_txt(b, src) for b in _descend(bases, {"identifier", "generic_name"})] if bases else [],
            annotations=_cs_anns(t, src), fields=_cs_fields(body, src) if body else {},
            methods=[_method(m, src, _cs_anns) for m in _descend(body, {"method_declaration"})] if body else [],
            start=t.start_point[0] + 1, end=t.end_point[0] + 1,
        ))
    return Module(ns, types)
