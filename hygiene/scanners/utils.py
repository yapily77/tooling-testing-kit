import os
import subprocess
import sys
from pathlib import Path


def _is_under_path(path: Path, root: Path) -> bool:
    """Check if *path* is the same as or nested under *root* (both relative or absolute)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False


def _make_root_path(raw_entry: str, factory_root: str | None) -> Path:
    """Resolve a single SCAN_ROOTS entry to a Path."""
    path = Path(raw_entry)
    if path.is_absolute():
        return path
    if factory_root:
        return Path(factory_root) / raw_entry
    return path


def _resolve_scan_roots() -> list[Path]:
    """Resolve SCAN_ROOTS env var into a list of Path objects.

    Each entry is relative to AIB_FACTORY_ROOT or absolute.
    Falls back to ``["src"]`` for backward compatibility when SCAN_ROOTS is unset.
    """
    scan_roots_env = os.environ.get("SCAN_ROOTS")
    if not scan_roots_env:
        return [Path("src")]

    factory_root = os.environ.get("AIB_FACTORY_ROOT")
    roots: list[Path] = []
    for raw_entry in scan_roots_env.split(","):
        raw = raw_entry.strip()
        if raw:
            roots.append(_make_root_path(raw, factory_root))
    return roots


def _is_py_file(rel_path: str) -> bool:
    """True if *rel_path* is a ``.py`` file that is not ``__init__.py``
    and does not live inside ``__pycache__``."""
    p = Path(rel_path)
    return (
        p.suffix == ".py"
        and p.name != "__init__.py"
        and "__pycache__" not in p.parts
    )


def _check_diff_flag() -> bool:
    """Return True if --diff was passed on the command line; remove it from sys.argv."""
    if "--diff" in sys.argv:
        sys.argv.remove("--diff")
        return True
    return False


def _resolve_explicit_path(raw_p: str, target_root: str | None) -> Path:
    """Resolve a single HYGIENE_FILES_TO_SCAN entry, enforcing TARGET_ROOT containment."""
    path = Path(raw_p)
    if not path.is_absolute() and target_root:
        path = Path(target_root) / path
    path = path.resolve()
    if target_root:
        try:
            path.relative_to(Path(target_root).resolve())
        except (ValueError, OSError):
            raise ValueError(
                f"HYGIENE_FILES_TO_SCAN path '{raw_p}' escapes TARGET_ROOT '{target_root}'"
            )
    return path


def _handle_explicit_files() -> list[Path] | None:
    """Process HYGIENE_FILES_TO_SCAN env var. Return paths list or None if unset."""
    if "HYGIENE_FILES_TO_SCAN" not in os.environ:
        return None

    paths_str = os.environ["HYGIENE_FILES_TO_SCAN"]
    if not paths_str:
        return []

    target_root = os.environ.get("TARGET_ROOT")
    resolved_paths: list[Path] = []
    for raw_p in paths_str.split(","):
        cleaned = raw_p.strip()
        if cleaned:
            resolved_paths.append(_resolve_explicit_path(cleaned, target_root))
    return resolved_paths


def _get_git_diff_files() -> set[str]:
    """Collect changed and new files from git."""
    changed_files: set[str] = set()

    res1 = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res1.returncode == 0:
        changed_files.update(res1.stdout.strip().split("\n"))

    res2 = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res2.returncode == 0:
        changed_files.update(res2.stdout.strip().split("\n"))

    return changed_files


def _filter_diff_to_roots(changed_files: set[str], scan_roots: list[Path]) -> list[Path]:
    """Filter git changed files to those under scan_roots and that are Python files."""
    paths: list[Path] = []
    for raw_line in sorted(changed_files):
        path = _resolve_diff_line(raw_line, scan_roots)
        if path is not None:
            paths.append(path)
    return paths


def _resolve_diff_line(raw_line: str, scan_roots: list[Path]) -> Path | None:
    line = raw_line.strip()
    if not line or not _is_py_file(line):
        return None
    path = Path(line)
    if not _is_under_any_root(path, scan_roots):
        return None
    return path if path.is_file() else None


def _is_under_any_root(path: Path, scan_roots: list[Path]) -> bool:
    return any(_is_under_path(path, root) for root in scan_roots)


def _get_diff_files(scan_roots: list[Path]) -> list[Path]:
    """Get git-changed Python files filtered to scan_roots."""
    try:
        changed_files = _get_git_diff_files()
        return _filter_diff_to_roots(changed_files, scan_roots)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"Error getting git diff files: {e}", file=sys.stderr)
        raise


def _git_ls_files_for_root(root: Path) -> list[str]:
    """Run git ls-files for a single root and return raw lines."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", str(root)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().split("\n")


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    """Remove duplicate paths by string key, preserving order."""
    seen: set[str] = set()
    unique: list[Path] = []
    for item in paths:
        key = str(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _get_all_git_files(scan_roots: list[Path]) -> list[Path]:
    """Get all tracked and untracked Python files under scan_roots via git ls-files."""
    all_paths: list[Path] = []
    for root in scan_roots:
        for raw_line in _git_ls_files_for_root(root):
            line = raw_line.strip()
            if line and _is_py_file(line):
                all_paths.append(Path(line))
    return _deduplicate_paths(all_paths)


def _fallback_walk_roots(scan_roots: list[Path]) -> list[Path]:
    """Fallback: recursively walk each root excluding __pycache__ and __init__.py."""
    all_paths: list[Path] = []
    for root in scan_roots:
        if root.is_dir():
            all_paths.extend(_walk_root(root))
    return _deduplicate_paths(all_paths)


def _walk_root(root: Path) -> list[Path]:
    paths: list[Path] = []
    for p in root.rglob("*.py"):
        if p.is_file() and p.name != "__init__.py" and "__pycache__" not in p.parts:
            paths.append(p)
    return paths


def get_src_files() -> list[Path]:
    """Get all Python files under configured scan roots, or override via env.

    Honors:
      - HYGIENE_FILES_TO_SCAN: optional comma list of explicit file paths.
      - SCAN_ROOTS: comma list of roots (relative to AIB_FACTORY_ROOT or absolute).
      - AIB_FACTORY_ROOT: base directory for relative SCAN_ROOTS entries.
      - ``--diff``: git-changed files only, filtered to SCAN_ROOTS.

    When SCAN_ROOTS is unset, falls back to scanning ``src`` (backward compat).
    """
    use_diff = _check_diff_flag()

    explicit_files = _handle_explicit_files()
    if explicit_files is not None:
        return explicit_files

    scan_roots = _resolve_scan_roots()
    return _resolve_scan_mode(use_diff, scan_roots)


def _resolve_scan_mode(use_diff: bool, scan_roots: list[Path]) -> list[Path]:
    if use_diff:
        return _get_diff_files(scan_roots)
    try:
        return [p for p in _get_all_git_files(scan_roots) if p.is_file()]
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"Error getting git files: {e}", file=sys.stderr)
        return _fallback_walk_roots(scan_roots)


def is_binary_file(file_path: Path) -> bool:
    """Check if a file is binary by searching for null bytes."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except OSError:
        return False
