#!/usr/bin/env python3
"""
Kill-Tries Scanner & Refactorer: Flat Control Flow & Anti-Pattern Eliminator.
Scans Python files in src/ for:
1. Priority 1: Try Pyramids / Try-Else-If Anti-Patterns.
2. Priority 2: Deep Nesting (Depth > 3).
3. Priority 3: Cyclomatic Complexity (CC > 5).

Uses AST pre-filtering first, Pydantic AI 2.0 (CONTROL_SHEET.scanner_model) for refactoring,
VirtualASTBuffer for in-memory AST verification, and AST validation before committing code changes.

Emits kit-hygiene/reports/kill_tries.json
"""

import ast
import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logfire
import yaml

# Ensure repo root in sys.path
from _bootstrap import pkg_root
from control import CONTROL_SHEET
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelRetry
from virtual_ast_buffer import VirtualASTBuffer

# Initialize Logfire instrumentation once globally
try:
    logfire.configure(send_to_logfire=False)
    logfire.instrument_pydantic_ai()
except ImportError:
    pass  # logfire is optional observability

CHECKPOINT_FILE = pkg_root / "reports" / "kill_tries_checkpoint.jsonl"
REPORT_FILE = pkg_root / "reports" / "kill_tries.json"
src_DIR = pkg_root.parent / "src"
PROMPT_TEMPLATE_PATH = pkg_root / "scanners" / "kill_tries_prompt.yaml"
PROMPT_RETRY_PATH = pkg_root / "scanners" / "kill_tries_prompt_retry.yaml"
LIST_FILE = pkg_root / "scanners" / "kill_tries_list.txt"

SAFE_MODULES = {"typing", "collections", "enum", "dataclasses", "itertools"}


def get_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%m-%d-%H:%M:%S") + f":{int(now.microsecond / 1000):03d}"


_PROVIDER_PATTERNS: list[tuple[str, str, str | None]] = [
    ("antigravity", "", "antigravity_manager"),
    (":8045", "", "antigravity_manager"),
    ("literouter", "", "literouter"),
    (":7766/v1", "", "literouter"),
    ("openrouter", "", "openrouter"),
]


def _match_provider(base_url: str) -> str | None:
    for needle, _suffix, label in _PROVIDER_PATTERNS:
        if needle in base_url or (base_url.endswith(needle) and needle):
            return label
    return None


def get_model_provider_name(model: Any) -> str:
    base_url = getattr(getattr(model, "provider", None), "base_url", "")
    matched = _match_provider(base_url)
    if matched:
        return matched
    return base_url.split("/")[2] if "/" in base_url else "unknown"


# Configure logging with ANSI colors
class ColoredFormatter(logging.Formatter):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"

    def __init__(self):
        super().__init__()
        self.COLORS: dict[str, str] = {
            "INFO": "\033[94m",
            "WARNING": "\033[93m",
            "ERROR": "\033[91m",
            "CRITICAL": "\033[91m\033[1m",
        }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        msg = record.getMessage()
        if msg.startswith("[") and "]" in msg:
            end_idx = msg.find("]") + 1
            msg = f"{self.BOLD}{self.GREEN}{msg[:end_idx]}{self.RESET} {msg[end_idx:].strip()}"
        return f"{color}[{record.levelname}]{self.RESET} {msg}"


handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter())
logger = logging.getLogger("KillTriesScanner")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.propagate = False


# =====================================================================
# PYDANTIC 2.0 DOMAIN SCHEMAS
# =====================================================================

class FunctionCandidate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    file_path: str
    function_name: str
    line: int
    end_line: int
    cc: int
    max_depth: int
    priority: int
    try_issues: list[tuple[int, str]] = Field(default_factory=list)
    source_code: str
    upstream_callers: str = ""
    module_context: str = ""


class RefactoringVerdict(BaseModel):
    model_config = ConfigDict(strip_whitespace=True, validate_assignment=True)

    function_name: str = Field(..., description="Name of the target function being refactored")
    refactored_code: str = Field(
        ...,
        description="Complete refactored python code starting at column 0 (no leading indentation), using flat control flow",
    )
    helper_functions: list[str] = Field(
        default_factory=list,
        description="Extracted private helper functions starting at column 0 (no leading indentation)",
    )
    explanation: str = Field(..., description="Summary of how anti-patterns and deep nesting were eliminated")

    @field_validator("refactored_code", "helper_functions", mode="before")
    @classmethod
    def strip_markdown_backticks(cls, v: Any) -> Any:
        return _clean_markdown(v)

    @model_validator(mode="after")
    def validate_structural_constraints(self) -> "RefactoringVerdict":
        self._check_unauthorized_imports()
        self._check_no_classes()
        self._check_no_nested_closures()
        self._check_helper_naming_convention()
        return self

    def _check_unauthorized_imports(self) -> None:
        combined = self.refactored_code + "\n" + "\n".join(self.helper_functions)
        unauthorized = [
            line.strip()
            for line in combined.splitlines()
            if _is_unauthorized_import(line.strip())
        ]
        if unauthorized:
            raise ModelRetry(
                f"CRITICAL: Unauthorized imports included: {unauthorized}. "
                f"You may ONLY import from {SAFE_MODULES} or internal `src` modules."
            )


