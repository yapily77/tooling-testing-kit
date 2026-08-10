import argparse
import ast
import json
import sys
from pathlib import Path

from _codebase_common import fail, ok, resolve_secure_path

sys.path.append(str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description="Clean unused import statements from a Python file.")
    parser.add_argument("relative_path", help="Path relative to repo root.")
    args = parser.parse_args()

    try:
        target = resolve_secure_path(args.relative_path)
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        sys.exit(1)

    if not target.exists():
        print(json.dumps(fail("Target file not found"), indent=2))
        sys.exit(1)

    try:
        source = target.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Collect all used names
        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                used_names.add(node.attr)

        lines = source.splitlines()
        new_lines = []
        removed = 0

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                try:
                    line_ast = ast.parse(line)
                    keep = False
                    for stmt in line_ast.body:
                        if isinstance(stmt, ast.Import):
                            for alias in stmt.names:
                                name_to_check = alias.asname or alias.name.split(".")[0]
                                if name_to_check in used_names:
                                    keep = True
                        elif isinstance(stmt, ast.ImportFrom):
                            for alias in stmt.names:
                                name_to_check = alias.asname or alias.name
                                if name_to_check in used_names:
                                    keep = True
                    if keep:
                        new_lines.append(line)
                    else:
                        removed += 1
                except (OSError, SyntaxError, TypeError, ValueError):
                    new_lines.append(line)
            else:
                new_lines.append(line)

        target.write_text("\n".join(new_lines) + ("\n" if lines and lines[-1] == "" else ""), encoding="utf-8")
        print(json.dumps(ok(f"Cleaned {removed} unused import(s)", {"path": args.relative_path, "removed_count": removed}), indent=2))

    except (OSError, SyntaxError, TypeError, ValueError) as e:
        print(json.dumps(fail(f"ast_clean_imports failed: {e}"), indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
