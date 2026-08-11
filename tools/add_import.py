import argparse
import ast
import json
import sys
from pathlib import Path

from _codebase_common import _normalize_content, fail, ok, resolve_secure_path

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _import_node(import_code: str) -> ast.stmt:
    stripped = import_code.strip()
    if not stripped.startswith(("import ", "from ")):
        raise ValueError(f"Not a valid import statement: {import_code!r}")
    tree = ast.parse(stripped)
    return tree.body[0]


def _insert_index(tree: ast.Module) -> int:
    """Index after any leading __future__ imports."""
    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        return i
    return len(tree.body)


def _has_duplicate_import(tree: ast.Module, new_node: ast.stmt) -> bool:
    """Check if the import already exists in the tree."""
    existing = {ast.dump(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))}
    return ast.dump(new_node) in existing


def _validate_path(args) -> Path:
    """Resolve and validate the target Python file path."""
    path = resolve_secure_path(args.relative_path)
    if not path.exists():
        print(json.dumps(fail(f"File not found: {args.relative_path}"), indent=2))
        sys.exit(1)
    if path.suffix != ".py":
        print(json.dumps(fail("Not a Python file."), indent=2))
        sys.exit(1)
    return path


def _perform_add_import(path: Path, args) -> None:
    """Parse file, check for duplicates, and insert import."""
    content = _normalize_content(path.read_text(encoding="utf-8"))
    tree = ast.parse(content)
    new_node = _import_node(args.import_code)

    if _has_duplicate_import(tree, new_node):
        print(json.dumps(ok(
            f"Import already present in {args.relative_path}",
            {"file_path": args.relative_path, "changed": False},
        ), indent=2))
        return

    idx = _insert_index(tree)
    tree.body.insert(idx, new_node)
    ast.fix_missing_locations(tree)
    updated = ast.unparse(tree)
    path.write_text(updated + "\n", encoding="utf-8")
    print(json.dumps(ok(
        f"Added import to {args.relative_path}",
        {"file_path": args.relative_path, "changed": True, "import": args.import_code},
    ), indent=2))


def main():
    parser = argparse.ArgumentParser(description="Add a new import to the top of a file using AST manipulation.")
    parser.add_argument("relative_path", help="Path to Python file.")
    parser.add_argument("import_code", help="Import line (e.g. 'from os import path').")
    args = parser.parse_args()

    try:
        path = resolve_secure_path(args.relative_path)
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        return

    path = _validate_path(args)

    try:
        _perform_add_import(path, args)
    except (OSError, SyntaxError, TypeError, ValueError) as e:
        print(json.dumps(fail(f"Failed to add import: {e}"), indent=2))


if __name__ == "__main__":
    main()
