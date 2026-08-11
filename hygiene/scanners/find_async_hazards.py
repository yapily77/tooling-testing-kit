import argparse
import ast
import json
import sys
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from _bootstrap import pkg_root
from control import CONTROL_SHEET
from utils import get_src_files


class AsyncHazardCandidate(BaseModel):
    name: str = Field(description="The name of the blocking call.")
    file_path: str = Field(description="The source file path relative to workspace root.")
    line: int = Field(description="The line number where the blocking call is found.")
    func_context: str = Field(description="The async function enclosing the blocking call.")


class AuditResult(BaseModel):
    name: str = Field(description="The name of the call audited.")
    file_path: str = Field(description="The file path of the candidate.")
    line: int = Field(description="The line number of the candidate.")
    status: str = Field(description="Verdict: 'ASYNC_HAZARD' or 'FALSE_POSITIVE'.")
    severity: str = Field(description="Severity: 'HIGH' (blocks event loop on hot API path), 'LOW' (infrequent/startup task).")
    reason: str = Field(description="A concise 1 to 2 sentence explanation of why it is a hazard or a false positive.")
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
        "You are an expert asynchronous programming auditor.\n"
        "Your task is to review a candidate event loop blocker (blocking synchronous call inside an async function) flagged by static analysis.\n"
        "Determine if the synchronous call represents a true async hazard (ASYNC_HAZARD) that blocks the asyncio event loop on active paths, "
        "or if it is a false positive (FALSE_POSITIVE) like synchronous calls executed inside standard executors/threads or startup-only tasks."
    ),
)


class AsyncHazardExtractor(ast.NodeVisitor):
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.candidates: list[AsyncHazardCandidate] = []
        self.current_async_func = None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        old_func = self.current_async_func
        self.current_async_func = node.name
        self.generic_visit(node)
        self.current_async_func = old_func

    def visit_Call(self, node: ast.Call):
        if self.current_async_func:
            hazard = self._detect_hazard(node)
            if hazard:
                name, = hazard
                self.candidates.append(
                    AsyncHazardCandidate(
                        name=name,
                        file_path=str(self.file_path),
                        line=node.lineno,
                        func_context=self.current_async_func
                    )
                )

        self.generic_visit(node)

    def _detect_time_sleep(self, node: ast.Call) -> bool:
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "sleep":
            return False
        return isinstance(node.func.value, ast.Name) and node.func.value.id == "time"

    def _detect_requests_call(self, node: ast.Call) -> bool:
        if not isinstance(node.func, ast.Attribute):
            return False
        if node.func.attr not in ["get", "post", "put", "delete", "request"]:
            return False
        return isinstance(node.func.value, ast.Name) and node.func.value.id == "requests"

    def _detect_subprocess_call(self, node: ast.Call) -> bool:
        if not isinstance(node.func, ast.Attribute):
            return False
        if node.func.attr not in ["run", "popen", "call", "check_output"]:
            return False
        return isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"

    def _detect_open_call(self, node: ast.Call) -> bool:
        return isinstance(node.func, ast.Name) and node.func.id == "open"

    def _detect_hazard(self, node: ast.Call) -> tuple[str, ...] | None:
        if self._detect_time_sleep(node):
            return ("time.sleep",)
        if self._detect_requests_call(node):
            return (f"requests.{node.func.attr}",)
        if self._detect_open_call(node):
            return ("open",)
        if self._detect_subprocess_call(node):
            return (f"subprocess.{node.func.attr}",)
        return None


def _extract_code_snippet(content: str, line: int, pre_lines: int = 10, post_lines: int = 20) -> str:
    lines = content.splitlines()
    start_idx = max(0, line - pre_lines)
    end_idx = min(len(lines), line + post_lines)
    return "\n".join(
        f"{idx}: {line_text}"
        for idx, line_text in zip(range(start_idx + 1, end_idx + 1), lines[start_idx:end_idx])
    )


def _build_audit_prompt(candidate: AsyncHazardCandidate, code_snippet: str) -> str:
    return (
        f"File Path: {candidate.file_path}\n"
        f"Enclosing Async Function: {candidate.func_context}\n"
        f"Blocking Call: {candidate.name}\n"
        f"Line Number: {candidate.line}\n\n"
        "Here is the code block around this candidate:\n"
        "```python\n"
        f"{code_snippet}\n"
        "```\n\n"
        "Audit if this represents a true event loop hazard (ASYNC_HAZARD) or a safe synchronous call (FALSE_POSITIVE)."
    )


def _execute_audit_with_backoff(prompt: str, max_attempts: int, backoffs: list[float]) -> AuditResult:
    for attempt in range(1, max_attempts + 1):
        try:
            response = audit_agent.run_sync(prompt, model_settings=ModelSettings(max_tokens=1024))
            return response.output
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
            if attempt < max_attempts:
                sleep_time = backoffs[attempt - 1]
                print(
                    f"WARNING: API call failed ({e}). Backing off for {sleep_time:.1f}s (attempt {attempt}/{max_attempts})...",
                    file=sys.stderr,
                )
                import time
                time.sleep(sleep_time)
            else:
                print(
                    f"CRITICAL: API call failed after {max_attempts} attempts. Shutting down.",
                    file=sys.stderr,
                )
                sys.exit(1)
    raise RuntimeError("Unreachable: audit loop exited without result")


def audit_candidate_with_llm(candidate: AsyncHazardCandidate, file_contents: dict[str, str]) -> AuditResult:
    import time

    print("Pausing 4 seconds before next audit call...")
    time.sleep(4.0)
    content = file_contents.get(candidate.file_path, "")
    code_snippet = _extract_code_snippet(content, candidate.line)
    prompt = _build_audit_prompt(candidate, code_snippet)
    backoffs = [90.0, 120.0, 240.0]
    max_attempts = len(backoffs) + 1
    return _execute_audit_with_backoff(prompt, max_attempts, backoffs)


