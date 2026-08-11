from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from _codebase_common import (
    EXCLUDE_DIRS,
    INCLUDE_EXTENSIONS,
    PROJECT_ROOT,
    _normalize_content,
    _safe_relative,
    fail,
    ok,
    resolve_secure_path,
)

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search for a literal string or regex across the repo.")
    parser.add_argument("pattern", help="Text or regex to search for.")
    parser.add_argument("directory", nargs="?", default="", help="Limit search to this subdirectory (empty = whole repo).")
    parser.add_argument("--extension-filter", default=None, help="Only search files with this extension, e.g. '.py'.")
    parser.add_argument("--case-sensitive", action="store_true", default=False, help="Default False.")
    parser.add_argument("--max-results", type=int, default=50, help="Cap results (default 50).")
    return parser


def _resolve_base(directory: str) -> Path:
    return PROJECT_ROOT if not directory else resolve_secure_path(directory)


def _matches_extension(file_path: Path, extension_filter: str | None) -> bool:
    return (extension_filter is None or file_path.suffix == extension_filter) and file_path.suffix in INCLUDE_EXTENSIONS


def _search_file(file_path: Path, pattern: str, flags: int) -> list[dict[str, object]] | None:
    try:
        content = _normalize_content(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    matches: list[dict[str, object]] = []
    for i, line in enumerate(content.splitlines()):
        if re.search(pattern, line, flags):
            matches.append({"file_path": _safe_relative(file_path), "line": i + 1, "text": line.strip()})
    return matches


def _iter_file_matches(file_path: Path, pattern: str, flags: int, extension_filter: str | None) -> Iterator[dict[str, object]]:
    if not _matches_extension(file_path, extension_filter):
        return
    matches = _search_file(file_path, pattern, flags)
    if matches:
        yield from matches


def _collect(base: Path, pattern: str, flags: int, extension_filter: str | None) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            results.extend(_iter_file_matches(Path(root) / f, pattern, flags, extension_filter))
    return results


def _print_max(results: list[dict[str, object]], max_results: int) -> None:
    print(json.dumps(ok(f"Found max {max_results} results", {"results": results}), indent=2))


def _print_ok(results: list[dict[str, object]]) -> None:
    print(json.dumps(ok(f"Found {len(results)} results", {"results": results}), indent=2))


def _print_fail(message: str) -> None:
    print(json.dumps(fail(message), indent=2))


def _run_grep(args: argparse.Namespace) -> None:
    base = _resolve_base(args.directory)
    flags = 0 if args.case_sensitive else re.IGNORECASE
    try:
        results = _collect(base, args.pattern, flags, args.extension_filter)
        if len(results) >= args.max_results:
            _print_max(results[: args.max_results], args.max_results)
        else:
            _print_ok(results)
    except OSError as e:
        _print_fail(f"Grep failed: {e}")


def main() -> None:
    args = _build_parser().parse_args()
    try:
        _run_grep(args)
    except ValueError as e:
        _print_fail(str(e))


if __name__ == "__main__":
    main()
