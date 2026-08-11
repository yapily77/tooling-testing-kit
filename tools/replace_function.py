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


def _is_func_def(node) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def _match_method(node, name) -> bool:
    return _is_func_def(node) and node.name == name


def _find_in_class_body(cls: ast.ClassDef, name: str):
    """Find a method by name in a class body."""
    return next(
        (sub for sub in cls.body if _match_method(sub, name)),
        None,
    )


def _find_class(tree, class_name):
    """Find a ClassDef by name in the AST."""
    return next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name),
        None,
    )


def _find_method_in_class(tree, name, class_name):
    """Search for a method within a specific class."""
    cls = _find_class(tree, class_name)
    if cls is None:
        return None, False
    method = _find_in_class_body(cls, name)
    return (method, True) if method else (None, False)


def _find_function_node(tree, name, class_name=None):
    """Find a function definition by name, optionally within a class."""
    if class_name:
        return _find_method_in_class(tree, name, class_name)
    node = next(
        (n for n in tree.body if _match_method(n, name)),
        None,
    )
    return (node, True) if node else (None, False)


def _replace_in_module(new_tree, function_name, new_node):
    """Replace a top-level function definition. Returns True if replaced."""
    i = next(
        (i for i, n in enumerate(new_tree.body) if _match_method(n, function_name)),
        -1,
    )
    if i >= 0:
        new_tree.body[i] = new_node
        return True
    return False


def _replace_in_class_body(cls: ast.ClassDef, function_name, new_node):
    """Replace a method in a class body. Returns True if replaced."""
    i = next(
        (i for i, sub in enumerate(cls.body) if _match_method(sub, function_name)),
        -1,
    )
    if i >= 0:
        cls.body[i] = new_node
        return True
    return False


def _replace_in_class(new_tree, class_name, function_name, new_node):
    """Replace a method within a class body."""
    cls = _find_class(new_tree, class_name)
    if cls is None:
        return False
    return _replace_in_class_body(cls, function_name, new_node)


def _validate_path(args) -> Path:
    """Validate file path and return resolved path."""
    path = resolve_secure_path(args.relative_path)
    if not path.exists():
        print(json.dumps(fail(f"File not found: {args.relative_path}"), indent=2))
        sys.exit(1)
    if path.suffix != ".py":
        print(json.dumps(fail("Not a Python file."), indent=2))
        sys.exit(1)
    return path


def _validate_function_code(args):
    """Validate that new_function_code is a single function definition."""
    new_func = ast.parse(args.new_function_code)
    if not new_func.body or not _is_func_def(new_func.body[0]):
        print(json.dumps(fail("new_function_code must be a single function definition."), indent=2))
        sys.exit(1)
    return new_func.body[0]


def _perform_replace(args, path, content, tree, new_node):
    """Perform the function replacement and output result."""
    target, found = _find_function_node(tree, args.function_name, args.class_name)
    if not found:
        class_part = f" in class {args.class_name}" if args.class_name else ""
        print(json.dumps(fail(f"Function {args.function_name}{class_part} not found."), indent=2))
        sys.exit(1)

    new_tree = ast.parse(content)
    if args.class_name:
        _replace_in_class(new_tree, args.class_name, args.function_name, new_node)
    else:
        _replace_in_module(new_tree, args.function_name, new_node)

    ast.fix_missing_locations(new_tree)
    updated = ast.unparse(new_tree)
    old_src = ast.unparse(target)
    new_src = ast.unparse(new_node)
    path.write_text(updated + "\n", encoding="utf-8")
    print(json.dumps(ok(
        f"Replaced function {args.function_name} in {args.relative_path}",
        {"changed": True, "diff": _bounded_diff(old_src, new_src)},
    ), indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Replace a function's source via AST manipulation."
    )
    parser.add_argument("relative_path", help="Path relative to project root.")
    parser.add_argument("function_name", help="Function name to replace.")
    parser.add_argument("new_function_code", help="Full new function source.")
    parser.add_argument("--class-name", default=None, help="Optional enclosing class.")
    args = parser.parse_args()

    try:
        path = resolve_secure_path(args.relative_path)
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        sys.exit(1)

    try:
        path = _validate_path(args)
        new_node = _validate_function_code(args)
        content = _normalize_content(path.read_text(encoding="utf-8"))
        tree = ast.parse(content)
        _perform_replace(args, path, content, tree, new_node)
    except SystemExit:
        raise
    except (OSError, SyntaxError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(json.dumps(fail(f"replace_function failed: {e}"), indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
