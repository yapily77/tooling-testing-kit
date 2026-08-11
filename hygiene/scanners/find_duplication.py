import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from _bootstrap import pkg_root
from control import CONTROL_SHEET
from utils import get_src_files


class DuplicationCandidate(BaseModel):
    name: str = Field(description="The duplicated code block preview.")
    file_a: str = Field(description="First file containing the duplicated block.")
    line_a: int = Field(description="Line number in File A.")
    file_b: str = Field(description="Second file containing the duplicated block.")
    line_b: int = Field(description="Line number in File B.")
    block_length: int = Field(description="Number of identical lines.")


class AuditResult(BaseModel):
    name: str = Field(description="Description of the duplicated code block.")
    file_path: str = Field(description="First file path.")
    line: int = Field(description="Line number.")
    status: str = Field(description="Verdict: 'DUPLICATION' or 'FALSE_POSITIVE'.")
    severity: str = Field(description="Severity: 'HIGH' (critical business math/logic cloned), 'LOW' (standard boilerplate).")
    reason: str = Field(description="A concise 1 to 2 sentence explanation of why this is a duplication violation and how to share it.")
    updated_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat(), description="The ISO datetime string when this violation was audited or updated.")


class AuditReport(BaseModel):
    scanned_files_count: int = Field(description="Total number of Python files scanned.")
    audit_results: list[AuditResult] = Field(default_factory=list)
    failed_audits: list[dict[str, Any]] = Field(default_factory=list)


scanner_model = CONTROL_SHEET.scanner_model

audit_agent = Agent(
    scanner_model,
    output_type=AuditResult,
    retries=3,
    system_prompt=(
        "You are an expert software engineer and code quality auditor.\n"
        "Your task is to review a candidate duplicated block of code (identical block of lines found in multiple files) flagged by static analysis.\n"
        "Determine if the block represents a true duplication (DUPLICATION) that should be refactored into a shared utility function to comply with DRY (Don't Repeat Yourself) principles, "
        "or if it is a false positive (FALSE_POSITIVE) like standard imports, boilerplates, class properties, or schema field declarations."
    ),
)

SKIP_TOKENS = ("", "pass", "return")
IMPORT_PREFIXES = ("import", "from")
_ERROR_TYPES = (OSError, ValueError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError)


def _is_skippable(line: str) -> bool:
    return not line or line.startswith(IMPORT_PREFIXES)


def _count_match_length(lines_a: list[str], lines_b: list[str], idx_a: int, idx_b: int) -> int:
    k = 0
    while (idx_a + k < len(lines_a)) and (idx_b + k < len(lines_b)):
        la = lines_a[idx_a + k]
        lb = lines_b[idx_b + k]
        if la == lb and la not in SKIP_TOKENS:
            k += 1
        else:
            break
    return k


def _find_match_in_b(
    lines_a: list[str], lines_b: list[str], idx_a: int, file_a: str, file_b: str, min_lines: int
) -> tuple[DuplicationCandidate | None, int]:
    line_a = lines_a[idx_a]
    idx_b = 0
    while idx_b < len(lines_b):
        line_b = lines_b[idx_b]
        if line_a == line_b and line_a not in SKIP_TOKENS:
            k = _count_match_length(lines_a, lines_b, idx_a, idx_b)
            if k >= min_lines:
                candidate = DuplicationCandidate(
                    name=f"Duplicate Block ({k} lines)",
                    file_a=file_a,
                    line_a=idx_a + 1,
                    file_b=file_b,
                    line_b=idx_b + 1,
                    block_length=k,
                )
                return candidate, k
        idx_b += 1
    return None, 1