def _write_report_header(out) -> None:
    out.write("# 🕵️ Async Hazards & Event Loop Blockers Report\n\n")
    out.write(f"Scanned `{0}` files in `src/`.\n\n")


def _group_results_by_file(audit_results: list[AuditResult]) -> dict[str, list[AuditResult]]:
    by_file = {}
    for result in audit_results:
        by_file.setdefault(result.file_path, []).append(result)
    return by_file


def _format_result_line(item: AuditResult) -> str:
    status_emoji = "🛑" if item.status == "ASYNC_HAZARD" else "✅"
    return f"### {status_emoji} Line {item.line}: `{item.name}` in `{item.file_path}`\n"


def _format_result_details(item: AuditResult) -> str:
    lines = [
        f"- **Verdict**: `{item.status}`\n",
        f"- **Severity**: `{item.severity}`\n",
        f"- **Reasoning**: {item.reason}\n\n",
    ]
    return "".join(lines)


def _write_file_section(out, f: str, list_results: list[AuditResult]) -> None:
    out.write(f"## 📂 `{f}`\n\n")
    sorted_results = sorted(list_results, key=lambda x: x.line)
    for item in sorted_results:
        out.write(_format_result_line(item))
        out.write(_format_result_details(item))


def generate_markdown_report(report: AuditReport, md_path: Path) -> None:
    with open(md_path, "w", encoding="utf-8") as out:
        out.write("# 🕵️ Async Hazards & Event Loop Blockers Report\n\n")
        out.write(f"Scanned `{report.scanned_files_count}` files in `src/`.\n\n")

        if not report.audit_results:
            out.write("🎉 *No async hazards found! All event loop paths look clean.*\n")
        else:
            by_file = _group_results_by_file(report.audit_results)
            for f, list_results in sorted(by_file.items()):
                _write_file_section(out, f, list_results)


def _scan_file(file_path: Path) -> tuple[str, str, list[AsyncHazardCandidate]]:
    path_str = str(file_path)
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        tree = ast.parse(content, filename=path_str)
        extractor = AsyncHazardExtractor(file_path)
        extractor.visit(tree)
        return (path_str, content, extractor.candidates)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
        print(f"Error parsing {path_str}: {e}", file=sys.stderr)
        return (path_str, "", [])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Async Hazards Scanner")
    parser.add_argument("--scripts", action="store_true", help="Run only static checks and print candidates")
    return parser.parse_args()


def _load_existing_results(json_path: Path) -> dict[tuple[str, int, str], dict]:
    existing_results = {}
    if not json_path.exists():
        return existing_results
    try:
        with open(json_path, encoding="utf-8") as f:
            existing_data = json.load(f)
            for res in existing_data.get("audit_results", []):
                existing_results[(res.get("file_path"), res.get("line"), res.get("name"))] = res
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
        print(f"WARNING: Failed to load existing JSON report: {e}", file=sys.stderr)
    return existing_results


def _print_candidates(all_candidates: list[AsyncHazardCandidate]) -> None:
    print("\nCandidates found:")
    for idx, cand in enumerate(all_candidates, 1):
        print(f"[{idx}] {cand.name} in {cand.file_path}:{cand.line} (enclosed by {cand.func_context})")


def _audit_candidate(index: int, total: int, candidate: AsyncHazardCandidate, file_contents: dict[str, str], json_path: Path, report: AuditReport, existing_results: dict) -> AuditResult:
    key = (candidate.file_path, candidate.line, candidate.name)
    if key in existing_results:
        print(f"[{index}/{total}] Skipping already audited candidate: {candidate.name} in {candidate.file_path}:{candidate.line}")
        res_data = existing_results[key]
        audit = AuditResult(**res_data)
        audit.updated_at = datetime.now().astimezone().isoformat()
        report.audit_results.append(audit)
        return audit
    print(f"[{index}/{total}] Auditing {candidate.name} in {candidate.file_path}:{candidate.line}...")
    try:
        audit = audit_candidate_with_llm(candidate, file_contents)
        audit.file_path = candidate.file_path
        audit.line = candidate.line
        report.audit_results.append(audit)
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))
        return audit
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
        print(f"WARNING: Auditing failed for {candidate.name}: {e}", file=sys.stderr)
        return None


def _run_audit_pass(all_candidates, file_contents, json_path, report, existing_results):
    total_candidates = len(all_candidates)
    for index, candidate in enumerate(all_candidates, 1):
        _audit_candidate(index, total_candidates, candidate, file_contents, json_path, report, existing_results)


def main():
    files = get_src_files()
    all_candidates = []
    file_contents = {}

    for file_path in files:
        path_str, content, candidates = _scan_file(file_path)
        file_contents[path_str] = content
        all_candidates.extend(candidates)

    import argparse
    parser = argparse.ArgumentParser(description="Async Hazards Scanner")
    parser.add_argument("--scripts", action="store_true", help="Run only static checks and print candidates")
    args = parser.parse_args()

    total_candidates = len(all_candidates)
    print(f"Scan complete. Found {total_candidates} candidate async hazards to audit.")

    if args.scripts:
        _print_candidates(all_candidates)
        sys.exit(0)

    report = AuditReport(scanned_files_count=len(files))
    output_dir = pkg_root / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "async_hazards_audit.json"
    existing_results = _load_existing_results(json_path)
    md_path = output_dir / "async_hazards_audit.md"

    _run_audit_pass(all_candidates, file_contents, json_path, report, existing_results)

    generate_markdown_report(report, md_path)
    print(f"Rendered Markdown report saved to {md_path}")


if __name__ == "__main__":
    main()
