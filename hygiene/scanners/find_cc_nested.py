from __future__ import annotations

import argparse
import os
import sys
from itertools import filterfalse
from pathlib import Path
from typing import Any

from radon.complexity import cc_visit  # type: ignore[import-untyped]

from _bootstrap import pkg_root  # noqa: F401

_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".eggs",
    "venv",
    ".venv",
    "env",
})

_Block = Any


def _should_ignore_dir(dirname: str) -> bool:
    return dirname in _IGNORE_DIRS


def _is_python_file(fname: str) -> bool:
    return fname.endswith(".py")


def get_all_python_files(root: Path) -> list[Path]:
    py_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = list(filterfalse(_should_ignore_dir, dirnames))
        for fname in filenames:
            if _is_python_file(fname):
                py_files.append(Path(dirpath) / fname)
    return py_files


def _read_source(fpath: Path) -> str | None:
    try:
        with open(fpath, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _visit_blocks(source: str) -> Any:
    try:
        return cc_visit(source)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _collect_dirty_blocks(blocks: list[_Block], min_cc: int) -> list[_Block]:
    return [b for b in blocks if b.complexity >= min_cc]


def _scan_one_file(fpath: Path, root: Path, min_cc: int) -> tuple[str, int, int, list[_Block]] | None:
    source = _read_source(fpath)
    if source is None:
        return None
    blocks = _visit_blocks(source)
    if blocks is None:
        return None
    dirty = _collect_dirty_blocks(blocks, min_cc)
    if not dirty:
        return None
    rel = str(fpath.relative_to(root))
    worst_cc = max(b.complexity for b in dirty)
    return (rel, worst_cc, len(dirty), dirty)


def _scan_files_for_cc(
    py_files: list[Path], root: Path, min_cc: int
) -> list[tuple[str, int, int, list[_Block]]]:
    results: list[tuple[str, int, int, list[_Block]]] = []
    for fpath in py_files:
        entry = _scan_one_file(fpath, root, min_cc)
        if entry is not None:
            results.append(entry)
    return results


def _format_results_header(target_dir: str, min_cc: int, top_count: int) -> None:
    print(f"\n{'=' * 70}")
    print(f"  Top {top_count} Files in {target_dir}/ with Functions CC >= {min_cc}")
    print("  (Aligned with kill_tries.py: CC > 5 per function)")
    print(f"{'=' * 70}\n")
    print(f"  {'Rank':<5} {'Worst':<7} {'Violators':<10} {'File'}")
    print(f"  {'-' * 5} {'-' * 6} {'-' * 10} {'-' * 50}")


def _format_results_table(top: list[tuple[str, int, int, list[_Block]]]) -> None:
    for rank, (rel, worst_cc, count, dirty) in enumerate(top, 1):
        print(f"  {rank:<5} {worst_cc:<7} {count:<10} {rel}")
        for b in sorted(dirty, key=lambda x: x.complexity, reverse=True):
            print(f"        CC {b.complexity}  {b.name} (line {b.lineno})")


def _format_results_footer(
    py_count: int, target_dir: str, min_cc: int, match_count: int, total_violations: int
) -> None:
    print(f"\n{'=' * 70}")
    print(f"  Scanned {py_count} Python files in {target_dir}/, {match_count} have CC >= {min_cc}")
    print(f"  Total violations: {total_violations}")
    print(f"{'=' * 70}\n")


def _format_and_print_results(
    results: list[tuple[str, int, int, list[_Block]]],
    target_dir: str,
    min_cc: int,
    limit: int,
    py_count: int,
) -> None:
    results.sort(key=lambda x: x[1], reverse=True)
    top = results[:limit]
    _format_results_header(target_dir, min_cc, len(top))
    _format_results_table(top)
    total_violations = sum(len(r[3]) for r in results)
    _format_results_footer(py_count, target_dir, min_cc, len(results), total_violations)


def _build_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find files with functions exceeding CC > 5 using radon, "
        "scoped to src/, aligned with kill_tries.py."
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of top files to show (default: 10)"
    )
    parser.add_argument(
        "--min-cc", type=int, default=6, help="Minimum per-function CC threshold (default: 6 = >5)"
    )
    parser.add_argument(
        "--target-dir", type=str, default="src", help="Directory to scan (default: src)"
    )
    return parser.parse_args()


def main() -> None:
    args = _build_parser()
    root = Path(__file__).resolve().parents[2]
    target = root / args.target_dir
    if not target.exists():
        print(f"Error: target directory '{target}' does not exist.")
        sys.exit(1)
    py_files = get_all_python_files(target)
    results = _scan_files_for_cc(py_files, root, args.min_cc)
    _format_and_print_results(results, args.target_dir, args.min_cc, args.limit, len(py_files))


if __name__ == "__main__":
    main()
