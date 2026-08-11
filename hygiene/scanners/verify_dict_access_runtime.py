from __future__ import annotations

import argparse
import ast
import asyncio
import importlib
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from _bootstrap import (
    pkg_root,
    target_root,
)

# kit-hygiene/scanners/verify_dict_access_runtime.py
#
# Runtime Layer-1 verifier for dictionary-style access on Pydantic models.
#
# Pipeline:
#   static scanner (find_dict_access_on_models.py) -> dict_access_on_models.json
#     (each candidate carries `kind` = METHOD | SUBSCRIPT | SUBSCRIPT_ASSIGN
#      and `access` = the actual offending expression)
#   this harness -> executes the producing function, reproduces the REAL access
#      on the returned object, and reports:
#        CONFIRMED_CRASH : object rejected dict access -> it is a model -> real bug
#        SAFE_MODEL      : object tolerated dict access -> it is a dict -> no bug
#        SAFE_DICT       : producer returned a plain dict/list -> no bug
#        UNVERIFIABLE    : producer could not be executed (DB/network/state)
#
# This is the DEFINITIVE Layer 1: it proves crashes by execution, not guesswork.

try:
    from src.core.schemas.unified import (
        ChartProfile,
        DaYunOutput,
        Pillar,
    )
    _UNIFIED_AVAILABLE: bool = True
except ImportError:
    ChartProfile = DaYunOutput = Pillar = None  # type: ignore[assignment,misc]
    _UNIFIED_AVAILABLE = False

BANNED_DICT_METHODS = {
    "get",
    "items",
    "keys",
    "values",
    "pop",
    "popitem",
    "setdefault",
    "update",
    "clear",
    "copy",
}


def build_sample_profile() -> ChartProfile | None:
    """Constructs a deterministic, valid ChartProfile for best-effort execution."""
    if not _UNIFIED_AVAILABLE:
        print("[INFO] src.core.schemas.unified not importable on this repo — skipping runtime verification sample")
        return None
    return ChartProfile(
        day_master="Jia",
        dm_element="Wood",
        year_pillar=Pillar(stem="Jia", branch="Zi"),
        month_pillar=Pillar(stem="Bing", branch="Yin"),
        day_pillar=Pillar(stem="Wu", branch="Chen"),
        hour_pillar=Pillar(stem="Geng", branch="Wu"),
        da_yun_pillar=Pillar(stem="Xin", branch="Wei"),
        favorable_elements=["Wood", "Water"],
        unfavorable_elements=["Metal", "Earth"],
        medicine=["Wood"],
        taboo=["Metal"],
        age=30,
        dob="1996-02-15",
        gender="M",
        da_yun=DaYunOutput(start_age=5, start_year=2001, direction="Forward", cycles=[]),
        day_stem_stream="Jia zi",
        elemental_concentration={"Wood": 40.0, "Fire": 20.0, "Earth": 20.0, "Metal": 10.0, "Water": 10.0},
        ge_ju_type="Normal",
        ge_ju_alignment_mod=1.0,
        shen_profile={},
        strength_profile={"spectrum_tier": "Neutral", "classification": "Mild Weak", "continuous_score": 5.0},
        dm_strength_type="Balanced",
        target_year=2026,
        da_yun_start_year=2026,
        neutral_elements=["Fire"],
        monthly_composite_score=75.5,
        domain_focus="General",
        months_into_dayun=12,
        macro_results={},
        compatibility_profile={},
        user_id="test_user",
        chat_id="test_chat",
        source="runtime_verifier",
    )


def workspace_root() -> Path:
    """Root of the repo being scanned (TARGET_ROOT env, else repo root)."""
    return target_root


def get_src_files() -> list[Path]:
    """Recursively find all Python files in src/."""
    src_dir = workspace_root() / "src"
    if not src_dir.exists():
        return []
    return list(src_dir.rglob("*.py"))


def _is_basemodel_name(base: ast.Name | ast.Attribute) -> bool:
    """Check if a base node references BaseModel."""
    if isinstance(base, ast.Name):
        return base.id == "BaseModel"
    return isinstance(base, ast.Attribute) and base.attr == "BaseModel"


def _is_basemodel_classdef(node: ast.ClassDef) -> bool:
    """Check if a ClassDef subclasses BaseModel."""
    return any(_is_basemodel_name(base) for base in node.bases)


