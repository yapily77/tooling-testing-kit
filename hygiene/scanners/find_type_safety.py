import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from _bootstrap import pkg_root  # noqa: F401
from control import CONTROL_SHEET
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from utils import get_src_files


class TypeSafetyCandidate(BaseModel):
    name: str = Field(description="The type safety error classification.")
    file_path: str = Field(description="The source file path relative to workspace root.")
    line: int = Field(description="The line number of the type error.")
    error_message: str = Field(description="The raw error message from the type checker.")


class AuditResult(BaseModel):
    name: str = Field(description="The type safety error classification.")
    file_path: str = Field(description="The file path of the candidate.")
    line: int = Field(description="The line number of the candidate.")
    status: str = Field(description="Verdict: 'TYPE_HAZARD' or 'FALSE_POSITIVE'.")
    severity: str = Field(description="Severity: 'HIGH' (critical type mismatch on engine/api parameters), 'LOW' (minor type annotation warning).")
    reason: str = Field(description="A concise 1 to 2 sentence explanation of why this type error is a hazard and how to resolve it.")
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
        "You are an expert static analysis and Python type safety auditor.\n"
        "Your task is to review a candidate type checker error (from mypy/pyright) flagged by static analysis.\n"
        "Verify if the type mismatch represents a true type hazard (TYPE_HAZARD) that can cause runtime exceptions, "
        "or if it is a false positive (FALSE_POSITIVE) such as untyped third-party libraries or standard dynamic overrides."
    ),
)


def _parse_mypy_line(line: str) -> TypeSafetyCandidate | None:
    """Parse a single mypy output line into a TypeSafetyCandidate."""
    parts = line.split(":", 3)
    if len(parts) >= 4 and "error" in parts[2].lower():
        file_path = parts[0].strip()
        try:
            line_no = int(parts[1].strip())
        except ValueError:
            return None
        error_msg = parts[3].strip()
        return TypeSafetyCandidate(
            name="MypyTypeError",
            file_path=file_path,
            line=line_no,
            error_message=error_msg,
        )
    return None


