#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

from control import REPO_ROOT, ControlSheet
from pydantic_ai import Agent


def estimate_tokens(text: str) -> int:
    """Approximate token calculation for Gemma 4 SentencePiece model."""
    return int(len(text) / 3.8)


def _find_match_lines(lines: list[str], regex) -> list[int]:
    """Return 1-indexed line numbers where regex matches."""
    return [i + 1 for i, line in enumerate(lines) if regex.search(line)]


def _build_context_block(lines: list[str], match_line: int, visited: set[int]) -> str:
    """Build a context block around a single match line."""
    start = max(0, match_line - 5)
    end = min(len(lines), match_line + 10)
    block = []
    for idx in range(start, end):
        if idx in visited:
            continue
        visited.add(idx)
        prefix = ">>> " if idx == match_line - 1 else "    "
        block.append(f"{idx + 1}:{prefix}{lines[idx]}")
    return "\n".join(block)


def extract_pattern_context(lines: list[str], pattern: str) -> str:
    """Find all matching lines and extract surrounding context windows."""
    regex = re.compile(pattern, re.IGNORECASE)
    match_lines = _find_match_lines(lines, regex)
    if not match_lines:
        return f"No matches found for pattern: {pattern}"

    visited = set()
    extracted_blocks = []
    for match_line in match_lines:
        block = _build_context_block(lines, match_line, visited)
        if block:
            extracted_blocks.append(block)

    return "\n\n--- Context Match ---\n\n".join(extracted_blocks)


def _parse_line_range(lines_arg: str, total_lines: int) -> tuple[int, int]:
    """Parse --lines argument into (start, end) 1-indexed line range."""
    match = re.match(r"^(\d+)-(\d+)$", lines_arg.strip())
    if match:
        return int(match.group(1)), int(match.group(2))
    try:
        return 1, int(lines_arg.strip())
    except ValueError:
        raise ValueError(f"Invalid lines format: {lines_arg}. Use 'start-end' or a single integer.")


def _resolve_file_path(filename: str) -> Path:
    """Resolve filename to an absolute path within REPO_ROOT."""
    file_path = Path(filename)
    if not file_path.is_absolute():
        file_path = (REPO_ROOT / file_path).resolve()
    if not file_path.exists():
        print(f"Error: File not found at {file_path}")
        sys.exit(1)
    if not file_path.is_relative_to(REPO_ROOT):
        print(f"Error: Path escape detected: {file_path} (outside {REPO_ROOT})")
        sys.exit(1)
    return file_path


def _read_file_lines(file_path: Path) -> list[str]:
    """Read file contents and return as list of lines."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    return content.splitlines()


def _get_code_segment(args, lines: list[str]) -> tuple[str, str]:
    """Extract code segment based on CLI args and return (segment, mode description)."""
    if args.lines:
        start, end = _parse_line_range(args.lines, len(lines))
        code_segment = _extract_lines_range(lines, start, end)
        mode_desc = f"lines {start}-{end}"
    elif args.pattern:
        code_segment = extract_pattern_context(lines, args.pattern)
        mode_desc = f"grep pattern '{args.pattern}'"
    else:
        code_segment = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))
        mode_desc = "full file"
    return code_segment, mode_desc


def _extract_lines_range(lines: list[str], start: int, end: int) -> str:
    """Extract specified line range (1-indexed)."""
    s = max(0, start - 1)
    e = min(len(lines), end)
    extracted = [f"{idx + 1}: {lines[idx]}" for idx in range(s, e)]
    return "\n".join(extracted)


def _truncate_to_token_limit(code_segment: str, tokens: int) -> str:
    """Truncate code segment to fit within 12K token limit."""
    if tokens <= 12000:
        return code_segment
    print(f"⚠️ Warning: Context segment is too large ({tokens} est. tokens). Truncating context to fit 12K limits.")
    return code_segment[:int(12000 * 3.8)] + "\n... [Context truncated due to 12K limit] ..."


def _build_prompt(args, file_path: Path, code_segment: str, mode_desc: str) -> str:
    """Build the LLM prompt from the code segment."""
    prompt = f"File: {args.filename} (mode: {mode_desc})\n"
    if args.query:
        prompt += f"Query/Instruction: {args.query}\n"
    prompt += f"\n```python\n{code_segment}\n```"
    return prompt


def _run_investigation(args, code_segment: str) -> None:
    """Run the codebase model investigation and print results."""
    model = ControlSheet.codebase_model
    investigate_agent = Agent(
        model,
        system_prompt=(
            "You are a surgical codebase investigation tool. Your task is to analyze the provided code context "
            "and provide exact, copy-pasteable solutions. DO NOT output conversational filler.\n"
            "Structure your output cleanly in Markdown:\n"
            "1. **Analysis**: Extremely concise summary (max 3 bullet points).\n"
            "2. **Proposed Solution**: Exact code diff or drop-in code block replacement."
        ),
    )
    prompt = _build_prompt(args, Path(args.filename), code_segment, args.mode_desc)
    print(f"🔍 Investigating {Path(args.filename).name} ({args.mode_desc}). Calling codebase model...")
    sys.stdout.flush()
    try:
        res = investigate_agent.run_sync(prompt)
        print("\n" + "=" * 80)
        print(res.output)
        print("=" * 80)
    except (OSError, RuntimeError, ValueError, TypeError) as e:
        print(f"\nFailed to analyze with codebase model: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Investigate file code/patterns using Gemma 4 model.")
    parser.add_argument("--filename", required=True, help="Path to the file to investigate.")
    parser.add_argument("--query", required=True, help="Specific question or instruction for the investigation.")
    parser.add_argument("--lines", help="Line range to inspect, e.g., '10-100' or single number '50' (1 to 50).")
    parser.add_argument("--pattern", help="Regex pattern to grep for context extraction.")

    args = parser.parse_args()

    file_path = _resolve_file_path(args.filename)
    lines = _read_file_lines(file_path)
    code_segment, mode_desc = _get_code_segment(args, lines)
    args.mode_desc = mode_desc
    tokens = estimate_tokens(code_segment)
    code_segment = _truncate_to_token_limit(code_segment, tokens)
    _run_investigation(args, code_segment)


if __name__ == "__main__":
    main()
