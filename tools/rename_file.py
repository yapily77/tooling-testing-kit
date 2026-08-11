import argparse
import json
import os
import sys
from pathlib import Path

from _codebase_common import fail, ok, resolve_secure_path

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _fail_and_exit(message: str) -> None:
    """Print a failure result as JSON and exit with code 1."""
    print(json.dumps(fail(message), indent=2))
    sys.exit(1)


def _resolve_source(args) -> Path:
    """Resolve and validate source path."""
    try:
        src = resolve_secure_path(args.source_relative_path)
    except ValueError as e:
        _fail_and_exit(str(e))
    if not src.exists():
        _fail_and_exit("Source not found")
    return src


def _resolve_destination(args) -> Path:
    """Resolve and validate destination path."""
    try:
        dst = resolve_secure_path(args.destination_relative_path)
    except ValueError as e:
        _fail_and_exit(str(e))
    if dst.exists():
        _fail_and_exit("Destination already exists")
    return dst


def main():
    parser = argparse.ArgumentParser(description="Rename/move a file within the repo.")
    parser.add_argument("source_relative_path", help="Source path relative to repo root.")
    parser.add_argument("destination_relative_path", help="Destination path relative to repo root.")
    args = parser.parse_args()

    src = _resolve_source(args)
    dst = _resolve_destination(args)

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        print(json.dumps(ok(
            f"Renamed {args.source_relative_path} -> {args.destination_relative_path}",
            {"from": args.source_relative_path, "to": args.destination_relative_path},
        ), indent=2))
    except OSError as e:
        _fail_and_exit(f"rename_file failed: {e}")


if __name__ == "__main__":
    main()
