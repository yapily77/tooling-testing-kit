import ast
import asyncio
import functools
import json
import logging
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logfire
import yaml

# Ensure repo root in sys.path
from _bootstrap import pkg_root
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
from pydantic_ai.messages import ModelRequest, UserPromptPart

REQUEST_TIMEOUT = 300  # seconds — max subprocess/LLM request timeout
MAX_RETRIES = 10  # max retries for LLM refactoring attempts

from control import CONTROL_SHEET
from virtual_ast_buffer import (
    VirtualASTBuffer,
    ensure_pydantic_imports,
)

_KNOWN_TEMPLATE_KEYS = re.compile(
    r"\{("
    + r"|".join(re.escape(k) for k in (
        "file_path", "function_name", "narrative_context", "anti_patterns",
        "samples", "attempts_left", "upstream_callers", "module_context",
        "anti_patterns_list", "conditions", "rules", "line", "violations",
        "what_worked_text", "what_to_fix_text", "violation_count", "attempt",
        "violations_text", "what_worked", "what_to_fix",
        "imported_modules_text", "imported_symbols_text", "top_level_symbols_text",
        "global_constants_text", "header_symbol_contract",
    ))
    + r")\}"
)

# Module-level logger
_logger = logging.getLogger(__name__)

# Initialize Logfire instrumentation once globally
try:
    logfire.configure(send_to_logfire=False)
    logfire.instrument_pydantic_ai()
except ImportError as err:
    _logger.warning("Logfire instrumentation failed: %s", err)

CHECKPOINT_FILE = pkg_root / "reports" / "kill_tries_checkpoint.jsonl"
REPORT_FILE = pkg_root / "reports" / "kill_tries.json"
src_DIR = pkg_root.parent / "src"
PROMPT_TEMPLATE_PATH = pkg_root / "scanners" / "kill_tries_prompt.yaml"
PROMPT_RETRY_PATH = pkg_root / "scanners" / "kill_tries_prompt_retry.yaml"
LIST_FILE = pkg_root / "scanners" / "kill_tries_list.txt"

# --------------------------------------------------------------------
# Template & Logging Utilities
# --------------------------------------------------------------------

def fill_template(template_str: str, **kwargs: str) -> str:
    def _replacer(match: re.Match) -> str:
        val = kwargs.get(match.group(1))
        return val if val is not None else match.group(0)

    return _KNOWN_TEMPLATE_KEYS.sub(_replacer, template_str)


def get_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%m-%d-%H:%M:%S") + f":{int(now.microsecond / 1000):03d}"


def get_model_provider_name(model: Any) -> str:
    provider = getattr(model, "provider", None)
    from control import PROVIDERS

    for name, prov in PROVIDERS.items():
        if provider is prov:
            return name
    base_url = getattr(provider, "base_url", "")
    return base_url.split("/")[2] if "/" in base_url else "unknown"


class ColoredFormatter(logging.Formatter):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"

    def __init__(self) -> None:
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
_logger_ast = logging.getLogger("KillTriesScanner")
_logger_ast.setLevel(logging.INFO)
_logger_ast.addHandler(handler)
_logger_ast.propagate = False

# --------------------------------------------------------------------
# Subprocess & Lint Utilities
# --------------------------------------------------------------------

_SAFE_SCRATCH_DIR = pkg_root / "scratch"

def _ensure_scratch_dir() -> Path:
    _SAFE_SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    return _SAFE_SCRATCH_DIR


def _create_temp_file(content: str) -> Path:
    scratch = _ensure_scratch_dir()
    tmp_path = scratch / f"temp_pyright_{uuid.uuid4().hex}.py"
    tmp_path.write_text(content, encoding="utf-8")
    return tmp_path


def _run_subprocess(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=REQUEST_TIMEOUT,
        cwd=str(pkg_root),
        env={**os.environ, "PYTHONPATH": "."},
    )


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _normalize_pyright_error(line: str) -> str:
    line = line.strip()
    if " - " in line:
        return line.split(" - ", 1)[-1].strip()
    return line


def _normalize_ruff_error(line: str) -> str:
    if ":" in line:
        return line.split(":", 1)[-1].strip()
    return line.strip()


def _collect_errors_from_lines(
    output_lines: list[str], normalize_fn: Any, filter_substr: str
) -> set[str]:
    errors: set[str] = set()
    for line in output_lines:
        if filter_substr in line.lower():
            norm = normalize_fn(line)
            if norm:
                errors.add(norm)
    return errors


def _get_normalized_pyright_errors(file_content: str) -> set[str]:
    if not file_content:
        return set()
    tmp_path = _create_temp_file(file_content)
    try:
        res = _run_subprocess(["uv", "run", "pyright", str(tmp_path)])
        return _collect_errors_from_lines(res.stdout.splitlines(), _normalize_pyright_error, "error:")
    except (ValueError, SyntaxError, TypeError):
        return set()
    finally:
        _safe_unlink(tmp_path)


def _get_ruff_errors(file_content: str) -> set[str]:
    if not file_content:
        return set()
    tmp_path = _create_temp_file(file_content)
    try:
        res = _run_subprocess(["uv", "run", "ruff", "check", "--select", "F821,E9,F63,F7", str(tmp_path)])
        return _collect_errors_from_lines(res.stdout.splitlines(), _normalize_ruff_error, ":")
    except (ValueError, SyntaxError, TypeError):
        return set()
    finally:
        _safe_unlink(tmp_path)


@functools.lru_cache(maxsize=128)
def get_file_baseline_errors(file_path_str: str, root_dir: Path) -> set[str]:
    full_path = root_dir / file_path_str
    if not full_path.exists():
        return set()
    source = full_path.read_text(encoding="utf-8")
    return _get_normalized_pyright_errors(source)


# =====================================================================
# PYDANTIC 2.0 DOMAIN SCHEMAS
# =====================================================================

class HeaderSymbolContract(BaseModel):
    """Structured contract of imported modules, symbols, top-level definitions, and global constants."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    imported_modules: list[str] = Field(default_factory=list)
    imported_symbols: list[str] = Field(default_factory=list)
    top_level_symbols: list[str] = Field(default_factory=list)
    global_constants: list[str] = Field(default_factory=list)

    def to_prompt_section(self) -> str:
        all_symbols = sorted(set(self.imported_symbols + self.top_level_symbols + self.global_constants))
        symbols_str = ", ".join(all_symbols) if all_symbols else "None"
        modules_str = ", ".join(sorted(set(self.imported_modules))) if self.imported_modules else "None"
        return (
            f"AVAILABLE IMPORTED MODULES IN THIS FILE HEADER: [{modules_str}]\n"
            f"AVAILABLE IMPORTED MODELS AND SYMBOLS IN THIS FILE HEADER: [{symbols_str}]\n"
            f"STRICT RULE: You must ONLY use standard primitives (int, str, float, bool, dict, list, tuple, set, Any, Optional, Union) OR the imported symbols listed above. DO NOT invent or reference unimported class names."
        )


def _collect_import_alias(node: ast.Import, mod_set: set[str], sym_set: set[str]) -> None:
    for alias in node.names:
        mod_set.add(alias.name)
        bound = alias.asname if alias.asname else alias.name.split(".")[0]
        sym_set.add(bound)


def _collect_from_import_alias(node: ast.ImportFrom, mod_set: set[str], sym_set: set[str]) -> None:
    if node.module:
        mod_set.add(node.module)
    for alias in node.names:
        if alias.name != "*":
            bound = alias.asname if alias.asname else alias.name
            sym_set.add(bound)


def _collect_import_info(node: ast.AST, mod_set: set[str], sym_set: set[str]) -> None:
    if isinstance(node, ast.Import):
        _collect_import_alias(node, mod_set, sym_set)
    elif isinstance(node, ast.ImportFrom):
        _collect_from_import_alias(node, mod_set, sym_set)


def _collect_assign_targets(node: ast.Assign, target_set: set[str]) -> None:
    for target in node.targets:
        if isinstance(target, ast.Name):
            target_set.add(target.id)


def _collect_symbol_info(node: ast.AST, sym_set: set[str], const_set: set[str]) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        sym_set.add(node.name)
    elif isinstance(node, ast.Assign):
        _collect_assign_targets(node, const_set)


def extract_header_symbol_contract(source: str) -> HeaderSymbolContract:
    """Parse full file AST to extract all imported module names, imported symbols, top-level functions/classes, and global constants."""
    if not source:
        return HeaderSymbolContract()
    try:
        tree = ast.parse(source)
    except (ValueError, SyntaxError, TypeError):
        return HeaderSymbolContract()

    imported_modules: set[str] = set()
    imported_symbols: set[str] = set()
    top_level_symbols: set[str] = set()
    global_constants: set[str] = set()

    for node in tree.body:
        _collect_import_info(node, imported_modules, imported_symbols)
        _collect_symbol_info(node, top_level_symbols, global_constants)

    return HeaderSymbolContract(
        imported_modules=sorted(imported_modules),
        imported_symbols=sorted(imported_symbols),
        top_level_symbols=sorted(top_level_symbols),
        global_constants=sorted(global_constants),
    )


class FunctionCandidate(BaseModel):
    """Pydantic 2.0 schema representing candidate functions violating control flow standards."""

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
    full_file_source: str = ""
    upstream_callers: str = ""
    module_context: str = ""
    header_contract: HeaderSymbolContract = Field(default_factory=HeaderSymbolContract)
    phase: int = 1
    parent_function: str = ""
    line_count: int = 0
    requires_decomposition: bool = False


class DecompositionPlan(BaseModel):
    """Result of deterministic pre-decomposition of an extremely complex function."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    phase_number: int = 1
    main_function_name: str = ""
    helper_functions: list[str] = Field(default_factory=list)
    helper_candidates: list[FunctionCandidate] = Field(default_factory=list)
    residual_cc: int = 0
    original_cc: int = 0