def _is_unauthorized_import(stripped: str) -> bool:
    if not stripped.startswith(("import ", "from ")):
        return False
    parts = stripped.split()
    mod = parts[1].split(".")[0] if len(parts) > 1 else ""
    return mod not in SAFE_MODULES and not mod.startswith("src")

    def _check_no_classes(self) -> None:
        combined = self.refactored_code + "\n" + "\n".join(self.helper_functions)
        class_lines = [line for line in combined.splitlines() if line.strip().startswith("class ")]
        if class_lines:
            raise ModelRetry(
                f"CRITICAL: You created a class: {class_lines}. Do NOT create classes to pass state. "
                f"Use flat dictionaries, tuples, or standard function arguments."
            )

    def _check_no_nested_closures(self) -> None:
        try:
            main_tree = ast.parse(self.refactored_code)
        except SyntaxError:
            return
        for node in ast.walk(main_tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != self.function_name:
                raise ModelRetry(
                    f"CRITICAL: Nested function `{node.name}` defined inside `refactored_code`. "
                    f"Move `{node.name}` into `helper_functions` and ensure it starts with `_{self.function_name}_`."
                )

    def _check_helper_naming_convention(self) -> None:
        for helper_code in self.helper_functions:
            _check_helper_underscore(helper_code)


def _check_helper_underscore(helper_code: str) -> None:
    try:
        helper_tree = ast.parse(helper_code)
    except SyntaxError:
        return
    for node in helper_tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_"):
            raise ModelRetry(
                f"CRITICAL: Helper function `{node.name}` MUST start with an underscore (e.g., `_{node.name}`)."
            )


def _clean_markdown(v: Any) -> Any:
    def _clean(s: str) -> str:
        s = s.strip()
        if s.startswith("```python"):
            s = s[9:]
        elif s.startswith("```"):
            s = s[3:]
        s = s.removesuffix("```")
        return s.strip()

    if isinstance(v, str):
        return _clean(v)
    elif isinstance(v, list):
        return [_clean(item) if isinstance(item, str) else item for item in v]
    return v


class RefactorDeps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    orig_code: str = ""
    full_file_source: str = ""
    file_path: str = ""
    line: int = 0
    end_line: int = 0
    func_name: str = ""
    baseline_errors: set[str] = Field(default_factory=set)


class RefactorResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    file_path: str
    function_name: str
    line: int
    status: str  # "APPROVED", "FAILED_VERIFICATION", "LLM_ERROR"
    attempts: int
    original_cc: int
    refactored_cc: int
    original_depth: int
    refactored_depth: int
    refactored_code: str
    helper_functions: list[str] = Field(default_factory=list)
    explanation: str
    verification_msg: str


refactor_result_adapter = TypeAdapter(RefactorResult)


# =====================================================================
# PYDANTIC-AI AGENT & OUTPUT VALIDATION
# =====================================================================

_refactor_agent = Agent(
    model=CONTROL_SHEET.scanner_model,
    deps_type=RefactorDeps,
    output_type=RefactoringVerdict,
    instructions="You are a principal Python architect strictly enforcing Flat Control Flow.",
    retries=3,
    model_settings={"temperature": 0.0},
)


class ComplexityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.complexity = 1

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.complexity += 1
        self.generic_visit(node)


class ReturnVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.return_types: set[str] = set()

    def visit_Return(self, node: ast.Return) -> None:
        self._classify_return(node)
        self.generic_visit(node)

    def _classify_return(self, node: ast.Return) -> None:
        if not node.value:
            return
        label = _RETURN_TYPE_MAP.get(type(node.value))
        if label:
            self.return_types.add(label)


_RETURN_TYPE_MAP: dict[type, str] = {
    ast.Dict: "dict",
    ast.Call: "call",
    ast.Tuple: "sequence",
    ast.List: "sequence",
    ast.Name: "var",
}


@_refactor_agent.output_validator
def enforce_return_shape(ctx: RunContext[RefactorDeps], result: RefactoringVerdict) -> RefactoringVerdict:
    if not ctx.deps or not ctx.deps.orig_code:
        return result

    _check_helper_complexity(result)
    _check_return_shape_preserved(ctx, result)
    _verify_ast_and_scope(ctx, result)
    return result


def _check_helper_complexity(result: RefactoringVerdict) -> None:
    for helper_code in result.helper_functions:
        _validate_helper_tree(helper_code)


def _validate_helper_tree(helper_code: str) -> None:
    try:
        helper_tree = ast.parse(helper_code)
    except SyntaxError:
        return
    for node in helper_tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        _validate_helper_func_cc(node)


def _validate_helper_func_cc(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    comp_vis = ComplexityVisitor()
    comp_vis.visit(node)
    if comp_vis.complexity > 5:
        msg = (
            f"CRITICAL: Extracted helper function `{node.name}` has Cyclomatic Complexity {comp_vis.complexity} (must be <= 5). "
            f"ALL helper functions MUST have CC <= 5. Break `{node.name}` down into simpler steps."
        )
        logger.warning(f"[ModelRetry] Helper CC > 5: {msg}")
        raise ModelRetry(msg)


def _get_return_types(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    vis = ReturnVisitor()
    vis.visit(tree)
    return vis.return_types


def _check_return_shape_preserved(ctx: RunContext[RefactoringVerdict], result: RefactoringVerdict) -> None:
    orig_types = _get_return_types(ctx.deps.orig_code)
    new_types = _get_return_types(result.refactored_code)
    if "dict" in orig_types and "call" in new_types:
        msg = (
            "CRITICAL: Return type mutation detected. The original function returned a raw dictionary (ast.Dict), "
            "but your refactored code returns a class/model instantiation. Preserve the exact dictionary return structure."
        )
        logger.warning(f"[ModelRetry] Return shape mutation: {msg}")
        raise ModelRetry(msg)


def _verify_ast_and_scope(ctx: RunContext[RefactoringVerdict], result: RefactoringVerdict) -> None:
    deps = ctx.deps
    if not deps.full_file_source or not deps.func_name:
        return
    try:
        buf = VirtualASTBuffer(deps.full_file_source, deps.file_path)
        temp_source = buf.replace_function(
            deps.func_name,
            result.refactored_code,
            result.helper_functions,
        )
    except (SyntaxError, ValueError) as e:
        _raise_vab_error(e)

    ref_for_imports = _build_ref_for_imports(result)
    temp_source = ensure_pydantic_imports(temp_source, ref_for_imports)
    _run_ruff_sandbox(temp_source)


def _raise_vab_error(e: Exception) -> None:
    msg = f"CRITICAL: Refactored code AST replacement failed in VirtualASTBuffer: {e}"
    logger.warning(f"[ModelRetry] VirtualASTBuffer Replace Error: {msg}")
    raise ModelRetry(msg)


def _build_ref_for_imports(result: RefactoringVerdict) -> str:
    helper_block = ""
    if result.helper_functions:
        helper_block = "\n\n" + "\n\n".join(h.rstrip() for h in result.helper_functions)
    return result.refactored_code + helper_block


def _run_ruff_sandbox(temp_source: str) -> None:
    _tmp_fd, tmp_path = tempfile.mkstemp(suffix=".py")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(temp_source)
        subprocess.run(["uv", "run", "ruff", "format", tmp_path], capture_output=True, text=True, check=False)
        ruff_res = subprocess.run(
            ["uv", "run", "ruff", "check", tmp_path], capture_output=True, text=True, check=False
        )
        if ruff_res.returncode != 0:
            clean_errors = "\n".join(
                [line.split(":", 1)[-1].strip() for line in ruff_res.stdout.splitlines() if ":" in line]
            )
            logger.warning(f"[ModelRetry] Ruff error:\n{clean_errors}")
            raise ModelRetry(
                f"CRITICAL: Code caused Ruff linter errors:\n{clean_errors}\n"
                f"Fix these errors. If you hallucinated a type hint (F821), change it to `dict`, `list`, or `Any`."
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# =====================================================================
# AST SCANNER & UTILITIES
# =====================================================================

class FunctionCandidateScanner(ast.NodeVisitor):
    CONTROL_NODES = (ast.If, ast.Try, ast.For, ast.While, ast.With)

    def __init__(self, filename: str, code_lines: list[str]) -> None:
        self.filename = filename
        self.code_lines = code_lines
        self.candidates: list[FunctionCandidate] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        comp_vis = ComplexityVisitor()
        comp_vis.visit(node)
        cc = comp_vis.complexity

        max_depth, _max_depth_line, try_issues = self._check_body_nesting(node.body, depth=0)

        if len(try_issues) > 0 or max_depth > 3 or cc > 5:
            end_line = getattr(node, "end_lineno", node.lineno)
            func_code = ast.unparse(node)

            priority = _derive_priority(try_issues, max_depth)
            self.candidates.append(
                FunctionCandidate(
                    file_path=self.filename,
                    function_name=node.name,
                    line=node.lineno,
                    end_line=end_line,
                    cc=cc,
                    max_depth=max_depth,
                    priority=priority,
                    try_issues=try_issues,
                    source_code=func_code,
                )
            )

        self.generic_visit(node)


def _derive_priority(try_issues: list, max_depth: int) -> int:
    if len(try_issues) > 0:
        return 1
    if max_depth > 3:
        return 2
    return 3


def _check_nested_try_body(stmt: ast.Try) -> list[tuple[int, str]]:
    issues: list[tuple[int, str]] = []
    for inner_stmt in stmt.body:
        if isinstance(inner_stmt, ast.Try):
            issues.append((inner_stmt.lineno, "Nested Try block inside Try body"))
    return issues


def _check_handler_bodies(stmt: ast.Try) -> list[tuple[int, str]]:
    issues: list[tuple[int, str]] = []
    for handler in stmt.handlers:
        for h_stmt in handler.body:
            if isinstance(h_stmt, ast.Try):
                issues.append((h_stmt.lineno, "Try block inside Except handler"))
    return issues


def _check_orelse(stmt: ast.Try) -> list[tuple[int, str]]:
    issues: list[tuple[int, str]] = []
    if stmt.orelse:
        for el_stmt in stmt.orelse:
            if isinstance(el_stmt, (ast.If, ast.Try)):
                issues.append((el_stmt.lineno, f"{el_stmt.__class__.__name__} inside Try-Else block"))
    return issues


def _collect_nested_try_issues(scanner: FunctionCandidateScanner, stmt: ast.Try) -> list[tuple[int, str]]:
    issues = _check_nested_try_body(stmt)
    issues.extend(_check_handler_bodies(stmt))
    issues.extend(_check_orelse(stmt))
    return issues


FunctionCandidateScanner._collect_nested_try_issues = _collect_nested_try_issues


def _try_sub_bodies(stmt: ast.Try, depth: int) -> list[tuple[list[ast.stmt], int]]:
    bodies: list[tuple[list[ast.stmt], int]] = [(stmt.body, depth + 1)]
    for h in stmt.handlers:
        bodies.append((h.body, depth + 1))
    bodies.append((stmt.orelse, depth + 1))
    bodies.append((stmt.finalbody, depth + 1))
    return bodies


def _collect_if_sub_bodies(stmt: ast.If, depth: int) -> list[tuple[list[ast.stmt], int]]:
    if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
        return [(stmt.body, depth + 1), (stmt.orelse, depth)]
    return [(stmt.body, depth + 1), (stmt.orelse, depth + 1)]


def _collect_for_while_sub_bodies(stmt: ast.stmt, depth: int) -> list[tuple[list[ast.stmt], int]]:
    return [(stmt.body, depth + 1), (stmt.orelse, depth + 1)]


def _collect_with_sub_bodies(stmt: ast.With, depth: int) -> list[tuple[list[ast.stmt], int]]:
    return [(stmt.body, depth + 1), ([], depth + 1)]


def _collect_sub_bodies(scanner: FunctionCandidateScanner, stmt: ast.stmt, depth: int) -> list[tuple[list[ast.stmt], int]]:
    if isinstance(stmt, ast.Try):
        return _try_sub_bodies(stmt, depth)
    if isinstance(stmt, ast.If):
        return _collect_if_sub_bodies(stmt, depth)
    if isinstance(stmt, (ast.For, ast.While)):
        return _collect_for_while_sub_bodies(stmt, depth)
    if isinstance(stmt, ast.With):
        return _collect_with_sub_bodies(stmt, depth)
    return []


FunctionCandidateScanner._collect_sub_bodies = _collect_sub_bodies


def _process_control_node(
    stmt: ast.stmt, depth: int, scanner: FunctionCandidateScanner
) -> tuple[int, int, list[tuple[int, str]]]:
    max_d = depth
    max_line = 0
    try_issues: list[tuple[int, str]] = []

    if depth + 1 > max_d:
        max_d = depth + 1
        max_line = stmt.lineno

    if isinstance(stmt, ast.Try):
        try_issues.extend(scanner._collect_nested_try_issues(stmt))

    return max_d, max_line, try_issues


def _check_body_nesting(
    scanner: FunctionCandidateScanner, statements: list[ast.stmt], depth: int
) -> tuple[int, int, list[tuple[int, str]]]:
    max_d = depth
    max_line = 0
    try_issues: list[tuple[int, str]] = []

    for stmt in statements:
        if not isinstance(stmt, scanner.CONTROL_NODES):
            continue
        max_d, max_line, try_issues = _visit_nesting_stmt(scanner, stmt, depth, max_d, max_line, try_issues)

    return max_d, max_line, try_issues


def _visit_nesting_stmt(
    scanner: FunctionCandidateScanner,
    stmt: ast.stmt,
    depth: int,
    max_d: int,
    max_line: int,
    try_issues: list[tuple[int, str]],
) -> tuple[int, int, list[tuple[int, str]]]:
    node_max, node_line, node_issues = _process_control_node(stmt, depth, scanner)
    if node_max > max_d:
        max_d = node_max
        max_line = node_line
    try_issues.extend(node_issues)
    for sb, sb_depth in scanner._collect_sub_bodies(stmt, depth):
        if sb:
            d, line_no, ti = scanner._check_body_nesting(sb, sb_depth)
            try_issues.extend(ti)
            if d > max_d:
                max_d = d
                max_line = line_no
    return max_d, max_line, try_issues


FunctionCandidateScanner._check_body_nesting = _check_body_nesting

def load_prompt_template(path: Path | None = None) -> dict:
    template_path = path or PROMPT_TEMPLATE_PATH
    if not template_path.exists():
        logger.warning(f"Prompt template not found at {template_path}")
        return {}
    with open(template_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_target_files() -> set[str] | None:
    if not LIST_FILE.exists():
        return None
    with open(LIST_FILE, encoding="utf-8") as f:
        paths = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    logger.info(f"Loaded {len(paths)} targeted files from kill_tries_list.txt")
    return paths


def format_prompt(
    template: dict,
    candidate: FunctionCandidate,
    attempt: int = 1,
    history: list | None = None,
    what_worked_text: str = "",
    violations_text: str = "",
) -> str:
    if not history:
        return _render_narrative(template, candidate, attempt, history, what_worked_text, violations_text)

    function_name = candidate.function_name
    file_path = candidate.file_path
    attempts_left = 5 - attempt + 1
    source_code = candidate.source_code

    return (
        f"=== ATTEMPT {attempt}/5 (CONCISE DELTA) ===\n\n"
        f"Previous attempt feedback for {function_name} ({file_path}):\n\n"
        f"ISSUES TO FIX:\n{violations_text}\n\n"
        f"WHAT WORKED (preserve these):\n{what_worked_text}\n\n"
        f"YOU HAVE {attempts_left} ATTEMPT(S) LEFT.\n"
        f"Take your previous attempt and surgically fix only the violations above.\n"
        f"CRITICAL: If you extract helper functions, prefix each with `_{function_name}_`.\n\n"
        f"<source_code>\n{source_code}\n</source_code>\n"
    )


def _render_narrative(
    template: dict,
    candidate: FunctionCandidate,
    attempt_num: int,
    history: list | None = None,
    what_worked_text: str = "",
    violations_text: str = "",
) -> str:
    system_prompt = template.get("system_prompt", "")
    system = template.get("system_instruction", "")
    anti_patterns = template.get("anti_patterns", "")

    return (
        f"{system_prompt}\n\n{system}\n\n"
        f"=== WHAT WENT WRONG ===\n{anti_patterns}\n\n"
        f"=== RULES ===\n{template.get('conditions', template.get('rules', ''))}\n\n"
        f"TARGET: Refactor {candidate.function_name} ({candidate.file_path}:{candidate.line}) to pass all checks.\n"
        f"CC={candidate.cc} | Depth={candidate.max_depth} | Priority={candidate.priority}\n\n"
        f"<source_code>\n{candidate.source_code}\n</source_code>\n"
    )


def _build_pydantic_import_map(tree: ast.Module) -> dict[str, bool]:
    result_map: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "pydantic":
            _collect_pydantic_aliases(node, result_map)
    return result_map


def _collect_pydantic_aliases(node: ast.ImportFrom, result_map: dict[str, bool]) -> None:
    for alias in node.names:
        result_map[alias.asname or alias.name] = True


def _scan_imports_for_pydantic(source: str) -> tuple[bool, bool]:
    try:
        source_tree = ast.parse(source)
    except SyntaxError:
        return False, False
    pydantic_imports = _build_pydantic_import_map(source_tree)
    return "BaseModel" in pydantic_imports, "Field" in pydantic_imports


def _scan_ref_for_pydantic_usage(code: str) -> tuple[bool, bool]:
    try:
        ref_tree = ast.parse(code)
    except SyntaxError:
        return False, False
    names = {node.id for node in ast.walk(ref_tree) if isinstance(node, ast.Name)}
    return "BaseModel" in names, "Field" in names


def ensure_pydantic_imports(source: str, ref_code: str) -> str:
    has_basemodel, has_field = _scan_imports_for_pydantic(source)
    uses_basemodel, uses_field = _scan_ref_for_pydantic_usage(ref_code)
    needed = _compute_needed_imports(
        uses_basemodel, has_basemodel, uses_field, has_field
    )
    if not needed:
        return source
    import_line = f"from pydantic import {', '.join(needed)}\n"
    return import_line + source


def _compute_needed_imports(
    uses_basemodel: bool, has_basemodel: bool, uses_field: bool, has_field: bool
) -> list[str]:
    needed = []
    if uses_basemodel and not has_basemodel:
        needed.append("BaseModel")
    if uses_field and not has_field:
        needed.append("Field")
    return needed


# =====================================================================
# AST VERIFICATION
# =====================================================================

class _ASTVerifier:
    def __init__(self, candidate_name: str = "", orig_cc: int = 0) -> None:
        self.candidate_name = candidate_name
        self.target_cc = 5 if orig_cc <= 5 else (orig_cc - 1)
        self.violations: list[str] = []
        self.candidate_cc = 0
        self.candidate_max_depth = 0

    def verify(self, code: str) -> tuple[bool, int, int, str]:
        tree = self._parse_code(code)
        if tree is None:
            return False, 999, 999, self._syntax_error
        self._walk_functions(tree, code)
        if self.violations:
            detail = "\n".join(f"  - {v}" for v in self.violations)
            return False, self.candidate_cc, self.candidate_max_depth, "VIOLATIONS FOUND:\n" + detail
        return True, self.candidate_cc, self.candidate_max_depth, "Passed verification."

    def _parse_code(self, code: str) -> ast.Module | None:
        try:
            return ast.parse(code)
        except SyntaxError as e:
            self._syntax_error = f"SyntaxError in refactored code: {e}"
            return None

    def _walk_functions(self, tree: ast.Module, code: str) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function_node(node, code)

    def _check_function_node(self, node: ast.FunctionDef | ast.AsyncFunctionDef, code: str) -> None:
        comp_vis = ComplexityVisitor()
        comp_vis.visit(node)
        func_cc = comp_vis.complexity

        scanner = FunctionCandidateScanner("test.py", code.splitlines())
        func_depth, _, try_issues = scanner._check_body_nesting(node.body, depth=0)

        if node.name == self.candidate_name:
            self.candidate_cc = func_cc
            self.candidate_max_depth = func_depth

        self._record_violations(node, func_cc, func_depth, try_issues)


    def _record_violations(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        func_cc: int,
        func_depth: int,
        try_issues: list,
    ) -> None:
        if len(try_issues) > 0:
            self.violations.append(f"try_pyramid:{try_issues}")
        node_target_cc = self.target_cc if node.name == self.candidate_name else 5
        if func_cc > node_target_cc:
            self.violations.append(f"cc_exceeds:{node.name} has CC={func_cc} (target <={node_target_cc})")
        if func_depth > 3:
            self.violations.append(f"nesting_exceeds:{node.name} depth={func_depth} (must be <=3)")


def verify_refactored_ast(
    code: str, candidate_name: str = "", contract_info: dict | None = None, orig_code: str = "", orig_cc: int = 0
) -> tuple[bool, int, int, str]:
    verifier = _ASTVerifier(candidate_name=candidate_name, orig_cc=orig_cc)
    return verifier.verify(code)


# =====================================================================
# REFACTORING ENGINE
# =====================================================================

async def refactor_single_attempt_with_llm(
    candidate: FunctionCandidate,
    attempt: int,
    history: list,
    prompt: str,
    template: dict,
    cand_idx: int = 0,
    total_cand: int = 0,
) -> tuple[bool, list, str, RefactorResult | None]:
    req_id = str(uuid.uuid4())[:8]
    model_obj = CONTROL_SHEET.scanner_model
    getattr(model_obj, "model_name", str(model_obj))
    _provider = get_model_provider_name(CONTROL_SHEET.scanner_model)
    start_t = time.time()

    print(
        f"🔵 [{get_timestamp()}] [{cand_idx}/{total_cand}][REQ {req_id}] provider={_provider} candidate={candidate.function_name} ({candidate.file_path}:{candidate.line}) attempt={attempt}/5",
        flush=True,
    )

    try:
        deps_obj = _prepare_deps(candidate)
        result = await _refactor_agent.run(prompt, message_history=history, deps=deps_obj)
        elapsed = round(time.time() - start_t, 2)
        history = result.all_messages()
        verdict: RefactoringVerdict = result.output

        full_code = verdict.refactored_code + ("\n\n" + "\n\n".join(verdict.helper_functions) if verdict.helper_functions else "")
        passed, new_cc, new_depth, msg = verify_refactored_ast(
            full_code, candidate.function_name, orig_code=candidate.source_code, orig_cc=candidate.cc
        )

        if passed:
            return _handle_success(candidate, attempt, elapsed, verdict, new_cc, new_depth, msg)

        return _handle_failed_attempt(candidate, attempt, history, msg, template, verdict, new_cc, new_depth)

    except Exception as e:
        _handle_exception(candidate, attempt, history, e, template)
        raise


def _prepare_deps(candidate: FunctionCandidate) -> RefactorDeps:
    full_source = ""
    target_path = pkg_root / candidate.file_path
    if target_path.exists():
        full_source = target_path.read_text(encoding="utf-8")
    return RefactorDeps(
        orig_code=candidate.source_code,
        full_file_source=full_source,
        file_path=candidate.file_path,
        line=candidate.line,
        end_line=candidate.end_line,
        func_name=candidate.function_name,
    )


def _handle_success(
    candidate: FunctionCandidate,
    attempt: int,
    elapsed: float,
    verdict: RefactoringVerdict,
    new_cc: int,
    new_depth: int,
    msg: str,
) -> tuple[bool, list, str, RefactorResult | None]:
    print(f"✅ [{get_timestamp()}] [PASSED] {candidate.function_name} PASSED on attempt {attempt}/5! (Duration: {elapsed}s)", flush=True)
    res = RefactorResult(
        file_path=candidate.file_path,
        function_name=candidate.function_name,
        line=candidate.line,
        status="APPROVED",
        attempts=attempt,
        original_cc=candidate.cc,
        refactored_cc=new_cc,
        original_depth=candidate.max_depth,
        refactored_depth=new_depth,
        refactored_code=verdict.refactored_code,
        helper_functions=verdict.helper_functions,
        explanation=verdict.explanation,
        verification_msg=msg,
    )
    return True, [], "", res


def _handle_failed_attempt(
    candidate: FunctionCandidate,
    attempt: int,
    history: list,
    msg: str,
    template: dict,
    verdict: RefactoringVerdict,
    new_cc: int,
    new_depth: int,
) -> tuple[bool, list, str, RefactorResult | None]:
    logger.warning(f"  ⚠️ [Attempt {attempt}/5 Retry] {candidate.function_name} failed AST check: {msg}")
    retry_prompt = format_prompt(template, candidate, attempt + 1, history, violations_text=msg)

    if attempt >= 5:
        res = RefactorResult(
            file_path=candidate.file_path,
            function_name=candidate.function_name,
            line=candidate.line,
            status="FAILED_VERIFICATION",
            attempts=5,
            original_cc=candidate.cc,
            refactored_cc=new_cc,
            original_depth=candidate.max_depth,
            refactored_depth=new_depth,
            refactored_code=candidate.source_code,
            helper_functions=[],
            explanation=f"Failed after 5 attempts: {msg}",
            verification_msg=msg,
        )
        return False, history, retry_prompt, res

    return False, history, retry_prompt, None


def _handle_exception(
    candidate: FunctionCandidate,
    attempt: int,
    history: list,
    e: Exception,
    template: dict,
) -> None:
    logger.error(f"Pydantic-AI attempt {attempt} failed for {candidate.function_name}: {e}")
    if attempt >= 5:
        res = RefactorResult(
            file_path=candidate.file_path,
            function_name=candidate.function_name,
            line=candidate.line,
            status="LLM_ERROR",
            attempts=attempt,
            original_cc=candidate.cc,
            refactored_cc=candidate.cc,
            original_depth=candidate.max_depth,
            refactored_depth=candidate.max_depth,
            refactored_code=candidate.source_code,
            helper_functions=[],
            explanation=f"LLM error: {e}",
            verification_msg=str(e),
        )
        save_checkpoint_item(res)


# =====================================================================
# MAIN PIPELINE
# =====================================================================

def _should_skip_file(
    py_file: Path, rel_path: str, target_files: set[str] | None
) -> bool:
    if not py_file.is_file():
        return True
    return bool(target_files and rel_path not in target_files)


def scan_all_candidates(target_files: set[str] | None = None) -> list[FunctionCandidate]:
    logger.info("Scanning src/ AST for Flat Control Flow candidates...")
    candidates: list[FunctionCandidate] = []
    root_resolved = pkg_root.resolve()

    for py_file in sorted(src_DIR.rglob("*.py")):
        rel_path = str(py_file.resolve().relative_to(root_resolved))
        if _should_skip_file(py_file, rel_path, target_files):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(py_file))
            scanner = FunctionCandidateScanner(rel_path, content.splitlines())
            scanner.visit(tree)
            candidates.extend(scanner.candidates)
        except (OSError, SyntaxError, ValueError, TypeError) as e:
            logger.warning(f"Skipped {py_file.name}: {e}")

    logger.info(f"✅ Found {len(candidates)} candidates violating Flat Control Flow standards.")
    return candidates


def save_checkpoint_item(res: RefactorResult) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(res.model_dump_json() + "\n")


async def main_async(do_refactor: bool, priorities: list[int], limit: int, resume: bool) -> None:
    target_files = load_target_files()
    candidates = scan_all_candidates(target_files=target_files)
    targets = [c for c in candidates if c.priority in priorities]

    if limit > 0:
        targets = targets[:limit]

    print(f"\n✨ Scanned {len(candidates)} total candidates. Processing {len(targets)} matching candidates...")

    template = load_prompt_template()
    queue: asyncio.Queue = asyncio.Queue()

    for idx, c in enumerate(targets, start=1):
        prompt = format_prompt(template, c, attempt=1)
        await queue.put({"candidate": c, "index": idx, "total": len(targets), "attempt": 1, "history": [], "prompt": prompt})

    results = await _run_worker_pool(queue, template, len(targets))
    _write_report(candidates, results)


async def _run_worker_pool(queue: asyncio.Queue, template: dict, total_targets: int) -> list[RefactorResult]:
    semaphore = asyncio.Semaphore(3)
    results: list[RefactorResult] = []

    async def worker_task(item: dict) -> None:
        res = await _process_queue_item(item, template, semaphore, queue, results)
        return res

    active_tasks = set()
    while not queue.empty() or active_tasks:
        if not queue.empty():
            item = await queue.get()
            t = asyncio.create_task(worker_task(item))
            active_tasks.add(t)
            t.add_done_callback(active_tasks.discard)
            await asyncio.sleep(2.0)
        else:
            await asyncio.sleep(0.5)
    return results


async def _process_queue_item(
    item: dict, template: dict, semaphore: asyncio.Semaphore, queue: asyncio.Queue, results: list[RefactorResult]
) -> None:
    cand: FunctionCandidate = item["candidate"]
    async with semaphore:
        _passed, new_hist, next_prmpt, res = await refactor_single_attempt_with_llm(
            cand, item["attempt"], item["history"], item["prompt"], template, item["index"], item["total"]
        )
    if res is not None:
        save_checkpoint_item(res)
        results.append(res)
    else:
        await queue.put(_make_retry_item(item, new_hist, next_prmpt))


def _make_retry_item(item: dict, new_hist: list, next_prmpt: str) -> dict:
    return {
        "candidate": item["candidate"],
        "index": item["index"],
        "total": item["total"],
        "attempt": item["attempt"] + 1,
        "history": new_hist,
        "prompt": next_prmpt,
    }


def _write_report(candidates: list[FunctionCandidate], results: list[RefactorResult]) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    summary_data = {
        "total_scanned_candidates": len(candidates),
        "refactored_count": len(results),
        "approved": [r.model_dump() for r in results if r.status == "APPROVED"],
        "failed": [r.model_dump() for r in results if r.status != "APPROVED"],
    }
    REPORT_FILE.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")
    logger.info(f"Report saved to {REPORT_FILE}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Kill-Tries AST Scanner & Refactorer")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--priority", type=str, default="all")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    priorities = [1, 2, 3] if args.priority == "all" else [int(p) for p in args.priority.split(",") if p.isdigit()]
    asyncio.run(main_async(do_refactor=not args.scan_only, priorities=priorities, limit=args.limit, resume=True))


if __name__ == "__main__":
    main()
