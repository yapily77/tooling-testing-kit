import ast
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from _bootstrap import pkg_root
from control import CONTROL_SHEET
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from utils import get_src_files


class CodeDefinition(BaseModel):
    name: str = Field(description="The name of the function, async function, or class.")
    file_path: str = Field(description="The source file path relative to workspace root.")
    line: int = Field(description="The starting line number of the definition.")
    type: str = Field(description="The type of definition: function, async_function, or class.")


class AuditResult(BaseModel):
    name: str = Field(description="Name of the audited function/class.")
    file_path: str = Field(description="The file path where it is defined.")
    line: int = Field(description="The line number where it is defined.")
    type: str = Field(description="The definition type (function, async_function, class).")
    status: str = Field(
        description="Status of the code symbol: 'CONFIRMED_DEAD', 'DISCONNECTED_CORE_LOGIC', or 'FALSE_POSITIVE'."
    )
    reason: str = Field(
        description="A concise 1 to 2 sentence explanation of why it is dead, disconnected, or dynamically called."
    )
    updated_at: str | None = Field(default=None, description="Timestamp of when the audit was performed.")


class AuditReport(BaseModel):
    scanned_files_count: int = Field(description="Total number of Python files scanned.")
    audit_results: list[AuditResult] = Field(
        default_factory=list, description="Audit results for all scanned candidate definitions."
    )
    failed_audits: list[dict] = Field(
        default_factory=list, description="List of definitions that failed LLM validation due to errors."
    )


scanner_model = CONTROL_SHEET.scanner_model

audit_agent = Agent(
    scanner_model,
    output_type=AuditResult,
    retries=3,
    system_prompt=(
        "You are an expert static analyzer and code auditor. "
        "Your task is to review a candidate 'dead' function or class, inspect its code context and references in other files, "
        "and confirm if it is indeed dead (never called/imported), if it represents disconnected core logic (unused in the active pipeline but referenced in book/manual documentation), "
        "or if it is a false positive (called dynamically, e.g., via getattr, eval, or as an entry point webhook)."
    ),
)

DECORATOR_KEYWORDS = ["router", "app", "message", "command", "webhook", "post",
                      "get", "put", "delete", "handler"]
STANDARD_WHITELIST = {
    "main",
    "telegram_webhook",
    "agent_webhook",
    "debug_session",
    "process_webhook_logic",
    "define_system_prompt",
    "add_the_users_name",
    "add_the_date",
}
API_ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError,
              RuntimeError, ImportError, json.JSONDecodeError)


def _index_md_words(md_file: Path, terms: dict[str, str]) -> None:
    try:
        content = md_file.read_text(encoding="utf-8").lower()
        words = re.findall(r"\b\w+\b", content)
        for w in words:
            if len(w) > 3:
                terms[w] = md_file.name
    except API_ERRORS as e:
        print(f"Warning reading {md_file.name}: {e}", file=sys.stderr)


def load_verified_manual_terms() -> dict[str, str]:
    """Reads all markdown files in the verified book folder and returns a mapping of word -> filename."""
    manual_dir = Path("_docs/DEV/V31/01_workflow/03_final_OWL_06_VERIFIED")
    terms: dict[str, str] = {}
    if not manual_dir.exists():
        print(f"Warning: Manual directory {manual_dir} not found.", file=sys.stderr)
        return terms

    for md_file in manual_dir.glob("*.md"):
        _index_md_words(md_file, terms)
    return terms


def check_against_manuals(name: str, manual_terms: dict[str, str]) -> str | None:
    """Checks if a function name or parts of it appear in the verified manual."""
    name_lower = name.lower()
    if name_lower in manual_terms:
        return manual_terms[name_lower]

    parts = name_lower.split("_")
    for part in parts:
        if len(part) > 4 and part in manual_terms:
            return manual_terms[part]

    return None