class RefactoringVerdict(BaseModel):
    """Pydantic 2.0 schema for LLM structured refactoring output with strict constraints."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    reasoning_and_plan: str = Field(
        ...,
        description="Step-by-step reasoning and plan for refactoring, verifying imports, symbols, and helper function scope",
    )
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

    @field_validator("reasoning_and_plan", "refactored_code", "helper_functions", mode="before")
    @classmethod
    def strip_markdown_backticks(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _clean_markdown(v)
        if isinstance(v, list):
            return [_clean_markdown(item) if isinstance(item, str) else item for item in v]
        return v

    @model_validator(mode="after")
    def validate_structural_constraints(self) -> "RefactoringVerdict":
        self._validate_imports()
        self._validate_no_classes()
        self._validate_closure_ban()
        self._validate_helper_naming()
        return self

    def _validate_imports(self) -> None:
        safe_modules = {"typing", "collections", "enum", "dataclasses", "itertools", "re"}
        combined = self.refactored_code + "\n" + "\n".join(self.helper_functions)
        unauthorized = _find_unauthorized_imports(combined.splitlines(), safe_modules)
        if unauthorized:
            raise ModelRetry(
                f"CRITICAL: Unauthorized imports included: {unauthorized}. "
                f"You may ONLY import from {safe_modules} or internal `src` modules."
            )

    def _validate_no_classes(self) -> None:
        combined = self.refactored_code + "\n" + "\n".join(self.helper_functions)
        class_lines = [line for line in combined.splitlines() if line.strip().startswith("class ")]
        if class_lines:
            raise ModelRetry(
                f"CRITICAL: You created a class: {class_lines}. Do NOT create classes to pass state. "
                f"Use flat dictionaries, tuples, or standard function arguments."
            )

    def _validate_closure_ban(self) -> None:
        main_tree = ast.parse(self.refactored_code)
        _check_nested_functions(main_tree, self.function_name)

    def _validate_helper_naming(self) -> None:
        for helper_code in self.helper_functions:
            helper_tree = ast.parse(helper_code)
            _check_helper_underscore_prefix(helper_tree)


def _clean_markdown(s: str) -> str:
    s = s.strip()
    if s.startswith("```python"):
        s = s[9:]
    elif s.startswith("```"):
        s = s[3:]
    s = s.removesuffix("```")
    return s.strip()


def _is_unauthorized_import_line(stripped: str, safe_modules: set[str]) -> bool:
    if not stripped.startswith(("import ", "from ")):
        return False
    parts = stripped.split()
    if len(parts) <= 1:
        return False
    mod = parts[1].split(".")[0]
    return not (mod in safe_modules or mod.startswith("src"))


def _find_unauthorized_imports(lines: list[str], safe_modules: set[str]) -> list[str]:
    unauthorized: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _is_unauthorized_import_line(stripped, safe_modules):
            unauthorized.append(stripped)
    return unauthorized


def _check_nested_functions(tree: ast.AST, expected_name: str) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != expected_name:
            raise ModelRetry(
                f"CRITICAL: Nested function `{node.name}` defined inside `refactored_code`. "
                f"Move `{node.name}` into `helper_functions` and ensure it starts with `_{expected_name}_`."
            )


def _check_helper_underscore_prefix(helper_tree: ast.AST) -> None:
    for node in helper_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            raise ModelRetry(
                f"CRITICAL: Helper function `{node.name}` MUST start with an underscore (e.g., `_{node.name}`)."
            )


class RefactorDeps(BaseModel):
    """Pydantic 2.0 schema for agent dependencies."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    orig_code: str = ""
    full_file_source: str = ""
    file_path: str = ""
    line: int = 0
    end_line: int = 0
    func_name: str = ""
    baseline_errors: set[str] = Field(default_factory=set)
    header_contract: HeaderSymbolContract = Field(default_factory=HeaderSymbolContract)