def run_mypy_checker() -> list[TypeSafetyCandidate]:
    candidates = []
    try:
        cmd = [sys.executable, "-m", "mypy", "src", "--ignore-missing-imports"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        for line in result.stdout.splitlines():
            cand = _parse_mypy_line(line)
            if cand is not None:
                candidates.append(cand)
    except (OSError, subprocess.SubprocessError, RuntimeError) as e:
        print(f"Error running mypy: {e}", file=sys.stderr)
    return candidates


def _build_code_snippet(content: str, target_line: int) -> str:
    """Build a code snippet from file content around the target line."""
    lines = content.splitlines()
    start_idx = max(0, target_line - 5)
    end_idx = min(len(lines), target_line + 10)
    return "\n".join(
        f"{idx}: {line}"
        for idx, line in zip(range(start_idx + 1, end_idx + 1), lines[start_idx:end_idx])
    )


def _build_audit_prompt(candidate: TypeSafetyCandidate, code_snippet: str) -> str:
    """Build the audit prompt string for the LLM."""
    return (
        f"File Path: {candidate.file_path}\n"
        f"Type Checker Error: {candidate.error_message}\n"
        f"Line Number: {candidate.line}\n\n"
        "Here is the code block around this candidate:\n"
        "```python\n"
        f"{code_snippet}\n"
        "```\n\n"
        "Audit if this represents a true type safety hazard (TYPE_HAZARD) or a minor/false positive annotation warning (FALSE_POSITIVE)."
    )


def _execute_audit_with_backoff(prompt: str) -> AuditResult:
    """Execute the audit agent with exponential backoff on failure."""
    import time

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
    raise RuntimeError("Unreachable: audit loop exited without returning")


def audit_candidate_with_llm(candidate: TypeSafetyCandidate, file_contents: dict[str, str]) -> AuditResult:
    import time

    print("Pausing 4 seconds before next audit call...")
    time.sleep(4.0)
    content = file_contents.get(candidate.file_path, "")
    code_snippet = _build_code_snippet(content, candidate.line)
    prompt = _build_audit_prompt(candidate, code_snippet)
    return _execute_audit_with_backoff(prompt)


def _write_results_section(out, report: AuditReport):
    """Write the audit results section of the markdown report."""
    by_file: dict[str, list[AuditResult]] = {}
    for result in report.audit_results:
        by_file.setdefault(result.file_path, []).append(result)

    for f, list_results in sorted(by_file.items()):
        out.write(f"## 📂 `{f}`\n\n")
        for item in sorted(list_results, key=lambda x: x.line):
            status_emoji = "🛑" if item.status == "TYPE_HAZARD" else "✅"
            out.write(f"### {status_emoji} Line {item.line}: Type Error\n")
            out.write(f"- **Verdict**: `{item.status}`\n")
            out.write(f"- **Severity**: `{item.severity}`\n")
            out.write(f"- **Reasoning**: {item.reason}\n\n")
        out.write("---\n\n")


def generate_markdown_report(report: AuditReport, md_path: Path):
    with open(md_path, "w", encoding="utf-8") as out:
        out.write("# 🕵️ Type Safety & Annotation Audit Report\n\n")
        out.write(f"Scanned `{report.scanned_files_count}` files in `src/`.\n\n")

        if not report.audit_results:
            out.write("🎉 *No type safety violations found! All type annotations pass checks.*\n")
        else:
            _write_results_section(out, report)


def _load_file_contents(files: list) -> dict[str, str]:
    """Read and return contents of all source files."""
    file_contents: dict[str, str] = {}
    for file_path in files:
        path_str = str(file_path)
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                file_contents[path_str] = f.read()
        except OSError as e:
            print(f"Error parsing {path_str}: {e}", file=sys.stderr)
    return file_contents


def _load_existing_results(json_path: Path) -> dict:
    """Load existing audit results from JSON file if present."""
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


def _audit_candidates(
    candidates: list[TypeSafetyCandidate],
    file_contents: dict[str, str],
    existing_results: dict,
    json_path: Path,
) -> list[AuditResult]:
    """Audit all candidates, reusing existing results where available."""
    results: list[AuditResult] = []
    total_candidates = len(candidates)
    for index, candidate in enumerate(candidates, 1):
        key = (candidate.file_path, candidate.line, candidate.name)
        if key in existing_results:
            print(
                f"[{index}/{total_candidates}] Skipping already audited candidate: "
                f"{candidate.name} in {candidate.file_path}:{candidate.line}"
            )
            res_data = existing_results[key]
            audit = AuditResult(**res_data)
            audit.updated_at = datetime.now().astimezone().isoformat()
            results.append(audit)
            continue
        print(
            f"[{index}/{total_candidates}] Auditing type error in "
            f"{candidate.file_path}:{candidate.line}..."
        )
        try:
            audit = audit_candidate_with_llm(candidate, file_contents)
            audit.file_path = candidate.file_path
            audit.line = candidate.line
            results.append(audit)

            report = AuditReport(
                scanned_files_count=0,
                audit_results=results,
            )
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(report.model_dump_json(indent=2))
        except (OSError, ValueError, TypeError, RuntimeError) as e:
            print(f"WARNING: Auditing failed for type error: {e}", file=sys.stderr)
    return results


def _print_script_mode_candidates(candidates: list[TypeSafetyCandidate]):
    """Print candidates in script mode and exit."""
    total = len(candidates)
    print(f"Scan complete. Found {total} candidate type safety errors to audit.")
    print("\nCandidates found:")
    for idx, cand in enumerate(candidates, 1):
        print(f"[{idx}] {cand.name} in {cand.file_path}:{cand.line}")
    sys.exit(0)


def main():
    files = get_src_files()
    file_contents = _load_file_contents(files)
    candidates = run_mypy_checker()

    import argparse
    parser = argparse.ArgumentParser(description="Type Safety Scanner")
    parser.add_argument("--scripts", action="store_true", help="Run only static checks and print candidates")
    args = parser.parse_args()

    total_candidates = len(candidates)
    print(f"Scan complete. Found {total_candidates} candidate type safety errors to audit.")

    if args.scripts:
        _print_script_mode_candidates(candidates)

    existing_results = _load_existing_results(
        Path("kit-hygiene/reports/type_safety_audit.json")
    )
    output_dir = Path("kit-hygiene/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "type_safety_audit.json"
    md_path = output_dir / "type_safety_audit.md"

    audit_results = _audit_candidates(candidates, file_contents, existing_results, json_path)

    report = AuditReport(
        scanned_files_count=len(files),
        audit_results=audit_results,
    )
    generate_markdown_report(report, md_path)
    print(f"Rendered Markdown report saved to {md_path}")


if __name__ == "__main__":
    main()