def _parse_file_for_models(file_path: Path) -> tuple[str, set[str]]:
    """Parse a file and return (mod_path, set of BaseModel subclass names)."""
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return "", set()
    mod_path = str(file_path.relative_to(workspace_root())).replace("/", ".").replace(".py", "")
    model_classes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and _is_basemodel_classdef(node):
            model_classes.add(node.name)
    return mod_path, model_classes


def discover_models(files: list[Path]) -> dict[str, str]:
    """Maps model class name -> module path (for instantiating annotated args)."""
    model_classes: dict[str, str] = {}
    for file_path in files:
        mod_path, models = _parse_file_for_models(file_path)
        if not mod_path or not models:
            continue
        for name in models:
            model_classes.setdefault(name, mod_path)
    return model_classes


def module_path_for_file(file_path: str) -> str | None:
    full = workspace_root() / file_path
    if not full.exists():
        return None
    rel = full.with_suffix("").relative_to(workspace_root())
    return ".".join(rel.parts)


def _func_spans_line(node: ast.FunctionDef | ast.AsyncFunctionDef, line: int) -> bool:
    """Check if a function node spans the given line number."""
    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        return False
    return node.lineno <= line <= node.end_lineno


def _find_enclosing_func(tree: ast.Module, line: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the function node whose body spans `line`."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _func_spans_line(node, line):
            return node
    return None


def _match_arg_annotation(arg: ast.arg, variable: str) -> tuple[str | None, str | None]:
    """Match a function arg against variable name; returns (annotation_id, type)."""
    if arg.arg != variable:
        return None, None
    if arg.annotation and isinstance(arg.annotation, ast.Name):
        return arg.annotation.id, "model_class"
    return None, None


def _resolve_func_arg_model_class(enclosing_func: ast.FunctionDef | ast.AsyncFunctionDef, variable: str) -> tuple[str | None, str | None]:
    """If `variable` is an annotated function arg, return (annotation, 'model_class')."""
    all_args = enclosing_func.args.args + enclosing_func.args.kwonlyargs
    for arg in all_args:
        result = _match_arg_annotation(arg, variable)
        if result != (None, None):
            return result
    return None, None


def _parse_module_for_func(file_path: str) -> tuple[str | None, ast.Module | None]:
    """Parse a module file; returns (mod_path, tree) or (None, None) on failure."""
    full_path = workspace_root() / file_path
    if not full_path.exists():
        return None, None
    try:
        with open(full_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(full_path))
    except (SyntaxError, OSError):
        return None, None
    return str(file_path), tree


def resolve_producing_function(file_path: str, line: int, variable: str) -> tuple[str | None, str | None]:
    """
    Finds the function that produced `variable` near `line`.
    Returns (function_name, resolution_type) where resolution_type is
    'function' (variable assigned from a call) or 'model_class' (variable is a
    function argument annotated with a model class).
    """
    _, tree = _parse_module_for_func(file_path)
    if tree is None:
        return None, None

    enclosing_func = _find_enclosing_func(tree, line)
    if not enclosing_func:
        return None, None

    model_class = _resolve_func_arg_model_class(enclosing_func, variable)
    if model_class != (None, None):
        return model_class
    return _resolve_last_call_in_func(enclosing_func, variable, line)


def _extract_call_name(node: ast.Call) -> str | None:
    """Extract function name from a Call node."""
    call = node.func
    if isinstance(call, ast.Name):
        return call.id
    return getattr(call, "attr", None)


def _collect_assigns_before_line(func: ast.FunctionDef | ast.AsyncFunctionDef, line: int) -> list[ast.Assign]:
    """Collect all Assign nodes in func body that occur on or before `line`."""
    assigns: list[ast.Assign] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and hasattr(node, "lineno") and node.lineno <= line:
            assigns.append(node)
    return assigns


def _check_assign_for_variable(node: ast.Assign, variable: str) -> str | None:
    """Check if an Assign node assigns a Call to `variable`; returns extracted call name."""
    targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
    if variable not in targets:
        return None
    if not isinstance(node.value, ast.Call):
        return None
    return _extract_call_name(node.value)


def _resolve_last_call_in_func(enclosing_func: ast.FunctionDef | ast.AsyncFunctionDef, variable: str, line: int) -> tuple[str | None, str | None]:
    """Walk func body to find last Call-assign to `variable` before `line`."""
    last_call_name: str | None = None
    for node in _collect_assigns_before_line(enclosing_func, line):
        name = _check_assign_for_variable(node, variable)
        if name is not None:
            last_call_name = name
    return last_call_name, "function"


def _navigate_attr(cur: Any, attr: str) -> Any:
    """Navigate a single attribute access."""
    return getattr(cur, attr)


def _navigate_subscript(cur: Any, idx: str) -> Any:
    """Navigate a single subscript access with fallback key."""
    key = idx.strip().strip("'\"") if idx.strip() else "__probe__"
    try:
        return cur[key]
    except (KeyError, TypeError, IndexError):
        return cur["__probe__"]


def _navigate(obj: Any, path: str) -> Any:
    """Walk `obj` through a dotted/bracketed path like a.b['c'] to reach the
    object that is actually subjected to the dict access."""
    cur = obj
    for m in re.finditer(r"\.([A-Za-z_][\w]*)|\[([^\]]*)\]", path):
        attr, idx = m.group(1), m.group(2)
        if attr:
            cur = _navigate_attr(cur, attr)
        else:
            cur = _navigate_subscript(cur, idx)
    return cur


def _probe_method_access(target: Any, method: str) -> str:
    """Probe a banned dict method access."""
    try:
        getattr(target, method)("__probe__")
        return "SAFE_MODEL"
    except (AttributeError, TypeError):
        return "CONFIRMED_CRASH"
    except KeyError:
        return "SAFE_MODEL"


def _find_banned_method(access: str) -> tuple[str | None, str]:
    """Find which banned dict method is used and return (method_name, target_path)."""
    for m in BANNED_DICT_METHODS:
        idx = access.rfind(f".{m}(")
        if idx != -1:
            return m, access[:idx]
    return None, access


def _probe_subscript_access(target: Any) -> str:
    """Probe a subscript access on target."""
    try:
        target["__probe__"]
        return "SAFE_MODEL"
    except (AttributeError, TypeError):
        return "CONFIRMED_CRASH"
    except KeyError:
        return "SAFE_MODEL"


def _probe_method_kind(obj: Any, access: str) -> str:
    """Probe a METHOD kind dict access."""
    method, target_path = _find_banned_method(access)
    if method is None:
        return "UNVERIFIABLE"
    target = _navigate(obj, target_path) if target_path else obj
    return _probe_method_access(target, method)


def _probe_subscript_kind(obj: Any, access: str) -> str:
    """Probe a SUBSCRIPT or SUBSCRIPT_ASSIGN kind dict access."""
    target_path = access.split("[", 1)[0]
    target = _navigate(obj, target_path) if target_path else obj
    return _probe_subscript_access(target)


def probe_access(obj: Any, candidate: dict[str, Any]) -> str:
    """
    Reproduce the REAL dict-style access on `obj`.
    Returns SAFE_MODEL if the object tolerates it (it is a dict -> no bug),
    or CONFIRMED_CRASH if it rejects it (it is a model -> real bug).
    """
    kind = candidate.get("kind", "")
    access = candidate.get("access", "")
    try:
        if kind == "METHOD":
            return _probe_method_kind(obj, access)
        return _probe_subscript_kind(obj, access)
    except (AttributeError, TypeError, KeyError):
        return "CONFIRMED_CRASH"


def instantiate_model(class_name: str, mod_path: str) -> BaseModel | None:
    try:
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, class_name)
        if class_name == "ChartProfile":
            return build_sample_profile()
        try:
            return cls()
        except (TypeError, ValueError, AttributeError):
            return None
    except (ImportError, AttributeError, ValueError):
        return None


