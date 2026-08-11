from __future__ import annotations

# kit-hygiene/scanners/find_registry_clashes.py
#
# Static + LLM + Runtime scanner: finds dict-style access on registry models
# from unified.py, which were converted from dicts to Pydantic models in Phase 1.
# Validates whether the call will crash based on the actual model API surface.
#
# Emits kit-hygiene/reports/registry_clashes.json
import ast
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import aiofiles

if TYPE_CHECKING:
    import instructor

import tenacity
from pydantic import BaseModel, Field

# Ensure repo root in sys.path
from _bootstrap import pkg_root
from control import ControlSheet, SystemSettings
from utils import get_src_files

# Initialize fast-json-repair if available
try:
    from fast_json_repair import repair_json
except ImportError:
    def repair_json(json_string: str, **kwargs: Any) -> Any: return json_string

# Configure logging with ANSI colors
class ColoredFormatter(logging.Formatter):
    COLORS: ClassVar[dict] = {
        'INFO': '\033[94m',      # Blue
        'WARNING': '\033[93m',   # Yellow
        'ERROR': '\033[91m',     # Red
        'CRITICAL': '\033[91m\033[1m' # Bold Red
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'
    GREEN = '\033[92m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        msg = record.getMessage()
        msg = self._emphasize_patterns(msg)
        return f"{color}[{record.levelname}]{self.RESET} {msg}"

    def _emphasize_patterns(self, msg: str) -> str:
        if handler := self._match_bracket_pattern(msg):
            return handler
        if "AST scan complete" in msg:
            return f"{self.BOLD}{self.GREEN}{msg}{self.RESET}"
        if "Scan complete" in msg or "Summary:" in msg:
            return f"{self.BOLD}{msg}{self.RESET}"
        return msg

    def _match_bracket_pattern(self, msg: str) -> str | None:
        if msg.startswith("[") and "]" in msg:
            end_idx = msg.find("]") + 1
            return f"{self.BOLD}{self.GREEN}{msg[:end_idx]}{self.RESET} {msg[end_idx:].strip()}"
        return None


def _setup_logger() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(ColoredFormatter())
    lg = logging.getLogger("RegistryScanner")
    lg.setLevel(logging.INFO)
    lg.addHandler(handler)
    lg.propagate = False
    return lg


logger = _setup_logger()

CHECKPOINT_FILE = pkg_root / "reports" / "registry_clashes_checkpoint.jsonl"
REPORT_FILE = pkg_root / "reports" / "registry_clashes.json"
BANNED_METHODS = {"keys", "items", "values", "get", "pop", "popitem", "setdefault", "update", "clear", "copy"}


# =====================================================================
# SCHEMA DEFINITIONS
# =====================================================================

class CallSite(BaseModel):
    source_module: str = ""
    file_path: str
    line: int
    variable: str
    method: str
    expression: str
    context_lines: list[str]


class AnalysisVerdict(BaseModel):
    status: str = Field(..., description="CRASH, SILENT_BUG, OK, or UNCERTAIN")
    reason: str = Field(..., description="Detailed explanation of why it will crash or work")
    registry_class: str = Field(..., description="Name of the registry class in unified.py")
    suggested_fix: str = Field(default="", description="How to fix the code, if broken")


class LLMScanResult(BaseModel):
    file_path: str
    scanned: bool
    findings: list[dict[str, Any]]


# =====================================================================
# LAYER 1: REGISTRY INTROSPECTION
# =====================================================================

def _is_registry_object(obj: object) -> bool:
    """Check if an object is a Pydantic BaseModel instance."""
    from src.core.schemas import unified
    return isinstance(obj, (unified.BaseModel,))


def _obj_has(cls: type, obj: object, attr: str) -> bool:
    """Check if either the class or instance has the given attribute."""
    return hasattr(cls, attr) or hasattr(obj, attr)


def _build_object_capabilities(cls: type, obj: object) -> dict:
    """Build the capability dict for a single registry object."""
    from src.core.schemas import unified
    return {
        "class_name": cls.__name__,
        "has_keys": _obj_has(cls, obj, 'keys'),
        "has_contains": hasattr(cls, '__contains__'),
        "has_getitem": hasattr(cls, '__getitem__'),
        "has_items": _obj_has(cls, obj, 'items'),
        "has_values": _obj_has(cls, obj, 'values'),
        "has_get": _obj_has(cls, obj, 'get'),
        "is_root_model": issubclass(cls, unified.RootModel) or hasattr(cls, '__pydantic_root_model__'),
    }


def build_registry_api_map() -> dict:
    """Introspect unified.py to find all registry objects and their API surfaces."""
    from src.core.schemas import unified

    registry_map = {}
    for name, obj in vars(unified).items():
        if name.startswith('_'):
            continue
        if _is_registry_object(obj):
            cls = type(obj)
            registry_map[name] = _build_object_capabilities(cls, obj)
    return registry_map


# =====================================================================
# LAYER 2: AST STATIC DETECTION
# =====================================================================

def get_context_lines(path: Path, line_num: int, window: int = 5) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        start = max(0, line_num - window - 1)
        end = min(len(lines), line_num + window)
        return lines[start:end]
    except (OSError, UnicodeDecodeError):
        return []


def base_source(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (OSError, UnicodeDecodeError):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{base_source(node.value)}.{node.attr}"
        return "?"


def _collect_imports(tree: ast.AST) -> tuple[dict[str, str], dict[str, str]]:
    """Walk the AST and build local_name -> original_name and local_name -> module maps."""
    import_map: dict[str, str] = {}
    import_module_map: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            _add_import_from(node, import_map, import_module_map)
        elif isinstance(node, ast.Import):
            _add_import(node, import_map, import_module_map)
    _collect_inner_imports(tree, import_map, import_module_map)
    return import_map, import_module_map


def _add_import_from(node: ast.ImportFrom, import_map: dict, import_module_map: dict) -> None:
    for alias in node.names:
        local_name = alias.asname or alias.name
        import_map[local_name] = alias.name
        import_module_map[local_name] = node.module


def _add_import(node: ast.Import, import_map: dict, import_module_map: dict) -> None:
    for alias in node.names:
        local_name = alias.asname or alias.name
        import_map[local_name] = alias.name
        import_module_map[local_name] = alias.name


def _collect_inner_imports(tree: ast.AST, import_map: dict, import_module_map: dict) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _collect_inner_import_from_func(node, import_map, import_module_map)


def _collect_inner_import_from_func(
    node: ast.AST, import_map: dict, import_module_map: dict
) -> None:
    for inner in ast.walk(node):
        if isinstance(inner, ast.ImportFrom) and inner.module:
            _add_import_from(inner, import_map, import_module_map)


def _is_registry_var(var_name: str, import_map: dict) -> bool:
    return var_name in import_map or var_name.isupper()


def _make_callsite(
    rel_path: str, node: ast.AST, var_name: str, import_module_map: dict,
    method: str, path: Path
) -> CallSite:
    return CallSite(
        file_path=rel_path,
        line=node.lineno,
        variable=var_name,
        source_module=import_module_map.get(var_name, ""),
        method=method,
        expression=ast.unparse(node),
        context_lines=get_context_lines(path, node.lineno)
    )


def _scan_method_call(
    node: ast.Call, import_map: dict, import_module_map: dict,
    rel_path: str, path: Path
) -> CallSite | None:
    """Detect banned dict methods like obj.keys()."""
    method = node.func.attr
    if method not in BANNED_METHODS:
        return None
    base = base_source(node.func.value)
    var_name = base.split(".")[0]
    if not _is_registry_var(var_name, import_map):
        return None
    return _make_callsite(rel_path, node, var_name, import_module_map, method, path)


def _scan_subscript(
    node: ast.Subscript, import_map: dict, import_module_map: dict,
    rel_path: str, path: Path
) -> CallSite | None:
    """Detect dict-style subscript access obj[key]."""
    base = base_source(node.value)
    var_name = base.split(".")[0]
    if not _is_registry_var(var_name, import_map):
        return None
    return _make_callsite(rel_path, node, var_name, import_module_map, "__getitem__", path)


def _scan_in_operator(
    node: ast.Compare, import_map: dict, import_module_map: dict,
    rel_path: str, path: Path
) -> CallSite | None:
    """Detect membership tests like item in REGISTRY."""
    if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        return None
    for comparator in node.comparators:
        cs = _try_make_in_callsite(comparator, import_map, import_module_map, rel_path, node, path)
        if cs:
            return cs
    return None


def _try_make_in_callsite(
    comparator: ast.expr, import_map: dict, import_module_map: dict,
    rel_path: str, parent_node: ast.Compare, path: Path
) -> CallSite | None:
    """Try to create a CallSite for a membership-test comparator."""
    base = base_source(comparator)
    var_name = base.split(".")[0]
    if _is_registry_var(var_name, import_map):
        return _make_callsite(rel_path, parent_node, var_name, import_module_map, "__contains__", path)
    return None


def _walk_candidates(
    tree: ast.AST, import_map: dict, import_module_map: dict,
    rel_path: str, path: Path
) -> list[CallSite]:
    """Walk AST nodes and collect all suspicious dict-style accesses."""
    candidates: list[CallSite] = []
    for node in ast.walk(tree):
        cs = _detect_candidate(node, import_map, import_module_map, rel_path, path)
        if cs is not None:
            candidates.append(cs)
    return candidates


def _detect_candidate(
    node: ast.AST, import_map: dict, import_module_map: dict,
    rel_path: str, path: Path
) -> CallSite | None:
    """Dispatch a single AST node to the appropriate detection helper."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _scan_method_call(node, import_map, import_module_map, rel_path, path)
    if isinstance(node, ast.Subscript):
        return _scan_subscript(node, import_map, import_module_map, rel_path, path)
    if isinstance(node, ast.Compare):
        return _scan_in_operator(node, import_map, import_module_map, rel_path, path)
    return None


def scan_file_ast(path: Path, registry_map: dict) -> tuple[list[CallSite], dict[str, str]]:
    """AST-walk to find imports and suspicious dict calls."""
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print("❌ ERROR: " + f"AST parse failed for {path}: {e}")
        raise
        return [], {}

    import_map, import_module_map = _collect_imports(tree)
    rel_path = str(path.relative_to(pkg_root))
    candidates = _walk_candidates(tree, import_map, import_module_map, rel_path, path)
    return candidates, import_map


# =====================================================================
# LAYER 3: LLM EVALUATION
# =====================================================================

def _resolve_orig_name(site: CallSite, import_map: dict, registry_map: dict) -> str | None:
    """Resolve the original registry name from the import map or registry_map."""
    orig_name = import_map.get(site.variable)
    if not orig_name and site.variable in registry_map:
        orig_name = site.variable
    return orig_name


def _build_api_context(site: CallSite, orig_name: str, registry_map: dict) -> str:
    """Build the API context string for the LLM prompt."""
    reg_info = registry_map[orig_name]
    ctx = f"Variable '{site.variable}' is imported from unified.py as '{orig_name}' (class {reg_info['class_name']}).\n"
    ctx += f"Class Capabilities: has_keys={reg_info['has_keys']}, has_contains={reg_info['has_contains']}, has_getitem={reg_info.get('has_getitem', False)}, "
    ctx += f"has_items={reg_info['has_items']}, has_values={reg_info['has_values']}, is_root_model={reg_info['is_root_model']}\n"
    if site.method == "__contains__" and not reg_info['has_contains'] and not reg_info['is_root_model']:
        ctx += "CRITICAL NOTE: This is a BaseModel without __contains__. The 'in' operator will fallback to iterating BaseModel fields (yielding tuples of field_name, value). Checking if a string is 'in' this model will always silently return False. This is a SILENT_BUG.\n"
    return ctx


def _build_llm_prompt(site: CallSite, api_context: str) -> str:
    """Build the LLM classification prompt for a call site."""
    return f"""
    Analyze this code snippet for a Pydantic migration dict-access clash.
    
    File: {site.file_path}
    Line: {site.line}
    Expression: {site.expression}
    
    API Context:
    {api_context}
    
    Code Context:
    ```python
    {chr(10).join(site.context_lines)}
    ```
    
    Determine if `{site.expression}` will raise an AttributeError/TypeError at runtime (CRASH), 
    is a silent logic bug returning False (SILENT_BUG), is perfectly safe (OK), 
    or if you cannot be certain without deeper type tracing (UNCERTAIN).
    """


def _build_verdict_dict(response, site: CallSite) -> dict:
    """Build the result dict from an LLM response."""
    return {
        "file_path": site.file_path,
        "line": site.line,
        "variable": site.variable,
        "method": site.method,
        "expression": site.expression,
        "status": response.status,
        "reason": response.reason,
        "registry_class": response.registry_class,
        "suggested_fix": response.suggested_fix,
    }


def _build_error_result_dict(site: CallSite, e: Exception, reg_class: str) -> dict:
    """Build the result dict for a fatal LLM error."""
    return {
        "file_path": site.file_path,
        "line": site.line,
        "variable": site.variable,
        "method": site.method,
        "expression": site.expression,
        "status": "ERROR",
        "reason": f"LLM error: {e!s}",
        "registry_class": reg_class,
        "suggested_fix": "",
    }


async def _call_llm_with_retry(client, prompt: str, max_retries: int = 3) -> Any:
    """Call the LLM with exponential backoff retries."""
    for attempt in range(max_retries):
        try:
            model_name = ControlSheet.scanner_model.model_name
            return await client.chat.completions.create(
                model=model_name,
                response_model=AnalysisVerdict,
                messages=[
                    {"role": "system", "content": "You are an expert Python code reviewer looking for bugs caused by migrating dictionaries to Pydantic BaseModels."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
            if attempt < max_retries - 1:
                print(f"\x1b[93m⚠️  LLM timeout/error -> {e}. Retrying ({attempt+1}/{max_retries})...\x1b[0m")
                import asyncio
                await asyncio.sleep(2 ** attempt)
            else:
                print(f"\x1b[91m🚨 FATAL LLM ERROR after {max_retries} attempts: {e}\x1b[0m")
                raise


@tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_exponential(multiplier=1, min=2, max=10))
async def evaluate_call_site(client: instructor.AsyncInstructor, site: CallSite, import_map: dict, registry_map: dict) -> dict:
    """Ask LLM to classify the crash certainty."""
    orig_name = _resolve_orig_name(site, import_map, registry_map)
    api_context = _build_api_context_or_default(site, orig_name, registry_map)
    prompt = _build_llm_prompt(site, api_context)
    response = await _call_llm_with_retry(client, prompt)
    return _build_verdict_dict(response, site)


def _build_api_context_or_default(site: CallSite, orig_name: str | None, registry_map: dict) -> str:
    """Build API context string, with fallback for unregistered variables."""
    if orig_name and orig_name in registry_map:
        return _build_api_context(site, orig_name, registry_map)
    return f"Variable '{site.variable}' is NOT directly imported from unified.py registries in this file. It may be a regular dict or a propagated registry."


# =====================================================================

def _try_import_from_source_module(site, orig_name: str):
    """Attempt to import from the source module where the variable was defined."""
    if not site.source_module:
        return None
    try:
        import importlib
        mod = importlib.import_module(site.source_module)
        return getattr(mod, orig_name, None)
    except ImportError:
        return None


def _try_import_from_local_file(site, orig_name: str):
    """Attempt to import from the file where the CallSite lives."""
    try:
        import importlib
        local_mod_path = site.file_path.replace(".py", "").replace("/", ".")
        mod = importlib.import_module(local_mod_path)
        return getattr(mod, orig_name, None)
    except ImportError:
        return None


def _try_import_from_unified(orig_name: str):
    """Fallback: attempt to import from unified.py."""
    try:
        from src.core.schemas import unified
        return getattr(unified, orig_name, None)
    except ImportError:
        return None


def _resolve_registry_object(site, import_map) -> object | None:
    """Try multiple import paths to resolve the registry object; return None if unfound."""
    orig_name = import_map.get(site.variable) or site.variable
    for resolver in (_try_import_from_source_module, _try_import_from_local_file):
        obj = resolver(site, orig_name)
        if obj is not None:
            return obj
    return _try_import_from_unified(orig_name)


def _check_method_safety(obj: object, method: str) -> str:
    """Check if a method is safe to call on the resolved object."""
    special = {
        "__contains__": lambda: not hasattr(type(obj), "__contains__"),
        "__getitem__": lambda: not hasattr(type(obj), "__getitem__"),
    }
    if method in special:
        return "CONFIRMED_BUG" if special[method]() else "SAFE"
    if hasattr(obj, method) or hasattr(type(obj), method):
        return "SAFE"
    return "CONFIRMED_CRASH"


def runtime_verify_pre(site, import_map) -> str:
    obj = _resolve_registry_object(site, import_map)
    if obj is None:
        return "UNVERIFIED"
    try:
        return _check_method_safety(obj, site.method)
    except (OSError, UnicodeDecodeError):
        return "UNVERIFIED"

# LAYER 4: RUNTIME VERIFICATION
# =====================================================================

def _classify_special_method(obj: object, method: str) -> str | None:
    """Check __contains__ and __getitem__ for special runtime semantics."""
    if method == "__contains__":
        return "CONFIRMED_BUG" if not hasattr(type(obj), "__contains__") else "SAFE"
    if method == "__getitem__":
        return "CONFIRMED_CRASH" if not hasattr(type(obj), "__getitem__") else "SAFE"
    return None


def _classify_runtime_method(obj: object, method: str) -> str:
    """Classify method safety at runtime, returning a verified status string."""
    special = _classify_special_method(obj, method)
    if special is not None:
        return special
    if hasattr(obj, method) or hasattr(type(obj), method):
        return "LLM_MISMATCH_SAFE"
    return "CONFIRMED_CRASH"


def runtime_verify(finding: dict, registry_map: dict) -> dict:
    """Attempt to import unified.py and check hasattr directly."""
    orig_name = str(finding.get("variable", ""))

    if finding["status"] not in ("CRASH", "SILENT_BUG"):
        return finding

    try:
        from src.core.schemas import unified
        obj = getattr(unified, orig_name, None)
        if not obj:
            finding["verified_status"] = "UNVERIFIED"
            return finding
        finding["verified_status"] = _classify_runtime_method(obj, finding["method"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
        finding["verified_status"] = f"IMPORT_ERROR: {e!s}"

    return finding


# =====================================================================
# ORCHESTRATOR
# =====================================================================

def load_checkpoint() -> set:
    if not CHECKPOINT_FILE.exists():
        return set()
    scanned = set()
    with open(CHECKPOINT_FILE) as f:
        for line in f:
            try:
                data = json.loads(line)
                if data.get("scanned"):
                    scanned.add(data["file_path"])
            except (json.JSONDecodeError, KeyError):
                pass
    return scanned


def append_checkpoint(result: dict):
    with open(CHECKPOINT_FILE, "a") as f:
        f.write(json.dumps(result) + "\n")


def _check_registry_clashes_disabled() -> bool:
    return os.getenv("KIT_ENABLE_REGISTRY_CLASHES", "false").lower() != "true"


def _init_llm_client(s: SystemSettings) -> instructor.AsyncInstructor:
    """Initialize and return an Instructor async client from system settings."""
    import instructor
    import openai
    if not s.api_key or not s.api_key.strip():
        raise RuntimeError(
            "KIT_ENABLE_REGISTRY_CLASHES=true but KIT_API_KEY is empty. "
            "Set a valid API key in .env — fail-closed to prevent unauthenticated requests."
        )
    client = openai.AsyncOpenAI(
        base_url=s.base_url,
        api_key=s.api_key,
    )
    return instructor.from_openai(client, mode=instructor.Mode.JSON)


def _scan_one_file(path: Path, scanned_files: set, registry_map: dict) -> tuple | None:
    """Scan a single file, returning (path, rel_path, candidates, import_map) or None."""
    if not path.is_absolute():
        path = pkg_root / path
    rel_path = str(path.relative_to(pkg_root))
    if rel_path in scanned_files:
        return None
    candidates, import_map = scan_file_ast(path, registry_map)
    if candidates:
        return (path, rel_path, candidates, import_map)
    return None


def _apply_limit(files_with_candidates: list, limit: int | None) -> list:
    """Apply the limit filter and print summary."""
    if limit is None:
        return files_with_candidates
    subset = files_with_candidates[:limit]
    total = sum(len(c) for _, _, c, _ in subset)
    print(f"Limiting audit to first {len(subset)} files ({total} candidates).")
    return subset


def _collect_candidates(
    files: list, scanned_files: set, registry_map: dict, limit: int | None,
    scripts_only: bool
) -> list:
    """Scan files for candidates, returning (path, rel_path, candidates, import_map) tuples."""
    files_with_candidates = _gather_candidate_files(files, scanned_files, registry_map)
    if not files_with_candidates:
        print("✅ No candidates found or all files already scanned.")
        return []
    total = sum(len(c) for _, _, c, _ in files_with_candidates)
    print(f"🧠 AST scan complete. Found {total} candidates across {len(files_with_candidates)} files to audit.")
    files_with_candidates = _apply_limit(files_with_candidates, limit)
    if scripts_only:
        print("Skipping LLM pass due to --scripts flag.")
        return []
    return files_with_candidates


def _gather_candidate_files(files: list, scanned_files: set, registry_map: dict) -> list:
    """Iterate over files and collect those with candidates."""
    files_with_candidates = []
    for path in files:
        result = _scan_one_file(path, scanned_files, registry_map)
        if result:
            files_with_candidates.append(result)
    return files_with_candidates


def _build_safe_result(rel_path: str, site: CallSite, import_map: dict) -> dict:
    """Build a result dict for a runtime-verified-safe call site."""
    return {
        "file_path": rel_path,
        "line": site.line,
        "variable": site.variable,
        "method": site.method,
        "expression": site.expression,
        "status": "OK",
        "reason": "Dynamically verified safe. LLM skipped.",
        "registry_class": import_map.get(site.variable, "?"),
        "suggested_fix": None,
        "verified_status": "LLM_MISMATCH_SAFE"
    }


def _print_outcome(res: dict, site: CallSite, pre_status: str) -> None:
    """Print the verdict for a single call site."""
    if res["status"] == "CRASH":
        print(f"       -> 🔴 VERDICT: {res.get('verified_status', 'CRASH')} | {res.get('registry_class', '?')} has no attribute '{site.method}'")
    elif res["status"] == "ERROR":
        print(f"       -> ⚠️ VERDICT: ERROR | {res['reason']}")
    else:
        print(f"       -> ⚠️ VERDICT: {res.get('verified_status', 'UNVERIFIED')} | {res['status']} | {res['reason']}")


async def _audit_file(
    path: Path, rel_path: str, candidates: list, import_map: dict,
    index: int, total_files: int, do_verify: bool, instructor_client
) -> list:
    """Audit all candidates within a single file, returning list of results."""
    print(f"\n[{index}/{total_files} files] [start] 📂 {rel_path} ({len(candidates)} candidates)")
    results = []
    candidates_done = 0
    total = len(candidates)
    for c_idx, site in enumerate(candidates, 1):
        print(f"    -> 🛠️ [{c_idx}/{total}] Checking `{site.variable}.{site.method}()` at line {site.line}...")
        pre_status = _get_pre_status(site, import_map, do_verify)
        if pre_status == "SAFE":
            print("       -> ✅ VERDICT: SAFE (Runtime verified, skipping LLM)")
            res = _build_safe_result(rel_path, site, import_map)
        else:
            print(f"       -> 🧠 Runtime says {pre_status}. Contacting LMM for suggested fix/classification...")
            res = await evaluate_call_site(instructor_client, site, import_map, {})
            if do_verify:
                res["verified_status"] = pre_status
                if pre_status in ("CONFIRMED_CRASH", "CONFIRMED_BUG"):
                    res["status"] = "CRASH"
        _print_outcome(res, site, pre_status)
        results.append(res)
        candidates_done += 1

    result_record = {"file_path": rel_path, "scanned": True, "findings": results}
    append_checkpoint(result_record)
    print(f"[{index}/{total_files} files] [ok] ✅ {rel_path} checkpointed.")
    return results


def _get_pre_status(site, import_map, do_verify: bool) -> str:
    """Return 'SAFE' if verification is disabled, otherwise runtime-verify."""
    if not do_verify:
        return "UNVERIFIED"
    return runtime_verify_pre(site, import_map)


async def _run_llm_audit(files_with_candidates: list, do_verify: bool, instructor_client) -> list:
    """Run the LLM audit loop over all candidate files."""
    all_findings = []
    total_files = len(files_with_candidates)
    for index, (path, rel_path, candidates, import_map) in enumerate(files_with_candidates, 1):
        results = await _audit_file(
            path, rel_path, candidates, import_map, index, total_files,
            do_verify, instructor_client
        )
        all_findings.extend(results)
    return all_findings


async def _load_final_findings() -> list:
    """Reload all findings from checkpoint for final report."""
    final_findings = []
    async with aiofiles.open(CHECKPOINT_FILE) as f:
        async for line in f:
            try:
                data = json.loads(line)
                if data.get("findings"):
                    final_findings.extend(data["findings"])
            except (json.JSONDecodeError, KeyError):
                pass
    return final_findings


_STATUS_FILTERS = {
    "clashes": "CRASH",
    "surprises": "SILENT_BUG",
    "suspects": "UNCERTAIN",
    "ok": "OK",
    "errors": "ERROR",
}


def _filter_by_status(findings: list, status: str) -> list:
    return [f for f in findings if f["status"] == status]


def _build_report(files_scanned: int, findings: list) -> dict:
    """Categorize findings into a report dict."""
    report = {"scanned_files_count": files_scanned}
    for key, status in _STATUS_FILTERS.items():
        report[key] = _filter_by_status(findings, status)
    return report


def _print_summary(report: dict) -> None:
    """Print the final scan summary."""
    print("="*50)
    print("🎯 FINAL SCAN SUMMARY")
    print("="*50)
    print(f"🔴 CRASH (Violations) : {len(report['clashes'])}")
    print(f"🟡 SILENT_BUG         : {len(report['surprises'])}")
    print(f"⚪ UNCERTAIN          : {len(report['suspects'])}")
    print(f"✅ OK (Safe)          : {len(report.get('ok', []))}")
    num_errors = len(report.get('errors', []))
    if num_errors > 0:
        print(f"\n\033[91m⚠️  API ERRORS OCCURRED: {num_errors}\033[0m")
        print(f"\033[91m   These {num_errors} candidates were skipped due to LLM connection failures.\033[0m")
        print("\033[91m   You MUST re-run the script to complete the scan.\033[0m")
    print("="*50 + "\n")


async def _write_final_report(files_scanned: int) -> None:
    """Load findings from checkpoint, build report, and write to disk."""
    print("✅ Scan complete. Writing final report...")
    final_findings = await _load_final_findings()
    report = _build_report(files_scanned, final_findings)
    async with aiofiles.open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved to {REPORT_FILE}")
    _print_summary(report)


async def main_async(do_verify: bool, limit: int | None = None, scripts_only: bool = False):
    if _check_registry_clashes_disabled():
        print("[INFO] registry clashes disabled")
        return

    registry_map = build_registry_api_map()
    print(f"📚 Loaded {len(registry_map)} registry schemas from unified.py")

    files = get_src_files()
    print(f"🔍 Scanning {len(files)} files in src/...")

    scanned_files = load_checkpoint()
    print(f"♻️ Resuming from checkpoint: {len(scanned_files)} already scanned")

    instructor_client = await _init_client_or_exit()
    files_with_candidates = _collect_candidates(files, scanned_files, registry_map, limit, scripts_only)
    if not files_with_candidates:
        await _write_final_report(len(files))
        return

    all_findings = await _run_llm_audit(files_with_candidates, do_verify, instructor_client)
    await _write_final_report(len(files))


async def _init_client_or_exit() -> instructor.AsyncInstructor:
    """Initialize the Instructor client, exiting on failure."""
    s = SystemSettings()
    try:
        return _init_llm_client(s)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
        print("❌ ERROR: " + f"Failed to initialize Instructor client: {e}")
        sys.exit(1)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scripts", action="store_true", help="AST only (skip LLM)")
    parser.add_argument("--diff", action="store_true", help="Only scan changed files")
    parser.add_argument("--verify", action="store_true", help="Run hasattr checks")
    args = parser.parse_args()

    asyncio.run(main_async(args.verify, None, args.scripts))


if __name__ == "__main__":
    main()
