"""AST-backed code model (tree-sitter) shared by the language collectors."""

from sre_kb.parsing.code_model import Call, MethodDecl, Module, TypeDecl, parse

__all__ = ["Call", "MethodDecl", "Module", "TypeDecl", "parse"]
