import ast
import json
import sys
from datetime import datetime
from pathlib import Path

from _bootstrap import pkg_root  # noqa: F401
from control import CONTROL_SHEET
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from utils import get_src_files


class SilentKillerCandidate(BaseModel):
    name: str = Field(description="The name of the variable, function, or block type.")
    file_path: str = Field(description="The source file path relative to workspace root.")
    line: int = Field(description="The starting line number of the candidate block.")
    type: str = Field(description="The type of candidate: swallowed_exception or silent_fallback.")


class AuditResult(BaseModel):
    name: str = Field(description="The name of the symbol/block audited.")
    file_path: str = Field(description="The file path of the candidate.")
    line: int = Field(description="The line number of the candidate.")
    type: str = Field(description="Type: swallowed_exception or silent_fallback.")
    status: str = Field(description="Verdict: 'SILENT_KILLER' or 'FALSE_POSITIVE'.")
    severity: str = Field(description="Severity of the violation: 'HIGH' (dangerous swallow), 'MEDIUM' (fallback with defaults), or 'LOW' (standard safe check).")
    reason: str = Field(
        description="A concise 1 to 2 sentence explanation of why it is a silent killer or how it is a safe fallback."
    )
    updated_at: str | None = Field(default=None, description="Timestamp of when the audit was performed.")


class AuditReport(BaseModel):
    scanned_files_count: int = Field(description="Total number of Python files scanned.")
    audit_results: list[AuditResult] = Field(
        default_factory=list, description="Audit results for all scanned candidate blocks."
    )
    failed_audits: list[dict] = Field(
        default_factory=list, description="List of candidates that failed LLM validation due to errors."
    )


scanner_model = CONTROL_SHEET.scanner_model

audit_agent = Agent(
    scanner_model,
    output_type=AuditResult,
    retries=3,
    system_prompt=(
        "You are an expert static analyzer and code quality auditor.\n"
        "Your task is to review a code snippet flagged as a potential 'silent killer' (e.g., swallowed exceptions, try/except pass, or silent default fallbacks).\n"
        "Inspect the context and determine if it is a dangerous silent failure that violates 'fail loudly' principles, "
        "or if it is a safe/intended fallback (like loading optional local configurations or checking dictionary presence)."
    ),
)


def _is_logger_call(func: ast.expr) -> bool:
    """Check if a function expression is a logger.exception/error/warning call."""
    if not isinstance(func, ast.Attribute):
        return False
    val_id = getattr(func.value, "id", None)
    return val_id == "logger" and func.attr in ("exception", "error", "warning")


def _is_exit_call(func: ast.expr) -> bool:
    """Check if a function expression is a call to exit or sys.exit."""
    if isinstance(func, ast.Name):
        return func.id in ("exit", "sys.exit")
    return False


def _is_loud_call(func: ast.expr) -> bool:
    """Check if a function expression is a loud call (logger or exit)."""
    if _is_logger_call(func):
        return True
    return _is_exit_call(func)


def _is_handler_loud(handler: ast.ExceptHandler) -> bool:
    """Check if a try/except handler has loud handling (raise, logger, or exit call)."""
    for child in ast.walk(handler):
        if isinstance(child, ast.Raise):
            return True
        if isinstance(child, ast.Call) and _is_loud_call(child.func):
            return True
    return False


def _get_handler_name(handler: ast.ExceptHandler) -> str:
    """Extract a human-readable name from an exception handler."""
    if isinstance(handler.type, ast.Name):
        return handler.type.id
    if isinstance(handler.type, ast.Attribute):
        return handler.type.attr
    return "Exception"


def _is_suspect_dict_default(default_arg: ast.expr) -> bool:
    """Check if a dict.get default value is a suspect placeholder."""
    if (
        isinstance(default_arg, ast.Constant)
        and isinstance(default_arg.value, str)
        and default_arg.value.lower() in ("n/a", "unknown", "null")
    ):
        return True
    return False


def _extract_dict_get_default(node: ast.Call) -> ast.expr | None:
    """Extract the default value from a dict.get call's args or keyword."""
    if len(node.args) >= 2:
        return node.args[1]
    for kw in node.keywords:
        if kw.arg == "default":
            return kw.value
    return None


def _is_safe_get_call(node: ast.Call) -> bool:
    """Check if a Call node is a _safe_get call."""
    return isinstance(node.func, ast.Name) and node.func.id == "_safe_get"


def _is_dict_get_fallback(node: ast.Call) -> bool:
    """Check if a Call node is a dict.get with a suspect default value."""
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
        return False
    default_arg = _extract_dict_get_default(node)
    return default_arg is not None and _is_suspect_dict_default(default_arg)


def _classify_safe_get_call(node: ast.Call) -> tuple[bool, str]:
    """Check if a Call node is a _safe_get or suspect dict.get call."""
    if _is_safe_get_call(node):
        return True, "_safe_get"
    if _is_dict_get_fallback(node):
        return True, "dict.get"
    return False, ""


