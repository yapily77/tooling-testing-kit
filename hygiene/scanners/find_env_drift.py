import argparse
import ast
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from _bootstrap import pkg_root  # noqa: F401
from control import CONTROL_SHEET
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from utils import get_src_files


class EnvDriftCandidate(BaseModel):
    name: str = Field(description="The name of the environment variable.")
    file_path: str = Field(description="The source file path relative to workspace root.")
    line: int = Field(description="The starting line number of the candidate block.")
    type: str = Field(description="Type: undocumented (used in code, missing in example) or unused_example (in example, not in code).")


class AuditResult(BaseModel):
    name: str = Field(description="The name of the env variable.")
    file_path: str = Field(description="The file path of the candidate.")
    line: int = Field(description="The line number of the candidate.")
    type: str = Field(description="Type: undocumented or unused_example.")
    status: str = Field(description="Verdict: 'DRIFT_VIOLATION' or 'FALSE_POSITIVE'.")
    severity: str = Field(description="Severity: 'HIGH' (critical secret/config missing from example), 'LOW' (minor diagnostic flag).")
    reason: str = Field(description="A concise 1 to 2 sentence explanation of why this represents env drift or a false positive.")
    updated_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat(), description="The ISO datetime string when this violation was audited or updated.")


class AuditReport(BaseModel):
    scanned_files_count: int = Field(description="Total number of Python files scanned.")
    audit_results: list[AuditResult] = Field(default_factory=list)
    failed_audits: list[dict] = Field(default_factory=list)


scanner_model = CONTROL_SHEET.scanner_model

audit_agent = Agent(
    scanner_model,
    output_type=AuditResult,
    retries=3,
    system_prompt=(
        "You are an expert devops and systems auditor.\n"
        "Your task is to review a candidate environment variable drift violation (where a variable is referenced in code but missing from `.env.example` or vice versa).\n"
        "Inspect the context and determine if it is a true environment drift violation (DRIFT_VIOLATION) that breaks staging/deployments, "
        "or if it is a false positive (FALSE_POSITIVE) such as standard library fallbacks (e.g., PORT) or system-level settings."
    ),
)


_WIDE_EXCEPTIONS = (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError)


def _parse_env_line(line: str) -> str | None:
    """Extract a variable name from a single .env.example line, or return None."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = stripped.split("=", 1)
    if not parts:
        return None
    return parts[0].strip()


class EnvVarExtractor(ast.NodeVisitor):
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.env_vars: list[tuple[str, int]] = []

    def visit_Call(self, node: ast.Call):
        var_name = self._extract_var_from_call(node)
        if var_name is not None:
            self.env_vars.append((var_name, node.lineno))
        self.generic_visit(node)

    @staticmethod
    def _extract_var_from_call(node: ast.Call) -> str | None:
        """Return the env var name from an os.getenv / os.environ.get call, or None."""
        if not isinstance(node.func, ast.Attribute) or not node.args:
            return None
        if not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            return None
        return EnvVarExtractor._get_env_var_name(node.func, node.args[0].value)

    @staticmethod
    def _get_env_var_name(func: ast.Attribute, var_value: str) -> str | None:
        """Check the attribute and return the env var name if it's an os.getenv or os.environ.get call."""
        attr = func.attr
        if attr == "getenv":
            return var_value
        if attr == "get" and isinstance(func.value, ast.Attribute) and func.value.attr == "environ":
            return var_value
        return None

    def visit_Subscript(self, node: ast.Subscript):
        var_name = self._extract_var_from_subscript(node)
        if var_name is not None:
            self.env_vars.append((var_name, node.lineno))
        self.generic_visit(node)

    @staticmethod
    def _extract_var_from_subscript(node: ast.Subscript) -> str | None:
        """Return the env var name from an os.environ["VAR"] subscript, or None."""
        if not isinstance(node.value, ast.Attribute):
            return None
        if node.value.attr != "environ":
            return None
        if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
            return None
        return node.slice.value


def load_env_example_vars() -> set[str]:
    example_path = Path(".env.example")
    if not example_path.exists():
        return set()
    return _read_env_example(example_path)


def _read_env_example(example_path: Path) -> set[str]:
    try:
        with open(example_path, encoding="utf-8") as f:
            result: set[str] = set()
            for line in f:
                if (var := _parse_env_line(line)) is not None:
                    result.add(var)
            return result
    except _WIDE_EXCEPTIONS as e:
        print(f"Warning: Could not read .env.example: {e}", file=sys.stderr)
        return set()


def audit_candidate_with_llm(candidate: EnvDriftCandidate, file_contents: dict[str, str]) -> AuditResult:
    print("Pausing 4 seconds before next audit call...")
    time.sleep(4.0)
    return _call_audit_agent(candidate, file_contents)


