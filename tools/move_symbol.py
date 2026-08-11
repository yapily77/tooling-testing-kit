import argparse
import ast
import json
import sys
from pathlib import Path

from _codebase_common import _normalize_content, fail, ok, resolve_secure_path

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _find_top_level(tree, name):
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == name
        ):
            return node
    return None


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Move a top-level symbol from one Python file to another (AST-based)."
    )
    parser.add_argument("symbol_name", help="Function or class name to move.")
    parser.add_argument("source_path", help="Source file path relative to project root.")
    parser.add_argument("dest_path", help="Destination file path relative to project root.")
    return parser.parse_args()


def _validate_paths(src: Path, dst: Path, symbol_name: str):
    if not src.exists() or not dst.exists():
        print(json.dumps(fail("Source and destination files must both exist."), indent=2))
        sys.exit(1)
    if src.suffix != ".py" or dst.suffix != ".py":
        print(json.dumps(fail("Both files must be .py."), indent=2))
        sys.exit(1)


def _resolve_symbol(src_tree, dst_tree, symbol_name, source_path, dest_path):
    node = _find_top_level(src_tree, symbol_name)
    if node is None:
        print(
            json.dumps(
                fail(f"Symbol {symbol_name} not found in {source_path}"),
                indent=2,
            )
        )
        sys.exit(1)

    if _find_top_level(dst_tree, symbol_name) is not None:
        print(json.dumps(fail("Symbol already exists in destination"), indent=2))
        sys.exit(1)

    return node


def _write_tree(tree: ast.Module, path: Path):
    path.write_text(ast.unparse(tree) + "\n", encoding="utf-8")


def _move_and_report(src_tree, dst_tree, node, src: Path, dst: Path, symbol_name, source_path, dest_path):
    src_tree.body.remove(node)
    dst_tree.body.append(node)
    ast.fix_missing_locations(src_tree)
    ast.fix_missing_locations(dst_tree)
    _write_tree(src_tree, src)
    _write_tree(dst_tree, dst)
    print(
        json.dumps(
            ok(
                f"Moved {symbol_name} from {source_path} to {dest_path}",
                {"symbol": symbol_name},
            ),
            indent=2,
        )
    )


def main():
    args = _parse_args()

    try:
        src = resolve_secure_path(args.source_path)
        dst = resolve_secure_path(args.dest_path)
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        sys.exit(1)

    _validate_paths(src, dst, args.symbol_name)

    try:
        src_content = _normalize_content(src.read_text(encoding="utf-8"))
        dst_content = _normalize_content(dst.read_text(encoding="utf-8"))
        src_tree = ast.parse(src_content)
        dst_tree = ast.parse(dst_content)

        node = _resolve_symbol(src_tree, dst_tree, args.symbol_name, args.source_path, args.dest_path)
        _move_and_report(src_tree, dst_tree, node, src, dst, args.symbol_name, args.source_path, args.dest_path)
    except SystemExit:
        raise
    except (OSError, SyntaxError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(json.dumps(fail(f"move_symbol failed: {e}"), indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
