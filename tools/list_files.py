import argparse
import json
import os
import sys
from pathlib import Path

from _codebase_common import (
    EXCLUDE_DIRS,
    INCLUDE_EXTENSIONS,
    PROJECT_ROOT,
    _safe_relative,
    fail,
    ok,
    resolve_secure_path,
)

sys.path.append(str(Path(__file__).resolve().parents[1]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List files in a repo directory with pagination.")
    parser.add_argument("directory", nargs="?", default="", help="Relative path to directory (empty = project root).")
    parser.add_argument("--extension-filter", default=None, help="Only return files with this extension, e.g. '.py'.")
    parser.add_argument("--recursive", action="store_true", default=True, help="Recurse into subdirectories.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum number of files to return.")
    parser.add_argument("--offset", type=int, default=0, help="Number of files to skip for pagination.")
    return parser.parse_args()


def resolve_base_directory(directory: str) -> Path | None:
    try:
        base = resolve_secure_path(directory) if directory else PROJECT_ROOT
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        return None

    if not base.exists():
        print(json.dumps(fail(f"Directory not found: {directory}"), indent=2))
        return None

    return base


def _matches_extension_filter(fp: Path, extension_filter: str | None) -> bool:
    if extension_filter:
        return fp.suffix == extension_filter
    return fp.suffix in INCLUDE_EXTENSIONS


def _iter_walker(base: Path, recursive: bool):
    return os.walk(base) if recursive else [(str(base), [], os.listdir(base))]


def _collect_in_dir(root: str, files: list[str], extension_filter: str | None) -> list[str]:
    found: list[str] = []
    for f in sorted(files):
        fp = Path(root) / f
        if not _matches_extension_filter(fp, extension_filter):
            continue
        found.append(_safe_relative(fp))
    return found


def collect_files(base: Path, args: argparse.Namespace) -> list[str]:
    all_found: list[str] = []
    for root, dirs, files in _iter_walker(base, args.recursive):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        all_found.extend(_collect_in_dir(root, files, args.extension_filter))
    all_found.sort()
    return all_found


def main():
    args = parse_args()

    base = resolve_base_directory(args.directory)
    if base is None:
        return

    all_found = collect_files(base, args)
    total_count = len(all_found)
    paged = all_found[args.offset : args.offset + args.limit]

    print(json.dumps(ok(
        f"Found {total_count} files in {args.directory or 'root'}",
        {
            "files": paged,
            "metadata": {
                "total": total_count,
                "returned": len(paged),
                "offset": args.offset,
                "limit": args.limit,
                "is_truncated": (args.offset + args.limit) < total_count,
            },
        },
    ), indent=2))


if __name__ == "__main__":
    main()
