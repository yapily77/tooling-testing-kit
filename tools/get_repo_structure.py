import argparse
import json
import sys
from pathlib import Path

from _codebase_common import EXCLUDE_DIRS, PROJECT_ROOT, fail, ok

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _sorted_entries(path: Path) -> list[Path]:
    """Return directory entries sorted with dirs first, then alphabetically."""
    try:
        return sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return []


def _filtered_entries(path: Path) -> list[Path]:
    """Filter out excluded directories from entry list."""
    return [e for e in _sorted_entries(path) if e.name not in EXCLUDE_DIRS]


def _is_last_entry(index: int, count: int) -> bool:
    """Check if this is the last entry in the list for connector rendering."""
    return index == count - 1


def _connector_for_index(index: int, count: int) -> str:
    """Return the tree connector string for the given index."""
    return "└── " if _is_last_entry(index, count) else "├── "


def _prefix_for_index(index: int, count: int, parent_prefix: str) -> str:
    """Return the prefix extension for child directories."""
    extension = "    " if _is_last_entry(index, count) else "│   "
    return parent_prefix + extension


def _render_entry(entry: Path, index: int, count: int, prefix: str, depth: int, max_depth: int, lines: list[str]) -> None:
    """Render a single tree entry and recurse into directories."""
    connector = _connector_for_index(index, count)
    suffix = "/" if entry.is_dir() else ""
    lines.append(f"{prefix}{connector}{entry.name}{suffix}")
    if entry.is_dir() and depth < max_depth:
        child_prefix = _prefix_for_index(index, count, prefix)
        _render_tree(entry, child_prefix, depth + 1, max_depth, lines)


def _render_tree(path: Path, prefix: str, depth: int, max_depth: int, lines: list[str]) -> None:
    """Recursively render tree entries into lines list."""
    if depth > max_depth:
        return
    entries = _filtered_entries(path)
    count = len(entries)
    for i, entry in enumerate(entries):
        _render_entry(entry, i, count, prefix, depth, max_depth, lines)


def _build_tree(max_depth: int) -> str:
    """Build an ASCII tree string of the project structure."""
    lines: list[str] = [f"{PROJECT_ROOT.name}/"]
    _render_tree(PROJECT_ROOT, "", 1, max_depth, lines)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Return an ASCII tree of the project structure.")
    parser.add_argument("--max-depth", type=int, default=4, help="How many directory levels to show.")
    args = parser.parse_args()

    try:
        tree_str = _build_tree(args.max_depth)
        print(json.dumps(ok(
            f"Project structure at {PROJECT_ROOT} (depth={args.max_depth})",
            {"structure": tree_str},
        ), indent=2, ensure_ascii=False))
    except OSError as e:
        print(json.dumps(fail(f"Failed to get repo structure: {e}"), indent=2))


if __name__ == "__main__":
    main()
