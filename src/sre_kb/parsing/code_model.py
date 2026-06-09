"""AST-backed code model (tree-sitter). A small, language-neutral structure the collectors
query instead of line regexes — which dissolves the regex brittleness (multi-class files,
multi-line calls/annotations, comments, receiver->field-type resolution, real try/catch).

`parse(language, text)` returns a Module for "java", "csharp", "python", "javascript", or "go".
Only the node shapes the collectors need are extracted; the grammars carry the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache

import tree_sitter_c_sharp as ts_cs
import tree_sitter_go as ts_go
import tree_sitter_java as ts_java
import tree_sitter_javascript as ts_js
import tree_sitter_python as ts_py
from tree_sitter import Language, Node, Parser

_STR_KINDS = {"string_literal", "verbatim_string_literal", "raw_string_literal", "interpolated_string_expression"}
_THROW = {"throw_statement", "throw_expression"}
_INVOKE = {"method_invocation", "invocation_expression"}

# Logging-call detection for swallow analysis. A substring test ("log" in recv+meth) used to
# misfire on receivers like `catalog`/`backlog`/`dialog`; match log-level method names or a
# logger-shaped receiver instead.
_LOG_METHODS = {
    "error", "warn", "warning", "info", "debug", "trace", "fatal", "critical",
    "log", "logerror", "logwarning", "logwarn", "loginformation", "logdebug",
    "logtrace", "logcritical",
}
_LOG_RECEIVERS = {"log", "logger", "logging", "_log", "_logger", "slf4j"}


def _is_log_call(recv: str, meth: str) -> bool:
    r, m = recv.lower(), meth.lower()
    return m in _LOG_METHODS or r in _LOG_RECEIVERS or r.endswith("logger")


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


_GRAMMARS = {"java": ts_java, "csharp": ts_cs, "python": ts_py, "javascript": ts_js, "go": ts_go}


@cache
def _lang(language: str) -> Language:
    return Language(_GRAMMARS[language].language())


@cache
def _parser(language: str) -> Parser:
    return Parser(_lang(language))


def parse(language: str, text: str) -> Module:
    src = text.encode("utf-8")
    root = _parser(language).parse(src).root_node
    return {
        "java": _parse_java, "csharp": _parse_csharp, "python": _parse_python,
        "javascript": _parse_javascript, "go": _parse_go,
    }[language](root, src)


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


_NESTED_TRY = {"try_statement"}


def _descend_outside(n: Node | None, types: set[str], stop: set[str]):
    """Like `_descend`, but never recurse into a subtree whose root type is in `stop`. Used so a
    nested try/catch's throw or log statement isn't attributed to the *enclosing* catch — judging an
    outer catch's rethrow/log on an inner catch's statements both missed real swallows and
    mis-cited others (#M6)."""
    if n is None:
        return
    if n.type in types:
        yield n
    for c in n.children:
        if c.type in stop:
            continue
        yield from _descend_outside(c, types, stop)


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
                # Check every catch clause (not just the first): a logged-and-swallowed
                # failure in a later catch is still data loss.
                for catch in (c for c in node.children if c.type == "catch_clause"):
                    cbody = catch.child_by_field_name("body") or next(
                        (c for c in catch.children if c.type == "block"), catch
                    )
                    if next(_descend_outside(cbody, _THROW, _NESTED_TRY), None) is not None:
                        continue  # this catch rethrows -> not swallowed here (ignore nested try/catch)
                    for c in _descend_outside(cbody, _INVOKE, _NESTED_TRY):
                        recv, meth = _call_rm(c, src)
                        if _is_log_call(recv, meth):
                            a = _str_args(c.child_by_field_name("arguments"), src)
                            return Swallow(meth, a[0] if a else "",
                                           catch.start_point[0] + 1, catch.end_point[0] + 1)
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
    nm = m.child_by_field_name("name") or next((c for c in m.children if c.type == "identifier"), None)
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
            methods=[_method(m, src, _java_anns) for m in (body.children if body else [])
                     if m.type in ("method_declaration", "constructor_declaration")],
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
    # Direct children only (like the Java collector): a nested class's fields belong to the nested
    # TypeDecl that the top-level descent yields separately, not to this enclosing type (#M5).
    for fd in (c for c in body.children if c.type == "field_declaration"):
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
        bases = next((c for c in t.children if c.type == "base_list"), None)  # base_list is unnamed
        types.append(TypeDecl(
            name=_txt(name, src) if name else "?", kind=t.type.split("_")[0],
            supertypes=[_txt(b, src) for b in _descend(bases, {"identifier", "generic_name"})] if bases else [],
            annotations=_cs_anns(t, src), fields=_cs_fields(body, src) if body else {},
            methods=[_method(m, src, _cs_anns) for m in body.children
                     if m.type in ("method_declaration", "constructor_declaration")] if body else [],
            start=t.start_point[0] + 1, end=t.end_point[0] + 1,
        ))
    return Module(ns, types)


# ---------------- Python ----------------
# Python is function/decorator-centric, not class-centric. We map a module's top-level functions
# onto the shared MethodDecl shape (decorators -> annotations, e.g. "app.get" -> {"": "/path"})
# under one synthetic module-level TypeDecl, so collectors query it like any other stack.

def _py_str_args(args: Node | None, src: bytes) -> tuple[str, ...]:
    if args is None:
        return ()
    out = []
    for s in _descend(args, {"string"}):
        t = _txt(s, src).strip()
        t = re.sub(r"^[rbfu]+(?=[\"'])", "", t, flags=re.I)  # drop string prefixes (r/b/f/u)
        out.append(t.strip("\"'"))
    return tuple(out)


def _py_decorators(deco_def: Node, src: bytes) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for d in deco_def.children:
        if d.type != "decorator":
            continue
        expr = next((c for c in d.children if c.type in ("call", "attribute", "identifier")), None)
        if expr is None:
            continue
        if expr.type == "call":
            fn = expr.child_by_field_name("function")
            args = _py_str_args(expr.child_by_field_name("arguments"), src)
            out[_txt(fn, src) if fn else ""] = {"": args[0]} if args else {}
        else:
            out[_txt(expr, src)] = {}
    return out


def _py_call_rm(call: Node, src: bytes) -> tuple[str, str]:
    fn = call.child_by_field_name("function")
    if fn is not None and fn.type == "attribute":
        obj, at = fn.child_by_field_name("object"), fn.child_by_field_name("attribute")
        return (_last_ident(obj, src) if obj else "", _txt(at, src) if at else "")
    return ("", _last_ident(fn, src) if fn is not None else "")


def _py_enclosing_swallow(call: Node, src: bytes) -> Swallow | None:
    """Python analogue of `_enclosing_swallow`: a `try` whose `except` clause logs but does not
    re-`raise`. Same swallow semantics, different node names (except_clause / raise_statement)."""
    node = call.parent
    while node is not None:
        if node.type == "try_statement":
            body = node.child_by_field_name("body") or next((c for c in node.children if c.type == "block"), None)
            if body and body.start_byte <= call.start_byte < body.end_byte:
                for exc in (c for c in node.children if c.type == "except_clause"):
                    eblock = next((c for c in exc.children if c.type == "block"), exc)
                    if next(_descend_outside(eblock, {"raise_statement"}, _NESTED_TRY), None) is not None:
                        continue  # this except re-raises -> not swallowed here (ignore nested try)
                    for c in _descend_outside(eblock, {"call"}, _NESTED_TRY):
                        recv, meth = _py_call_rm(c, src)
                        if _is_log_call(recv, meth):
                            a = _py_str_args(c.child_by_field_name("arguments"), src)
                            return Swallow(meth, a[0] if a else "",
                                           exc.start_point[0] + 1, exc.end_point[0] + 1)
                return None
        node = node.parent
    return None


def _py_calls(body: Node | None, src: bytes) -> list[Call]:
    out = []
    for call in _descend(body, {"call"}):
        recv, meth = _py_call_rm(call, src)
        out.append(Call(recv, meth, call.start_point[0] + 1,
                        _py_str_args(call.child_by_field_name("arguments"), src),
                        _py_enclosing_swallow(call, src)))
    return out


def _py_function(fdef: Node, src: bytes, span_node: Node, decorators: dict) -> MethodDecl:
    nm = fdef.child_by_field_name("name")
    return MethodDecl(
        name=_txt(nm, src) if nm else "",
        annotations=decorators,
        start=span_node.start_point[0] + 1,  # the decorator line, for evidence
        name_line=(nm.start_point[0] + 1) if nm else fdef.start_point[0] + 1,
        end=fdef.end_point[0] + 1,
        calls=_py_calls(fdef.child_by_field_name("body"), src),
    )


def _parse_python(root: Node, src: bytes) -> Module:
    funcs: list[MethodDecl] = []
    for child in root.children:
        if child.type == "function_definition":
            funcs.append(_py_function(child, src, child, {}))
        elif child.type == "decorated_definition":
            fdef = next((c for c in child.children if c.type == "function_definition"), None)
            if fdef is not None:
                funcs.append(_py_function(fdef, src, child, _py_decorators(child, src)))
    module = TypeDecl(name="module", kind="module", supertypes=[], annotations={},
                      fields={}, methods=funcs, start=1, end=root.end_point[0] + 1)
    return Module("", [module])


# ---------------- JavaScript ----------------
# Express has no decorators: a route is the *call* `app.get('/path', handler)`. We synthesize each
# route into the decorator-shaped MethodDecl the FastAPI/Spring collectors already consume
# (annotation `app.get` -> {"": "/path"}, calls = the handler body's egress), so the Node collector
# reuses the same query shape. A route is told apart from an egress call (`axios.get(url)`) by having
# both a string argument (the path) AND a function argument (the handler).

_JS_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "options", "head"}
_JS_FUNCS = {"arrow_function", "function_expression", "function_declaration"}


