import argparse
import ast
import json
import sys
from pathlib import Path

from _codebase_common import fail, ok, resolve_secure_path

sys.path.append(str(Path(__file__).resolve().parents[1]))


def main():
    args = _parse_args()
    target = _resolve_target(args.relative_path)
    if target is None:
        return

    result = _process_file(target, args.relative_path)
    _print_result(result)


def _parse_args():
    parser = argparse.ArgumentParser(description="Clean unused import statements from a Python file.")
    parser.add_argument("relative_path", help="Path relative to repo root.")
    return parser.parse_args()


def _resolve_target(relative_path: str) -> Path | None:
    try:
        target = resolve_secure_path(relative_path)
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        sys.exit(1)
    if not target.exists():
        print(json.dumps(fail("Target file not found"), indent=2))
        sys.exit(1)
    return target


def _process_file(target: Path, relative_path: str) -> dict:
    try:
        source = target.read_text(encoding="utf-8")
        tree = ast.parse(source)

        used_names = _collect_used_names(tree)
        new_lines, removed = _filter_import_lines(source.splitlines(), used_names)

        target.write_text(_join_lines(new_lines), encoding="utf-8")
        return ok(f"Cleaned {removed} unused import(s)", {"path": relative_path, "removed_count": removed})
    except (OSError, SyntaxError, TypeError, ValueError) as e:
        return fail(f"ast_clean_imports failed: {e}")


def _collect_used_names(tree: ast.AST) -> set[str]:
    used_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            used_names.add(node.attr)
    return used_names


def _filter_import_lines(lines: list[str], used_names: set[str]) -> tuple[list[str], int]:
    new_lines = []
    removed = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            keep = _should_keep_import(line, used_names)
            if keep:
                new_lines.append(line)
            else:
                removed += 1
        else:
            new_lines.append(line)
    return new_lines, removed


def _should_keep_import(line: str, used_names: set[str]) -> bool:
    try:
        line_ast = ast.parse(line)
    except (OSError, SyntaxError, TypeError, ValueError):
        return True
    for stmt in line_ast.body:
        if _stmt_uses_names(stmt, used_names):
            return True
    return False


def _stmt_uses_names(stmt: ast.stmt, used_names: set[str]) -> bool:
    if isinstance(stmt, ast.Import):
        return _import_uses_names(stmt, used_names)
    if isinstance(stmt, ast.ImportFrom):
        return _import_from_uses_names(stmt, used_names)
    return False


def _import_uses_names(stmt: ast.Import, used_names: set[str]) -> bool:
    for alias in stmt.names:
        if alias.asname:
            return True
        if alias.name.split(".")[0] in used_names:
            return True
    return False


def _import_from_uses_names(stmt: ast.ImportFrom, used_names: set[str]) -> bool:
    for alias in stmt.names:
        if alias.asname or alias.name in used_names:
            return True
    return False


def _join_lines(lines: list[str]) -> str:
    return "\n".join(lines) + ("\n" if lines and lines[-1] == "" else "")


def _print_result(result: dict) -> None:
    exit_code = 0 if result.get("success") else 1
    print(json.dumps(result, indent=2))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
