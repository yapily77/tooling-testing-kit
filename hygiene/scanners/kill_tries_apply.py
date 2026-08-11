#!/usr/bin/env python3
"""
Kill-Tries Apply Script: Applies approved refactorings from checkpoint to src/.

Reads kit-hygiene/reports/kill_tries_checkpoint.jsonl and applies
APPROVED refactorings atomically (per-function with ruff validation).
"""

import ast
import json
import logging
import os
import tempfile
from collections import defaultdict
from pathlib import Path

from _bootstrap import pkg_root
from virtual_ast_buffer import (
    VirtualASTBuffer,
    ensure_pydantic_imports,
    verify_class_structure_intact,
)

CHECKPOINT_FILE = pkg_root / "reports" / "kill_tries_checkpoint.jsonl"
src_DIR = pkg_root.parent / "src"
REPORT_FILE = pkg_root / "reports" / "kill_tries.json"

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
logger = logging.getLogger("KillTriesApply")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.propagate = False


# --------------------------------------------------------------------
# AST utilities
# --------------------------------------------------------------------

def _safe_parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _is_func_node(node: ast.stmt) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def _is_import_node(node: ast.stmt) -> bool:
    return isinstance(node, ast.Import) or (
        isinstance(node, ast.ImportFrom) and node.module
    )


def _collect_module_imports(tree: ast.Module) -> set[str]:
    module_imports: set[str] = set()
    for node in tree.body:
        if _is_import_node(node):
            for alias in node.names:
                module_imports.add(alias.asname or alias.name)
    return module_imports


# --------------------------------------------------------------------
# Top-level deduplication
# --------------------------------------------------------------------

def _is_duplicate_func(node: ast.stmt, seen_names: dict[str, int]) -> bool:
    return _is_func_node(node) and node.name in seen_names


def _filter_duplicate_indices(tree: ast.Module) -> tuple[list[int], dict[str, int]]:
    seen_names: dict[str, int] = {}
    indices_to_remove: list[int] = []
    for i, node in enumerate(tree.body):
        if _is_duplicate_func(node, seen_names):
            indices_to_remove.append(i)
        else:
            seen_names[node.name] = i
    return indices_to_remove, seen_names


def _deduplicate_top_level(source: str) -> str:
    tree = _safe_parse(source)
    if tree is None:
        return source
    indices_to_remove, _ = _filter_duplicate_indices(tree)
    if not indices_to_remove:
        return source
    tree.body = [node for i, node in enumerate(tree.body) if i not in indices_to_remove]
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


# --------------------------------------------------------------------
# Global statement / import cleanup
# --------------------------------------------------------------------

def _filter_global_names(stmt: ast.Global, module_imports: set[str]) -> tuple[list[str], list[str]]:
    to_remove = [name for name in stmt.names if name in module_imports]
    remaining = [name for name in stmt.names if name not in to_remove]
    return to_remove, remaining


def _process_global_stmt(
    stmt: ast.Global, module_imports: set[str]
) -> tuple[list[str] | None, list[str] | None]:
    to_remove, remaining = _filter_global_names(stmt, module_imports)
    if not to_remove:
        return None, None
    return to_remove, remaining


def _import_names_set(stmt: ast.Import) -> set[str]:
    return {a.asname or a.name for a in stmt.names}


def _filter_remaining_aliases(stmt: ast.Import, removed_set: set[str]) -> list[ast.alias] | None:
    remaining = [a for a in stmt.names if (a.asname or a.name) not in removed_set]
    return remaining if remaining else None


def _prune_import_names(stmt: ast.Import, removed_set: set[str]) -> list[ast.alias] | None:
    import_names = _import_names_set(stmt)
    if import_names == removed_set:
        return None
    if import_names.issubset(removed_set):
        return _filter_remaining_aliases(stmt, removed_set)
    return stmt.names


