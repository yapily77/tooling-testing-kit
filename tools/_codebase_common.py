"""Shared stdlib helpers for the shadow CLI codebase tools.

Replaces the legacy external ``infra/codebase/mcp_codebase.py`` dependency so the
/tools CLI wrappers are fully self-contained within the repo (no libcst, no
out-of-repo imports). Keeps the ``{success, message, data}`` JSON envelope that the
orchestrator harness (admin/orchestrator/infra/tools.py ``_run_tool``) consumes as a
raw stdout string, and that the test suite asserts against.
"""

from __future__ import annotations

import difflib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {"__pycache__", ".git", ".venv", "node_modules", ".agent", ".gemini"}
INCLUDE_EXTENSIONS = {".py", ".md", ".json", ".txt", ".yaml", ".yml", ".toml", ".sql", ".sh"}


def _safe_relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _normalize_content(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _ensure_trailing_newline(text: str) -> str:
    """Ensure text ends with a newline to prevent difflib hunk fusion."""
    if text and not text.endswith("\n"):
        return text + "\n"
    return text


def _bounded_diff(old_text: str, new_text: str, context: int = 15) -> str:
    """Generate a bounded unified diff between old and new text."""
    old_text = _ensure_trailing_newline(old_text)
    new_text = _ensure_trailing_newline(new_text)
    diff = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile="a", tofile="b", n=context, lineterm="\n",
        )
    )
    if not diff:
        return "(no changes detected)"
    return "".join(diff)


def resolve_secure_path(relative_path: str) -> Path:
    """Resolve a path and ensure it stays within PROJECT_ROOT."""
    root = PROJECT_ROOT.resolve()
    if relative_path.startswith(f"{root.name}/"):
        relative_path = relative_path[len(f"{root.name}/") :]
    elif relative_path == root.name:
        relative_path = ""
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"Path escape detected: {relative_path}")
    return target


def ok(message: str, data: dict[str, object]) -> dict[str, object]:
    return {"success": True, "message": message, "data": data}


def fail(message: str) -> dict[str, object]:
    return {"success": False, "message": message}
