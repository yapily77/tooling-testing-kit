import ast
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from _bootstrap import pkg_root  # noqa: F401
from control import CONTROL_SHEET
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from utils import get_src_files


class SecretCandidate(BaseModel):
    name: str = Field(description="The name of the variable or context.")
    file_path: str = Field(description="The source file path relative to workspace root.")
    line: int = Field(description="The starting line number of the candidate block.")
    value_preview: str = Field(description="A sanitized preview of the potential secret value.")


class AuditResult(BaseModel):
    name: str = Field(description="The name of the symbol/block audited.")
    file_path: str = Field(description="The file path of the candidate.")
    line: int = Field(description="The line number of the candidate.")
    status: str = Field(description="Verdict: 'HARDCODED_SECRET' or 'FALSE_POSITIVE'.")
    severity: str = Field(description="Severity: 'HIGH' (real API key / credentials), 'LOW' (dummy keys or test credentials).")
    reason: str = Field(description="A concise 1 to 2 sentence explanation of why this is a secret or a false positive.")
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
        "You are an expert security auditor.\n"
        "Your task is to review a candidate hardcoded secret (like API keys, tokens, passwords, or URLs) flagged by static analysis.\n"
        "Inspect the context and determine if it is a real hardcoded secret (HARDCODED_SECRET) that should be moved to env vars, "
        "or if it is a safe test placeholder/mock value (FALSE_POSITIVE) used only for unit testing or dummy integrations."
    ),
)

_SECRET_KEYWORDS = ["api_key", "token", "secret", "password", "auth_key", "jwt"]
_SECRET_REGEX = re.compile(
    r"(?:sk-[a-zA-Z0-9]{20,}|bearer\s+[a-zA-Z0-9_\-\.]{15,}|[a-fA-F0-9]{32,}|nvapi-[a-zA-Z0-9_\-]{30,})",
    re.IGNORECASE
)


def _is_secret_target_name(name: str) -> bool:
    lowered = name.lower()
    return any(k in lowered for k in _SECRET_KEYWORDS)


def _make_preview(val: str) -> str:
    if len(val) > 8:
        return val[:4] + "..." + val[-4:]
    return val


def _is_valid_secret_value(val: str) -> bool:
    if len(val) <= 6:
        return False
    if val.startswith("{{") and val.endswith("}}"):
        return False
    return True


def _build_candidate(name: str, file_path: str, line: int, val: str) -> SecretCandidate:
    return SecretCandidate(
        name=name,
        file_path=file_path,
        line=line,
        value_preview=_make_preview(val)
    )


class SecretsExtractor(ast.NodeVisitor):
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.candidates: list[SecretCandidate] = []

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and _is_secret_target_name(target.id):
                self._check_assignment_value(node, target.id)
        self.generic_visit(node)

    def _check_assignment_value(self, node: ast.Assign, target_name: str):
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            return
        val = node.value.value
        if not _is_valid_secret_value(val):
            return
        self.candidates.append(
            _build_candidate(target_name, str(self.file_path), node.lineno, val)
        )

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            match = _SECRET_REGEX.search(node.value)
            if match:
                self.candidates.append(
                    _build_candidate("string_literal", str(self.file_path), node.lineno, node.value)
                )


def audit_candidate_with_llm(candidate: SecretCandidate, file_contents: dict[str, str]) -> AuditResult:
    import time

    print("Pausing 4 seconds before next audit call...")
    time.sleep(4.0)
    cand_file = candidate.file_path
    content = file_contents.get(cand_file, "")
    lines = content.splitlines()

    start_idx = max(0, candidate.line - 5)
    end_idx = min(len(lines), candidate.line + 10)
    code_snippet = _build_code_snippet(lines, start_idx, end_idx)

    prompt = _build_audit_prompt(candidate, cand_file, code_snippet)

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


def _build_code_snippet(lines: list[str], start_idx: int, end_idx: int) -> str:
    return "\n".join(
        f"{idx}: {line}" for idx, line in zip(range(start_idx + 1, end_idx + 1), lines[start_idx:end_idx])
    )


def _build_audit_prompt(candidate: SecretCandidate, cand_file: str, code_snippet: str) -> str:
    return (
        f"File Path: {cand_file}\n"
        f"Symbol Name: {candidate.name}\n"
        f"Target Line: {candidate.line}\n"
        f"Value Preview: {candidate.value_preview}\n\n"
        "Here is the code block around this candidate:\n"
        "```python\n"
        f"{code_snippet}\n"
        "```\n\n"
        "Audit if this represents a dangerous hardcoded credential (HARDCODED_SECRET) or a safe placeholder/mock value (FALSE_POSITIVE)."
    )


