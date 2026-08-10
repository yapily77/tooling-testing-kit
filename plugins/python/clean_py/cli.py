from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .validator import validate_file


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the clean_py CLI."""
    parser = argparse.ArgumentParser(
        prog="clean_py",
        description="Python code validator (AST policy, ruff, mypy strict, radon CC).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a Python file against quality constraints.",
    )
    validate_parser.add_argument(
        "file_path",
        type=str,
        help="Path to the Python file to validate.",
    )
    validate_parser.add_argument(
        "--python",
        type=str,
        default=None,
        help="Path to Python binary (default: auto-discover from .venv).",
    )
    validate_parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Workspace directory (default: parent of file).",
    )

    return parser


def resolve_python_bin(workspace_dir: str | None) -> str | None:
    """Resolve Python binary path from workspace .venv."""
    if workspace_dir is None:
        return None
    from .validator import discover_python

    return discover_python(Path(workspace_dir))


def run_validate(args: argparse.Namespace) -> int:
    """Run the validate subcommand and print JSON output."""
    result = validate_file(
        args.file_path,
        python_bin=args.python,
        workspace_dir=args.workspace,
    )
    output = {
        "valid": result.valid,
        "errors": result.errors,
    }
    print(json.dumps(output, indent=2))
    return 0 if result.valid else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        return run_validate(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
