#!/usr/bin/env python3
"""
Codebase Hygiene Cleanup Automator (AST-First)
==============================================
Runs purely locally (0 tokens) to:
1. Auto-sync Environment Drift: Parses all os.getenv/os.environ usage in src/
   and appends missing keys to .env.example.
2. Auto-strip Confirmed Dead Code: Reads dead_code_audit.json and surgically
   removes functions/classes marked as 'CONFIRMED_DEAD' using indentation-based block parsing.

Usage:
    uv run python kit-hygiene/cleanup.py
"""

import ast
import json
import re
import sys
from pathlib import Path

# Workspace root
ROOT_DIR = Path(__file__).resolve().parents[1]
src_DIR = ROOT_DIR / "src"
ENV_EXAMPLE = ROOT_DIR / ".env.example"
DEAD_CODE_JSON = ROOT_DIR / "kit-hygiene" / "reports" / "dead_code_audit.json"


# =====================================================================
# PART 1: ENVIRONMENT DRIFT AUTO-SYNC
# =====================================================================

def _scan_env_vars_in_content(content: str) -> set[str]:
    patterns = [
        re.compile(r"os\.getenv\(\s*['\"]([A-Z0-9_]+)['\"]"),
        re.compile(r"os\.environ\[\s*['\"]([A-Z0-9_]+)['\"]"),
        re.compile(r"os\.environ\.get\(\s*['\"]([A-Z0-9_]+)['\"]")
    ]
    env_vars = set()
    for p in patterns:
        for m in p.finditer(content):
            env_vars.add(m.group(1))
    return env_vars


def _scan_directory_for_env_vars(src_dir: Path) -> set[str]:
    env_vars = set()
    for py_file in src_dir.glob("**/*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            env_vars.update(_scan_env_vars_in_content(content))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
            print(f"  Warning reading {py_file}: {e}")
    return env_vars


def _parse_existing_env_vars(example_content: str) -> set[str]:
    existing_vars = set()
    pattern = re.compile(r"^(?:#\s*)?([A-Z0-9_]+)\s*=")
    for line in example_content.splitlines():
        line = line.strip()
        if line:
            m = pattern.match(line)
            if m:
                existing_vars.add(m.group(1))
    return existing_vars


def _append_missing_env_vars(env_example: Path, missing_vars: list[str]) -> None:
    if not missing_vars:
        print("  ✅ .env.example is fully up-to-date. No environment drift detected.")
        return
    print(f"  Appending {len(missing_vars)} missing variables to .env.example...")
    with open(env_example, "a", encoding="utf-8") as f:
        f.write("\n# ── AUTO-SYNCED MISSING VARIABLES ───────────────────────────\n")
        f.writelines(f"# {var}=\n" for var in missing_vars)
    print("  .env.example updated successfully.")


def sync_environment_drift():
    print("🔍 Scanning src/ for environment variable usage...")
    env_vars = _scan_directory_for_env_vars(src_DIR)

    if not env_vars:
        print("  No environment variables found in src/.")
        return

    print(f"  Found {len(env_vars)} environment variables in use.")

    if not ENV_EXAMPLE.exists():
        print(f"  Creating missing {ENV_EXAMPLE.name}")
        ENV_EXAMPLE.write_text("# Environment Template\n", encoding="utf-8")

    example_content = ENV_EXAMPLE.read_text(encoding="utf-8")
    existing_vars = _parse_existing_env_vars(example_content)

    missing_vars = sorted(env_vars - existing_vars)
    _append_missing_env_vars(ENV_EXAMPLE, missing_vars)


# =====================================================================
# PART 2: SURGICAL DEAD CODE STRIPPER
# =====================================================================
class LogTee:
    """Tee all prints to cleanup.log and stdout."""
    def __init__(self, log_path: Path):
        self.terminal = sys.stdout
        self.log_path = log_path
        self.log = open(log_path, "a", encoding="utf-8")  # noqa: SIM115

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.log.close()
        return False

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()


def find_definition_node(tree: ast.AST, name: str, def_type: str) -> ast.AST | None:
    """Recursively search for the AST node defining the target function/class."""
    target_types = {
        "function": (ast.FunctionDef, ast.AsyncFunctionDef),
        "async_function": (ast.AsyncFunctionDef,),
        "class": (ast.ClassDef,)
    }.get(def_type, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))

    for node in ast.walk(tree):
        if isinstance(node, target_types) and getattr(node, "name", None) == name:
            return node
    return None