def _file_pairs(file_paths: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for i in range(len(file_paths)):
        for j in range(i + 1, len(file_paths)):
            pairs.append((file_paths[i], file_paths[j]))
    return pairs


def _collect_duplication_pairs(
    file_a: str, file_b: str, lines_a: list[str], lines_b: list[str],
    min_lines: int, candidates: list[DuplicationCandidate],
) -> None:
    idx_a = 0
    while idx_a < len(lines_a):
        if _is_skippable(lines_a[idx_a]):
            idx_a += 1
            continue

        candidate, advance = _find_match_in_b(lines_a, lines_b, idx_a, file_a, file_b, min_lines)
        if candidate is not None:
            candidates.append(candidate)
            idx_a += advance
            break
        idx_a += 1


def find_duplications(file_contents: dict[str, str], min_lines: int = 8) -> list[DuplicationCandidate]:
    candidates: list[DuplicationCandidate] = []
    file_paths = list(file_contents.keys())
    file_lines = {f: [line.strip() for line in content.splitlines()] for f, content in file_contents.items()}

    for file_a, file_b in _file_pairs(file_paths):
        _collect_duplication_pairs(file_a, file_b, file_lines[file_a], file_lines[file_b], min_lines, candidates)

    return candidates


class _AuditError(Exception):
    pass


def _read_source_snippet(candidate: DuplicationCandidate, file_contents: dict[str, str]) -> str:
    content_a = file_contents.get(candidate.file_a, "").splitlines()
    start = candidate.line_a - 1
    end = start + candidate.block_length
    return "\n".join(content_a[start:end])


def _build_audit_prompt(candidate: DuplicationCandidate, snippet: str) -> str:
    return (
        f"File A: {candidate.file_a} (Line {candidate.line_a})\n"
        f"File B: {candidate.file_b} (Line {candidate.line_b})\n"
        f"Duplicate Line Count: {candidate.block_length}\n\n"
        "Here is the duplicated code block:\n"
        "```python\n"
        f"{snippet}\n"
        "```\n\n"
        "Audit if this represents a true copy-paste logic violation (DUPLICATION) "
        "or standard boilerplate (FALSE_POSITIVE)."
    )


def _execute_audit_with_retry(prompt: str, backoffs: list[float]) -> AuditResult:
    max_attempts = len(backoffs) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            response = audit_agent.run_sync(prompt, model_settings=ModelSettings(max_tokens=1024))
            return response.output
        except _ERROR_TYPES as e:
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
                raise _AuditError(str(e)) from e
    raise _AuditError("exhausted retries")


def audit_candidate_with_llm(candidate: DuplicationCandidate, file_contents: dict[str, str]) -> AuditResult:
    print("Pausing 4 seconds before next audit call...")
    time.sleep(4.0)

    snippet = _read_source_snippet(candidate, file_contents)
    prompt = _build_audit_prompt(candidate, snippet)
    backoffs = [90.0, 120.0, 240.0]

    return _execute_audit_with_retry(prompt, backoffs)


def generate_markdown_report(report: AuditReport, md_path: Path) -> None:
    with open(md_path, "w", encoding="utf-8") as out:
        out.write("# Code Duplication & Copypasta Report\n\n")
        out.write(f"Scanned `{report.scanned_files_count}` files in `src/`.\n\n")

        if not report.audit_results:
            out.write("No code duplications found! Codebase is perfectly DRY.\n")
            return

        for item in sorted(report.audit_results, key=lambda x: x.line):
            status_emoji = "HIGH" if item.status == "DUPLICATION" else "OK"
            out.write(f"### {status_emoji} `{item.name}`\n")
            out.write(f"- File A: `{item.file_path}` (Line {item.line})\n")
            out.write(f"- Verdict: `{item.status}`\n")
            out.write(f"- Severity: `{item.severity}`\n")
            out.write(f"- Reasoning: {item.reason}\n\n")
            out.write("---\n\n")


def _load_file_contents(files: list[Path]) -> dict[str, str]:
    file_contents: dict[str, str] = {}
    for file_path in files:
        path_str = str(file_path)
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                file_contents[path_str] = f.read()
        except _ERROR_TYPES as e:
            print(f"Error parsing {path_str}: {e}", file=sys.stderr)
    return file_contents


def _load_existing_results(json_path: Path) -> dict[tuple[str, int, str], dict[str, Any]]:
    existing_results: dict[tuple[str, int, str], dict[str, Any]] = {}
    if not json_path.exists():
        return existing_results
    try:
        with open(json_path, encoding="utf-8") as f:
            existing_data = json.load(f)
        for res in existing_data.get("audit_results", []):
            res_data: dict[str, Any] = res
            key = (
                str(res_data.get("file_path")),
                int(res_data.get("line")),  # type: ignore[arg-type]
                str(res_data.get("name")),
            )
            existing_results[key] = res_data
    except _ERROR_TYPES as e:
        print(f"WARNING: Failed to load existing JSON report: {e}", file=sys.stderr)
    return existing_results


def _handle_skipped_candidate(
    candidate: DuplicationCandidate, existing_results: dict[tuple[str, int, str], dict[str, Any]], report: AuditReport,
    total_candidates: int, index: int,
) -> None:
    print(f"[{index}/{total_candidates}] Skipping already audited duplication in {candidate.file_a}:{candidate.line_a}")
    res_data = existing_results[(candidate.file_a, candidate.line_a, candidate.name)]
    audit = AuditResult(**res_data)
    audit.updated_at = datetime.now().astimezone().isoformat()
    report.audit_results.append(audit)


def _audit_candidate(
    candidate: DuplicationCandidate, existing_results: dict[tuple[str, int, str], dict[str, Any]],
    report: AuditReport, total_candidates: int, index: int, json_path: Path, file_contents: dict[str, str],
) -> None:
    key = (candidate.file_a, candidate.line_a, candidate.name)
    if key in existing_results:
        _handle_skipped_candidate(candidate, existing_results, report, total_candidates, index)
        return

    print(f"[{index}/{total_candidates}] Auditing duplicate block in {candidate.file_a}:{candidate.line_a}...")
    try:
        audit = audit_candidate_with_llm(candidate, file_contents)
        audit.file_path = candidate.file_a
        audit.line = candidate.line_a
        report.audit_results.append(audit)
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))
    except (_AuditError, *_ERROR_TYPES) as e:
        print(f"WARNING: Auditing failed for duplicate block: {e}", file=sys.stderr)


def _print_candidates(candidates: list[DuplicationCandidate]) -> None:
    print("\nCandidates found:")
    for idx, cand in enumerate(candidates, 1):
        print(
            f"[{idx}] Block {cand.name} duplicated between:\n"
            f"    - {cand.file_a}:{cand.line_a}\n"
            f"    - {cand.file_b}:{cand.line_b}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Duplication Scanner")
    parser.add_argument("--scripts", action="store_true", help="Run only static checks and print candidates")
    args = parser.parse_args()

    files = get_src_files()
    file_contents = _load_file_contents(files)
    candidates = find_duplications(file_contents)

    total_candidates = len(candidates)
    print(f"Scan complete. Found {total_candidates} candidate duplications to audit.")

    if args.scripts:
        _print_candidates(candidates)
        sys.exit(0)

    report = AuditReport(scanned_files_count=len(files))
    output_dir = pkg_root / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "duplication_audit.json"
    existing_results = _load_existing_results(json_path)
    md_path = output_dir / "duplication_audit.md"

    for index, candidate in enumerate(candidates, 1):
        _audit_candidate(candidate, existing_results, report, total_candidates, index, json_path, file_contents)

    generate_markdown_report(report, md_path)
    print(f"Rendered Markdown report saved to {md_path}")


if __name__ == "__main__":
    main()