def _build_audit_prompt(candidate: EnvDriftCandidate, file_contents: dict[str, str]) -> str:
    cand_file = candidate.file_path
    content = file_contents.get(cand_file, "")
    lines = content.splitlines()

    start_idx = max(0, candidate.line - 5)
    end_idx = min(len(lines), candidate.line + 10)
    code_snippet = "\n".join(f"{idx}: {line}" for idx, line in zip(range(start_idx + 1, end_idx + 1), lines[start_idx:end_idx]))

    return (
        f"File Path: {cand_file}\n"
        f"Variable Name: {candidate.name}\n"
        f"Type of Drift: {candidate.type}\n"
        f"Target Line: {candidate.line}\n\n"
        "Here is the code block around this candidate:\n"
        "```python\n"
        f"{code_snippet}\n"
        "```\n\n"
        "Audit if this represents a true env drift violation (DRIFT_VIOLATION) or a standard library fallback (FALSE_POSITIVE)."
    )


def _call_audit_agent(candidate: EnvDriftCandidate, file_contents: dict[str, str]) -> AuditResult:
    prompt = _build_audit_prompt(candidate, file_contents)
    backoffs = [90.0, 120.0, 240.0]
    max_attempts = len(backoffs) + 1

    for attempt in range(1, max_attempts + 1):
        try:
            response = audit_agent.run_sync(prompt, model_settings=ModelSettings(max_tokens=1024))
            return response.output
        except _WIDE_EXCEPTIONS as e:
            if attempt < max_attempts:
                sleep_time = backoffs[attempt - 1]
                print(
                    f"WARNING: API call failed ({e}). Backing off for {sleep_time:.1f}s (attempt {attempt}/{max_attempts})...",
                    file=sys.stderr,
                )
                time.sleep(sleep_time)
            else:
                _abort_after_failures(max_attempts)
                raise RuntimeError("Unreachable: _abort_after_failures calls sys.exit")


def _abort_after_failures(max_attempts: int) -> None:
    print(
        f"CRITICAL: API call failed after {max_attempts} attempts. Shutting down.",
        file=sys.stderr,
    )
    sys.exit(1)


def generate_markdown_report(report: AuditReport, md_path: Path):
    with open(md_path, "w", encoding="utf-8") as out:
        _write_report_header(out, report)
        if report.audit_results:
            _write_report_body(out, report.audit_results)


def _write_report_header(out, report: AuditReport):
    out.write("# \U0001f575\ufe0f Environment Variables Drift Audit Report\n\n")
    out.write(f"Scanned `{report.scanned_files_count}` files in `src/`.\n\n")
    if not report.audit_results:
        out.write("\U0001f389 *No environment drift detected! .env.example matches the codebase.*\n")


def _write_report_body(out, audit_results: list[AuditResult]):
    by_file: dict[str, list[AuditResult]] = {}
    for result in audit_results:
        by_file.setdefault(result.file_path, []).append(result)

    for f, list_results in sorted(by_file.items()):
        out.write(f"## \U0001f4c2 `{f}`\n\n")
        for item in sorted(list_results, key=lambda x: x.line):
            _write_result_item(out, item)


def _write_result_item(out, item: AuditResult):
    status_emoji = "\U0001f6a8" if item.status == "DRIFT_VIOLATION" else "\u2705"
    out.write(f"### {status_emoji} Line {item.line}: `{item.name}` ({item.type})\n")
    out.write(f"- **Verdict**: `{item.status}`\n")
    out.write(f"- **Severity**: `{item.severity}`\n")
    out.write(f"- **Reasoning**: {item.reason}\n\n")


def _collect_code_vars(files: list[Path]) -> tuple[dict[str, str], dict[str, list[tuple[str, int]]]]:
    """Walk source files and extract env var references. Returns (file_contents, code_vars)."""
    file_contents: dict[str, str] = {}
    code_vars: dict[str, list[tuple[str, int]]] = {}

    for file_path in files:
        path_str = str(file_path)
        content = _read_source_file(file_path, path_str)
        if content is None:
            continue
        file_contents[path_str] = content
        _extract_vars_from_ast(content, path_str, file_path, code_vars)

    return file_contents, code_vars


def _read_source_file(file_path: Path, path_str: str) -> str | None:
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except _WIDE_EXCEPTIONS as e:
        print(f"Error parsing {path_str}: {e}", file=sys.stderr)
        return None