def _compute_node_bounds(node: ast.AST, lines: list[str]) -> tuple[int, int]:
    start_line = getattr(node, "lineno", 1)
    dec_list = getattr(node, "decorator_list", [])
    for dec in dec_list:
        dec_lineno = getattr(dec, "lineno", start_line)
        start_line = min(start_line, dec_lineno)

    end_line = getattr(node, "end_lineno", start_line)
    start_idx = start_line - 1
    end_idx = end_line

    while end_idx < len(lines):
        if lines[end_idx].strip():
            break
        end_idx += 1

    return start_idx, end_idx


def _delete_lines_and_verify(content: str, file_path: Path, start_idx: int, end_idx: int, name: str) -> bool:
    lines = content.splitlines()
    new_lines = lines[:start_idx] + lines[end_idx:]
    file_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    try:
        ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"  ❌ Syntax check failed after removing '{name}' from {file_path.name}: {e}")
        print("  Reverting changes...")
        file_path.write_text(content, encoding="utf-8")
        raise


def strip_dead_code_block(file_path: Path, name: str, def_type: str) -> bool:
    """
    Surgically remove a function/class definition block from a file
    using AST end_lineno for perfect accuracy.
    """
    if not file_path.exists():
        print(f"  Warning: File {file_path} not found.")
        return False

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"  Error parsing AST for {file_path.name}: {e}")
        raise

    node = find_definition_node(tree, name, def_type)
    if not node:
        print(f"  Warning: Could not locate AST node for {def_type} '{name}' in {file_path.name}.")
        return False

    lines = content.splitlines()
    start_idx, end_idx = _compute_node_bounds(node, lines)

    print(f"  Removing {def_type} '{name}' from {file_path.name} (Lines {start_idx + 1} to {end_idx})")

    return _delete_lines_and_verify(content, file_path, start_idx, end_idx, name)


def _load_dead_code_audit(dead_code_json: Path) -> list[dict]:
    try:
        data = json.loads(dead_code_json.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"  Error reading {dead_code_json}: {e}")
        raise

    results = data.get("audit_results", [])
    return [r for r in results if r.get("status") == "CONFIRMED_DEAD"]


def _process_dead_items(dead_items: list[dict], root_dir: Path) -> int:
    success_count = 0
    for item in dead_items:
        name = item.get("name")
        file_path_str = item.get("file_path")
        def_type = item.get("type", "function")

        if not name:
            continue
        if not file_path_str:
            continue

        file_path = root_dir / str(file_path_str)
        if strip_dead_code_block(file_path, str(name), str(def_type)):
            success_count += 1

    return success_count


def strip_dead_code():
    print("\n🔍 Checking dead_code_audit.json for CONFIRMED_DEAD candidates...")
    if not DEAD_CODE_JSON.exists():
        print(f"  Error: {DEAD_CODE_JSON} not found. Please run the scanner first.")
        return

    dead_items = _load_dead_code_audit(DEAD_CODE_JSON)
    if not dead_items:
        print("  No 'CONFIRMED_DEAD' code blocks found in the audit report.")
        return

    print(f"  Found {len(dead_items)} dead code blocks to remove.")
    success_count = _process_dead_items(dead_items, ROOT_DIR)

    print(f"\n  Finished. Surgically removed {success_count}/{len(dead_items)} dead code blocks.")


def main():
    log_dir = ROOT_DIR / "kit-hygiene"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "cleanup.log"

    # Enable Tee logging
    with LogTee(log_path) as tee:
        sys.stdout = tee

        print("🧹 Starting Codebase Hygiene Cleanup Pipeline (Phase 1)...")
        print("=" * 60)

        try:
            # 1. Sync environment drift variables
            sync_environment_drift()

            # 2. Surgically strip confirmed dead code
            strip_dead_code()

            print("\n✅ Phase 1 Cleanup Completed.")
        finally:
            sys.stdout = tee.terminal


if __name__ == "__main__":
    main()