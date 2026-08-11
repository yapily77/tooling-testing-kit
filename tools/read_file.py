import argparse
import sys

from _codebase_common import _normalize_content, resolve_secure_path

sys.path.append(str(__import__("pathlib").Path(__file__).resolve().parents[1]))


def _build_parser():
    parser = argparse.ArgumentParser(description="Read a specific line range of a file in the repo.")
    parser.add_argument("relative_path", help="Path relative to project root.")
    parser.add_argument("--start-line", type=int, help="First line to read (1-indexed).")
    parser.add_argument("--end-line", type=int, help="Last line to read (inclusive).")
    return parser


def _resolve_path(relative_path):
    try:
        return resolve_secure_path(relative_path)
    except ValueError as e:
        print(f"ERROR: {e}")
        return None


def _read_content(path, relative_path):
    if not path.exists():
        print(f"ERROR: File not found: {relative_path}")
        return None
    try:
        return _normalize_content(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"ERROR: Failed to read {relative_path}: {e}")
        raise


def _apply_range(lines, start_line, end_line):
    total_lines = len(lines)
    s = (start_line - 1) if start_line else 0
    e = end_line if end_line else total_lines
    return lines[s:e], s, e, total_lines


def _print_result(relative_path, paged, s, e, total_lines):
    print(f"=== File read: {relative_path} (lines {s + 1}-{min(e, total_lines)} of {total_lines}) ===")
    print("\n".join(paged))


def main():
    parser = _build_parser()
    args = parser.parse_args()

    path = _resolve_path(args.relative_path)
    if path is None:
        return

    content = _read_content(path, args.relative_path)
    if content is None:
        return

    lines = content.splitlines()
    paged, s, e, total_lines = _apply_range(lines, args.start_line, args.end_line)
    _print_result(args.relative_path, paged, s, e, total_lines)


if __name__ == "__main__":
    main()