class DefinitionExtractor(ast.NodeVisitor):
    """AST visitor to collect function and class definitions, identifying entrypoints."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.definitions: list[CodeDefinition] = []
        self.whitelisted_names: set[str] = set()

    def _check_decorators(self, node, name: str):
        for decorator in node.decorator_list:
            dec_name = _get_decorator_name(decorator)
            if any(k in dec_name.lower() for k in DECORATOR_KEYWORDS):
                self.whitelisted_names.add(name)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if not node.name.startswith("__"):
            self.definitions.append(
                CodeDefinition(name=node.name, file_path=str(self.file_path),
                               line=node.lineno, type="function")
            )
            self._check_decorators(node, node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if not node.name.startswith("__"):
            self.definitions.append(
                CodeDefinition(name=node.name, file_path=str(self.file_path),
                               line=node.lineno, type="async_function")
            )
            self._check_decorators(node, node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        if not node.name.startswith("__"):
            self.definitions.append(
                CodeDefinition(name=node.name, file_path=str(self.file_path),
                               line=node.lineno, type="class")
            )
            self._check_decorators(node, node.name)
        self.generic_visit(node)


def _decorator_name_from_expr(expr) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return ""


def _get_decorator_name(decorator) -> str:
    if isinstance(decorator, ast.Call):
        return _decorator_name_from_expr(decorator.func)
    return _decorator_name_from_expr(decorator)


def _resolve_import_module(node: ast.ImportFrom, ref_parts: tuple) -> str:
    imported_mod = ""
    if node.level > 0:
        slice_len = len(ref_parts) - (node.level - 1)
        base_parts = ref_parts[:slice_len]
        if node.module:
            imported_mod = ".".join(base_parts + (node.module,))
        else:
            imported_mod = ".".join(base_parts)
    else:
        if node.module:
            imported_mod = node.module
    return imported_mod


def _check_import_node(node: ast.AST, def_mod: str, ref_parts: tuple, name: str) -> bool:
    if isinstance(node, ast.Import):
        return _matches_import(node.names, def_mod)
    if isinstance(node, ast.ImportFrom):
        imported_mod = _resolve_import_module(node, ref_parts)
        return _matches_from_import(node.names, def_mod, imported_mod, name)
    return False


def is_module_imported(ref_tree: ast.AST, ref_file: Path,
                       def_file: Path, name: str) -> bool:
    """Check if the referencing file actually imports the module containing the definition."""
    def_parts = def_file.with_suffix("").parts
    def_mod = ".".join(def_parts)
    ref_parts = ref_file.parent.parts

    return any(
        _check_import_node(node, def_mod, ref_parts, name)
        for node in ast.walk(ref_tree)
    )


def _matches_import(aliases, def_mod: str) -> bool:
    for alias in aliases:
        if alias.name == def_mod or alias.name.startswith(def_mod + "."):
            return True
    return False


def _check_explicit_name_match(
    imported_mod: str, def_mod: str, name: str, aliases
) -> bool:
    if imported_mod != def_mod:
        return False
    for alias in aliases:
        if alias.name == name or alias.name == "*":
            return True
    return False


def _matches_submodule_import(
    imported_mod: str, def_mod: str, aliases
) -> bool:
    if not def_mod.startswith(imported_mod + "."):
        return False
    remaining = def_mod[len(imported_mod) + 1:]
    next_part = remaining.split(".")[0]
    for alias in aliases:
        if alias.name == next_part or alias.name == "*":
            return True
    return False


def _matches_from_import(aliases, def_mod: str,
                         imported_mod: str, name: str) -> bool:
    if _check_explicit_name_match(imported_mod, def_mod, name, aliases):
        return True
    return _matches_submodule_import(imported_mod, def_mod, aliases)


def _build_context_window(lines: list[str], line_idx: int) -> str:
    start_idx = max(0, line_idx - 6)
    end_idx = min(len(lines), line_idx + 5)
    context = "\n".join(
        f"{idx}: {line_str}"
        for idx, line_str in zip(
            range(start_idx + 1, end_idx + 1), lines[start_idx:end_idx]
        )
    )
    return f"--- Reference in {line_idx} (Lines {start_idx + 1}-{end_idx}) ---\n{context}"


def _collect_file_snippets(f_path: str, content: str, name: str) -> list[str]:
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    lines = content.splitlines()
    snippets: list[str] = []
    matches_found = 0
    for line_idx, line in enumerate(lines, 1):
        if not pattern.search(line):
            continue
        snippets.append(f"--- Reference in {f_path} ---\n" + _build_context_window_for(lines, line_idx))
        matches_found += 1
        if matches_found >= 5:
            break
    return snippets


def _build_context_window_for(lines: list[str], line_idx: int) -> str:
    start_idx = max(0, line_idx - 6)
    end_idx = min(len(lines), line_idx + 5)
    context = "\n".join(
        f"{idx}: {line_str}"
        for idx, line_str in zip(
            range(start_idx + 1, end_idx + 1), lines[start_idx:end_idx]
        )
    )
    return context


def get_match_context_snippets(name: str, file_contents: dict[str, str],
                               referencing_files: list[str]) -> str:
    """Extract a small context window (5 lines before/after) for each reference match."""
    snippets: list[str] = []
    for f_path in referencing_files:
        content = file_contents.get(f_path, "")
        snippets.extend(_collect_file_snippets(f_path, content, name))
    return "\n\n".join(snippets)


def _build_audit_prompt(definition: CodeDefinition, code_snippet: str,
                        reference_context: str, matched_manual: str | None) -> str:
    prompt = (
        f"File Path: {definition.file_path}\n"
        f"Definition Type: {definition.type}\n"
        f"Name: {definition.name}\n"
        f"Defined on Line: {definition.line}\n\n"
        "Here is the code block around this definition:\n"
        "```python\n"
        f"{code_snippet}\n"
        "```\n\n"
        "Here is the context of how/where this symbol is referenced in other codebase files:\n"
        f"{reference_context}\n\n"
    )
    if matched_manual:
        prompt += (
            f"NOTE: This symbol has been detected as referenced in the "
            f"verified manual chapter: {matched_manual}.\n"
            "If it is not active, it is likely 'DISCONNECTED_CORE_LOGIC' "
            "rather than 'CONFIRMED_DEAD'.\n\n"
        )
    prompt += ("Perform a walkthrough of the codebase references. "
               "Audit if this definition is truly dead, disconnected core logic, or a false positive.")
    return prompt


def _extract_code_snippet(def_content: str, line: int) -> str:
    lines = def_content.splitlines()
    start_idx = max(0, line - 2)
    end_idx = min(len(lines), line + 30)
    return "\n".join(lines[start_idx:end_idx])


def audit_candidate_with_llm(
    definition: CodeDefinition,
    file_contents: dict[str, str],
    referencing_files: list[str],
    matched_manual: str | None = None,
) -> AuditResult:
    import time

    print("Pausing 4 seconds before next audit call...")
    time.sleep(4.0)

    def_content = file_contents.get(definition.file_path, "")
    code_snippet = _extract_code_snippet(def_content, definition.line)
    reference_context = get_match_context_snippets(
        definition.name, file_contents, referencing_files
    )
    if not reference_context:
        reference_context = "No static references found in other files (0 matches)."

    prompt = _build_audit_prompt(definition, code_snippet, reference_context, matched_manual)
    return _run_audit_with_backoff(prompt)


def _run_audit_with_backoff(prompt: str) -> AuditResult:
    import time

    backoffs = [90.0, 120.0, 240.0]
    max_attempts = len(backoffs) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            response = audit_agent.run_sync(prompt, model_settings=ModelSettings(max_tokens=1024))
            return response.output
        except API_ERRORS as e:
            _handle_audit_error(e, attempt, max_attempts, backoffs)
    return None  # unreachable; handled inside


def _handle_audit_error(e: Exception, attempt: int,
                        max_attempts: int, backoffs: list[float]):
    import time

    if attempt < max_attempts:
        sleep_time = backoffs[attempt - 1]
        print(
            f"WARNING: API call failed ({e}). Backing off for {sleep_time:.1f}s "
            f"(attempt {attempt}/{max_attempts})...",
            file=sys.stderr,
        )
        time.sleep(sleep_time)
    else:
        print(
            f"CRITICAL: API call failed after {max_attempts} attempts. Shutting down.",
            file=sys.stderr,
        )
        sys.exit(1)


def _write_report_header(out, report: AuditReport):
    out.write("# 🕵️ Dead Code Audit Report\n\n")
    out.write(f"Scanned `{report.scanned_files_count}` files in `src/`.\n\n")

    if report.failed_audits:
        out.write(
            f"⚠️ **Warning**: `{len(report.failed_audits)}` definitions failed to audit "
            f"due to LLM errors. Details at the bottom of the report.\n\n"
        )

    if not report.audit_results:
        if not report.failed_audits:
            out.write("🎉 *No dead code found! All definitions appear to have active references.*\n")
        else:
            out.write("ℹ️ *No dead code candidates could be audited successfully due to errors.*\n")


def _write_report_results(out, report: AuditReport):
    by_file: dict[str, list[AuditResult]] = {}
    for result in report.audit_results:
        by_file.setdefault(result.file_path, []).append(result)

    for f, dead_list in sorted(by_file.items()):
        out.write(f"## 📂 `{f}`\n\n")
        for item in sorted(dead_list, key=lambda x: x.line):
            status_emoji = "🛑" if item.status == "CONFIRMED_DEAD" else "✅"
            out.write(f"### {status_emoji} `{item.name}` (Line {item.line})\n")
            out.write(f"- **Type**: {item.type.capitalize()}\n")
            out.write(f"- **Verdict**: `{item.status}`\n")
            out.write(f"- **Reasoning**: {item.reason}\n\n")
        out.write("---\n\n")


def _write_failed_audits(out, report: AuditReport):
    if not report.failed_audits:
        return
    out.write("## ⚠️ Failed Audits (LLM / API Errors)\n\n")
    out.write(
        "The following definitions could not be audited successfully because the LLM/API call failed:\n\n"
    )
    for item in report.failed_audits:
        out.write(
            f"- `{item['name']}` defined in `{item['file_path']}` "
            f"(Line {item['line']}): **Error**: `{item['error']}`\n"
        )
    out.write("\n")


def generate_markdown_report(report: AuditReport, md_path: Path):
    """Deterministically convert the Pydantic/JSON audit report to Markdown."""
    with open(md_path, "w", encoding="utf-8") as out:
        _write_report_header(out, report)
        _write_report_results(out, report)
        _write_failed_audits(out, report)


def _collect_whitelist_lines(whitelist_file: Path) -> set[str]:
    whitelist: set[str] = set()
    try:
        with open(whitelist_file, encoding="utf-8") as f:
            for line in f:
                cleaned = line.strip()
                if cleaned and not cleaned.startswith("#"):
                    whitelist.add(cleaned)
    except API_ERRORS as e:
        print(f"Warning: Could not read kit-hygiene/whitelist.txt: {e}", file=sys.stderr)
    return whitelist


def load_manual_whitelist() -> set[str]:
    """Load whitelisted symbol names from kit-hygiene/whitelist.txt if it exists."""
    whitelist_file = Path("kit-hygiene/whitelist.txt")
    if not whitelist_file.exists():
        return set()
    return _collect_whitelist_lines(whitelist_file)


def _scan_file_definitions(file_path, file_contents, ast_trees,
                           all_defs, decorator_whitelisted) -> None:
    path_str = str(file_path)
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        file_contents[path_str] = content

        tree = ast.parse(content, filename=path_str)
        ast_trees[path_str] = tree
        extractor = DefinitionExtractor(file_path)
        extractor.visit(tree)

        decorator_whitelisted.update(extractor.whitelisted_names)

        for definition in extractor.definitions:
            all_defs.setdefault(definition.name, []).append(definition)
    except API_ERRORS as e:
        print(f"Error parsing {path_str}: {e}", file=sys.stderr)


def _check_same_file_reference(definition, content, pattern) -> bool:
    return _same_file_references(content, pattern, definition.line)


def _check_cross_file_reference(
    other_file: str, other_tree, def_file_path: Path, definition
) -> bool:
    if not other_tree:
        return False
    other_file_path = Path(other_file)
    return is_module_imported(
        other_tree, other_file_path, def_file_path, definition.name
    )


def _find_referencing_files(definition, file_contents, ast_trees) -> list:
    """Find all files that reference a definition, verifying import context."""
    pattern = re.compile(rf"\b{re.escape(definition.name)}\b")
    def_file_str = definition.file_path
    def_file_path = Path(def_file_str)
    referencing_files = []

    for other_file, content in file_contents.items():
        _classify_reference(
            other_file, def_file_str, content, pattern, other_tree := ast_trees.get(other_file),
            def_file_path, definition, referencing_files
        )

    return referencing_files


def _classify_reference(
    other_file, def_file_str, content, pattern, other_tree,
    def_file_path, definition, referencing_files
) -> None:
    if other_file == def_file_str:
        if _check_same_file_reference(definition, content, pattern):
            referencing_files.append(other_file)
    elif pattern.search(content):
        if _check_cross_file_reference(other_file, other_tree, def_file_path, definition):
            referencing_files.append(other_file)


def _same_file_references(content: str, pattern, def_line: int) -> bool:
    lines = content.splitlines()
    def_line_idx = def_line - 1
    for idx, line in enumerate(lines):
        if idx == def_line_idx:
            continue
        if pattern.search(line):
            return True
    return False


def _collect_audit_candidates(all_defs, whitelist, file_contents,
                              ast_trees) -> list:
    candidates_and_references = []
    for name, occurrences in all_defs.items():
        if name in whitelist:
            continue
        for definition in occurrences:
            referencing_files = _find_referencing_files(definition, file_contents, ast_trees)
            if not referencing_files:
                candidates_and_references.append((definition, referencing_files))
    return candidates_and_references


def _build_codedefs_catalog(files) -> tuple:
    all_defs = {}
    file_contents = {}
    ast_trees = {}
    decorator_whitelisted = set()

    for file_path in files:
        _scan_file_definitions(
            file_path, file_contents, ast_trees, all_defs, decorator_whitelisted
        )

    return all_defs, file_contents, ast_trees, decorator_whitelisted


def _load_existing_results(json_path: Path) -> dict:
    existing_results = {}
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                existing_data = json.load(f)
                for res in existing_data.get("audit_results", []):
                    existing_results[
                        (res.get("file_path"), res.get("line"), res.get("name"))
                    ] = res
        except API_ERRORS as e:
            print(f"WARNING: Failed to load existing JSON report: {e}", file=sys.stderr)
    return existing_results


def _audit_candidates(candidates_and_references, file_contents,
                      manual_terms, json_path) -> tuple:
    report = AuditReport(scanned_files_count=len(file_contents))
    total_candidates = len(candidates_and_references)
    existing_results = _load_existing_results(json_path)

    for index, (definition, referencing_files) in enumerate(
        candidates_and_references, 1
    ):
        key = (definition.file_path, definition.line, definition.name)
        if key in existing_results:
            print(
                f"[{index}/{total_candidates}] Skipping already audited definition: "
                f"{definition.name} in {definition.file_path}"
            )
            res_data = existing_results[key]
            audit = AuditResult(**res_data)
            audit.updated_at = datetime.now().astimezone().isoformat()
            report.audit_results.append(audit)
            continue

        print(f"[{index}/{total_candidates}] Auditing {definition.name} in "
              f"{definition.file_path}...")
        try:
            matched_manual = check_against_manuals(definition.name, manual_terms)
            audit = audit_candidate_with_llm(
                definition, file_contents, referencing_files, matched_manual
            )
            audit.file_path = definition.file_path
            audit.line = definition.line
            audit.type = definition.type
            report.audit_results.append(audit)

            with open(json_path, "w", encoding="utf-8") as f:
                f.write(report.model_dump_json(indent=2))
        except API_ERRORS as e:
            error_msg = str(e)
            print(
                f"WARNING: Auditing failed or exhausted retries for "
                f"{definition.name} in {definition.file_path}: {error_msg}",
                file=sys.stderr,
            )
            report.failed_audits.append(
                {
                    "name": definition.name,
                    "file_path": definition.file_path,
                    "line": definition.line,
                    "error": error_msg,
                }
            )
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(report.model_dump_json(indent=2))

    return report, total_candidates


def _print_candidates(candidates_and_references):
    total_candidates = len(candidates_and_references)
    print(f"AST scan complete. Found {total_candidates} candidate dead definitions to audit.")
    print("\nCandidates found:")
    for idx, (definition, referencing_files) in enumerate(
        candidates_and_references, 1
    ):
        print(f"[{idx}] {definition.name} ({definition.type}) "
              f"in {definition.file_path}:{definition.line}")


def main():
    files = get_src_files()

    all_defs, file_contents, ast_trees, decorator_whitelisted = _build_codedefs_catalog(files)

    whitelist = set(STANDARD_WHITELIST)
    whitelist.update(decorator_whitelisted)
    whitelist.update(load_manual_whitelist())

    candidates_and_references = _collect_audit_candidates(
        all_defs, whitelist, file_contents, ast_trees
    )

    import argparse
    parser = argparse.ArgumentParser(description="Dead Code Scanner")
    parser.add_argument("--scripts", action="store_true",
                        help="Run only static checks and print candidates")
    args = parser.parse_args()

    if args.scripts:
        _print_candidates(candidates_and_references)
        sys.exit(0)

    output_dir = pkg_root / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "dead_code_audit.json"
    md_path = output_dir / "dead_code_audit.md"

    manual_terms = load_verified_manual_terms()
    report, total_candidates = _audit_candidates(
        candidates_and_references, file_contents, manual_terms, json_path
    )

    try:
        generate_markdown_report(report, md_path)
        print(f"Rendered Markdown report saved to {md_path}")
    except API_ERRORS as e:
        print(f"Error generating Markdown report: {e}", file=sys.stderr)

    print(f"\nAudit completed. JSON store stored in {json_path}")


if __name__ == "__main__":
    main()
