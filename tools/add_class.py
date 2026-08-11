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


def _class_node(class_code: str) -> ast.ClassDef:
    stripped = class_code.strip()
    tree = ast.parse(stripped)
    if not tree.body:
        raise ValueError(f"Empty class code: {class_code!r}")
    node = tree.body[0]
    if not isinstance(node, ast.ClassDef):
        raise TypeError(
            f"add_class expects a class definition, got {type(node).__name__}"
        )
    return node


def _find_class(tree: ast.Module, name: str) -> tuple[ast.ClassDef | None, bool]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node, True
    return None, False


def _is_insertable_node(node: ast.stmt, target_name: str) -> bool:
    """Check if a node matches the target name for insertion positioning."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name == target_name
    if isinstance(node, ast.ClassDef):
        return node.name == target_name
    return False


def _insert_after_in_body(body: list[ast.stmt], target_name: str, new_node: ast.stmt) -> bool:
    """Insert new_node after the node matching target_name in body."""
    for i, node in enumerate(body):
        if _is_insertable_node(node, target_name):
            body.insert(i + 1, new_node)
            return True
    return False


def _insert_after(
    body: list[ast.stmt], target_name: str, new_node: ast.stmt
) -> bool:
    return _insert_after_in_body(body, target_name, new_node)


def _validate_file(args) -> Path:
    """Resolve path and validate it's a Python file that exists."""
    path = resolve_secure_path(args.relative_path)
    if not path.exists():
        print(json.dumps(fail(f"File not found: {args.relative_path}"), indent=2))
        sys.exit(1)
    if path.suffix != ".py":
        print(json.dumps(fail("Not a Python file."), indent=2))
        sys.exit(1)
    return path


def _perform_add_class(path: Path, args) -> None:
    new_node = _class_node(args.class_code)
    content = _normalize_content(path.read_text(encoding="utf-8"))
    tree = ast.parse(content)
    class_name = new_node.name

    _, found = _find_class(tree, class_name)
    if found:
        print(json.dumps(ok(
            f"Class {class_name} already exists in {args.relative_path}",
            {"file_path": args.relative_path, "changed": False},
        ), indent=2))
        return

    target_body = tree.body
    if args.insert_after is not None:
        if not _insert_after(target_body, args.insert_after, new_node):
            target_body.append(new_node)
    else:
        target_body.append(new_node)

    ast.fix_missing_locations(tree)
    updated = ast.unparse(tree)
    path.write_text(updated + "\n", encoding="utf-8")
    print(json.dumps(ok(
        f"Added class {class_name} to {args.relative_path}",
        {
            "file_path": args.relative_path, "changed": True,
            "class": class_name, "diff": _bounded_diff(content, updated),
        },
    ), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add a new class to a Python file using AST manipulation."
    )
    parser.add_argument("relative_path", help="Path to Python file relative to project root.")
    parser.add_argument("class_code", help="Full class source code to add.")
    parser.add_argument(
        "--insert-after", default=None, help="Insert after this class or function name."
    )
    args = parser.parse_args()

    try:
        path = resolve_secure_path(args.relative_path)
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        sys.exit(1)

    _validate_file(args)

    try:
        _perform_add_class(path, args)
    except (SystemExit, OSError, SyntaxError, TypeError, ValueError) as e:
        print(json.dumps(fail(f"add_class failed: {e}"), indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