def _js_str_args(args: Node | None, src: bytes) -> tuple[str, ...]:
    if args is None:
        return ()
    out = []
    for s in _descend(args, {"string"}):
        frag = next((c for c in s.children if c.type == "string_fragment"), None)
        out.append(_txt(frag, src) if frag else _txt(s, src).strip("\"'`"))
    return tuple(out)


def _js_call_rm(call: Node, src: bytes) -> tuple[str, str]:
    fn = call.child_by_field_name("function")
    if fn is not None and fn.type == "member_expression":
        obj, prop = fn.child_by_field_name("object"), fn.child_by_field_name("property")
        return (_last_ident(obj, src) if obj else "", _txt(prop, src) if prop else "")
    return ("", _last_ident(fn, src) if fn is not None else "")


def _js_enclosing_swallow(call: Node, src: bytes) -> Swallow | None:
    """JS analogue of `_enclosing_swallow`: a `try` whose `catch` logs but does not re-`throw`. Same
    swallow semantics, JS node names (catch_clause / throw_statement)."""
    node = call.parent
    while node is not None:
        if node.type == "try_statement":
            body = node.child_by_field_name("body")
            if body and body.start_byte <= call.start_byte < body.end_byte:
                for catch in (c for c in node.children if c.type == "catch_clause"):
                    cbody = catch.child_by_field_name("body") or catch
                    if next(_descend_outside(cbody, {"throw_statement"}, _NESTED_TRY), None) is not None:
                        continue  # this catch re-throws -> not swallowed here (ignore nested try)
                    for c in _descend_outside(cbody, {"call_expression"}, _NESTED_TRY):
                        recv, meth = _js_call_rm(c, src)
                        if _is_log_call(recv, meth):
                            a = _js_str_args(c.child_by_field_name("arguments"), src)
                            return Swallow(meth, a[0] if a else "",
                                           catch.start_point[0] + 1, catch.end_point[0] + 1)
                return None
        node = node.parent
    return None


