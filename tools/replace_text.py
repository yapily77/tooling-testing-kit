import argparse
import json
import re
import sys

from _codebase_common import (
    _bounded_diff,
    _normalize_content,
    ALLOWED_EXTENSIONS,
    fail,
    ok,
    resolve_secure_path,
)

sys.path.append(str(Path(__file__).resolve().parents[1]))
from pathlib import Path


def _validate_path(args) -> Path:
    """Resolve and validate the target file path."""
    try:
        path = resolve_secure_path(args.relative_path)
    except ValueError as e:
        print(json.dumps(fail(str(e)), indent=2))
        sys.exit(1)
    if not path.exists():
        print(json.dumps(fail(f"File not found: {args.relative_path}"), indent=2))
        sys.exit(1)
    if path.suffix not in ALLOWED_EXTENSIONS:
        print(json.dumps(fail(f"Unsupported file type: {path.suffix}"), indent=2))
        sys.exit(1)
    return path


def _replace_with_regex(text: str, args) -> tuple[str, int]:
    """Replace text using regex pattern."""
    flags = re.IGNORECASE if args.case_insensitive else 0
    return re.subn(args.target_text, args.replacement_text, text, flags=flags)


def _replace_literal(text: str, args) -> tuple[str, int]:
    """Replace literal text, handling case-insensitivity and whitespace variants."""
    target = args.target_text
    if args.ignore_whitespace:
        target = re.sub(r"\s+", r"\\s+", re.escape(target))
        return re.subn(target, args.replacement_text, text)
    if args.case_insensitive:
        return _replace_case_insensitive(text, args)
    return text.replace(target, args.replacement_text), text.count(target)


def _replace_case_insensitive(text: str, args) -> tuple[str, int]:
    """Case-insensitive literal replacement preserving original formatting."""
    target = args.target_text
    low_old = text.lower()
    low_t = target.lower()
    count = low_old.count(low_t)
    if count == 0:
        return text, 0
    out = []
    start = 0
    idx = low_old.find(low_t, start)
    while idx != -1:
        out.append(text[start:idx])
        out.append(args.replacement_text)
        start = idx + len(target)
        idx = low_old.find(low_t, start)
    out.append(text[start:])
    return "".join(out), count


def main():
    parser = argparse.ArgumentParser(
        description="Replace exact text or regex in a repo file."
    )
    parser.add_argument("relative_path", help="Path relative to project root.")
    parser.add_argument("target_text", help="Text (or regex) to find.")
    parser.add_argument("replacement_text", help="Replacement text.")
    parser.add_argument("--is-regex", action="store_true", help="Treat target as regex.")
    parser.add_argument("--case-insensitive", action="store_true")
    parser.add_argument("--ignore-whitespace", action="store_true")
    args = parser.parse_args()

    path = _validate_path(args)

    try:
        old_text = _normalize_content(path.read_text(encoding="utf-8"))
        if args.is_regex:
            new_text, n = _replace_with_regex(old_text, args)
        else:
            new_text, n = _replace_literal(old_text, args)

        if n == 0:
            print(json.dumps(ok(f"No match found in {args.relative_path}", {"changed": False}), indent=2))
            return

        path.write_text(new_text, encoding="utf-8")
        print(json.dumps(ok(
            f"Replaced {n} occurrence(s) in {args.relative_path}",
            {"changed": True, "count": n, "diff": _bounded_diff(old_text, new_text)},
        ), indent=2))
    except (OSError, ValueError, TypeError, re.error) as e:
        print(json.dumps(fail(f"replace_text failed: {e}"), indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
