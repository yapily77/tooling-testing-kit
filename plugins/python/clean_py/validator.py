from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]


def run_subprocess(
    cmd: Sequence[str],
    cwd: Path,
    display_path: str = "",
) -> tuple[int, str, str]:
    """Run a subprocess and return (exit_code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            check=False,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        msg = "TIMEOUT exceeded 30s"
        return 1, "", f"{display_path}: {msg}" if display_path else msg
    except FileNotFoundError:
        return 1, "", "command not found"


def check_ast_violations(source: str, display_path: str) -> list[str]:
    """Parse AST and check for policy violations (bare except, swallowed exceptions)."""
    tree, parse_error = _try_parse_ast(source, display_path)
    if tree is None:
        return [parse_error]
    return _collect_handler_issues(tree, display_path)


def _try_parse_ast(source: str, display_path: str) -> tuple[ast.AST | None, str]:
    """Parse source string into an AST. Returns (tree, "") on success or (None, error_msg) on failure."""
    try:
        tree = ast.parse(source, filename=display_path)
        return tree, ""
    except SyntaxError as exc:
        lineno = exc.lineno or 0
        offset = exc.offset or 0
        msg = f"{display_path}:line {lineno}:{offset}: syntax error: {exc.msg}"
        return None, msg


def _collect_handler_issues(tree: ast.AST, display_path: str) -> list[str]:
    """Walk the AST and collect all ExceptHandler issues."""
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            issues.extend(_check_except_handler(node, display_path))
    return issues


def _check_except_handler(node: ast.ExceptHandler, display_path: str) -> list[str]:
    """Check a single ExceptHandler node for policy violations."""
    if node.type is None:
        err = f"line {node.lineno}: bare 'except:' is forbidden; catch a specific exception"
        return [f"[AST POLICY] {display_path}: {err}"]
    return _check_swallowed(node, display_path)


def _check_swallowed(node: ast.ExceptHandler, display_path: str) -> list[str]:
    """Check if a broad except handler swallows the exception with pass."""
    if not _is_broad_exception(node) or not node.body:
        return []
    if all(isinstance(stmt, ast.Pass) for stmt in node.body):
        err = f"line {node.lineno}: swallowed broad exception with 'pass' is forbidden"
        return [f"[AST POLICY] {display_path}: {err} (anti-slop policy)"]
    return []


def _is_broad_exception(node: ast.ExceptHandler) -> bool:
    """Check if an except handler catches a broad exception type."""
    if node.type is None:
        return True
    if isinstance(node.type, ast.Name):
        return node.type.id in {"Exception", "BaseException"}
    return False


def parse_ruff_output(stdout: str, display_path: str) -> list[str]:
    """Parse JSON output from ruff check."""
    parsed = _safe_json_loads(stdout)
    if parsed is None:
        return [f"[RUFF LINTER ERRORS] {display_path}: {stdout.strip()}"]

    diagnostics = _extract_ruff_diagnostics(parsed)
    return [_format_ruff_diagnostic(d, display_path) for d in diagnostics]


def _safe_json_loads(stdout: str) -> Any:
    """Safely parse JSON, returning None on failure."""
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_ruff_diagnostics(parsed: Any) -> list[dict[str, Any]]:
    """Extract diagnostics list from ruff JSON output."""
    if isinstance(parsed, list):
        return _filter_dicts(parsed)
    if isinstance(parsed, dict):
        return _extract_diagnostics_from_dict(parsed)
    return []


def _filter_dicts(items: list[Any]) -> list[dict[str, Any]]:
    """Filter a list to only dict items."""
    return [item for item in items if isinstance(item, dict)]


def _extract_diagnostics_from_dict(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract diagnostics from a dict wrapper (ruff v0.5+ format)."""
    diags = parsed.get("diagnostics")
    if isinstance(diags, list):
        return _filter_dicts(diags)
    return []


def _format_ruff_diagnostic(d: dict[str, Any], display_path: str) -> str:
    """Format a single ruff diagnostic into an error string."""
    location = d.get("location", {})
    line = location.get("row", location.get("line", "?"))
    code_val = d.get("code", "ERR")
    message = d.get("message", "")
    return f"{display_path}:{line}: [{code_val}] {message}"


def run_ruff(python_bin: str, file_path: Path, display_path: str) -> list[str]:
    """Run ruff check on a Python file and return errors."""
    cmd = [python_bin, "-m", "ruff", "check", "--output-format", "json", str(file_path)]
    code, stdout, _stderr = run_subprocess(cmd, file_path.parent, display_path)
    if code == 0:
        return []
    return parse_ruff_output(stdout, display_path)


def run_mypy(
    python_bin: str,
    file_path: Path,
    display_path: str,
    target_exists: bool,
    final_target_path: Path | None = None,
) -> list[str]:
    """Run mypy --strict on a Python file and return errors."""
    args = _build_mypy_args(python_bin, file_path, target_exists, final_target_path)
    code, stdout, _stderr = run_subprocess(args, file_path.parent, display_path)
    if code == 0:
        return []
    return _format_mypy_errors(stdout, display_path)


