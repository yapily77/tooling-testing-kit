import argparse
import ast
import json
import sys
from pathlib import Path

from _codebase_common import (
    _bounded_diff,
    _normalize_content,
    fail,
    ok,
    resolve_secure_path,
)

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _function_node(function_code: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    stripped = function_code.strip()
    tree = ast.parse(stripped)
    if not tree.body:
        raise ValueError(f"Empty function code: {function_code!r}")
    node = tree.body[0]
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise TypeError(
            f"add_function expects a function definition, got {type(node).__name__}"
        )
    return node


def _match_function_in_body(body: list[ast.stmt], name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find a function definition by name in a statement list."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _find_function_in_class(tree: ast.Module, name: str, class_name: str) -> tuple[ast.AST | None, bool]:
    """Search for a method within a specific class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            method = _match_function_in_body(node.body, name)
            if method:
                return method, True
    return None, False


def _find_function(tree: ast.Module, name: str, class_name: str | None = None) -> tuple[ast.AST | None, bool]:
    """Find a function by name, optionally within a class."""
    if class_name is not None:
        return _find_function_in_class(tree, name, class_name)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node, True
    return None, False


def _is_target_node(node: ast.stmt, target_name: str) -> bool:
    """Check if a node matches the target name for insertion positioning."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name == target_name
    if isinstance(node, ast.ClassDef):
        return node.name == target_name
    return False


def _insert_after_in_body(body: list[ast.stmt], target_name: str, new_node: ast.stmt) -> bool:
    """Insert new_node after the node matching target_name in body."""
    for i, node in enumerate(body):
        if _is_target_node(node, target_name):
            body.insert(i + 1, new_node)
            return True
    return False


def _find_class_body(body: list[ast.stmt], class_name: str) -> list[ast.stmt] | None:
    """Find the body of a class by name in the given statement list."""
    for node in body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node.body
    return None


def _insert_after(
    body: list[ast.stmt], target_name: str, new_node: ast.stmt, class_name: str | None = None
) -> bool:
    """Insert new_node after target_name, optionally within a class body."""
    if class_name is not None:
        search_body = _find_class_body(body, class_name)
        if search_body is None:
            return False
    else:
        search_body = body
    return _insert_after_in_body(search_body, target_name, new_node)


def _validate_file_args(args) -> Path:
    """Validate path and file type, returning resolved path."""
    try:
        path = resolve_secure_path(args.relative_path)
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        sys.exit(1)
    if not path.exists():
        print(json.dumps(fail(f"File not found: {args.relative_path}"), indent=2))
        sys.exit(1)
    if path.suffix != ".py":
        print(json.dumps(fail("Not a Python file."), indent=2))
        sys.exit(1)
    return path


def _get_target_body(tree: ast.Module, class_name: str | None) -> list[ast.stmt]:
    """Get the body list to insert into, optionally within a class."""
    if class_name is not None:
        class_body = _find_class_body(tree.body, class_name)
        if class_body is not None:
            return class_body
    return tree.body


def _perform_add_function(path: Path, args) -> None:
    new_node = _function_node(args.function_code)
    content = _normalize_content(path.read_text(encoding="utf-8"))
    tree = ast.parse(content)
    func_name = new_node.name

    _, found = _find_function(tree, func_name, args.class_name)
    if found:
        print(json.dumps(ok(
            f"Function {func_name} already exists in {args.relative_path}",
            {"file_path": args.relative_path, "changed": False},
        ), indent=2))
        return

    target_body = _get_target_body(tree, args.class_name)
    if args.insert_after is not None:
        if not _insert_after(target_body, args.insert_after, new_node, args.class_name):
            target_body.append(new_node)
    else:
        target_body.append(new_node)

    ast.fix_missing_locations(tree)
    updated = ast.unparse(tree)
    path.write_text(updated + "\n", encoding="utf-8")
    print(json.dumps(ok(
        f"Added function {func_name} to {args.relative_path}",
        {
            "file_path": args.relative_path, "changed": True,
            "function": func_name, "diff": _bounded_diff(content, updated),
        },
    ), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add a new function to a Python file using AST manipulation."
    )
    parser.add_argument("relative_path", help="Path to Python file relative to project root.")
    parser.add_argument("function_code", help="Full function source code to add.")
    parser.add_argument(
        "--class-name", default=None, help="Optional enclosing class to add the method into."
    )
    parser.add_argument(
        "--insert-after", default=None, help="Insert after this function or class name."
    )
    args = parser.parse_args()

    path = _validate_file_args(args)

    try:
        _perform_add_function(path, args)
    except (SystemExit, OSError, SyntaxError, TypeError, ValueError) as e:
        print(json.dumps(fail(f"add_function failed: {e}"), indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
