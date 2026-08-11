#!/usr/bin/env python3
"""
CC Reduction Status Scanner
Calculates live Cyclomatic Complexity for all functions in 99_YOLO_Mode.md,
cross-referencing with beads ticket status.
"""

import ast
import os
import re
import sys

from pathlib import Path


_CC_TYPES = (
    ast.If,
    ast.While,
    ast.For,
    ast.AsyncFor,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
)


def _is_cc_branch(child: ast.AST) -> bool:
    return isinstance(child, _CC_TYPES)


def _compute_bool_cc(child: ast.BoolOp) -> int:
    return len(child.values) - 1


def _add_complexity_for_node(node: ast.AST) -> int:
    """Return complexity contribution of a single node (beyond the base 1)."""
    if _is_cc_branch(node):
        return 1
    if isinstance(node, ast.BoolOp):
        return _compute_bool_cc(node)
    if isinstance(node, ast.IfExp):
        return 1
    if isinstance(node, ast.Match):
        return len(node.cases)
    return 0


def compute_cc(node: ast.AST) -> int:
    cc = 1
    for child in ast.walk(node):
        cc += _add_complexity_for_node(child)
    return cc


def _process_python_file(filepath: str) -> dict[str, dict[str, int]]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=filepath)
    except (AttributeError, TypeError, SyntaxError):
        return {}

    violations: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cc = compute_cc(node)
            if cc > 5:
                violations[node.name] = cc
    return violations


def scan_live_cc(target_dir: str = "src") -> dict[str, dict[str, int]]:
    all_violations: dict[str, dict[str, int]] = {}
    for root, _, files in os.walk(target_dir):
        for file in files:
            if not file.endswith(".py"):
                continue
            filepath = os.path.join(root, file)
            file_violations = _process_python_file(filepath)
            if file_violations:
                all_violations[filepath] = file_violations
    return all_violations


def _parse_table_line(line: str) -> tuple[str, str, int, str] | None:
    m = re.search(
        r"\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|",
        line,
    )
    if not m:
        return None
    fp, fn, cc, tid = m.groups()
    return fp.strip(), fn.strip(), int(cc), tid.strip()


def _parse_batch_line(line: str) -> str | None:
    line_str = line.strip()
    if not line_str.startswith("## Batch "):
        return None
    return line_str.replace("## ", "").strip()


def _is_table_entry(line: str, current_batch: bool) -> bool:
    if not current_batch:
        return False
    stripped = line.strip()
    if not stripped.startswith("| "):
        return False
    if stripped.startswith("| #"):
        return False
    if stripped.startswith("|---"):
        return False
    return True


def _read_yolo_lines(yolo_path: str) -> list[str]:
    if not os.path.exists(yolo_path):
        print(f"Error: {yolo_path} not found.")
        sys.exit(1)
    with open(yolo_path, "r", encoding="utf-8") as f:
        return f.readlines()


def parse_yolo_mode(
    yolo_path: str = "kit-hygiene/scanners/99_YOLO_Mode.md",
) -> dict[str, list[dict]]:
    batch_items: dict[str, list[dict]] = {}
    current_batch = None

    lines = _read_yolo_lines(yolo_path)

    for line in lines:
        parsed_batch = _parse_batch_line(line)
        if parsed_batch is not None:
            current_batch = parsed_batch
            batch_items[current_batch] = []
            continue

        if _is_table_entry(line, current_batch is not None):
            parsed = _parse_table_line(line)
            if parsed is None:
                continue
            fp, fn, cc, tid = parsed
            batch_items[current_batch].append(
                {
                    "file": fp,
                    "function": fn,
                    "cc": cc,
                    "ticket": tid,
                }
            )
    return batch_items


def _classify_items(items: list[dict], live_cc: dict[str, dict[str, int]]) -> tuple[list[dict], list[dict]]:
    active = []
    clean = []
    for item in items:
        fp = item["file"]
        fn = item["function"]
        if fp in live_cc and fn in live_cc[fp]:
            item["current_cc"] = live_cc[fp][fn]
            active.append(item)
        else:
            clean.append(item)
    return active, clean


def _format_header() -> None:
    print("=======================================================================")
    print("                 CC REDUCTION PROGRESS STATUS                          ")
    print("=======================================================================\n")


def _print_active_item(a: dict) -> None:
    print(
        f"   \u2514\u2500OPEN: {a['file']} :: {a['function']} (CC={a['current_cc']}) -> {a['ticket']}"
    )


def _print_batch(batch_name: str, items: list[dict], live_cc: dict[str, dict[str, int]]) -> tuple[int, int, int]:
    active, clean = _classify_items(items, live_cc)

    b_total = len(items)
    b_active = len(active)
    b_clean = len(clean)
    pct = (b_clean / b_total * 100) if b_total > 0 else 100.0

    print(
        f"[{batch_name}] {b_clean}/{b_total} Clean ({pct:5.1f}%) | {b_active} Remaining"
    )
    for a in active:
        _print_active_item(a)

    return b_total, b_active, b_clean


def _print_summary(total_items: int, total_active: int, total_clean: int) -> None:
    print("\n-----------------------------------------------------------------------")
    overall_pct = (total_clean / total_items * 100) if total_items > 0 else 100.0
    print(
        f"OVERALL SUMMARY: {total_clean}/{total_items} Complete ({overall_pct:.1f}%) | {total_active} Remaining"
    )
    print("=======================================================================\n")


def main():
    live_cc = scan_live_cc()
    batch_items = parse_yolo_mode()

    total_items = 0
    total_active = 0
    total_clean = 0

    _format_header()

    for batch_name, items in batch_items.items():
        b_total, b_active, b_clean = _print_batch(batch_name, items, live_cc)
        total_items += b_total
        total_active += b_active
        total_clean += b_clean

    _print_summary(total_items, total_active, total_clean)


if __name__ == "__main__":
    main()