def _build_mypy_args(
    python_bin: str,
    file_path: Path,
    target_exists: bool,
    final_target_path: Path | None,
) -> list[str]:
    """Build the mypy command arguments."""
    args: list[str] = [python_bin, "-m", "mypy", "--strict"]
    if target_exists and final_target_path is not None:
        args.extend(["--shadow-file", str(final_target_path), str(file_path), str(final_target_path)])
    else:
        args.append(str(file_path))
    return args


def _format_mypy_errors(stdout: str, display_path: str) -> list[str]:
    """Format mypy output into error list."""
    stripped = stdout.strip()
    if not stripped:
        return [f"[MYPY TYPE ERRORS] {display_path}: unknown error"]
    return [f"[MYPY TYPE ERRORS]\n{stripped}"]


def parse_radon_output(stdout: str, display_path: str) -> list[str]:
    """Parse JSON output from radon cc and extract complexity violations."""
    parsed = _safe_json_loads(stdout)
    if parsed is None:
        return [f"[RADON ERROR] {display_path}: {stdout.strip()}"]

    issues: list[str | None] = []
    if isinstance(parsed, dict):
        for blocks in parsed.values():
            issues.extend(_check_radon_blocks(blocks, display_path))
    return _filter_none(issues)


def _check_radon_blocks(blocks: object, display_path: str) -> list[str | None]:
    """Check a list of radon complexity blocks for violations."""
    if not isinstance(blocks, list):
        return []
    return [_check_radon_block(block, display_path) for block in blocks if isinstance(block, dict)]


def _check_radon_block(block: dict[str, Any], display_path: str) -> str | None:
    """Check a single radon block for complexity violation. Returns None if OK."""
    complexity = block.get("complexity")
    if not isinstance(complexity, (int, float)):
        return None
    limit = 6
    if complexity < limit:
        return None
    lineno = block.get("lineno", "?")
    block_type = block.get("type", "?")
    name = block.get("name", "?")
    return f"{display_path}: Line {lineno}: {block_type} '{name}' has CC {complexity} (Limit: < {limit})"


def _filter_none(items: Sequence[str | None]) -> list[str]:
    """Filter out None values from a sequence."""
    return [item for item in items if item is not None]


def run_radon(python_bin: str, file_path: Path, display_path: str) -> list[str]:
    """Run radon cc on a Python file and return complexity violations."""
    cmd = [python_bin, "-m", "radon", "cc", "-j", str(file_path)]
    code, stdout, _stderr = run_subprocess(cmd, file_path.parent, display_path)
    if code == 0:
        return parse_radon_output(stdout, display_path)
    issues = parse_radon_output(stdout, display_path)
    if issues:
        return issues
    return [_format_radon_error(stdout, display_path)]


def _format_radon_error(stdout: str, display_path: str) -> str:
    """Format a radon error message."""
    stripped = stdout.strip()
    if not stripped:
        return f"[RADON ERROR] {display_path}: unknown error"
    return f"[RADON ERROR] {display_path}: {stripped}"


def discover_python(workspace_dir: Path) -> str | None:
    """Discover Python binary in .venv directories."""
    venv_dir = workspace_dir / ".venv"
    candidates = [
        venv_dir / "Scripts" / "python.exe",
        venv_dir / "bin" / "python",
        venv_dir / "bin" / "python3",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def read_file_source(file_path: Path, display_path: str) -> str | list[str]:
    """Read source from a file. Returns source string or list of error strings."""
    try:
        return file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"cannot read file {display_path}: {exc}"]


def validate_file(
    file_path: str | Path,
    python_bin: str | None = None,
    workspace_dir: str | Path | None = None,
) -> ValidationResult:
    """Validate a Python file against AST policy, ruff, mypy strict, and radon CC < 6."""
    target = _resolve_target(file_path, workspace_dir).resolve()
    display_path = str(target)

    if not target.is_file():
        return ValidationResult(valid=False, errors=[f"file not found: {display_path}"])

    source = read_file_source(target, display_path)
    if isinstance(source, list):
        return ValidationResult(valid=False, errors=source)

    ast_errors = check_ast_violations(source, display_path)
    if ast_errors:
        return ValidationResult(valid=False, errors=ast_errors)

    resolved_python = python_bin or _resolve_python(target)
    errors: list[str] = []
    errors.extend(run_ruff(resolved_python, target, display_path))
    errors.extend(run_mypy(resolved_python, target, display_path, target_exists=True, final_target_path=target))
    errors.extend(run_radon(resolved_python, target, display_path))
    return ValidationResult(valid=len(errors) == 0, errors=errors)


def _resolve_target(file_path: str | Path, workspace_dir: str | Path | None) -> Path:
    """Resolve the target file path."""
    target = Path(file_path)
    if not target.is_absolute() and workspace_dir:
        target = Path(workspace_dir) / target
    return target


def _resolve_python(target: Path) -> str:
    """Resolve the Python binary to use."""
    discovered = discover_python(target.parent)
    return discovered or sys.executable