_SAMPLES: dict[str, Any] = {
    "chartprofile": build_sample_profile,
    "pillar": lambda: Pillar(stem="Jia", branch="Zi"),
    "dict": dict,
    "str": lambda: "",
    "int": lambda: 0,
    "bool": lambda: False,
    "list": list,
}


def _sample_value_for_annotation(ann: str, param: inspect.Parameter) -> Any:
    ann_lower = ann.lower()
    for key, factory in _SAMPLES.items():
        if key in ann_lower:
            return factory()
    if param.default != inspect.Parameter.empty:
        return param.default
    return None


def _build_func_kwargs(func: Any) -> dict[str, Any]:
    """Build keyword arguments for a function from its signature annotations."""
    kwargs: dict[str, Any] = {}
    sig = inspect.signature(func)
    for name, param in sig.parameters.items():
        kwargs[name] = _sample_value_for_annotation(str(param.annotation), param)
    return kwargs


def _get_func_from_module(func_name: str, mod_path: str) -> Any:
    """Import module and retrieve function; returns None on failure."""
    try:
        mod = importlib.import_module(mod_path)
        return getattr(mod, func_name)
    except (ImportError, AttributeError):
        return None


def _invoke_func(func: Any, kwargs: dict[str, Any]) -> Any:
    """Invoke a function (sync or async) with kwargs."""
    if inspect.iscoroutinefunction(func):
        return asyncio.run(func(**kwargs))
    return func(**kwargs)