def _js_calls(node: Node | None, src: bytes) -> list[Call]:
    out = []
    for call in _descend(node, {"call_expression"}):
        recv, meth = _js_call_rm(call, src)
        out.append(Call(recv, meth, call.start_point[0] + 1,
                        _js_str_args(call.child_by_field_name("arguments"), src),
                        _js_enclosing_swallow(call, src)))
    return out


def _js_handler_name(fn: Node, src: bytes) -> str:
    """A named `function foo(){}` handler keeps its name; an anonymous arrow has none."""
    return next((_txt(c, src) for c in fn.children if c.type == "identifier"), "")


def _parse_javascript(root: Node, src: bytes) -> Module:
    methods: list[MethodDecl] = []
    for call in _descend(root, {"call_expression"}):
        fn = call.child_by_field_name("function")
        if fn is None or fn.type != "member_expression":
            continue
        prop = fn.child_by_field_name("property")
        verb = (_txt(prop, src) if prop else "").lower()
        if verb not in _JS_HTTP_VERBS:
            continue
        args = call.child_by_field_name("arguments")
        if args is None:
            continue
        strs = _js_str_args(args, src)
        handler = next((c for c in args.children if c.type in _JS_FUNCS), None)
        if not strs or handler is None:
            continue  # a path string AND a handler function -> a route, not an egress call
        obj = fn.child_by_field_name("object")
        recv = _last_ident(obj, src) if obj else ""
        methods.append(MethodDecl(
            name=_js_handler_name(handler, src),
            annotations={f"{recv}.{verb}": {"": strs[0]}},
            start=call.start_point[0] + 1,
            name_line=call.start_point[0] + 1,
            end=call.end_point[0] + 1,
            calls=_js_calls(handler, src),
        ))
    module = TypeDecl(name="module", kind="module", supertypes=[], annotations={},
                      fields={}, methods=methods, start=1, end=root.end_point[0] + 1)
    return Module("", [module])


