import argparse
import json
import sys
from pathlib import Path

from _codebase_common import fail, ok, resolve_secure_path

sys.path.append(str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description="Delete a file within the repo.")
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
        target.unlink()
        print(json.dumps(ok(f"Deleted {args.relative_path}", {"path": args.relative_path}), indent=2))
    except OSError as e:
        print(json.dumps(fail(f"delete_file failed: {e}"), indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