def generate_markdown_report(report: AuditReport, md_path: Path):
    with open(md_path, "w", encoding="utf-8") as out:
        out.write("# Hardcoded Secrets Audit Report\n\n")
        out.write(f"Scanned `{report.scanned_files_count}` files in `src/`.\n\n")

        if not report.audit_results:
            out.write("No hardcoded secrets found! All files appear secure.\n")
        else:
            by_file = _group_results_by_file(report.audit_results)
            for f, list_results in sorted(by_file.items()):
                out.write(f"## `{f}`\n\n")
                for item in sorted(list_results, key=lambda x: x.line):
                    status_emoji = "STOP" if item.status == "HARDCODED_SECRET" else "OK"
                    out.write(f"### {status_emoji} Line {item.line}: `{item.name}`\n")
                    out.write(f"- **Verdict**: `{item.status}`\n")
                    out.write(f"- **Severity**: `{item.severity}`\n")
                    out.write(f"- **Reasoning**: {item.reason}\n\n")
                out.write("---\n\n")


def _group_results_by_file(results: list[AuditResult]) -> dict[str, list[AuditResult]]:
    by_file: dict[str, list[AuditResult]] = {}
    for result in results:
        by_file.setdefault(result.file_path, []).append(result)
    return by_file


def _scan_files(files: list[Path]) -> tuple[list[SecretCandidate], dict[str, str]]:
    all_candidates: list[SecretCandidate] = []
    file_contents: dict[str, str] = {}

    for file_path in files:
        path_str = str(file_path)
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                file_contents[path_str] = content

            tree = ast.parse(content, filename=path_str)
            extractor = SecretsExtractor(file_path)
            extractor.visit(tree)
            all_candidates.extend(extractor.candidates)
        except (OSError, SyntaxError) as e:
            print(f"Error parsing {path_str}: {e}", file=sys.stderr)

    return all_candidates, file_contents


def _parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Secrets Scanner")
    parser.add_argument("--scripts", action="store_true", help="Run only static checks and print candidates")
    return parser.parse_args()


def _load_existing_results(json_path: Path) -> dict:
    if not json_path.exists():
        return {}
    try:
        with open(json_path, encoding="utf-8") as f:
            existing_data = json.load(f)
            return {
                (res.get("file_path"), res.get("line"), res.get("name")): res
                for res in existing_data.get("audit_results", [])
            }
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"WARNING: Failed to load existing JSON report: {e}", file=sys.stderr)
        return {}


def _audit_candidates(all_candidates: list[SecretCandidate], file_contents: dict[str, str], existing_results: dict):
    report = AuditReport(scanned_files_count=0)
    output_dir = Path("kit-hygiene/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "secrets_audit.json"

    total = len(all_candidates)
    for index, candidate in enumerate(all_candidates, 1):
        key = (candidate.file_path, candidate.line, candidate.name)
        if key in existing_results:
            print(f"[{index}/{total}] Skipping already audited candidate: {candidate.name} in {candidate.file_path}:{candidate.line}")
            res_data = existing_results[key]
            audit = AuditResult(**res_data)
            audit.updated_at = datetime.now().astimezone().isoformat()
            report.audit_results.append(audit)
            continue
        print(f"[{index}/{total}] Auditing {candidate.name} in {candidate.file_path}:{candidate.line}...")
        try:
            audit = audit_candidate_with_llm(candidate, file_contents)
            audit.file_path = candidate.file_path
            audit.line = candidate.line
            report.audit_results.append(audit)
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(report.model_dump_json(indent=2))
        except (OSError, ValueError, TypeError, RuntimeError) as e:
            print(f"WARNING: Auditing failed for {candidate.name}: {e}", file=sys.stderr)

    return report


def main():
    files = get_src_files()
    all_candidates, file_contents = _scan_files(files)

    args = _parse_args()

    total_candidates = len(all_candidates)
    print(f"AST scan complete. Found {total_candidates} candidate secrets to audit.")

    if args.scripts:
        print("\nCandidates found:")
        for idx, cand in enumerate(all_candidates, 1):
            print(f"[{idx}] {cand.name} in {cand.file_path}:{cand.line} (Preview: {cand.value_preview})")
        sys.exit(0)

    output_dir = Path("kit-hygiene/reports")
    json_path = output_dir / "secrets_audit.json"
    existing_results = _load_existing_results(json_path)
    md_path = output_dir / "secrets_audit.md"

    report = _audit_candidates(all_candidates, file_contents, existing_results)
    report.scanned_files_count = len(files)
    generate_markdown_report(report, md_path)
    print(f"Rendered Markdown report saved to {md_path}")


if __name__ == "__main__":
    main()