# ---------------- Go ----------------
# Go web frameworks (gin/echo/chi/fiber) register a route as a call `router.GET("/path", handler)` —
# same call-as-route shape as Express, synthesized into the decorator-shaped MethodDecl. A route is
# told apart from stdlib egress (`http.Get(url)`, one URL arg) by a verb method name AND a path string
# that starts with "/" AND a handler argument (a function literal or a handler-func identifier).

_GO_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}
# Package-level net/http client calls used as egress; matched as `http.Get(...)` etc.
_GO_EGRESS = {"get", "post", "head", "postform"}


def _go_str(node: Node, src: bytes) -> str:
    return _txt(node, src).strip("`\"")


def _go_call_rm(call: Node, src: bytes) -> tuple[str, str]:
    fn = call.child_by_field_name("function")
    if fn is not None and fn.type == "selector_expression":
        op, fld = fn.child_by_field_name("operand"), fn.child_by_field_name("field")
        return (_last_ident(op, src) if op else "", _txt(fld, src) if fld else "")
    return ("", _last_ident(fn, src) if fn is not None else "")


def _go_calls(node: Node | None, src: bytes) -> list[Call]:
    out = []
    for call in _descend(node, {"call_expression"}):
        recv, meth = _go_call_rm(call, src)
        out.append(Call(recv, meth, call.start_point[0] + 1, (), None))
    return out


def _parse_go(root: Node, src: bytes) -> Module:
    methods: list[MethodDecl] = []
    for call in _descend(root, {"call_expression"}):
        fn = call.child_by_field_name("function")
        if fn is None or fn.type != "selector_expression":
            continue
        fld = fn.child_by_field_name("field")
        verb = (_txt(fld, src) if fld else "").lower()
        if verb not in _GO_VERBS:
            continue
        args = call.child_by_field_name("arguments")
        if args is None:
            continue
        path_node = next((c for c in args.children if c.type == "interpreted_string_literal"), None)
        if path_node is None:
            continue
        path = _go_str(path_node, src)
        handler = next((c for c in args.children if c.type in ("identifier", "func_literal")), None)
        if not path.startswith("/") or handler is None:
            continue  # a "/"-path string AND a handler arg -> a route, not an egress/lookup call
        op = fn.child_by_field_name("operand")
        recv = _last_ident(op, src) if op else ""
        methods.append(MethodDecl(
            name="" if handler.type == "func_literal" else _txt(handler, src),
            annotations={f"{recv}.{verb}": {"": path}},
            start=call.start_point[0] + 1,
            name_line=call.start_point[0] + 1,
            end=call.end_point[0] + 1,
            calls=_go_calls(handler, src) if handler.type == "func_literal" else [],
        ))
    module = TypeDecl(name="module", kind="module", supertypes=[], annotations={},
                      fields={}, methods=methods, start=1, end=root.end_point[0] + 1)
    return Module("", [module])