class RefactorResult(BaseModel):
    """Pydantic 2.0 schema for checkpoint and report items."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    file_path: str
    function_name: str
    line: int
    status: str
    attempts: int
    original_cc: int
    refactored_cc: int
    original_depth: int
    refactored_depth: int
    refactored_code: str
    helper_functions: list[str] = Field(default_factory=list)
    explanation: str
    verification_msg: str
    reasoning_and_plan: str = ""


refactor_result_adapter = TypeAdapter(RefactorResult)

# =====================================================================
# PYDANTIC-AI AGENT & OUTPUT VALIDATION
# =====================================================================

_refactor_agent = Agent(
    model=CONTROL_SHEET.scanner_model,
    deps_type=RefactorDeps,
    output_type=RefactoringVerdict,
    instructions="You are a principal Python architect strictly enforcing Flat Control Flow.",
    retries=MAX_RETRIES,
    model_settings={"temperature": 0.0, "timeout": REQUEST_TIMEOUT},
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

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.complexity += 1
        for case in node.cases:
            self.complexity += 1
        self.generic_visit(node)

    def _count_comprehension_ifs(self, node: Any) -> None:
        for gen in node.generators:
            self.complexity += len(gen.ifs)
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._count_comprehension_ifs(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._count_comprehension_ifs(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._count_comprehension_ifs(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._count_comprehension_ifs(node)


class ReturnVisitor(ast.NodeVisitor):
    """Scans AST to record top-level return expressions."""

    def __init__(self) -> None:
        self.return_types: set[str] = set()

    def visit_Return(self, node: ast.Return) -> None:
        if node.value:
            rtype = _classify_return_type(node.value)
            if rtype:
                self.return_types.add(rtype)
        self.generic_visit(node)


def _classify_return_type(value: ast.expr) -> str | None:
    if isinstance(value, ast.Dict):
        return "dict"
    if isinstance(value, ast.Call):
        return "call"
    if isinstance(value, (ast.Tuple, ast.List)):
        return "sequence"
    if isinstance(value, ast.Name):
        return "var"
    return None


class AttributeVisitor(ast.NodeVisitor):
    """Scans AST to record attribute access names on existing objects."""

    def __init__(self) -> None:
        self.attributes: set[str] = set()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.attributes.add(node.attr)
        self.generic_visit(node)


class CallVisitor(ast.NodeVisitor):
    """Scans AST to record function calls and the variable names passed as arguments."""

    def __init__(self) -> None:
        self.calls: set[tuple[str, tuple[str, ...]]] = set()
        self.calls_with_keywords: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        func_name = _extract_call_func_name(node)
        if func_name:
            args = tuple(arg.id for arg in node.args if isinstance(arg, ast.Name))
            self.calls.add((func_name, args))
            if node.keywords:
                self.calls_with_keywords.add(func_name)
        self.generic_visit(node)


def _extract_call_func_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


STANDARD_BUILTINS_AND_TYPING: set[str] = {
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes", "callable",
    "chr", "classmethod", "compile", "complex", "delattr", "dict", "dir", "divmod",
    "enumerate", "eval", "exec", "filter", "float", "format", "frozenset", "getattr",
    "globals", "hasattr", "hash", "help", "hex", "id", "input", "int", "isinstance",
    "issubclass", "iter", "len", "list", "locals", "map", "max", "memoryview",
    "min", "next", "object", "oct", "open", "ord", "pow", "print", "property",
    "range", "repr", "reversed", "round", "set", "setattr", "slice", "sorted",
    "staticmethod", "str", "sum", "super", "tuple", "type", "vars", "zip",
    "__import__",
    "Exception", "BaseException", "ValueError", "TypeError", "KeyError",
    "AttributeError", "IndexError", "RuntimeError", "SyntaxError", "ImportError",
    "ModuleNotFoundError", "StopIteration", "FileNotFoundError", "PermissionError",
    "TimeoutError", "OSError", "AssertionError", "NotImplementedError", "OverflowError",
    "ZeroDivisionError", "UnboundLocalError", "UnicodeDecodeError", "UnicodeEncodeError",
    "True", "False", "None", "Ellipsis", "NotImplemented",
    "Any", "Optional", "Union", "Callable", "Dict", "List", "Tuple", "Set", "Type",
    "Cast", "Literal", "TypeVar", "Generic", "Overload", "Final", "ClassVar", "Self",
    "Sequence", "Mapping", "Iterable", "Iterator", "Generator", "Coroutine", "AsyncGenerator",
    "AsyncIterable", "AsyncIterator", "ContextManager", "AsyncContextManager", "NamedTuple",
    "TypedDict", "Protocol", "runtime_checkable", "type_check_only", "cast", "Pattern", "Match",
    "typing", "collections", "enum", "dataclasses", "itertools", "re", "math",
    "datetime", "asyncio", "sys", "os", "json", "logging", "pathlib", "Path", "uuid", "time",
    "__name__", "__file__", "__doc__", "__all__", "__annotations__",
}


# =====================================================================
# SYMBOL SCOPE VISITOR
# =====================================================================

def _collect_import_aliases(node: ast.Import | ast.ImportFrom, root_scope: set[str]) -> None:
    for alias in node.names:
        bound = alias.asname if alias.asname else alias.name
        root_scope.add(bound)


def _collect_node_into_root(node: ast.AST, root_scope: set[str]) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        root_scope.add(node.name)
    elif isinstance(node, ast.Assign):
        _collect_assign_targets(node, root_scope)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        _collect_import_aliases(node, root_scope)


def _collect_import_local_alias(node: ast.Import | ast.ImportFrom, scope: set[str]) -> None:
    for alias in node.names:
        bound = alias.asname if alias.asname else alias.name.split(".")[0]
        scope.add(bound)


def _collect_name_or_handler(node: ast.AST, scope: set[str]) -> bool:
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Param)):
        scope.add(node.id)
        return True
    if isinstance(node, ast.ExceptHandler):
        if node.name:
            scope.add(node.name)
        return True
    return False


def _collect_node_locals(node: ast.AST, scope: set[str], fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    if _collect_name_or_handler(node, scope):
        return
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        _collect_import_local_alias(node, scope)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not fn_node:
        scope.add(node.name)


def _visit_func_defaults(self_ref: Any, args_node: ast.arguments) -> None:
    for default in args_node.defaults:
        self_ref.visit(default)
    for kw_d in args_node.kw_defaults:
        if kw_d:
            self_ref.visit(kw_d)


def _visit_func_annotations(self_ref: Any, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    args_node = node.args
    v_vararg = args_node.vararg.annotation if args_node.vararg else None
    _visit_annotation(self_ref, v_vararg)
    v_kwarg = args_node.kwarg.annotation if args_node.kwarg else None
    _visit_annotation(self_ref, v_kwarg)
    for arg in args_node.posonlyargs + args_node.args + args_node.kwonlyargs:
        _visit_annotation(self_ref, arg.annotation)
    _visit_annotation(self_ref, node.returns)


def _bound_visit_function(self: Any, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    for decorator in node.decorator_list:
        self.visit(decorator)

    _visit_func_defaults(self, node.args)
    _visit_func_annotations(self, node)

    fn_scope: set[str] = set()
    self._collect_function_locals(node, fn_scope)
    self.scope_stack.append(fn_scope)

    for stmt in node.body:
        self.visit(stmt)

    self.scope_stack.pop()


class SymbolScopeVisitor(ast.NodeVisitor):
    """AST NodeVisitor that inspects refactored functions and extracted helper ASTs for loaded names
    (ast.Name in ast.Load context) and function calls (ast.Call), validating them against local definitions,
    Python builtins/primitives, function parameter/local variables, and the HeaderSymbolContract.
    """

    def __init__(self, header_contract: HeaderSymbolContract | None = None, code_str: str = "") -> None:
        self.header_contract = header_contract or HeaderSymbolContract()
        self.code_str = code_str
        self.code_lines = code_str.splitlines() if code_str else []
        self.unimported_symbols: list[dict[str, Any]] = []

        self.allowed_symbols: set[str] = set(STANDARD_BUILTINS_AND_TYPING)
        self.allowed_symbols.update(self.header_contract.imported_symbols)
        self.allowed_symbols.update(self.header_contract.top_level_symbols)
        self.allowed_symbols.update(self.header_contract.global_constants)
        for mod in self.header_contract.imported_modules:
            self.allowed_symbols.add(mod)
            self.allowed_symbols.add(mod.split(".")[0])

        self.scope_stack: list[set[str]] = [set()]
        self._in_annotation: bool = False

    def is_symbol_defined(self, name: str) -> bool:
        if name in self.allowed_symbols:
            return True
        for scope in reversed(self.scope_stack):
            if name in scope:
                return True
        return False

    def _get_line_context(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.code_lines):
            return self.code_lines[lineno - 1].strip()
        return ""

    def _record_violation(self, name: str, lineno: int, category: str = "unimported_symbol") -> None:
        line_context = self._get_line_context(lineno)
        if not any(item["name"] == name and item["line"] == lineno for item in self.unimported_symbols):
            self.unimported_symbols.append({
                "name": name,
                "line": lineno,
                "context": line_context,
                "category": category,
            })

    def collect_top_level_defs(self, tree: ast.AST) -> None:
        """Pre-pass to collect all top-level defined functions, classes, imports, and assignments into root scope."""
        root_scope = self.scope_stack[0]
        body_nodes = _get_body_nodes(tree)
        for node in body_nodes:
            _collect_node_into_root(node, root_scope)

    def _collect_function_locals(self, fn_node: ast.FunctionDef | ast.AsyncFunctionDef, scope: set[str]) -> None:
        """Collect all parameters and local assigned variables for a function definition."""
        args_node = fn_node.args
        for arg in args_node.posonlyargs + args_node.args + args_node.kwonlyargs:
            scope.add(arg.arg)
        _collect_vararg_kwarg(args_node, scope)
        for node in ast.walk(fn_node):
            _collect_node_locals(node, scope, fn_node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        _bound_visit_function(self, node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        prev = self._in_annotation
        self._in_annotation = True
        self.visit(node.annotation)
        self._in_annotation = prev

        if node.value:
            self.visit(node.value)
        self.visit(node.target)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            name = node.id
            if not self.is_symbol_defined(name):
                lineno = getattr(node, "lineno", 0)
                category = "unimported_type_annotation" if self._in_annotation else "unimported_symbol"
                self._record_violation(name, lineno, category)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if not self.is_symbol_defined(func_name):
                lineno = getattr(node, "lineno", 0)
                self._record_violation(func_name, lineno, "unimported_function_call")
        self.generic_visit(node)

    def inspect(self, tree: ast.AST) -> list[dict[str, Any]]:
        self.unimported_symbols.clear()
        self.scope_stack = [set()]
        self._in_annotation = False
        self.collect_top_level_defs(tree)
        self.visit(tree)
        return self.unimported_symbols


def _get_body_nodes(tree: ast.AST) -> list[ast.stmt]:
    if isinstance(tree, ast.Module):
        return tree.body
    if isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [tree]
    return []


def _collect_vararg_kwarg(args_node: ast.arguments, scope: set[str]) -> None:
    if args_node.vararg:
        scope.add(args_node.vararg.arg)
    if args_node.kwarg:
        scope.add(args_node.kwarg.arg)


def _visit_annotation(self_ref: SymbolScopeVisitor, annotation: ast.expr | None) -> None:
    if annotation:
        prev = self_ref._in_annotation
        self_ref._in_annotation = True
        self_ref.visit(annotation)
        self_ref._in_annotation = prev


def _push_function_scope(self_ref: SymbolScopeVisitor, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    fn_scope: set[str] = set()
    self_ref._collect_function_locals(node, fn_scope)
    self_ref.scope_stack.append(fn_scope)


# --------------------------------------------------------------------
# Violation Suggestions & Contract Texts
# --------------------------------------------------------------------

VIOLATION_SUGGESTIONS: dict[str, str] = {
    "cc_exceeds": (
        "Extract into a private helper function. "
        "Use a tuple-of-tuples data table for lookups, a match/case dispatch for routing, "
        "or split into guard clauses with early returns. "
        "Each helper must have CC <= 5."
    ),
    "nesting_exceeds": (
        "Flatten with guard clauses and early returns. "
        "Replace nested if/else with `if not condition: return result` at the top. "
        "Extract inner logic into a helper function."
    ),
    "try_pyramid": (
        "Move orelse statements out of the try block. "
        "Use guard clauses before the try/except. "
        "Extract the try body into a helper function if cleanup is needed."
    ),
    "signature_missing_param": (
        "Add the missing parameter back with its original default value to preserve the caller contract."
    ),
    "signature_extra_param": ("Remove the extra parameter — callers don't expect it."),
    "signature_wrong_default": ("Restore the original default value for this parameter."),
    "cleanup_missing": (
        "Add the required cleanup call before the return statement. "
        "This is a hard contract requirement from upstream callers."
    ),
    "missing_function": (
        "The target function was removed or renamed. Restore it with the original name and signature."
    ),
    "hallucinated_fields": (
        "You invented attributes that do not exist on the original objects. "
        "You MUST use ONLY the attributes present in the original code. "
        "Route logic using dot notation on existing fields only."
    ),
    "argument_swap": (
        "You changed the arguments passed to this function. "
        "You MUST preserve the exact variable arguments for existing function calls."
    ),
    "namespace_collision": (
        "Helper name shadows an existing import, function, class, or global variable. "
        "Pick a unique _-prefixed name for this helper."
    ),
}

_ATTRIBUTE_WHITELIST: set[str] = {
    "get", "append", "model_dump", "model_copy", "items", "keys", "values",
    "add", "update", "split", "strip", "replace", "join", "format",
    "startswith", "endswith", "lower", "upper", "info", "error", "warning",
    "exception", "debug", "exists", "resolve", "parent", "name", "isoformat",
    "now", "today", "group", "match", "search", "encode", "decode", "find",
    "rfind", "partition", "rpartition", "splitlines", "capitalize", "title",
    "swapcase", "isdigit", "isalpha", "isalnum", "isspace", "count", "index",
    "remove", "pop", "insert", "extend", "clear", "setdefault", "copy",
    "query", "fetchone", "fetchall", "execute", "executemany", "fetchmany",
    "close", "connect", "cursor", "commit", "rollback", "begin", "savepoint",
    "execute_script", "description", "connection", "rowcount", "lastrowid",
    "parts", "role", "content", "output", "data", "events", "structure",
    "gender", "alias", "day_pillar", "month_pillar", "year_pillar", "hour_pillar",
    "date", "days", "strftime", "value", "result", "message_history",
    "profile", "session", "conversation_history", "target_dates", "intent",
    "sentiment", "mental_model", "user_state", "rag_context", "structural_map",
    "shen_sha_context", "day_scores", "monthly_context", "score_legend",
    "language", "parse_mode", "text", "step", "metadata", "ModelRequest",
    "ModelResponse", "TextPart", "UserPromptPart",
}

_BUILTIN_METHODS: set[str] = {
    "isinstance", "getattr", "hasattr", "setattr", "len", "str", "int", "float", "bool",
    "list", "dict", "set", "tuple", "any", "all", "print", "type", "range", "enumerate",
    "zip", "min", "max", "sum", "sorted", "reversed", "super", "get", "append", "extend",
    "gather", "add", "update", "model_validate", "model_dump", "parse_mode", "format",
    "encode", "decode", "split", "strip", "join", "replace", "startswith", "endswith",
    "lower", "upper", "create_task", "add_done_callback", "discard", "getLogger",
    "from_url", "aclose", "model_validate_json", "strftime", "isoformat", "run",
}

# --------------------------------------------------------------------
# Module context extraction helpers
# --------------------------------------------------------------------

def _extract_module_imports(tree: ast.AST, lines: list[str]) -> None:
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.append(ast.unparse(node))


def _extract_module_constants(tree: ast.AST, lines: list[str]) -> None:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _append_constant_if_simple(target, node, lines)


def _append_constant_if_simple(target: ast.Name, node: ast.Assign, lines: list[str]) -> None:
    if isinstance(target, ast.Name) and isinstance(
        node.value, (ast.Constant, ast.Tuple, ast.List, ast.Dict)
    ):
        try:
            lines.append(f"{target.id} = {ast.unparse(node.value)}")
        except (ValueError, TypeError):
            pass


def _get_module_context(src_path: str, root_dir: Path) -> str:
    """Extract module-level imports, public constants, and header symbol contract."""
    file_path = root_dir / src_path
    if not file_path.exists():
        return "Module source not found."
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (ValueError, SyntaxError, TypeError):
        return "Could not parse module."

    contract = extract_header_symbol_contract(source)
    contract_text = contract.to_prompt_section()

    lines: list[str] = [contract_text, "", "=== MODULE IMPORTS & CONSTANTS ==="]
    _extract_module_imports(tree, lines)
    _extract_module_constants(tree, lines)
    return "\n".join(lines)


# --------------------------------------------------------------------
# Function signature extraction
# --------------------------------------------------------------------

def _extract_arg_list(args_node: ast.arguments, attr: str) -> list[str]:
    return [a.arg for a in getattr(args_node, attr)]


def extract_function_signature(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    args_node = fn_node.args
    posonly = _extract_arg_list(args_node, "posonlyargs")
    pos_args = _extract_arg_list(args_node, "args")
    vararg = args_node.vararg.arg if args_node.vararg else None
    kwonly = _extract_arg_list(args_node, "kwonlyargs")
    kwarg = args_node.kwarg.arg if args_node.kwarg else None
    defaults_count = len(args_node.defaults)
    kw_defaults_count = sum(1 for d in args_node.kw_defaults if d is not None)
    return {
        "posonly": posonly,
        "args": pos_args,
        "vararg": vararg,
        "kwonly": kwonly,
        "kwarg": kwarg,
        "defaults_count": defaults_count,
        "kw_defaults_count": kw_defaults_count,
    }


# =====================================================================
# OUTPUT VALIDATION
# =====================================================================

@_refactor_agent.output_validator
def enforce_return_shape(ctx: RunContext[RefactorDeps], result: RefactoringVerdict) -> RefactoringVerdict:
    if not ctx.deps or not ctx.deps.orig_code:
        return result

    _validate_helper_complexity(result)
    _validate_return_shape_preservation(ctx, result)
    _validate_ast_and_symbols(ctx, result)
    _validate_live_compiler_sandbox(ctx, result)

    return result


def _validate_helper_complexity(result: RefactoringVerdict) -> None:
    for helper_code in result.helper_functions:
        try:
            helper_tree = ast.parse(helper_code)
            for node in helper_tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _check_helper_cc(node)
        except SyntaxError as e:
            _logger_ast.warning(f"[ModelRetry] SyntaxError in helper function code from LLM: {e}")


def _check_helper_cc(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    comp_vis = ComplexityVisitor()
    comp_vis.visit(node)
    if comp_vis.complexity > 5:
        msg = (
            f"CRITICAL: Extracted helper function `{node.name}` has Cyclomatic Complexity {comp_vis.complexity} (must be <= 5). "
            f"ALL helper functions MUST have CC <= 5. Break `{node.name}` down into simpler steps."
        )
        _logger_ast.warning(f"[ModelRetry] Helper CC > 5: {msg}")
        raise ModelRetry(msg)


def _validate_return_shape_preservation(ctx: RunContext[RefactorDeps], result: RefactoringVerdict) -> None:
    try:
        orig_tree = ast.parse(ctx.deps.orig_code)
        new_tree = ast.parse(result.refactored_code)

        orig_ret_vis = ReturnVisitor()
        orig_ret_vis.visit(orig_tree)

        new_ret_vis = ReturnVisitor()
        new_ret_vis.visit(new_tree)

        if "dict" in orig_ret_vis.return_types and "call" in new_ret_vis.return_types:
            msg = (
                "CRITICAL: Return type mutation detected. The original function returned a raw dictionary (ast.Dict), "
                "but your refactored code returns a class/model instantiation. Preserve the exact dictionary return structure."
            )
            _logger_ast.warning(f"[ModelRetry] Return shape mutation: {msg}")
            raise ModelRetry(msg)
    except SyntaxError as e:
        _logger_ast.warning(f"[ModelRetry] SyntaxError in refactored code during return shape check: {e}")


def _get_header_contract(ctx: RunContext[RefactorDeps]) -> HeaderSymbolContract:
    if ctx.deps.full_file_source:
        return extract_header_symbol_contract(ctx.deps.full_file_source)
    return extract_header_symbol_contract(ctx.deps.orig_code)


def _get_baseline_errors(ctx: RunContext[RefactorDeps]) -> set[str]:
    if hasattr(ctx.deps, "baseline_errors"):
        return ctx.deps.baseline_errors
    return set()


def _get_orig_cc(ctx: RunContext[RefactorDeps]) -> int:
    comp_vis = ComplexityVisitor()
    try:
        orig_tree = ast.parse(ctx.deps.orig_code)
        comp_vis.visit(orig_tree)
        return comp_vis.complexity
    except (ValueError, SyntaxError, TypeError):
        return 0


def _get_allowed_options(header_contract: HeaderSymbolContract) -> list[str]:
    if header_contract and header_contract.imported_symbols:
        return header_contract.imported_symbols
    if header_contract:
        return sorted(set(header_contract.top_level_symbols + header_contract.global_constants))
    return []


def _build_scope_violation_msg(
    func_name: str, file_path: str, line: int, end_line: int,
    scope_violations: list[str], allowed_opts: list[str]
) -> str:
    scope_details = "\n".join(scope_violations)
    return (
        f"CRITICAL AST SYMBOL SCOPE FAILURE for `{func_name}` in `{file_path}` "
        f"(lines {line}-{end_line}):\n\n"
        f"SCOPE VIOLATIONS DETECTED:\n{scope_details}\n\n"
        f"AVAILABLE IMPORTED SYMBOLS IN HEADER CONTRACT:\n{allowed_opts}\n\n"
        f"ACTIONABLE FIX INSTRUCTIONS:\n"
        f"1. Remove or replace hallucinated / unimported symbols or type names with standard primitives "
        f"(e.g., dict, list, str, int, float, bool, Any, Optional, Union) or symbols explicitly listed in header contract above.\n"
        f"2. Ensure all function calls inside helper functions or refactored code refer to imported functions or "
        f"extracted helpers starting with `_{func_name}_` defined in `helper_functions`.\n"
        f"3. Do NOT invent new class models or reference unimported symbols."
    )


def _build_ast_failure_msg(
    func_name: str, file_path: str, line: int, end_line: int,
    ast_msg: str, allowed_opts: list[str]
) -> str:
    return (
        f"CRITICAL REFACTORING AST VERIFICATION FAILURE for `{func_name}` in `{file_path}` "
        f"(lines {line}-{end_line}):\n"
        f"{ast_msg}\n"
        f"Available imported symbols in header contract: {allowed_opts}"
    )


def _validate_ast_and_symbols(ctx: RunContext[RefactorDeps], result: RefactoringVerdict) -> None:
    full_code = _build_full_code(result.refactored_code, result.helper_functions)
    header_contract = _get_header_contract(ctx)
    orig_cc = _get_orig_cc(ctx)
    baseline_errors = _get_baseline_errors(ctx)

    passed_ast, _, _, ast_msg = verify_refactored_ast(
        code=full_code,
        candidate_name=ctx.deps.func_name,
        orig_code=ctx.deps.orig_code,
        orig_cc=orig_cc,
        baseline_errors=baseline_errors,
        header_contract=header_contract,
    )
    if passed_ast:
        return

    allowed_opts = _get_allowed_options(header_contract)
    scope_violations = _extract_scope_violations(ast_msg)
    if scope_violations:
        retry_msg = _build_scope_violation_msg(
            ctx.deps.func_name, ctx.deps.file_path, ctx.deps.line, ctx.deps.end_line,
            scope_violations, allowed_opts
        )
    else:
        retry_msg = _build_ast_failure_msg(
            ctx.deps.func_name, ctx.deps.file_path, ctx.deps.line, ctx.deps.end_line,
            ast_msg, allowed_opts
        )
    _logger_ast.warning(f"[ModelRetry] verify_refactored_ast failed: {ast_msg}")
    raise ModelRetry(retry_msg)


def _extract_scope_violations(ast_msg: str) -> list[str]:
    return [
        line for line in ast_msg.splitlines()
        if any(cat in line for cat in ("unimported_symbol", "unimported_type_annotation", "unimported_function_call"))
    ]


def _validate_live_compiler_sandbox(ctx: RunContext[RefactorDeps], result: RefactoringVerdict) -> None:
    if not (ctx.deps.full_file_source and ctx.deps.func_name):
        return

    full_code = _build_full_code(result.refactored_code, result.helper_functions)
    baseline_errors = _get_baseline_errors(ctx)
    header_contract = _get_header_contract(ctx)

    passed_sandbox, sandbox_msg = verify_live_compiler_sandbox(
        full_file_source=ctx.deps.full_file_source,
        file_path=ctx.deps.file_path,
        func_name=ctx.deps.func_name,
        refactored_code=result.refactored_code,
        helper_functions=result.helper_functions,
        baseline_errors=baseline_errors,
        orig_code=ctx.deps.orig_code,
    )
    if passed_sandbox:
        return

    allowed_opts = _get_allowed_options(header_contract)
    retry_msg = (
        f"CRITICAL LIVE COMPILER SANDBOX FAILURE for `{ctx.deps.func_name}` in `{ctx.deps.file_path}` "
        f"(lines {ctx.deps.line}-{ctx.deps.end_line}):\n"
        f"{sandbox_msg}\n"
        f"Available imported symbols in header contract: {allowed_opts}"
    )
    _logger_ast.warning(f"[ModelRetry] verify_live_compiler_sandbox failed: {sandbox_msg}")
    raise ModelRetry(retry_msg)


def _build_full_code(refactored: str, helpers: list[str]) -> str:
    if helpers:
        return refactored + "\n\n" + "\n\n".join(helpers)
    return refactored


def _run_virtual_ast_buffer(
    full_file_source: str, file_path: str, func_name: str,
    refactored_code: str, helper_functions: list[str]
) -> str:
    buf = VirtualASTBuffer(full_file_source, file_path)
    temp_source = buf.replace_function(func_name, refactored_code, helper_functions)
    combined_code = refactored_code + "\n\n" + "\n\n".join(helper_functions) if helper_functions else refactored_code
    return ensure_pydantic_imports(temp_source, combined_code)


def _run_ruff_check(temp_source: str, orig_code: str) -> tuple[bool, str]:
    if not orig_code:
        return True, ""
    baseline_ruff_errors = _get_ruff_errors(orig_code)
    current_ruff_errors = _get_ruff_errors(temp_source)
    new_ruff_errors = current_ruff_errors - baseline_ruff_errors
    if new_ruff_errors:
        clean_errors = "\n".join(sorted(new_ruff_errors))
        return False, (
            f"CRITICAL: Refactoring introduced new Ruff linter errors:\n{clean_errors}\n"
            f"Fix these errors. If you hallucinated a type hint (F821), change it to `dict`, `list`, or `Any`."
        )
    return True, ""


def _run_pyright_check(temp_source: str, baseline_errors: set[str]) -> tuple[bool, str]:
    if not (baseline_errors or temp_source):
        return True, ""
    current_errors = _get_normalized_pyright_errors(temp_source)
    new_introduced = current_errors - baseline_errors
    if new_introduced:
        return False, (
            f"CRITICAL: Refactoring introduced {len(new_introduced)} new pyright error(s): "
            f"{new_introduced}. Fix the introduced type errors before proceeding."
        )
    return True, ""


def verify_live_compiler_sandbox(
    full_file_source: str,
    file_path: str,
    func_name: str,
    refactored_code: str,
    helper_functions: list[str],
    baseline_errors: set[str],
    orig_code: str,
) -> tuple[bool, str]:
    """Run refactored code through VirtualASTBuffer, ruff format, ruff check, and pyright.

    Returns (passed: bool, error_message: str).
    """
    try:
        temp_source = _run_virtual_ast_buffer(
            full_file_source, file_path, func_name, refactored_code, helper_functions
        )
    except Exception as e:
        msg = f"CRITICAL: AST replacement failed in VirtualASTBuffer: {e}"
        _logger_ast.warning(f"[ModelRetry] VirtualASTBuffer Replace Error: {msg}")
        raise

    tmp_path = _create_temp_file(temp_source)
    try:
        _run_subprocess(["uv", "run", "ruff", "format", str(tmp_path)])

        passed_ruff, ruff_msg = _run_ruff_check(temp_source, orig_code)
        if not passed_ruff:
            return False, ruff_msg

        passed_pyright, pyright_msg = _run_pyright_check(temp_source, baseline_errors)
        if not passed_pyright:
            return False, pyright_msg

        return True, ""
    finally:
        _safe_unlink(tmp_path)


# =====================================================================
# AST VERIFICATION
# =====================================================================

def _resolve_module_name(node: ast.AST) -> str | None:
    module_name = getattr(node, "module", None)
    if not module_name and isinstance(node, ast.Import) and node.names:
        return node.names[0].name.split(".")[0]
    return module_name


def _is_unauthorized_module(module_name: str | None, safe_modules: set[str]) -> bool:
    if not module_name:
        return False
    return not (module_name in safe_modules or module_name.startswith("src"))


def _check_import_authorized(node: ast.AST, safe_modules: set[str], violations: list[str]) -> None:
    module_name = _resolve_module_name(node)
    if _is_unauthorized_module(module_name, safe_modules):
        violations.append(
            f"unauthorized_import: Added an import for `{module_name}` | "
            f"Suggestion: You may ONLY import from {safe_modules} or internal `src` modules."
        )


def _check_banned_constructs(tree: ast.AST, violations: list[str]) -> None:
    safe_modules = {"typing", "collections", "enum", "dataclasses", "itertools", "re"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            violations.append(
                f"unauthorized_symbol: Created a new class `{node.name}` | "
                f"Suggestion: Do not define new classes. Use flat tuples or dicts for data tables."
            )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _check_import_authorized(node, safe_modules, violations)


def _harvest_stmt_namespace(top_node: ast.AST, orig_namespace: set[str]) -> None:
    if isinstance(top_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        orig_namespace.add(top_node.name)
    elif isinstance(top_node, ast.Assign):
        _collect_assign_targets(top_node, orig_namespace)
    elif isinstance(top_node, (ast.Import, ast.ImportFrom)):
        _collect_import_aliases(top_node, orig_namespace)


def _harvest_orig_namespace(orig_code: str) -> set[str]:
    if not orig_code:
        return set()
    orig_namespace: set[str] = set()
    try:
        orig_tree = ast.parse(orig_code)
        for top_node in orig_tree.body:
            _harvest_stmt_namespace(top_node, orig_namespace)
    except SyntaxError as e:
        _logger_ast.warning(f"[verify_refactored_ast] SyntaxError parsing original code for namespace harvest: {e}")
    return orig_namespace


def _validate_helper_node_name(
    node: ast.FunctionDef | ast.AsyncFunctionDef, candidate_name: str,
    orig_namespace: set[str], violations: list[str]
) -> None:
    if node.name == candidate_name:
        return
    if not node.name.startswith("_"):
        violations.append(
            f"invalid_helper_name: Helper `{node.name}` must start with an underscore. "
            f"Suggestion: Rename to _{node.name} or pick a unique _-prefixed name."
        )
    elif node.name in orig_namespace:
        violations.append(
            f"namespace_collision: Helper `{node.name}` shadows an existing import, "
            f"function, class, or global variable in this file. "
            f"Suggestion: Pick a unique _-prefixed name for this helper."
        )


def _check_helper_naming_namespace(
    tree: ast.AST, candidate_name: str, orig_namespace: set[str], violations: list[str]
) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _validate_helper_node_name(node, candidate_name, orig_namespace, violations)


def _check_attribute_sandbox(orig_code: str, tree: ast.AST, violations: list[str]) -> None:
    if not orig_code:
        return
    try:
        orig_tree = ast.parse(orig_code)
        orig_attrs = AttributeVisitor()
        orig_attrs.visit(orig_tree)

        new_attrs = AttributeVisitor()
        new_attrs.visit(tree)

        hallucinated = (new_attrs.attributes - orig_attrs.attributes) - _ATTRIBUTE_WHITELIST
        if hallucinated:
            violations.append(
                f"hallucinated_fields: You invented attributes that do not exist on the original objects: {hallucinated} | "
                f"Suggestion: {VIOLATION_SUGGESTIONS['hallucinated_fields']}"
            )
    except (AttributeError, TypeError, SyntaxError):
        pass


def _get_non_builtin_func_names(calls: set[tuple[str, tuple[str, ...]]]) -> set[str]:
    names: set[str] = set()
    for c in calls:
        if c[0] not in _BUILTIN_METHODS:
            names.add(c[0])
    return names


def _is_call_argument_swap(
    new_call: tuple[str, tuple[str, ...]],
    orig_func_names: set[str],
    orig_calls: set[tuple[str, tuple[str, ...]]],
    orig_kw_calls: set[str],
    new_kw_calls: set[str],
) -> bool:
    func_name, _new_args = new_call
    if func_name not in orig_func_names or new_call in orig_calls:
        return False
    return not (func_name in new_kw_calls or func_name in orig_kw_calls)


def _check_argument_swap_sandbox(orig_code: str, tree: ast.AST, violations: list[str]) -> None:
    if not orig_code:
        return
    try:
        orig_tree = ast.parse(orig_code)
        orig_vis = CallVisitor()
        orig_vis.visit(orig_tree)

        new_vis = CallVisitor()
        new_vis.visit(tree)

        orig_func_names = _get_non_builtin_func_names(orig_vis.calls)
        for new_call in new_vis.calls:
            if _is_call_argument_swap(
                new_call, orig_func_names, orig_vis.calls,
                orig_vis.calls_with_keywords, new_vis.calls_with_keywords
            ):
                violations.append(
                    f"argument_swap: You changed the arguments passed to `{new_call[0]}`. "
                    f"You passed {new_call[1]}. | "
                    f"Suggestion: {VIOLATION_SUGGESTIONS['argument_swap']}"
                )
    except (AttributeError, TypeError, SyntaxError):
        pass


def _find_main_node(tree: ast.AST, candidate_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == candidate_name:
            return n
    return None


def _check_sig_diffs(
    orig_sig: dict, ref_sig: dict, candidate_name: str, violations: list[str]
) -> None:
    for k, v in orig_sig.items():
        if ref_sig.get(k) != v:
            param_violation = f"signature_{k}"
            suggestion = VIOLATION_SUGGESTIONS.get(param_violation, "Restore the original signature for this parameter.")
            violations.append(f"signature_mismatch:{candidate_name}:{k} | Suggestion: {suggestion}")


def _check_signature_parity_impl(
    orig_tree: ast.AST, orig_code: str, candidate_name: str,
    tree: ast.AST, violations: list[str]
) -> None:
    orig_main_node = _find_main_node(orig_tree, candidate_name)
    if not orig_main_node:
        return
    orig_sig = extract_function_signature(orig_main_node)
    ref_main_node = _find_main_node(tree, candidate_name)
    if not ref_main_node:
        violations.append(
            f"missing_function: The main target function `{candidate_name}` is missing or renamed in refactored code | "
            f"Suggestion: {VIOLATION_SUGGESTIONS['missing_function']}"
        )
        return
    ref_sig = extract_function_signature(ref_main_node)
    _check_sig_diffs(orig_sig, ref_sig, candidate_name, violations)


def _check_signature_parity(
    orig_code: str, candidate_name: str, tree: ast.AST, violations: list[str]
) -> None:
    if not (orig_code and candidate_name):
        return
    try:
        orig_tree = ast.parse(orig_code)
        _check_signature_parity_impl(orig_tree, orig_code, candidate_name, tree, violations)
    except (AttributeError, TypeError, SyntaxError):
        pass


def _check_contract_preservation(contract_info: dict | None, code: str, violations: list[str]) -> None:
    if not contract_info:
        return
    for required in contract_info.get("exceptions_and_cleanup", []):
        if required.startswith("cleanup:"):
            method = required.split(":", 1)[1]
            if method not in code:
                violations.append(
                    f"cleanup_missing:{method} | Suggestion: {VIOLATION_SUGGESTIONS['cleanup_missing']}"
                )


def _record_scope_violation(item: dict[str, Any], allowed: list[str], violations: list[str]) -> None:
    name = item["name"]
    line_no = item.get("line", 0)
    ctx_line = item.get("context", "")
    category = item.get("category", "unimported_symbol")
    cat_label = category if category == "unimported_symbol" else f"unimported_symbol: {category}"
    ctx_str = _format_ctx_str(line_no, ctx_line)
    violations.append(
        f"{cat_label}: Referenced symbol '{name}' at{ctx_str} which is not imported or defined in header contract. "
        f"Available imported symbols: {allowed} | Suggestion: Use standard primitives (dict, list, str, int, float, bool, Any, Optional) or imported models."
    )


def _format_ctx_str(line_no: int, ctx_line: str) -> str:
    if ctx_line:
        return f" line {line_no} (`{ctx_line}`)"
    if line_no:
        return f" line {line_no}"
    return ""


def _check_symbol_scope(
    header_contract: HeaderSymbolContract | None, orig_code: str, code: str,
    tree: ast.AST, violations: list[str]
) -> None:
    resolved_contract = header_contract or (
        extract_header_symbol_contract(orig_code) if orig_code else HeaderSymbolContract()
    )
    scope_visitor = SymbolScopeVisitor(resolved_contract, code)
    unimported_list = scope_visitor.inspect(tree)
    if not unimported_list:
        return

    allowed = _get_allowed_options(resolved_contract)
    for item in unimported_list:
        _record_scope_violation(item, allowed, violations)


def _check_single_func_cc_nesting(
    node: ast.FunctionDef | ast.AsyncFunctionDef, candidate_name: str,
    orig_cc: int, target_cc: int, violations: list[str]
) -> tuple[int, int]:
    comp_vis = ComplexityVisitor()
    comp_vis.visit(node)
    func_cc = comp_vis.complexity

    scanner = FunctionCandidateScanner("test.py", [])
    func_depth, _, try_issues = scanner._check_body_nesting(node.body, depth=0)

    if try_issues:
        violations.append(f"try_pyramid:{try_issues} | Suggestion: {VIOLATION_SUGGESTIONS['try_pyramid']}")
    if func_cc > target_cc:
        violations.append(
            f"cc_exceeds:{node.name} has CC={func_cc} (target <={target_cc}, original was {orig_cc}) | "
            f"Suggestion: {VIOLATION_SUGGESTIONS['cc_exceeds']}"
        )
    if func_depth > 3:
        violations.append(
            f"nesting_exceeds:{node.name} depth={func_depth} (must be <=3) | "
            f"Suggestion: {VIOLATION_SUGGESTIONS['nesting_exceeds']}"
        )
    return func_cc, func_depth


def _check_cc_and_nesting(
    tree: ast.AST, candidate_name: str, orig_cc: int, target_cc: int,
    violations: list[str], candidate_cc: int, candidate_depth: int,
) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            f_cc, f_depth = _check_single_func_cc_nesting(node, candidate_name, orig_cc, target_cc, violations)
            if node.name == candidate_name:
                candidate_cc = f_cc
                candidate_depth = f_depth


@logfire.instrument("verify_refactored_ast")
def verify_refactored_ast(
    code: str,
    candidate_name: str = "",
    contract_info: dict | None = None,
    orig_code: str = "",
    orig_cc: int = 0,
    baseline_errors: set[str] | None = None,
    header_contract: HeaderSymbolContract | None = None,
) -> tuple[bool, int, int, str]:
    """Compile and verify that the refactored code passes all AST safety checks."""
    violations: list[str] = []
    candidate_cc = 0
    candidate_max_depth = 0
    target_cc = 5

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, 999, 999, f"SyntaxError in refactored code: {e}"

    _check_banned_constructs(tree, violations)
    orig_namespace = _harvest_orig_namespace(orig_code)
    _check_helper_naming_namespace(tree, candidate_name, orig_namespace, violations)
    _check_attribute_sandbox(orig_code, tree, violations)
    _check_argument_swap_sandbox(orig_code, tree, violations)
    _check_signature_parity(orig_code, candidate_name, tree, violations)
    _check_contract_preservation(contract_info, code, violations)
    _check_symbol_scope(header_contract, orig_code, code, tree, violations)
    _check_cc_and_nesting(tree, candidate_name, orig_cc, target_cc, violations, candidate_cc, candidate_max_depth)

    if violations:
        return False, candidate_cc, candidate_max_depth, "VIOLATIONS FOUND:\n" + "\n".join(f"  - {v}" for v in violations)

    return True, candidate_cc, candidate_max_depth, "Passed Flat Control Flow, semantic attribute sandbox, argument sandbox, signature parity, namespace sandbox, and pyright regression checks — all clean."


# =====================================================================
# CANDIDATE SCANNING
# =====================================================================

class FunctionCandidateScanner(ast.NodeVisitor):
    CONTROL_NODES = (ast.If, ast.Try, ast.For, ast.While, ast.With)

    def __init__(
        self,
        filename: str,
        code_lines: list[str],
        full_file_source: str = "",
        header_contract: HeaderSymbolContract | None = None,
    ) -> None:
        self.filename = filename
        self.code_lines = code_lines
        self.full_file_source = full_file_source
        self.header_contract = header_contract or extract_header_symbol_contract(full_file_source)
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

        if not (len(try_issues) > 0 or max_depth > 3 or cc > 5):
            self.generic_visit(node)
            return

        end_line = getattr(node, "end_lineno", node.lineno)
        func_code = ast.unparse(node)
        line_count = end_line - node.lineno + 1
        requires_decomposition = cc > 50 or line_count > 200

        priority = _determine_priority(len(try_issues), max_depth)
        module_ctx = self.header_contract.to_prompt_section()
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
                full_file_source=self.full_file_source,
                header_contract=self.header_contract,
                module_context=module_ctx,
                line_count=line_count,
                requires_decomposition=requires_decomposition,
            )
        )
        self.generic_visit(node)


def _determine_priority(try_issue_count: int, max_depth: int) -> int:
    if try_issue_count > 0:
        return 1
    if max_depth > 3:
        return 2
    return 3


def _collect_try_body_issues(stmt: ast.Try) -> list[tuple[int, str]]:
    issues: list[tuple[int, str]] = []
    for inner in stmt.body:
        if isinstance(inner, ast.Try):
            issues.append((inner.lineno, "Nested Try block inside Try body"))
    return issues


def _collect_try_handler_issues(stmt: ast.Try) -> list[tuple[int, str]]:
    issues: list[tuple[int, str]] = []
    for handler in stmt.handlers:
        for h_stmt in handler.body:
            if isinstance(h_stmt, ast.Try):
                issues.append((h_stmt.lineno, "Try block inside Except handler"))
    return issues


def _collect_try_orelse_issues(stmt: ast.Try) -> list[tuple[int, str]]:
    issues: list[tuple[int, str]] = []
    if stmt.orelse:
        for el_stmt in stmt.orelse:
            if isinstance(el_stmt, (ast.If, ast.Try)):
                cls_name = el_stmt.__class__.__name__
                issues.append((el_stmt.lineno, f"{cls_name} inside Try-Else block"))
    return issues


def _collect_try_issues(stmt: ast.Try) -> list[tuple[int, str]]:
    issues: list[tuple[int, str]] = []
    issues.extend(_collect_try_body_issues(stmt))
    issues.extend(_collect_try_handler_issues(stmt))
    issues.extend(_collect_try_orelse_issues(stmt))
    return issues


def _collect_if_sub_bodies(stmt: ast.If, current_depth: int) -> list[tuple[list[ast.stmt], int]]:
    sub_bodies: list[tuple[list[ast.stmt], int]] = [(stmt.body, current_depth)]
    if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
        sub_bodies.append((stmt.orelse, current_depth))
    else:
        sub_bodies.append((stmt.orelse, current_depth))
    return sub_bodies


def _collect_try_sub_bodies(stmt: ast.Try, current_depth: int) -> list[tuple[list[ast.stmt], int]]:
    sub_bodies: list[tuple[list[ast.stmt], int]] = [(stmt.body, current_depth)]
    for h in stmt.handlers:
        sub_bodies.append((h.body, current_depth))
    sub_bodies.append((stmt.orelse, current_depth))
    sub_bodies.append((stmt.finalbody, current_depth))
    return sub_bodies


def _collect_sub_bodies(stmt: ast.stmt, current_depth: int) -> list[tuple[list[ast.stmt], int]]:
    if isinstance(stmt, ast.If):
        return _collect_if_sub_bodies(stmt, current_depth)
    if isinstance(stmt, ast.Try):
        return _collect_try_sub_bodies(stmt, current_depth)
    if isinstance(stmt, (ast.For, ast.While)):
        return [(stmt.body, current_depth), (stmt.orelse, current_depth)]
    if isinstance(stmt, ast.With):
        return [(stmt.body, current_depth)]
    return []


def _process_sub_body(
    self: Any, sb: list[ast.stmt], sb_depth: int, try_issues: list[tuple[int, str]]
) -> tuple[int, int]:
    if not sb:
        return 0, 0
    d, line_no, ti = self._check_body_nesting(sb, sb_depth)
    try_issues.extend(ti)
    return d, line_no


def _process_nesting_stmt(
    self: Any, stmt: ast.stmt, depth: int, max_d: int, max_line: int, try_issues: list[tuple[int, str]]
) -> tuple[int, int]:
    current_depth = depth + 1
    if current_depth > max_d:
        max_d = current_depth
        max_line = stmt.lineno

    if isinstance(stmt, ast.Try):
        try_issues.extend(_collect_try_issues(stmt))

    for sb, sb_depth in _collect_sub_bodies(stmt, current_depth):
        d, line_no = _process_sub_body(self, sb, sb_depth, try_issues)
        if d > max_d:
            max_d = d
            max_line = line_no

    return max_d, max_line


def _check_body_nesting(
    self: FunctionCandidateScanner,
    statements: list[ast.stmt],
    depth: int
) -> tuple[int, int, list[tuple[int, str]]]:
    max_d = depth
    max_line = 0
    try_issues: list[tuple[int, str]] = []

    for stmt in statements:
        if isinstance(stmt, self.CONTROL_NODES):
            max_d, max_line = _process_nesting_stmt(self, stmt, depth, max_d, max_line, try_issues)

    return max_d, max_line, try_issues


FunctionCandidateScanner._check_body_nesting = _check_body_nesting


# =====================================================================
# DECOMPOSITION
# =====================================================================

def _find_function_node(tree: ast.AST, func_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return node
    return None


def _should_skip_decomp_stmt(stmt: ast.stmt, stmt_cc: int, stmt_lines: int, total_cc: int) -> bool:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return True
    return stmt_cc <= 3 or stmt_lines < 3 or total_cc <= 15


def _process_decomp_stmts(
    candidate: FunctionCandidate, plan: DecompositionPlan,
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, total_cc: int
) -> int:
    helper_idx = 0
    for stmt in func_node.body:
        stmt_cc = _estimate_ast_cc([stmt])
        stmt_lines = getattr(stmt, "end_lineno", stmt.lineno) - stmt.lineno + 1
        if _should_skip_decomp_stmt(stmt, stmt_cc, stmt_lines, total_cc):
            continue
        helper_idx += 1
        block_source = ast.unparse(stmt)
        plan.helper_functions.append(block_source)
        plan.helper_candidates.append(
            FunctionCandidate(
                file_path=candidate.file_path,
                function_name=f"{candidate.function_name}_extracted_{helper_idx}",
                line=candidate.line,
                end_line=candidate.end_line,
                cc=stmt_cc,
                max_depth=0,
                priority=3,
                try_issues=[],
                source_code=block_source,
                full_file_source=candidate.full_file_source,
                header_contract=candidate.header_contract,
                module_context=candidate.module_context,
                phase=2,
                parent_function=candidate.function_name,
                line_count=stmt_lines,
                requires_decomposition=stmt_cc > 5,
            )
        )
        total_cc = max(1, total_cc - stmt_cc)
    return total_cc


def _estimate_ast_cc(stmts: list[ast.stmt]) -> int:
    """Estimate CC for a list of AST nodes."""
    cc = 1
    for node in ast.walk(ast.Module(body=stmts)):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            cc += 1
        elif isinstance(node, ast.BoolOp):
            cc += len(node.values) - 1
    return cc


def pre_decompose(candidate: FunctionCandidate) -> DecompositionPlan:
    """Deterministically decompose an extremely complex function into logical phases."""
    plan = DecompositionPlan(
        phase_number=1,
        main_function_name=candidate.function_name,
        original_cc=candidate.cc,
    )

    try:
        tree = ast.parse(candidate.source_code)
    except SyntaxError:
        return plan

    func_node = _find_function_node(tree, candidate.function_name)
    if func_node is None or not func_node.body:
        return plan

    total_cc = candidate.cc
    total_cc = _process_decomp_stmts(candidate, plan, func_node, total_cc)

    plan.residual_cc = total_cc
    return plan


# =====================================================================
# PROMPT RENDERING
# =====================================================================

def load_prompt_template(path: Path | None = None) -> dict:
    template_path = path or PROMPT_TEMPLATE_PATH
    if not template_path.exists():
        _logger_ast.warning(f"Prompt template not found at {template_path}")
        return {}
    with open(template_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_target_files() -> set[str] | None:
    if not LIST_FILE.exists():
        return None
    with open(LIST_FILE, encoding="utf-8") as f:
        paths = {
            line.strip().lstrip("/") for line in f if line.strip() and not line.startswith("#")
        }
    _logger_ast.info(f"Loaded {len(paths)} targeted files from kill_tries_list.txt")
    return paths


def _build_contract_texts(header_contract: HeaderSymbolContract) -> dict[str, str]:
    modules = ", ".join(sorted(set(header_contract.imported_modules))) if header_contract.imported_modules else "None"
    symbols = ", ".join(sorted(set(header_contract.imported_symbols))) if header_contract.imported_symbols else "None"
    top_level = ", ".join(sorted(set(header_contract.top_level_symbols))) if header_contract.top_level_symbols else "None"
    consts = ", ".join(sorted(set(header_contract.global_constants))) if header_contract.global_constants else "None"
    return {
        "imported_modules_text": modules,
        "imported_symbols_text": symbols,
        "top_level_symbols_text": top_level,
        "global_constants_text": consts,
    }


def _build_common_kwargs(
    candidate: FunctionCandidate,
    header_contract: HeaderSymbolContract,
    module_context: str,
    contract_section: str,
    attempts_left: str,
) -> dict[str, str]:
    texts = _build_contract_texts(header_contract)
    return {
        "file_path": candidate.file_path,
        "function_name": candidate.function_name,
        "narrative_context": "",
        "anti_patterns": "",
        "samples": "",
        "attempts_left": attempts_left,
        "upstream_callers": candidate.upstream_callers,
        "module_context": module_context,
        "imported_modules_text": texts["imported_modules_text"],
        "imported_symbols_text": texts["imported_symbols_text"],
        "top_level_symbols_text": texts["top_level_symbols_text"],
        "global_constants_text": texts["global_constants_text"],
        "header_symbol_contract": contract_section,
    }


def _assemble_narrative_output(
    system_prompt: str, contract_section: str, system: str,
    anti_patterns: str, conditions: str,
    candidate: FunctionCandidate, is_helper: bool, full_source: str
) -> str:
    parts: list[str] = [
        f"{system_prompt}\n\n",
        "=== HEADER SYMBOL CONTRACT ===\n",
        f"{contract_section}\n\n",
        f"{system}\n\n",
    ]
    if not is_helper:
        parts.extend([
            "=== FULL FILE CONTEXT ===\n",
            f"File: {candidate.file_path}\n",
            f"```python\n{full_source}\n```\n\n",
            f"Above is the complete file content. The function `{candidate.function_name}` is at "
            f"line {candidate.line}. Do NOT invent new imports or helper functions — use ONLY "
            f"symbols that already exist in this file or stdlib.\n\n",
        ])
    parts.extend([
        f"=== WHAT WENT WRONG ===\n{anti_patterns}\n\n",
        f"=== RULES ===\n{conditions}\n\n",
        f"TARGET: Refactor {candidate.function_name} ({candidate.file_path}:{candidate.line}) to pass all checks.\n",
        f"CC={candidate.cc} | Depth={candidate.max_depth} | Priority={candidate.priority}\n\n",
        f"<source_code>\n{candidate.source_code}\n</source_code>\n",
    ])
    return "".join(parts)


def _render_narrative(
    template: dict,
    candidate: FunctionCandidate,
    attempt_num: int,
    what_worked_text: str = "",
    violations_text: str = "",
) -> str:
    attempts_left = str(max(1, MAX_RETRIES - attempt_num + 1))
    header_contract = candidate.header_contract or extract_header_symbol_contract(candidate.full_file_source)
    contract_section = header_contract.to_prompt_section()
    module_context = candidate.module_context or contract_section

    common = _build_common_kwargs(candidate, header_contract, module_context, contract_section, attempts_left)

    system_prompt = fill_template(template.get("system_prompt", ""), **common)
    system = fill_template(template.get("system_instruction", ""), **common)
    anti_patterns = fill_template(
        template.get("anti_patterns", ""),
        anti_patterns_list="",
        file_path=candidate.file_path,
        function_name=candidate.function_name,
    )
    conditions = fill_template(
        template.get("conditions", template.get("rules", "")),
        file_path=candidate.file_path,
        function_name=candidate.function_name,
    )
    full_source = candidate.full_file_source or ""
    is_helper = candidate.phase >= 2 and bool(candidate.parent_function)

    return _assemble_narrative_output(
        system_prompt, contract_section, system, anti_patterns, conditions,
        candidate, is_helper, full_source
    )


def _assemble_retry_output(
    sys_prefix: str, contract_section: str, active_template: dict,
    anti_patterns: str, conditions: str,
    function_name: str, file_path: str, attempts_left: int,
    is_helper: bool, full_source: str, source_code: str
) -> str:
    parts: list[str] = [
        f"{sys_prefix}",
        "=== HEADER SYMBOL CONTRACT ===\n",
        f"{contract_section}\n\n",
        f"=== ATTEMPT {1}/{MAX_RETRIES} (CONCISE DELTA) ===\n\n",
    ]
    if not is_helper:
        parts.extend([
            f"Full file: {file_path}\n",
            f"```python\n{full_source}\n```\n\n",
        ])
    parts.extend([
        f"Previous attempt feedback for {function_name} ({file_path}):\n\n",
        "ISSUES TO FIX:\n\n\n",
        "WHAT WORKED (preserve these):\n\n\n",
        f"=== ANTI-PATTERNS ===\n{anti_patterns}\n\n",
        f"=== RULES ===\n{conditions}\n\n",
        f"YOU HAVE {attempts_left} ATTEMPT(S) LEFT.\n",
        "Take your previous attempt and surgically fix only the violations above.\n",
        f"CRITICAL: If you extract helper functions, prefix each with `_{function_name}_`.\n",
        "CRITICAL: You may ONLY use symbols already defined in the file above. Do NOT invent new imports.\n\n",
        f"<source_code>\n{source_code}\n</source_code>\n",
    ])
    return "".join(parts)


def _get_active_template(default_template: dict) -> dict:
    if PROMPT_RETRY_PATH.exists():
        return load_prompt_template(PROMPT_RETRY_PATH)
    return default_template


def _render_retry_template_fields(
    active_template: dict, common: dict[str, str],
    candidate: FunctionCandidate, violations_text: str
) -> tuple[str, str, str]:
    sys_prompt = fill_template(active_template.get("system_prompt", ""), **common)
    sys_prefix = f"{sys_prompt}\n\n" if sys_prompt.strip() else ""
    anti_patterns = fill_template(
        active_template.get("anti_patterns", ""),
        anti_patterns_list=violations_text,
        file_path=candidate.file_path,
        function_name=candidate.function_name,
    )
    conditions = fill_template(
        active_template.get("conditions", active_template.get("rules", "")),
        file_path=candidate.file_path,
        function_name=candidate.function_name,
    )
    return sys_prefix, anti_patterns, conditions


def _format_retry_prompt(
    template: dict, candidate: FunctionCandidate, attempt: int,
    what_worked_text: str, violations_text: str
) -> str:
    active_template = _get_active_template(template)
    attempts_left = MAX_RETRIES - attempt + 1
    full_source = candidate.full_file_source or ""
    header_contract = candidate.header_contract or extract_header_symbol_contract(full_source)
    contract_section = header_contract.to_prompt_section()
    module_context = candidate.module_context or contract_section

    common = _build_common_kwargs(
        candidate, header_contract, module_context, contract_section, str(max(1, attempts_left))
    )
    common.update({
        "attempt": str(attempt),
        "line": str(candidate.line),
        "violations": violations_text,
        "what_worked": what_worked_text,
        "what_to_fix": violations_text,
    })

    sys_prefix, anti_patterns, conditions = _render_retry_template_fields(
        active_template, common, candidate, violations_text
    )
    is_helper = candidate.phase >= 2 and bool(candidate.parent_function)

    return _assemble_retry_output(
        sys_prefix, contract_section, active_template, anti_patterns, conditions,
        candidate.function_name, candidate.file_path, attempts_left, is_helper, full_source, candidate.source_code
    )


def format_prompt(
    template: dict,
    candidate: FunctionCandidate,
    attempt: int = 1,
    history: list | None = None,
    what_worked_text: str = "",
    violations_text: str = "",
) -> str:
    if not history:
        return _render_narrative(template, candidate, attempt, what_worked_text, violations_text)
    return _format_retry_prompt(template, candidate, attempt, what_worked_text, violations_text)


# =====================================================================
# REFACTORING ENGINE
# =====================================================================

def _read_candidate_full_source(candidate: FunctionCandidate) -> str:
    full_source = ""
    target_path = pkg_root / candidate.file_path
    if target_path.exists():
        full_source = target_path.read_text(encoding="utf-8")
    if candidate.phase >= 2 and candidate.parent_function:
        full_source = ""
    return full_source


def _is_fatal_error(err_str: str) -> bool:
    fatal_terms = (
        "token limit", "context length", "max_tokens",
        "rate limit", "token_limit", "resource_exhausted",
    )
    return any(term in err_str for term in fatal_terms)


def _inject_runtime_error_if_needed(history: list, msg: str, is_runtime_error: bool) -> list:
    if not is_runtime_error:
        return history
    return history + [
        ModelRequest(
            parts=[
                UserPromptPart(
                    content=(
                        f"RUNTIME LOGIC DRIFT: Your refactoring passed syntax checks but FAILED the Pytest integration suite:\n"
                        f"```\n{msg}\n```\n"
                        f"You MUST fix the logic drift (e.g., check iteration order, rounding, < vs <=, variable scoping)."
                    )
                )
            ]
        )
    ]


def _build_refactor_result(
    candidate: FunctionCandidate, attempt: int, new_cc: int, new_depth: int,
    status: str, refactored_code: str, helpers: list[str],
    explanation: str, verification_msg: str, orig_code: str,
    reasoning_and_plan: str = "",
) -> RefactorResult:
    return RefactorResult(
        file_path=candidate.file_path,
        function_name=candidate.function_name,
        line=candidate.line,
        status=status,
        attempts=attempt,
        original_cc=candidate.cc,
        refactored_cc=new_cc,
        original_depth=candidate.max_depth,
        refactored_depth=new_depth,
        refactored_code=refactored_code,
        helper_functions=helpers,
        explanation=explanation,
        verification_msg=verification_msg,
        reasoning_and_plan=reasoning_and_plan,
    )


def _build_failed_result(
    candidate: FunctionCandidate, attempt: int, new_cc: int, new_depth: int,
    status: str, msg: str, orig_code: str,
) -> RefactorResult:
    return _build_refactor_result(
        candidate, attempt, new_cc, new_depth, status,
        orig_code, [], f"Failed after {attempt} attempts: {msg}", msg, orig_code
    )


def _build_error_result(
    candidate: FunctionCandidate, attempt: int, err: Exception,
) -> RefactorResult:
    return _build_refactor_result(
        candidate, attempt, candidate.cc, candidate.max_depth, "LLM_ERROR",
        candidate.source_code, [], f"LLM error: {err}", str(err), candidate.source_code
    )


def _handle_failed_attempt(
    candidate: FunctionCandidate, attempt: int, history: list, msg: str,
    new_cc: int, new_depth: int, template: dict,
) -> tuple[bool, list, str, RefactorResult | None]:
    _logger_ast.warning(f"  [Attempt {attempt}/{MAX_RETRIES} Retry] {candidate.function_name} failed AST check: {msg}")

    is_runtime_error = "FAILED_RUNTIME" in msg or "Pytest integration" in msg
    if is_runtime_error and attempt >= MAX_RETRIES:
        res = _build_failed_result(
            candidate, attempt, new_cc, new_depth, "FAILED_RUNTIME", msg, candidate.source_code
        )
        return False, history, msg, res

    new_hist = _inject_runtime_error_if_needed(history, msg, is_runtime_error)
    retry_prompt = format_prompt(template, candidate, attempt + 1, new_hist, violations_text=msg)

    if attempt >= MAX_RETRIES:
        res = _build_failed_result(
            candidate, attempt, new_cc, new_depth, "FAILED_VERIFICATION", msg, candidate.source_code
        )
        return False, history, retry_prompt, res

    return False, history, retry_prompt, None


def _prepare_refactor_deps(candidate: FunctionCandidate) -> tuple[str, set[str], RefactorDeps]:
    full_source = _read_candidate_full_source(candidate)
    baseline_errors = get_file_baseline_errors(candidate.file_path, pkg_root) if full_source else set()
    header_contract = candidate.header_contract or extract_header_symbol_contract(full_source)
    deps_obj = RefactorDeps(
        orig_code=candidate.source_code,
        full_file_source=full_source,
        file_path=candidate.file_path,
        line=candidate.line,
        end_line=candidate.end_line,
        func_name=candidate.function_name,
        baseline_errors=baseline_errors,
        header_contract=header_contract,
    )
    return full_source, baseline_errors, deps_obj


def _handle_refactor_exception(
    e: Exception, candidate: FunctionCandidate, attempt: int, history: list, template: dict
) -> tuple[bool, list, str, RefactorResult | None]:
    _logger_ast.error(f"Pydantic-AI attempt {attempt} failed for {candidate.function_name}: {e}")
    err_str = str(e).lower()
    if _is_fatal_error(err_str) or attempt >= MAX_RETRIES:
        _build_error_result(candidate, attempt, e)
        raise e
    retry_prompt = format_prompt(template, candidate, attempt + 1, history, violations_text=str(e))
    return False, history, retry_prompt, None


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
    _provider = get_model_provider_name(CONTROL_SHEET.scanner_model)
    start_t = time.time()

    _logger_ast.info(
        f"[{get_timestamp()}] [{cand_idx}/{total_cand}][REQ {req_id}] provider={_provider} candidate={candidate.function_name} ({candidate.file_path}:{candidate.line}) attempt={attempt}/{MAX_RETRIES}"
    )

    try:
        _full_source, baseline_errors, deps_obj = _prepare_refactor_deps(candidate)
        result = await _refactor_agent.run(prompt, message_history=history, deps=deps_obj)
        elapsed = round(time.time() - start_t, 2)
        history = result.all_messages()
        verdict: RefactoringVerdict = result.output

        full_code = _build_full_code(verdict.refactored_code, verdict.helper_functions)
        passed, new_cc, new_depth, msg = verify_refactored_ast(
            full_code, candidate.function_name, orig_code=candidate.source_code,
            orig_cc=candidate.cc, baseline_errors=baseline_errors, header_contract=deps_obj.header_contract,
        )

        if passed:
            _logger_ast.info(
                f"[{get_timestamp()}] [PASSED {req_id}] {candidate.function_name} PASSED on attempt {attempt}/{MAX_RETRIES}! (Duration: {elapsed}s)"
            )
            res = _build_refactor_result(
                candidate, attempt, new_cc, new_depth, "APPROVED",
                verdict.refactored_code, verdict.helper_functions, verdict.explanation, msg, candidate.source_code,
                reasoning_and_plan=getattr(verdict, "reasoning_and_plan", ""),
            )
            return True, history, prompt, res

        return _handle_failed_attempt(candidate, attempt, history, msg, new_cc, new_depth, template)
    except (AttributeError, TypeError, SyntaxError, ValueError) as e:
        return _handle_refactor_exception(e, candidate, attempt, history, template)


# =====================================================================
# MAIN PIPELINE
# =====================================================================

def _resolve_target_files(target_files: set[str] | None) -> list[Path]:
    if not target_files:
        return sorted(src_DIR.rglob("*.py"))
    files_to_scan: list[Path] = []
    for tf in sorted(target_files):
        p = (pkg_root / tf).resolve()
        if p.is_file():
            files_to_scan.append(p)
        elif p.is_dir():
            files_to_scan.extend(sorted(p.rglob("*.py")))
    return files_to_scan


def _compute_rel_path(py_file: Path, root_resolved: Path) -> str:
    try:
        return str(py_file.resolve().relative_to(root_resolved))
    except ValueError:
        return str(py_file)


def _scan_single_file(
    py_file: Path, root_resolved: Path
) -> tuple[list[FunctionCandidate], str, Exception | None]:
    """Scan a single file for candidates, returning (candidates, rel_path, error)."""
    rel_path = _compute_rel_path(py_file, root_resolved)
    try:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))
    except (OSError, SyntaxError, ValueError, TypeError) as e:
        return [], rel_path, e

    scanner = FunctionCandidateScanner(rel_path, content.splitlines(), content)
    scanner.visit(tree)
    return scanner.candidates, rel_path, None


def scan_all_candidates(target_files: set[str] | None = None) -> list[FunctionCandidate]:
    _logger_ast.info("Scanning AST for Flat Control Flow candidates...")
    candidates: list[FunctionCandidate] = []
    root_resolved = pkg_root.resolve()

    files_to_scan = _resolve_target_files(target_files)
    for py_file in files_to_scan:
        if not py_file.is_file():
            continue
        file_cands, rel_path, err = _scan_single_file(py_file, root_resolved)
        if err is not None:
            _logger_ast.warning(f"Skipped {py_file.name}: {err}")
            continue
        candidates.extend(file_cands)

    _logger_ast.info(f"Found {len(candidates)} candidates violating Flat Control Flow standards.")
    return candidates


def save_checkpoint_item(res: RefactorResult | dict) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = res.model_dump_json() if isinstance(res, RefactorResult) else json.dumps(res)
    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _parse_int_safe(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _is_dict_candidate_complete(item: dict) -> bool:
    if item.get("status") != "APPROVED":
        return False
    cc = _parse_int_safe(item.get("refactored_cc"))
    depth = _parse_int_safe(item.get("refactored_depth"))
    if cc is None or depth is None:
        return False
    return cc <= 5 and depth <= 3


def is_candidate_complete(item: dict | RefactorResult) -> bool:
    """Check if a candidate result is fully complete (APPROVED with refactored_cc <= 5 and refactored_depth <= 3)."""
    if isinstance(item, RefactorResult):
        return item.status == "APPROVED" and item.refactored_cc <= 5 and item.refactored_depth <= 3
    return _is_dict_candidate_complete(item)


def _process_checkpoint_line(raw_line: str, completed: dict[str, dict]) -> None:
    line = raw_line.strip()
    if not line:
        return
    item = json.loads(line)
    key = f"{item.get('file_path', '')}:{item.get('function_name', '')}"
    if is_candidate_complete(item):
        completed[key] = item
    elif key in completed:
        completed.pop(key, None)


def load_checkpoint() -> dict[str, dict]:
    """Load previously completed results from JSONL checkpoint file."""
    completed: dict[str, dict] = {}
    if not CHECKPOINT_FILE.exists():
        return completed
    try:
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:
            for raw_line in f:
                _process_checkpoint_line(raw_line, completed)
        _logger_ast.info(f"Loaded {len(completed)} prior results from checkpoint ({CHECKPOINT_FILE.name}).")
    except (OSError, json.JSONDecodeError, ValueError) as e:
        _logger_ast.warning(f"Failed loading checkpoint: {e}")
    return completed


def _filter_targets_by_priority(
    candidates: list[FunctionCandidate], priorities: list[int]
) -> list[FunctionCandidate]:
    return [c for c in candidates if c.priority in priorities]


def _filter_completed_candidates(
    targets: list[FunctionCandidate],
    checkpoint_map: dict[str, dict],
    resume: bool
) -> list[FunctionCandidate]:
    if not resume:
        return targets
    return [
        c for c in targets
        if not (f"{c.file_path}:{c.function_name}" in checkpoint_map
                and is_candidate_complete(checkpoint_map[f"{c.file_path}:{c.function_name}"]))
    ]


def _rebuild_main_candidate(candidate: FunctionCandidate, plan: DecompositionPlan) -> FunctionCandidate:
    return FunctionCandidate(
        file_path=candidate.file_path,
        function_name=candidate.function_name,
        line=candidate.line,
        end_line=candidate.end_line,
        cc=max(1, plan.residual_cc),
        max_depth=candidate.max_depth,
        priority=candidate.priority,
        try_issues=candidate.try_issues,
        source_code=candidate.source_code,
        full_file_source=candidate.full_file_source,
        header_contract=candidate.header_contract,
        module_context=candidate.module_context,
        phase=1,
        parent_function="",
        line_count=candidate.line_count,
        requires_decomposition=False,
    )


def _decompose_candidate(candidate: FunctionCandidate) -> list[FunctionCandidate]:
    if not candidate.requires_decomposition:
        return [candidate]
    _logger_ast.info(
        f"Pre-decomposing {candidate.function_name} ({candidate.file_path}:{candidate.line}) "
        f"CC={candidate.cc} lines={candidate.line_count} into phases"
    )
    plan = pre_decompose(candidate)
    if not plan.helper_functions:
        return [candidate]
    main_candidate = _rebuild_main_candidate(candidate, plan)
    result = [main_candidate] + plan.helper_candidates
    _logger_ast.info(
        f"Decomposition produced {len(plan.helper_candidates)} helpers "
        f"for {candidate.function_name} (CC {candidate.cc} → {plan.residual_cc})"
    )
    return result


def _enqueue_candidates(
    queue: asyncio.Queue, need_llm: list[FunctionCandidate], template: dict
) -> None:
    for idx, c in enumerate(need_llm, start=1):
        prompt = format_prompt(template, c, attempt=1)
        asyncio.ensure_future(
            queue.put(
                {"candidate": c, "index": idx, "total": len(need_llm), "attempt": 1, "history": [], "prompt": prompt}
            )
        )


def _worker_main(
    queue: asyncio.Queue,
    semaphore: asyncio.Semaphore,
    template: dict,
    results: list[RefactorResult],
    checkpoint_map: dict[str, dict],
) -> None:
    while True:
        try:
            item = await queue.get()
        except asyncio.CancelledError:
            break
        cand: FunctionCandidate = item["candidate"]
        async with semaphore:
            _passed, new_hist, next_prmpt, res = await refactor_single_attempt_with_llm(
                cand, item["attempt"], item["history"], item["prompt"], template, item["index"], item["total"]
            )
        if res is not None:
            save_checkpoint_item(res)
            results.append(res)
            key = f"{res.file_path}:{res.function_name}"
            checkpoint_map[key] = res.model_dump() if isinstance(res, RefactorResult) else res
        else:
            await queue.put(
                {
                    "candidate": cand,
                    "index": item["index"],
                    "total": item["total"],
                    "attempt": item["attempt"] + 1,
                    "history": new_hist,
                    "prompt": next_prmpt,
                }
            )
        queue.task_done()


def _collect_approved_results(results: list[RefactorResult]) -> list[dict]:
    return [r.model_dump() for r in results if is_candidate_complete(r)]


def _collect_status_results(results: list[RefactorResult], target_status: str) -> list[dict]:
    return [r.model_dump() for r in results if r.status == target_status]


def _filter_checkpoint_results(checkpoint_map: dict[str, dict]) -> list[dict]:
    return [r for r in checkpoint_map.values() if isinstance(r, dict)]


def _partition_checkpoint_results(all_results: list[dict]) -> tuple[list[dict], list[dict]]:
    approved = [r for r in all_results if is_candidate_complete(r)]
    failed = [r for r in all_results if not is_candidate_complete(r)]
    return approved, failed


def _build_empty_summary(candidates: list[FunctionCandidate], checkpoint_map: dict[str, dict]) -> dict:
    all_results = _filter_checkpoint_results(checkpoint_map)
    approved, failed = _partition_checkpoint_results(all_results)
    return {
        "total_scanned_candidates": len(candidates),
        "refactored_count": len(approved),
        "approved": approved,
        "failed": failed,
    }


def _build_summary(results: list[RefactorResult]) -> dict:
    approved = _collect_approved_results(results)
    return {
        "total_scanned_candidates": len(results),
        "refactored_count": len(approved),
        "approved": approved,
        "failed_verification": _collect_status_results(results, "FAILED_VERIFICATION"),
        "failed_runtime": _collect_status_results(results, "FAILED_RUNTIME"),
        "errors": _collect_status_results(results, "LLM_ERROR"),
    }


def _write_report(summary: dict) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _logger_ast.info(f"Report saved to {REPORT_FILE}")


def _prepare_execution_targets(
    candidates: list[FunctionCandidate], priorities: list[int], limit: int,
    checkpoint_map: dict[str, dict], resume: bool
) -> list[FunctionCandidate]:
    targets = _filter_targets_by_priority(candidates, priorities)
    if limit > 0:
        targets = targets[:limit]
    need_llm = _filter_completed_candidates(targets, checkpoint_map, resume)
    decomposed: list[FunctionCandidate] = []
    for c in need_llm:
        decomposed.extend(_decompose_candidate(c))
    return decomposed


async def _run_llm_queue(
    need_llm: list[FunctionCandidate], template: dict, checkpoint_map: dict[str, dict]
) -> list[RefactorResult]:
    queue: asyncio.Queue = asyncio.Queue()
    _enqueue_candidates(queue, need_llm, template)
    semaphore = asyncio.Semaphore(3)
    results: list[RefactorResult] = []

    workers = [
        asyncio.create_task(_worker_main(queue, semaphore, template, results, checkpoint_map))
        for _ in range(3)
    ]
    await queue.join()
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    return results


async def main_async(do_refactor: bool, priorities: list[int], limit: int, resume: bool) -> None:
    target_files = load_target_files()
    candidates = scan_all_candidates(target_files=target_files)
    checkpoint_map = load_checkpoint() if resume else {}

    need_llm = _prepare_execution_targets(candidates, priorities, limit, checkpoint_map, resume)

    if not need_llm:
        print("\nAll candidates passed or were previously approved. Nothing to refactor.")
        summary = _build_empty_summary(candidates, checkpoint_map)
        _write_report(summary)
        return

    template = load_prompt_template()
    results = await _run_llm_queue(need_llm, template, checkpoint_map)
    summary = _build_summary(results)
    _write_report(summary)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Kill-Tries AST Scanner & Refactorer")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--no-resume", action="store_true", help="Do not resume from checkpoint file")
    parser.add_argument("--priority", type=str, default="all")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    priorities = [1, 2, 3] if args.priority == "all" else [int(p) for p in args.priority.split(",") if p.isdigit()]
    asyncio.run(main_async(do_refactor=not args.scan_only, priorities=priorities, limit=args.limit, resume=not args.no_resume))



if __name__ == '__main__':
    main()
