import argparse
import ast
import json
import sys
from pathlib import Path

from _codebase_common import _normalize_content, fail, ok, resolve_secure_path

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _extract_symbols(tree: ast.Module) -> list[dict]:
    """Extract class and function symbols from parsed AST."""
    symbols = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            symbols.append({"name": node.name, "type": "class", "line": node.lineno})
            symbols.extend(_extract_methods(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({"name": node.name, "type": "function", "line": node.lineno})
    return symbols


def _extract_methods(class_node: ast.ClassDef) -> list[dict]:
    """Extract method definitions from a class node."""
    methods = []
    for child in class_node.body:
        if isinstance(child, ast.FunctionDef):
            methods.append({"name": f"{class_node.name}.{child.name}", "type": "method", "line": child.lineno})
    return methods


def _resolve_file_path(relative_path: str) -> Path:
    """Resolve and validate the target Python file path."""
    path = resolve_secure_path(relative_path)
    if not path.exists():
        print(json.dumps(fail(f"File not found: {relative_path}"), indent=2))
        sys.exit(1)
    if path.suffix != ".py":
        print(json.dumps(fail("Not a Python file."), indent=2))
        sys.exit(1)
    return path


def _parse_source(path: Path, relative_path: str) -> ast.Module:
    """Read and parse source code into AST tree."""
    try:
        content = _normalize_content(path.read_text(encoding="utf-8"))
        return ast.parse(content)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(json.dumps(fail(f"Failed to parse {relative_path}: {e}"), indent=2))
        raise


def main():
    parser = argparse.ArgumentParser(description="List classes and functions defined in a Python file.")
    parser.add_argument("relative_path", help="Path relative to project root.")
    args = parser.parse_args()

    try:
        path = resolve_secure_path(args.relative_path)
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        return

    if not path.exists():
        print(json.dumps(fail(f"File not found: {args.relative_path}"), indent=2))
        return
    if path.suffix != ".py":
        print(json.dumps(fail("Not a Python file."), indent=2))
        return

    try:
        content = _normalize_content(path.read_text(encoding="utf-8"))
        tree = ast.parse(content)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(json.dumps(fail(f"Failed to parse {args.relative_path}: {e}"), indent=2))
        raise
        return

    symbols = _extract_symbols(tree)

    print(json.dumps(ok(
        f"Found {len(symbols)} symbols in {args.relative_path}",
        {"symbols": symbols},
    ), indent=2))


if __name__ == "__main__":
    main()
