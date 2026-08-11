import argparse
import ast
import json
import sys
from pathlib import Path

from _codebase_common import _normalize_content, fail, ok, resolve_secure_path

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _constant_node(constant_code: str, constant_name: str = "") -> ast.stmt:
    stripped = constant_code.strip()
    if "=" not in stripped and constant_name:
        stripped = f"{constant_name} = {stripped}"
    tree = ast.parse(stripped)
    node = tree.body[0]
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        raise TypeError(f"Not a valid constant assignment: {constant_code!r}")
    return node


def _ann_assign_matches(node: ast.AnnAssign, constant_name: str) -> bool:
    """Check if an AnnAssign node targets the given constant name."""
    target = node.target
    return isinstance(target, ast.Name) and target.id == constant_name


def _node_matches_constant(node: ast.stmt, constant_name: str) -> bool:
    """Check if a module-level statement defines the given constant name."""
    if isinstance(node, ast.Assign):
        return any(
            isinstance(t, ast.Name) and t.id == constant_name
            for t in node.targets
        )
    if isinstance(node, ast.AnnAssign):
        return _ann_assign_matches(node, constant_name)
    return False


def _existing_constant(tree: ast.Module, constant_name: str) -> bool:
    """Check if a constant with the given name already exists at module level."""
    return any(
        _node_matches_constant(node, constant_name)
        for node in tree.body
    )


def _validate_path(args) -> Path:
    """Validate the constant code and file path, returning the resolved path."""
    if not args.constant_code or not args.constant_code.strip():
        raise ValueError("no value supplied")
    path = resolve_secure_path(args.relative_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {args.relative_path}")
    if path.suffix != ".py":
        raise ValueError("Not a Python file.")
    return path


def _add_constant_impl(path: Path, args) -> None:
    new_node = _constant_node(args.constant_code, args.constant_name)
    content = _normalize_content(path.read_text(encoding="utf-8"))
    tree = ast.parse(content)

    if _existing_constant(tree, args.constant_name):
        print(json.dumps(ok(
            f"Constant already present in {args.relative_path}",
            {"file_path": args.relative_path, "changed": False, "constant": args.constant_name},
        ), indent=2))
        return

    tree.body.append(new_node)
    ast.fix_missing_locations(tree)
    updated = ast.unparse(tree)
    path.write_text(updated + "\n", encoding="utf-8")
    print(json.dumps(ok(
        f"Added constant to {args.relative_path}",
        {"file_path": args.relative_path, "changed": True, "constant": args.constant_name},
    ), indent=2))


def main():
    parser = argparse.ArgumentParser(description="Add a top-level constant to a Python file using AST manipulation.")
    parser.add_argument("relative_path", help="Path to Python file.")
    parser.add_argument("constant_name", help="Name of the constant to add.")
    parser.add_argument("constant_code", help="Full assignment line or value code for the constant.")
    args = parser.parse_args()

    try:
        path = _validate_path(args)
    except ValueError as e:
        msg = str(e) if "no value" not in str(e) else (
            "add_constant failed: no value supplied — pass a simple "
            "constant assignment, e.g. MY_CONST = 'value' (use write_file "
            "or replace_text for class/function definitions)"
        )
        print(json.dumps(fail(msg), indent=2))
        sys.exit(1)
    except FileNotFoundError as e:
        print(json.dumps(fail(str(e)), indent=2))
        sys.exit(1)

    try:
        _add_constant_impl(path, args)
    except (OSError, SyntaxError, TypeError, ValueError) as e:
        print(json.dumps(fail(f"add_constant failed: {e}"), indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