def _process_next_import(
    next_stmt: ast.Import, to_remove_names: list[str]
) -> tuple[bool, list[ast.alias] | None]:
    removed_set = set(to_remove_names)
    pruned = _prune_import_names(next_stmt, removed_set)
    if pruned is None:
        return False, None
    if pruned is next_stmt.names:
        return True, None
    return True, pruned


def _try_remove_next_import(
    next_stmt: ast.Import, to_remove: list[str], skip_state: list[bool]
) -> list[ast.stmt]:
    keep_next, new_names = _process_next_import(next_stmt, to_remove)
    if not keep_next and new_names is None:
        skip_state[0] = True
        return []
    if not keep_next:
        return [next_stmt]
    if new_names is not None:
        next_stmt.names = new_names
    skip_state[0] = True
    return [next_stmt]


def _is_global_import_removal_needed(stmt: ast.Global, module_imports: set[str]) -> tuple[list[str] | None, list[str] | None]:
    to_remove, remaining = _process_global_stmt(stmt, module_imports)
    if to_remove is None or remaining:
        return None, None
    return to_remove, remaining


def _process_global_import_removal(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    stmt: ast.Global,
    to_remove: list[str],
    skip_state: list[bool],
) -> list[ast.stmt]:
    if not _has_following_import(node, stmt):
        return [stmt]
    next_stmt = _get_next_stmt(node, stmt)
    if not isinstance(next_stmt, ast.Import):
        return [stmt]
    return _try_remove_next_import(next_stmt, to_remove, skip_state)


def _process_func_body_node(
    stmt: ast.stmt,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    module_imports: set[str],
    skip_state: list[bool],
) -> list[ast.stmt]:
    if not isinstance(stmt, ast.Global):
        return [stmt]
    to_remove, _ = _is_global_import_removal_needed(stmt, module_imports)
    if to_remove is None:
        return [stmt]
    return _process_global_import_removal(node, stmt, to_remove, skip_state)


def _has_following_import(node: ast.FunctionDef | ast.AsyncFunctionDef, stmt: ast.Global) -> bool:
    body = node.body
    idx = body.index(stmt)
    return idx + 1 < len(body)


def _get_next_stmt(node: ast.FunctionDef | ast.AsyncFunctionDef, stmt: ast.Global) -> ast.stmt:
    body = node.body
    idx = body.index(stmt)
    return body[idx + 1]


def _process_func_body_stmts(
    node: ast.FunctionDef | ast.AsyncFunctionDef, module_imports: set[str]
) -> None:
    skip_state = [False]
    new_body: list[ast.stmt] = []
    for stmt in node.body:
        if skip_state[0]:
            skip_state[0] = False
            continue
        new_body.extend(
            _process_func_body_node(stmt, node, module_imports, skip_state)
        )
    node.body = new_body


def _cleanup_local_imports(source: str) -> str:
    tree = _safe_parse(source)
    if tree is None:
        return source
    module_imports = _collect_module_imports(tree)
    if not module_imports:
        return source
    for node in ast.walk(tree):
        if _is_func_node(node):
            _process_func_body_stmts(node, module_imports)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def _clean_hallucinated_code(source: str) -> str:
    source = _deduplicate_top_level(source)
    source = _cleanup_local_imports(source)
    return source


# --------------------------------------------------------------------
# Checkpoint persistence
# --------------------------------------------------------------------

def save_checkpoint_item(item: dict):
    """Append single result item to CHECKPOINT_FILE."""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(item) + "\n")


def _parse_checkpoint_jsonl() -> dict[str, dict]:
    return _load_jsonl_entries(CHECKPOINT_FILE)