def _classify_result(result: Any, candidate: dict[str, Any]) -> str:
    """Classify the result of a function execution."""
    if isinstance(result, (dict, list)):
        return "SAFE_DICT"
    if isinstance(result, BaseModel):
        return probe_access(result, candidate)
    return "UNVERIFIABLE"


def execute_and_verify(func_name: str, mod_path: str, candidate: dict[str, Any]) -> str:
    """Executes `func_name` in `mod_path` and probes the returned object."""
    func = _get_func_from_module(func_name, mod_path)
    if func is None:
        return "UNVERIFIABLE"

    try:
        kwargs = _build_func_kwargs(func)
    except (LookupError, TypeError):
        return "UNVERIFIABLE"

    try:
        result = _invoke_func(func, kwargs)
    except (TypeError, ValueError, RuntimeError, OSError):
        return "UNVERIFIABLE"

    return _classify_result(result, candidate)


def _load_candidates_from_path(path: Path) -> list[dict[str, Any]]:
    """Attempt to load candidates from a JSON path."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cands = data.get("verified", []) + data.get("failed", [])
        if cands:
            return cands
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return []
    return []


def load_candidates() -> list[dict[str, Any]]:
    reports_dir = pkg_root / "reports"
    json_path = reports_dir / "dict_access_on_models.json"
    sample_path = pkg_root / "studio" / "upload" / "dict_access_on_models_sample.json"
    for path in (json_path, sample_path):
        cands = _load_candidates_from_path(path)
        if cands:
            return cands
    return []


def _resolve_model_class_verdict(file_path: str, line: int, variable: str, model_classes: dict[str, str]) -> tuple[str, str]:
    """Resolve verdict for a model-class-typed argument."""
    func_name, res_type = resolve_producing_function(file_path, line, variable)
    if func_name and res_type == "model_class" and func_name in model_classes:
        inst = instantiate_model(func_name, model_classes[func_name])
        if inst is not None:
            verdict = probe_access(inst, {"kind": "SUBSCRIPT", "access": ""})
            return verdict, f"Annotated arg of model class {func_name}"
    return "UNVERIFIABLE", "Could not resolve producing function"


def _resolve_function_verdict(file_path: str, func_name: str, candidate: dict[str, Any]) -> tuple[str, str]:
    """Resolve verdict by executing a function."""
    if func_name:
        mod_path = module_path_for_file(file_path)
        if mod_path:
            verdict = execute_and_verify(func_name, mod_path, candidate)
            return verdict, f"Resolved to {func_name}"
    return "UNVERIFIABLE", "Could not resolve producing function"


def _process_candidate(idx: int, total: int, candidate: dict[str, Any], model_classes: dict[str, str]) -> tuple[str, str]:
    """Process a single candidate and return (verdict, detail)."""
    file_path = candidate.get("file_path")
    line = candidate.get("line")
    variable = candidate.get("variable")

    func_name, res_type = resolve_producing_function(file_path, line, variable)

    if func_name and res_type == "model_class" and func_name in model_classes:
        verdict, detail = _resolve_model_class_verdict(file_path, line, variable, model_classes)
    elif func_name:
        verdict, detail = _resolve_function_verdict(file_path, func_name, candidate)
    else:
        verdict = "UNVERIFIABLE"
        detail = "Could not resolve producing function"

    print(f"[{idx}/{total}] {file_path}:{line} `{variable}` -> {verdict}")
    return verdict, detail


def _format_result_entry(file_path: str, line: int, variable: str, candidate: dict[str, Any], verdict: str, detail: str) -> dict[str, Any]:
    return {
        "file_path": file_path,
        "line": line,
        "variable": variable,
        "verdict": verdict,
        "kind": candidate.get("kind", ""),
        "access": candidate.get("access", ""),
        "detail": detail,
    }


def _list_candidates(candidates: list[dict[str, Any]]) -> None:
    for idx, c in enumerate(candidates, 1):
        print(
            f"[{idx}] {c.get('file_path')}:{c.get('line')} `{c.get('variable')}` {c.get('kind', '')}: {c.get('access', '')}"
        )
    sys.exit(0)


def _write_json_report(results: list[dict[str, Any]]) -> None:
    reports_dir = pkg_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_json = reports_dir / "dict_access_runtime.json"
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")


def _group_results_by_file(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_file: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_file.setdefault(r["file_path"], []).append(r)
    return by_file


def _format_verdict_icon(verdict: str) -> str:
    if verdict == "CONFIRMED_CRASH":
        return "💥"
    if verdict in ("SAFE_DICT", "SAFE_MODEL"):
        return "✅"
    return "⚠️"


def _format_md_item(item: dict[str, Any]) -> str:
    icon = _format_verdict_icon(item["verdict"])
    return (
        f"- {icon} **L{item['line']}** `{item['variable']}`: **{item['verdict']}** "
        f"({item['kind']} `{item['access']}` — {item['detail']})\n"
    )


def _write_md_report(results: list[dict[str, Any]], tallies: dict[str, int]) -> None:
    reports_dir = pkg_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_md = reports_dir / "dict_access_runtime.md"
    lines = [
        "# 🏃 Runtime Verification: Dict Access on Pydantic Models\n",
        (f"**Summary:** CONFIRMED_CRASH: {tallies['CONFIRMED_CRASH']} | "
        f"SAFE_DICT: {tallies['SAFE_DICT']} | "
        f"SAFE_MODEL: {tallies['SAFE_MODEL']} | "
        f"UNVERIFIABLE: {tallies['UNVERIFIABLE']}\n"),
    ]
    by_file = _group_results_by_file(results)
    for fp, items in sorted(by_file.items()):
        lines.append(f"\n## 📂 `{fp}`\n")
        for item in sorted(items, key=lambda x: x["line"]):
            lines.append(_format_md_item(item))
    out_md.write_text("".join(lines), encoding="utf-8")


def _run_verification(candidates: list[dict[str, Any]], model_classes: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Run verification on all candidates and return (results, tallies)."""
    results: list[dict[str, Any]] = []
    tallies = {"CONFIRMED_CRASH": 0, "SAFE_DICT": 0, "SAFE_MODEL": 0, "UNVERIFIABLE": 0}
    total = len(candidates)
    print(f"Starting runtime verification for {total} candidates...")
    for idx, candidate in enumerate(candidates, 1):
        file_path = candidate.get("file_path")
        line = candidate.get("line")
        variable = candidate.get("variable")
        verdict, detail = _process_candidate(idx, total, candidate, model_classes)
        tallies[verdict] += 1
        entry = _format_result_entry(file_path, line, variable, candidate, verdict, detail)
        results.append(entry)
    return results, tallies