def _extract_vars_from_ast(content: str, path_str: str, file_path: Path, code_vars: dict[str, list]):
    try:
        tree = ast.parse(content, filename=path_str)
    except _WIDE_EXCEPTIONS as e:
        print(f"Error parsing {path_str}: {e}", file=sys.stderr)
        return
    extractor = EnvVarExtractor(file_path)
    extractor.visit(tree)
    for var_name, line in extractor.env_vars:
        code_vars.setdefault(var_name, []).append((path_str, line))


def _collect_candidates(code_vars: dict[str, list[tuple[str, int]]], example_vars: set[str]) -> list[EnvDriftCandidate]:
    """Build the list of drift candidates from code vars and example vars."""
    candidates: list[EnvDriftCandidate] = []
    candidates.extend(_undocumented_candidates(code_vars, example_vars))
    candidates.extend(_unused_example_candidates(example_vars, code_vars))
    return candidates


def _undocumented_candidates(code_vars: dict[str, list[tuple[str, int]]], example_vars: set[str]) -> list[EnvDriftCandidate]:
    result: list[EnvDriftCandidate] = []
    for var_name, occurrences in code_vars.items():
        if var_name not in example_vars:
            for path_str, line in occurrences:
                result.append(EnvDriftCandidate(name=var_name, file_path=path_str, line=line, type="undocumented"))
    return result


def _unused_example_candidates(example_vars: set[str], code_vars: dict) -> list[EnvDriftCandidate]:
    result: list[EnvDriftCandidate] = []
    for var_name in example_vars:
        if var_name not in code_vars:
            result.append(EnvDriftCandidate(name=var_name, file_path=".env.example", line=1, type="unused_example"))
    return result


def _load_existing_results(json_path: Path) -> dict[tuple[str, int, str], dict]:
    if not json_path.exists():
        return {}
    try:
        with open(json_path, encoding="utf-8") as f:
            existing_data = json.load(f)
    except _WIDE_EXCEPTIONS as e:
        print(f"WARNING: Failed to load existing JSON report: {e}", file=sys.stderr)
        return {}
    return {
        (res.get("file_path"), res.get("line"), res.get("name")): res
        for res in existing_data.get("audit_results", [])
    }


def _run_audit_loop(
    candidates: list[EnvDriftCandidate],
    file_contents: dict[str, str],
    report: AuditReport,
    json_path: Path,
    existing_results: dict,
):
    total = len(candidates)
    for index, candidate in enumerate(candidates, 1):
        key = (candidate.file_path, candidate.line, candidate.name)
        if key in existing_results:
            print(f"[{index}/{total}] Skipping already audited candidate: {candidate.name} in {candidate.file_path}:{candidate.line}")
            audit = AuditResult(**existing_results[key])
            audit.updated_at = datetime.now().astimezone().isoformat()
            report.audit_results.append(audit)
            continue
        print(f"[{index}/{total}] Auditing {candidate.name} in {candidate.file_path}:{candidate.line}...")
        _audit_one_candidate(candidate, file_contents, report, json_path)


def _audit_one_candidate(candidate: EnvDriftCandidate, file_contents: dict[str, str], report: AuditReport, json_path: Path):
    try:
        audit = audit_candidate_with_llm(candidate, file_contents)
        audit.file_path = candidate.file_path
        audit.line = candidate.line
        audit.type = candidate.type
        report.audit_results.append(audit)
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))
    except _WIDE_EXCEPTIONS as e:
        print(f"WARNING: Auditing failed for {candidate.name}: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Env Drift Scanner")
    parser.add_argument("--scripts", action="store_true", help="Run only static checks and print candidates")
    args = parser.parse_args()

    files = get_src_files()
    example_vars = load_env_example_vars()
    file_contents, code_vars = _collect_code_vars(files)
    candidates = _collect_candidates(code_vars, example_vars)

    total = len(candidates)
    print(f"Scan complete. Found {total} environment drift candidates to audit.")

    if args.scripts:
        _print_candidates(candidates)
        return

    _run_full_audit(files, candidates, file_contents)


def _print_candidates(candidates: list[EnvDriftCandidate]):
    print("\nCandidates found:")
    for idx, cand in enumerate(candidates, 1):
        print(f"[{idx}] {cand.name} ({cand.type}) in {cand.file_path}:{cand.line}")
    sys.exit(0)


def _run_full_audit(files: list[Path], candidates: list[EnvDriftCandidate], file_contents: dict[str, str]):
    output_dir = Path("kit-hygiene/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "env_drift_audit.json"
    md_path = output_dir / "env_drift_audit.md"

    existing_results = _load_existing_results(json_path)
    report = AuditReport(scanned_files_count=len(files))

    _run_audit_loop(candidates, file_contents, report, json_path, existing_results)
    generate_markdown_report(report, md_path)
    print(f"Rendered Markdown report saved to {md_path}")


if __name__ == "__main__":
    main()