class SilentKillerExtractor(ast.NodeVisitor):
    """AST visitor to collect swallowed exceptions and silent fallbacks."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.candidates: list[SilentKillerCandidate] = []

    def visit_Try(self, node: ast.Try):
        for handler in node.handlers:
            if not _is_handler_loud(handler):
                handler_name = _get_handler_name(handler)
                self.candidates.append(
                    SilentKillerCandidate(
                        name=handler_name,
                        file_path=str(self.file_path),
                        line=handler.lineno,
                        type="swallowed_exception"
                    )
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        is_fallback, name = _classify_safe_get_call(node)
        if is_fallback:
            self.candidates.append(
                SilentKillerCandidate(
                    name=name,
                    file_path=str(self.file_path),
                    line=node.lineno,
                    type="silent_fallback"
                )
            )
        self.generic_visit(node)


def audit_candidate_with_llm(
    candidate: SilentKillerCandidate, file_contents: dict[str, str]
) -> AuditResult:
    import time

    # Firing takes a 4-second pause to prevent rate-limiting/overload
    print("Pausing 4 seconds before next audit call...")
    time.sleep(4.0)
    """Send candidate and its surrounding code context to the LLM for silent killer audit."""
    cand_file = candidate.file_path
    content = file_contents.get(cand_file, "")
    lines = content.splitlines()

    # Extract context: 10 lines before, 30 lines after
    start_idx = max(0, candidate.line - 10)
    end_idx = min(len(lines), candidate.line + 30)
    code_snippet = "\n".join(f"{idx}: {line}" for idx, line in zip(range(start_idx + 1, end_idx + 1), lines[start_idx:end_idx]))

    prompt = (
        f"File Path: {cand_file}\n"
        f"Candidate Type: {candidate.type}\n"
        f"Symbol Name: {candidate.name}\n"
        f"Target Line: {candidate.line}\n\n"
        "Here is the code block around this candidate:\n"
        "```python\n"
        f"{code_snippet}\n"
        "```\n\n"
        "Perform a walkthrough of this code context. Audit if this represents a dangerous silent failure/fallback (SILENT_KILLER) or a safe, expected pattern (FALSE_POSITIVE)."
    )

    backoffs = [90.0, 120.0, 240.0]
    max_attempts = len(backoffs) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            response = audit_agent.run_sync(prompt, model_settings=ModelSettings(max_tokens=1024))
            return response.output
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            if attempt < max_attempts:
                sleep_time = backoffs[attempt - 1]
                print(
                    f"WARNING: API call failed ({e}). Backing off for {sleep_time:.1f}s (attempt {attempt}/{max_attempts})...",
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
    """Write the report header section."""
    out.write("# 🕵️ Silent Killers & Fallback Audit Report\n\n")
    out.write(f"Scanned `{report.scanned_files_count}` files in `src/`.\n\n")
    if report.failed_audits:
        out.write(f"⚠️ **Warning**: `{len(report.failed_audits)}` candidates failed to audit due to LLM errors.\n\n")


def _write_empty_results_section(out, report: AuditReport):
    """Write the 'no results' message."""
    if not report.failed_audits:
        out.write("🎉 *No silent killers or fallbacks found! All files adhere to the 'fail loudly' policy.*\n")
    else:
        out.write("ℹ️ *No candidate could be audited successfully due to errors.*\n")


def _group_results_by_file(report: AuditReport) -> dict[str, list[AuditResult]]:
    """Group audit results by file path."""
    by_file: dict[str, list[AuditResult]] = {}
    for result in report.audit_results:
        f = result.file_path
        if f not in by_file:
            by_file[f] = []
        by_file[f].append(result)
    return by_file


def _write_grouped_results(out, report: AuditReport):
    """Write the grouped audit results section."""
    by_file = _group_results_by_file(report)
    for f, list_results in sorted(by_file.items()):
        out.write(f"## 📂 `{f}`\n\n")
        for item in sorted(list_results, key=lambda x: x.line):
            status_emoji = "🛑" if item.status == "SILENT_KILLER" else "✅"
            out.write(f"### {status_emoji} Line {item.line}: `{item.name}` ({item.type})\n")
            out.write(f"- **Verdict**: `{item.status}`\n")
            out.write(f"- **Severity**: `{item.severity}`\n")
            out.write(f"- **Reasoning**: {item.reason}\n\n")
        out.write("---\n\n")


def _write_failed_audits_section(out, report: AuditReport):
    """Write the failed audits section."""
    if not report.failed_audits:
        return
    out.write("## ⚠️ Failed Audits (LLM / API Errors)\n\n")
    for item in report.failed_audits:
        out.write(f"- `{item['name']}` in `{item['file_path']}` (Line {item['line']}): **Error**: `{item['error']}`\n")
    out.write("\n")


def generate_markdown_report(report: AuditReport, md_path: Path):
    """Deterministically convert the Pydantic/JSON audit report to Markdown."""
    with open(md_path, "w", encoding="utf-8") as out:
        _write_report_header(out, report)
        if not report.audit_results:
            _write_empty_results_section(out, report)
        else:
            _write_grouped_results(out, report)
        _write_failed_audits_section(out, report)


def _scan_files(files: list[Path]) -> tuple[dict[str, str], list[SilentKillerCandidate]]:
    """Parse source files, collect file contents and candidates."""
    all_candidates: list[SilentKillerCandidate] = []
    file_contents: dict[str, str] = {}
    for file_path in files:
        path_str = str(file_path)
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                file_contents[path_str] = content
            tree = ast.parse(content, filename=path_str)
            extractor = SilentKillerExtractor(file_path)
            extractor.visit(tree)
            all_candidates.extend(extractor.candidates)
        except (OSError, SyntaxError) as e:
            print(f"Error parsing {path_str}: {e}", file=sys.stderr)
    return file_contents, all_candidates


def _load_existing_results(json_path: Path) -> dict[tuple, dict]:
    """Load existing audit results from JSON store."""
    existing_results: dict[tuple, dict] = {}
    if not json_path.exists():
        return existing_results
    try:
        with open(json_path, encoding="utf-8") as f:
            existing_data = json.load(f)
            for res in existing_data.get("audit_results", []):
                existing_results[(res.get("file_path"), res.get("line"), res.get("name"))] = res
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"WARNING: Failed to load existing JSON report: {e}", file=sys.stderr)
    return existing_results


def _audit_single_candidate(
    candidate: SilentKillerCandidate,
    index: int,
    total: int,
    existing_results: dict[tuple, dict],
    report: AuditReport,
    file_contents: dict[str, str],
    json_path: Path,
) -> None:
    """Process a single candidate: reuse cached result or audit via LLM."""
    key = (candidate.file_path, candidate.line, candidate.name)
    if key in existing_results:
        res_data = existing_results[key]
        audit = AuditResult(**res_data)
        audit.updated_at = datetime.now().astimezone().isoformat()
        report.audit_results.append(audit)
        return
    print(f"[{index}/{total}] Auditing {candidate.name} ({candidate.type}) in {candidate.file_path}:{candidate.line}...")
    try:
        audit = audit_candidate_with_llm(candidate, file_contents)
        audit.file_path = candidate.file_path
        audit.line = candidate.line
        audit.type = candidate.type
        report.audit_results.append(audit)
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))
    except (OSError, ValueError, TypeError, RuntimeError) as e:
        _record_failed_audit(candidate, index, total, str(e), report, json_path)


def _record_failed_audit(
    candidate: SilentKillerCandidate,
    index: int,
    total: int,
    error_msg: str,
    report: AuditReport,
    json_path: Path,
) -> None:
    """Record a failed audit and persist the report."""
    print(
        f"WARNING: Auditing failed for {candidate.name} at {candidate.file_path}:{candidate.line}: {error_msg}",
        file=sys.stderr,
    )
    report.failed_audits.append(
        {
            "name": candidate.name,
            "file_path": candidate.file_path,
            "line": candidate.line,
            "error": error_msg,
        }
    )
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))


def _print_scripts_output(all_candidates: list[SilentKillerCandidate]) -> None:
    """Print the static-only candidate listing and exit."""
    print("\nCandidates found:")
    for idx, cand in enumerate(all_candidates, 1):
        print(f"[{idx}] {cand.name} ({cand.type}) in {cand.file_path}:{cand.line}")
    sys.exit(0)


def main():
    import argparse

    files = get_src_files()
    file_contents, all_candidates = _scan_files(files)

    parser = argparse.ArgumentParser(description="Silent Killer Scanner")
    parser.add_argument("--scripts", action="store_true", help="Run only static checks and print candidates")
    args = parser.parse_args()

    total_candidates = len(all_candidates)
    print(f"AST scan complete. Found {total_candidates} candidate silent killers to audit.")

    if args.scripts:
        _print_scripts_output(all_candidates)

    report = AuditReport(scanned_files_count=len(files))

    output_dir = Path("kit-hygiene/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "silent_killers_audit.json"
    md_path = output_dir / "silent_killers_audit.md"

    existing_results = _load_existing_results(json_path)

    for index, candidate in enumerate(all_candidates, 1):
        _audit_single_candidate(candidate, index, total_candidates, existing_results, report, file_contents, json_path)

    try:
        generate_markdown_report(report, md_path)
        print(f"Rendered Markdown report saved to {md_path}")
    except (OSError, ValueError, RuntimeError) as e:
        print(f"Error generating Markdown report: {e}", file=sys.stderr)

    print(f"\nAudit completed. JSON store stored in {json_path}")


if __name__ == "__main__":
    main()