def _print_summary(tallies: dict[str, int]) -> None:
    print(
        f"\nLayer 1 Runtime Verification complete. "
        f"CONFIRMED_CRASH: {tallies['CONFIRMED_CRASH']}, "
        f"SAFE_DICT: {tallies['SAFE_DICT']}, "
        f"SAFE_MODEL: {tallies['SAFE_MODEL']}, "
        f"UNVERIFIABLE: {tallies['UNVERIFIABLE']}"
    )
    reports_dir = pkg_root / "reports"
    out_json = reports_dir / "dict_access_runtime.json"
    out_md = reports_dir / "dict_access_runtime.md"
    print(f"Reports written to {out_json} and {out_md}")


def main():
    parser = argparse.ArgumentParser(description="Runtime Verifier for Dict Access on Pydantic Models")
    parser.add_argument("--scripts", action="store_true", help="List candidates without executing")
    args = parser.parse_args()

    candidates = load_candidates()
    if not candidates:
        print("No candidate JSON found. Run find_dict_access_on_models.py first.")
        sys.exit(1)

    if args.scripts:
        _list_candidates(candidates)

    files = get_src_files()
    model_classes = discover_models(files)

    results, tallies = _run_verification(candidates, model_classes)

    _write_json_report(results)
    _write_md_report(results, tallies)
    _print_summary(tallies)


if __name__ == "__main__":
    main()
