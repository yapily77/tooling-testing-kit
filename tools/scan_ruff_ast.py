#!/usr/bin/env python3
"""
AST-based ruff-style violation scanner for 9 target test files.
Uses only stdlib `ast` + `json`. Outputs JSON list of {file,line,rule,desc}.
"""
from __future__ import annotations

import ast
import json
import os
from collections.abc import Callable
from typing import Any

BASE: str = "/home/yapilwsl/arthityap/tooling"
FILES: list[str] = [
    "tests/02_unit_bedrock/test_mcp.py",
    "tests/03_regression_locks/test_audit_stable.py",
    "tests/04_bug_repros/test_replicate_chartprofile_crash.py",
    "tests/04_bug_repros/test_replicate_input_crashes.py",
    "tests/05_integration_e2e/e2e/test_battery_full.py",
    "tests/05_integration_e2e/e2e/test_command_hooks.py",
    "tests/05_integration_e2e/e2e/test_conductor_scenarios.py",
    "tests/05_integration_e2e/e2e/test_monthly_report.py",
    "tests/05_integration_e2e/e2e/test_webhook_routing.py",
]

V: list[dict[str, Any]] = []


def emit(fname: str, line: int, rule: str, desc: str) -> None:
    V.append({"file": fname, "line": line, "rule": rule, "desc": desc})


def _is_keys_call(comp: ast.expr) -> bool:
    return isinstance(comp, ast.Call) and isinstance(comp.func, ast.Attribute) and comp.func.attr == "keys"


def _has_nested_if_no_else(node: ast.If) -> bool:
    body0: ast.stmt = node.body[0]
    if not isinstance(body0, ast.If):
        return False
    return not node.orelse and not body0.orelse


def detect_sim117(node: ast.stmt, fname: str) -> None:
    if isinstance(node, ast.With) and len(node.body) == 1 and isinstance(node.body[0], ast.With):
        emit(fname, node.lineno, "SIM117", "Use single `with` statement with multiple context managers instead of nested")


def detect_sim102(node: ast.stmt, fname: str) -> None:
    if isinstance(node, ast.If) and len(node.body) == 1 and _has_nested_if_no_else(node):
        emit(fname, node.lineno, "SIM102", "Combine nested `if` into one")


def detect_e722(node: ast.stmt, fname: str) -> None:
    if isinstance(node, ast.ExceptHandler):
        if node.type is None:
            emit(fname, node.lineno, "E722", "Do not use bare 'except'")
        elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
            emit(fname, node.lineno, "E722", "Do not use blind 'except Exception'")


def detect_sim118(node: ast.expr, fname: str) -> None:
    if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.In):
        for comp in node.comparators:
            if _is_keys_call(comp):
                emit(fname, node.lineno, "SIM118", "Use `key in dict` instead of `key in dict.keys()`")


def detect_f403(node: ast.stmt, fname: str) -> None:
    if isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name == "*":
                emit(fname, node.lineno, "F403", "'from module import *' used; use explicit imports")


def detect_s311(node: ast.expr, fname: str) -> None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "random":
        emit(fname, node.lineno, "S311", "Standard pseudo-random generators are not suitable for security/cryptographic purposes")


def _is_raise_without_from(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Raise):
        return False
    if node.exc is None or node.cause is not None:
        return False
    parent: Any = getattr(node, "parent", None)
    return isinstance(parent, ast.ExceptHandler)


def detect_b904(node: ast.stmt, fname: str) -> None:
    if _is_raise_without_from(node):
        emit(fname, node.lineno, "B904", "`raise` without `from` inside except; use `raise ... from err`")


def detect_e501(path: str, fname: str) -> None:
    with open(path) as f:
        for i, line in enumerate(f, 1):
            stripped: str = line.rstrip("\n")
            if len(stripped) > 88:
                emit(fname, i, "E501", f"line too long ({len(stripped)} > 88 chars)")


def get_parents(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]


def run_stmt_detectors(node: ast.stmt, fname: str) -> None:
    detectors: list[Callable[[ast.stmt, str], None]] = [detect_sim102, detect_sim117, detect_e722, detect_f403, detect_b904]
    for det in detectors:
        det(node, fname)


def run_expr_detectors(node: ast.expr, fname: str) -> None:
    detectors: list[Callable[[ast.expr, str], None]] = [detect_sim118, detect_s311]
    for det in detectors:
        det(node, fname)


def run_detectors(tree: ast.AST, fname: str) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            run_stmt_detectors(node, fname)
        if isinstance(node, ast.expr):
            run_expr_detectors(node, fname)


def scan_file(fname: str) -> None:
    path: str = os.path.join(BASE, fname)
    with open(path) as fh:
        src: str = fh.read()
    tree: ast.AST = ast.parse(src)
    get_parents(tree)
    run_detectors(tree, fname)
    detect_e501(path, fname)


def dedupe() -> list[dict[str, Any]]:
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in V:
        key: tuple[str, int, str, str] = (str(item["file"]), int(item["line"]), str(item["rule"]), str(item["desc"]))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    unique.sort(key=lambda x: (x["file"], x["line"], x["rule"]))
    return unique


def main() -> None:
    for f in FILES:
        scan_file(f)
    print(json.dumps(dedupe(), indent=2))


if __name__ == "__main__":
    main()
