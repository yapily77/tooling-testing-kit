#!/usr/bin/env python3
"""
fix_midfile_imports.py — AST tool to fix E402 mid-file imports and remove duplicate definitions.
Moves all mid-file imports to the top of python files in src/.
"""

import ast
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
src_dir = repo_root / "src"


def fix_file_imports(file_path: Path) -> bool:
    content = _read_file_content(file_path)
    if content is None:
        return False

    lines = content.splitlines(keepends=True)
    mid_file_imports = _find_mid_file_imports(content)
    if not mid_file_imports:
        return False

    new_source = _rebuild_source(lines, mid_file_imports)
    return _write_if_valid(file_path, new_source, mid_file_imports)


def _read_file_content(file_path: Path) -> str | None:
    try:
        return file_path.read_text(encoding="utf-8")
    except (OSError, SyntaxError):
        return None


def _find_mid_file_imports(content: str) -> list[tuple[int, int, str]]:
    try:
        tree = ast.parse(content)
    except (OSError, SyntaxError):
        return []

    mid_file_imports: list[tuple[int, int, str]] = []
    first_non_import_lineno = None
    for stmt in tree.body:
        first_non_import_lineno = _scan_stmt(stmt, tree, first_non_import_lineno, mid_file_imports)
    return mid_file_imports


def _scan_stmt(stmt, tree, first_non_import_lineno, mid_file_imports):
    if _is_skippable_header(stmt, tree):
        return first_non_import_lineno
    if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
        if first_non_import_lineno is None:
            return stmt.lineno
        return first_non_import_lineno
    if _is_mid_file_import(stmt, first_non_import_lineno):
        start_line = stmt.lineno - 1
        end_line = getattr(stmt, "end_lineno", stmt.lineno)
        mid_file_imports.append((start_line, end_line, ast.unparse(stmt)))
    return first_non_import_lineno


def _is_skippable_header(stmt: ast.stmt, tree: ast.Module) -> bool:
    if _is_module_docstring(stmt, tree):
        return True
    return _is_future_import(stmt)


def _is_module_docstring(stmt: ast.stmt, tree: ast.Module) -> bool:
    if stmt is not tree.body[0]:
        return False
    if not isinstance(stmt, ast.Expr):
        return False
    if not isinstance(stmt.value, ast.Constant):
        return False
    return isinstance(stmt.value.value, str)


def _is_future_import(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"


def _is_mid_file_import(stmt: ast.Import | ast.ImportFrom, first_non_import: int | None) -> bool:
    return first_non_import is not None and stmt.lineno > first_non_import


def _rebuild_source(lines: list[str], mid_file_imports: list[tuple[int, int, str]]) -> str:
    sorted_imports = sorted(mid_file_imports, key=lambda x: x[0], reverse=True)
    imports_to_add: set[str] = set()

    for start_line, end_line, stmt_code in sorted_imports:
        imports_to_add.add(stmt_code)
        del lines[start_line:end_line]

    top_imports_code = "\n".join(sorted(imports_to_add)) + "\n"
    insert_line_idx = _find_insert_index(lines)
    new_lines = lines.copy()
    new_lines.insert(insert_line_idx, top_imports_code)
    return "".join(new_lines)


def _find_insert_index(lines: list[str]) -> int:
    try:
        new_tree = ast.parse("".join(lines))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return 0
    insert_line_idx = 0
    for stmt in new_tree.body:
        if _is_skippable_header(stmt, new_tree):
            insert_line_idx = stmt.end_lineno
            continue
        break
    return insert_line_idx


def _write_if_valid(file_path: Path, new_source: str, mid_file_imports: list) -> bool:
    try:
        ast.parse(new_source)
        file_path.write_text(new_source, encoding="utf-8")
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"Failed fixing imports for {file_path.name}: {e}")
        raise
        return False


def main():
    fixed_count = 0
    for py_file in sorted(src_dir.rglob("*.py")):
        if py_file.is_file() and fix_file_imports(py_file):
            fixed_count += 1
    print(f"🎉 Moved mid-file imports to top in {fixed_count} file(s).")


if __name__ == "__main__":
    main()
