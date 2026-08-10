#!/usr/bin/env python3
"""Example: a clean Python script that passes all quality gates.

Quality gates this script demonstrably satisfies:
  - Cyclomatic complexity (radon CC) < 6 for every function
  - Full type annotations (PEP 604 + built-in generics, mypy --strict clean)
  - No bare/broad except clauses (ruff E722 + F841 compliant)
  - No mutable default arguments
  - All file I/O uses context managers (no unsafe open())
  - No swallowed errors — exceptions are re-raised or logged with context
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence


def read_file_lines(path: Path) -> list[str]:
    """Return all non-empty lines from *path*, stripped of trailing whitespace."""
    with path.open("r", encoding="utf-8") as handle:
        return [line.rstrip() for line in handle if line.strip()]


def filter_comment_lines(lines: list[str]) -> list[str]:
    """Filter out lines that start with ``#``."""
    return [line for line in lines if not line.lstrip().startswith("#")]


def count_words(lines: Sequence[str]) -> dict[str, int]:
    """Return a word-frequency dictionary from the given *lines*."""
    counts: dict[str, int] = {}
    for line in lines:
        for word in line.split():
            counts[word] = counts.get(word, 0) + 1
    return counts


def top_n_words(counts: dict[str, int], n: int) -> list[tuple[str, int]]:
    """Return the *n* most common ``(word, frequency)`` pairs."""
    sorted_items = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
    return sorted_items[:n]


def analyze_text_file(path: str, top_n: int = 10) -> None:
    """Read, analyze, and print a word-frequency summary for *path*."""
    file_path = Path(path)
    if not file_path.is_file():
        print(f"Error: {file_path} is not a regular file.", file=sys.stderr)
        sys.exit(1)

    lines = read_file_lines(file_path)
    code_lines = filter_comment_lines(lines)
    counts = count_words(code_lines)
    top = top_n_words(counts, top_n)

    print(f"Analyzed {len(code_lines)} non-comment lines in {file_path.name}")
    print("Top words:")
    for word, freq in top:
        print(f"  {word}: {freq}")


def main() -> int:
    """Entry point: parse arguments and run the analysis."""
    args = sys.argv[1:]
    if len(args) != 1:
        print(f"Usage: {Path(sys.argv[0]).name} <text-file-path>", file=sys.stderr)
        return 2

    try:
        analyze_text_file(args[0])
    except OSError as exc:
        print(f"File error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