def _merge_report_approved(existing: dict[str, dict]) -> dict[str, dict]:
    if not REPORT_FILE.exists():
        return existing
    with open(REPORT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    for item in data.get("approved", []):
        key = f"{item['file_path']}:{item['function_name']}"
        item["status"] = "APPROVED"
        if key not in existing:
            existing[key] = item
    logger.info(f"Merged total {len(existing)} entries from report JSON.")
    return existing


def _load_jsonl_entries(path: Path) -> dict[str, dict]:
    completed: dict[str, dict] = {}
    if not path.exists():
        return completed
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            item = json.loads(line)
            key = f"{item['file_path']}:{item['function_name']}"
            completed[key] = item
    logger.info(f"Loaded {len(completed)} entries from checkpoint JSONL.")
    return completed


def load_checkpoint() -> dict[str, dict]:
    completed = _parse_checkpoint_jsonl()
    return _merge_report_approved(completed)


# --------------------------------------------------------------------
# Test / lint utilities
# --------------------------------------------------------------------

def test_file_with_ruff(file_path: Path) -> tuple[bool, str]:
    import subprocess
    try:
        res = subprocess.run(
            ["uv", "run", "ruff", "check", "--select", "F821,E9,F63,F7", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        return (res.returncode == 0, res.stdout + res.stderr)
    except (OSError, subprocess.SubprocessError) as e:
        return (False, str(e))


def _name_matches(stem: str, p_stem: str) -> bool:
    return stem == p_stem or stem in p_stem or p_stem in stem


def _search_test_dir(
    test_dir: Path, stem: str, path_obj: Path
) -> str | None:
    for p in test_dir.rglob("*.py"):
        p_stem = p.stem.lower().replace("test_", "")
        if _name_matches(stem, p_stem):
            return str(p.relative_to(pkg_root))
    return None


def find_relevant_test_file(rel_path: str) -> str | None:
    path_obj = Path(rel_path)
    stem = path_obj.stem.lower()
    test_dir = pkg_root / "TEST" / "unit"
    if not test_dir.exists():
        return None
    return _search_test_dir(test_dir, stem, path_obj)


def _run_pytest(test_target: str) -> bool:
    import subprocess
    try:
        res = subprocess.run(
            ["uv", "run", "pytest", test_target],
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def test_suite_with_pytest(rel_path: str | None = None) -> bool:
    """Run unit test suite for relevant test file if it exists."""
    if not rel_path:
        test_target = "TEST/unit/"
    else:
        rel_test = find_relevant_test_file(rel_path)
        if not rel_test:
            logger.info(f"   ℹ️ No relevant unit test file found for {rel_path} in TEST/unit/. Skipping pytest gate.")
            return True
        test_target = rel_test

    return _run_pytest(test_target)


# --------------------------------------------------------------------
# File processing
# --------------------------------------------------------------------

def _is_engine_path(rel_path: str) -> bool:
    return rel_path.startswith("src/engine/") or "src/engine/" in rel_path


def _group_items_by_file(approved_items: list[dict]) -> dict[str, list[dict]]:
    by_file: dict[str, list[dict]] = defaultdict(list)
    for item in approved_items:
        by_file[item["file_path"]].append(item)
    return by_file


def _find_func_node(tree: ast.Module, fname: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if _is_func_node(node) and node.name == fname:
            return node
    return None


def _build_helper_code(helpers: list[str]) -> str:
    if not helpers:
        return ""
    return "\n\n" + "\n\n".join(h.rstrip() for h in helpers)


def _build_ref_code(ref_code: str, helpers: list[str]) -> str:
    return ref_code + _build_helper_code(helpers)


def _record_failure(item: dict, msg: str):
    fail_item = dict(item)
    fail_item["status"] = "FAILED_RUNTIME"
    fail_item["verification_msg"] = msg
    save_checkpoint_item(fail_item)


def _replace_and_validate(
    lines: list[str], rel_path: str, fname: str, ref_code: str, helpers: list[str]
) -> tuple[bool, str, list[str], list[str], str]:
    ref_full = _build_ref_code(ref_code, helpers)
    try:
        buf = VirtualASTBuffer("\n".join(lines) + "\n", str(rel_path))
        test_source = buf.replace_function(fname, ref_code, helpers)
        test_source = ensure_pydantic_imports(test_source, ref_full)
        ast.parse(test_source)
    except Exception as e:
        return False, "", [], [], f"AST replace/parse failed for {fname}: {e}"
    _tmp_fd, tmp_path = tempfile.mkstemp(suffix=".py")
    try:
        with open(tmp_path, "w", encoding="utf-8") as _tf:
            _tf.write(test_source)
        passed, ruff_out = test_file_with_ruff(Path(tmp_path))
        if passed:
            return True, test_source, helpers, [], ""
        return False, "", [], [], f"Ruff failed for {fname}: {ruff_out.strip()}"
    finally:
        os.unlink(tmp_path)


def _apply_single_item(
    item: dict, rel_path: str, lines: list[str], file_state: dict
) -> bool:
    fname = item["function_name"]
    ref_code = item["refactored_code"].rstrip()
    helpers = item.get("helper_functions", [])
    current_source = "\n".join(lines)
    tree = _safe_parse(current_source)
    if tree is None:
        _record_failure(item, f"Cannot parse current state of {rel_path}")
        return False
    target_node = _find_func_node(tree, fname)
    if target_node is None:
        logger.warning(f"Function {fname} not found in current AST of {rel_path}")
        return False
    lines_backup = list(lines)
    ok, test_source, used_helpers, _, err = _replace_and_validate(
        lines, rel_path, fname, ref_code, helpers
    )
    if not ok:
        file_state["lines"] = lines_backup
        _record_failure(item, err)
        return False
    file_state["lines"] = test_source.splitlines()
    file_state["ref_codes"].append(ref_code)
    if helpers:
        file_state["helpers"].extend(helpers)
    file_state["applied_targets"] += 1
    return True


def _write_and_test(
    file_path: Path, new_source: str, rel_path: str,
    applied_targets: int, skip_pytest: bool, items: list[dict],
) -> bool:
    file_path.write_text(new_source, encoding="utf-8")
    if skip_pytest:
        logger.info(f"✅ Successfully wrote {applied_targets} refactored function(s) to {rel_path} (Pytest gate skipped via --skip-pytest).")
        return True
    logger.info(f"⏳ Running Pytest integration checks for {rel_path}...")
    if not test_suite_with_pytest(rel_path):
        logger.warning(f"⚠️ Pytest integration check failed after applying {rel_path}. Reverting file changes.")
        return False
    logger.info(f"✅ Successfully wrote {applied_targets} refactored function(s) to {rel_path} and passed Pytest gate.")
    return True


def _revert_and_log(file_path: Path, source: str, rel_path: str, msg: str):
    file_path.write_text(source, encoding="utf-8")
    logger.error(f"❌ {msg} for {rel_path}. Reverting file changes.")


def _record_pytest_failures(items: list[dict], rel_path: str):
    msg = f"Pytest integration check failed for {rel_path} after applying helper extractions."
    for item in items:
        _record_failure(item, msg)


def _commit_file_changes(
    file_path: Path, rel_path: str, source: str, lines: list[str],
    applied_targets: int, skip_pytest: bool, items: list[dict],
) -> int:
    new_source = "\n".join(lines) + "\n"
    new_source = _clean_hallucinated_code(new_source)
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        _revert_and_log(file_path, source, rel_path, f"AST verification failed: {e}")
        return 0
    if not verify_class_structure_intact(source, new_source):
        logger.warning(f"⚠️ Class structure verification failed for {rel_path}. Reverting file.")
        file_path.write_text(source, encoding="utf-8")
        return 0
    if _write_and_test(file_path, new_source, rel_path, applied_targets, skip_pytest, items):
        return applied_targets
    file_path.write_text(source, encoding="utf-8")
    _record_pytest_failures(items, rel_path)
    return 0


def _is_target_present(tree: ast.Module, fname: str) -> bool:
    return _find_func_node(tree, fname) is not None


def _init_file_state(source: str) -> dict:
    return {"lines": source.splitlines(), "ref_codes": [], "helpers": [], "applied_targets": 0}


def _apply_single_item_to_state(
    item: dict, rel_path: str, file_state: dict, tree: ast.Module
) -> bool:
    if not _is_target_present(tree, item["function_name"]):
        return False
    before_lines = list(file_state["lines"])
    result = _apply_single_item(item, rel_path, file_state["lines"], file_state)
    if not result:
        file_state["lines"] = before_lines
    return result


def _apply_file_items_loop(
    items: list[dict], rel_path: str, file_state: dict, tree: ast.Module
) -> bool:
    file_modified = False
    for item in items:
        if _apply_single_item_to_state(item, rel_path, file_state, tree):
            file_modified = True
    return file_modified


def _process_file_items(
    rel_path: str, items: list[dict], skip_pytest: bool
) -> int:
    file_path = pkg_root / rel_path
    if not file_path.exists():
        logger.warning(f"File not found: {rel_path}")
        return 0
    source = file_path.read_text(encoding="utf-8")
    tree = _safe_parse(source)
    if tree is None:
        logger.error(f"Cannot parse {rel_path}")
        raise SyntaxError(f"Cannot parse {rel_path}")
    file_state = _init_file_state(source)
    if _apply_file_items_loop(items, rel_path, file_state, tree):
        return _commit_file_changes(
            file_path, rel_path, source, file_state["lines"],
            file_state["applied_targets"], skip_pytest, items,
        )
    return 0


def apply_checkpoint_to_files(
    approved_items: list[dict], allow_engine: bool = False, skip_pytest: bool = False
) -> int:
    """Apply a specific list of APPROVED refactorings to source files in src/."""
    if not approved_items:
        return 0
    by_file = _group_items_by_file(approved_items)
    applied_count = 0
    for rel_path, items in by_file.items():
        if not allow_engine and _is_engine_path(rel_path):
            logger.info(f"🛡️ Engine read-only policy: Skipping apply to {rel_path} (use --allow-engine to override)")
            continue
        applied_count += _process_file_items(rel_path, items, skip_pytest)
    return applied_count


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------

def _build_arg_parser():
    import argparse
    parser = argparse.ArgumentParser(
        description="Apply approved kill-tries refactorings to src/ with per-function ruff validation."
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Filter for a specific file path (e.g. src/engine/coordinator.py)",
    )
    parser.add_argument(
        "--allow-engine",
        action="store_true",
        help="Allow applying approved refactorings to src/engine/ files",
    )
    parser.add_argument(
        "--skip-pytest",
        "--no-pytest",
        action="store_true",
        dest="skip_pytest",
        help="Skip Pytest integration check (useful when full suite has pre-existing errors)",
    )
    return parser


def _filter_by_path(all_approved: list[dict], filter_rel_path: str) -> list[dict]:
    filtered = [v for v in all_approved if v.get("file_path") == filter_rel_path]
    if not filtered:
        logger.info(f"No APPROVED refactorings found for filter: {filter_rel_path}")
    return filtered


def _filter_approved(checkpoint: dict[str, dict], filter_rel_path: str | None) -> list[dict]:
    all_approved = [v for v in checkpoint.values() if v.get("status") == "APPROVED"]
    if not all_approved:
        logger.info("No APPROVED refactorings found in checkpoint.")
        return []
    if filter_rel_path:
        return _filter_by_path(all_approved, filter_rel_path)
    return all_approved


def main():
    parser = _build_arg_parser()
    args = parser.parse_args()
    checkpoint = load_checkpoint()
    display = _filter_approved(checkpoint, args.file)
    if not display:
        return
    logger.info(f"Applying {len(display)} approved refactorings to src/...")
    applied_count = apply_checkpoint_to_files(
        display, allow_engine=args.allow_engine, skip_pytest=args.skip_pytest
    )
    logger.info(f"Done. Applied {applied_count} refactoring(s).")


if __name__ == "__main__":
    main()
