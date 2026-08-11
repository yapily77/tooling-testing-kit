import ast
import json
import sys
from datetime import datetime
from pathlib import Path

from _bootstrap import pkg_root
from control import CONTROL_SHEET
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from utils import get_src_files


class CircularDepCandidate(BaseModel):
    name: str = Field(description="The dependency cycle path representation.")
    file_path: str = Field(description="The entrypoint file of the cycle.")
    line: int = Field(description="The line number of the import causing the cycle.")
    cycle_path: list[str] = Field(description="The list of files forming the import cycle.")


class AuditResult(BaseModel):
    name: str = Field(description="The cycle path description.")
    file_path: str = Field(description="The entrypoint file path.")
    line: int = Field(description="The import line number.")
    status: str = Field(description="Verdict: 'CIRCULAR_DEP' or 'FALSE_POSITIVE'.")
    severity: str = Field(
        description="Severity: 'HIGH' (real loop causing runtime failures), 'LOW' (unused/dormant loop)."
    )
    reason: str = Field(
        description="A concise 1 to 2 sentence explanation of why this loop is a problem and how to resolve it."
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now().astimezone().isoformat(),
        description="The ISO datetime string when this violation was audited or updated.",
    )


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
        "You are an expert software architect and static analyzer.\n"
        "Your task is to review a candidate circular dependency import loop flagged by static analysis.\n"
        "Verify if the import path creates a true circular import loop (CIRCULAR_DEP) that can cause runtime ImportErrors, "
        "or if it is a false positive (FALSE_POSITIVE) such as imports inside functions/methods (which are resolved lazily at runtime)."
    ),
)

_SRC_PREFIX = "src."


class ImportExtractor(ast.NodeVisitor):
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.imports: list[tuple[str, int, bool]] = []
        self.inside_function = False

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._with_function_context(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._with_function_context(node)

    def _with_function_context(self, node):
        old = self.inside_function
        self.inside_function = True
        self.generic_visit(node)
        self.inside_function = old

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append((alias.name, node.lineno, self.inside_function))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self.imports.append((node.module, node.lineno, self.inside_function))
        self.generic_visit(node)


def _try_prefixed(neighbor: str, graph: dict[str, list]) -> str | None:
    """Try resolving with 'src.' prefix."""
    if not neighbor.startswith(_SRC_PREFIX):
        resolved = _SRC_PREFIX + neighbor
        if resolved in graph:
            return resolved
    return None


def _try_suffix_match(neighbor: str, graph: dict[str, list]) -> str | None:
    """Try matching by suffix or exact name."""
    for g_key in graph:
        if g_key.endswith(f".{neighbor}") or g_key == neighbor:
            return g_key
    return None


def _resolve_module_name(neighbor: str, graph: dict[str, list]) -> str | None:
    """Resolve a neighbor module name to a key in the graph."""
    resolved = _try_prefixed(neighbor, graph)
    if resolved:
        return resolved
    if neighbor.startswith(_SRC_PREFIX) and neighbor in graph:
        return neighbor
    return _try_suffix_match(neighbor, graph)


def find_cycles(graph: dict[str, list[tuple[str, int, bool]]]) -> list[CircularDepCandidate]:
    cycles = []
    visited: dict[str, int] = {}

    def dfs(node: str, path: list[str]):
        visited[node] = 1
        path.append(node)

        for neighbor, line, _is_local in graph.get(node, []):
            resolved = _resolve_module_name(neighbor, graph)
            if resolved:
                _handle_resolved(resolved, line, node, cycles, visited, path, graph)

        path.pop()
        visited[node] = 2

    def _handle_resolved(resolved, line, node, cycles, visited, path, graph):
        state = visited.get(resolved, 0)
        if state == 1:
            cycle_idx = path.index(resolved)
            cycle_path = path[cycle_idx:] + [resolved]
            cycles.append(
                CircularDepCandidate(
                    name=" -> ".join(cycle_path), file_path=node, line=line, cycle_path=cycle_path
                )
            )
        elif state == 0:
            dfs(resolved, path)

    for node in graph:
        if visited.get(node, 0) == 0:
            dfs(node, [])

    return cycles


def _build_code_snippet(content: str, line: int) -> str:
    """Extract a code snippet around the given line number."""
    lines = content.splitlines()
    start_idx = max(0, line - 5)
    end_idx = min(len(lines), line + 10)
    return "\n".join(
        f"{idx}: {line}" for idx, line in zip(range(start_idx + 1, end_idx + 1), lines[start_idx:end_idx])
    )


def _run_audit_with_backoff(prompt: str, max_attempts: int) -> AuditResult:
    """Execute the LLM audit with exponential backoff."""
    import time

    backoffs = [90.0, 120.0, 240.0]
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
                time.sleep(sleep_time)
            else:
                print(
                    f"CRITICAL: API call failed after {max_attempts} attempts. Shutting down.",
                    file=sys.stderr,
                )
                sys.exit(1)
    return AuditResult(name="", file_path="", line=0, status="FALSE_POSITIVE", severity="LOW", reason="")


def audit_candidate_with_llm(candidate: CircularDepCandidate, file_contents: dict[str, str]) -> AuditResult:
    import time

    print("Pausing 4 seconds before next audit call...")
    time.sleep(4.0)
    cand_file = candidate.file_path
    content = file_contents.get(cand_file, "")
    code_snippet = _build_code_snippet(content, candidate.line)

    prompt = (
        f"File Path: {cand_file}\n"
        f"Import Line: {candidate.line}\n"
        f"Cycle Path: {candidate.name}\n\n"
        "Here is the code block around this candidate import:\n"
        "```python\n"
        f"{code_snippet}\n"
        "```\n\n"
        "Audit if this represents a true circular dependency hazard (CIRCULAR_DEP) or a lazy/safe functional import (FALSE_POSITIVE)."
    )

    backoffs = [90.0, 120.0, 240.0]
    max_attempts = len(backoffs) + 1
    return _run_audit_with_backoff(prompt, max_attempts)


def _write_header(out, report: AuditReport):
    out.write("# 🕵️ Circular Dependency Audit Report\n\n")
    out.write(f"Scanned `{report.scanned_files_count}` files in `src/`.\n\n")
    if not report.audit_results:
        out.write("🎉 *No circular dependencies found! Clean import DAG.*\n")


def _write_file_section(out, f: str, list_results: list[AuditResult]):
    out.write(f"## 📂 `{f}`\n\n")
    for item in sorted(list_results, key=lambda x: x.line):
        status_emoji = "🛑" if item.status == "CIRCULAR_DEP" else "✅"
        out.write(f"### {status_emoji} Line {item.line}: `{item.name}`\n")
        out.write(f"- **Verdict**: `{item.status}`\n")
        out.write(f"- **Severity**: `{item.severity}`\n")
        out.write(f"- **Reasoning**: {item.reason}\n\n")
    out.write("---\n\n")


def generate_markdown_report(report: AuditReport, md_path: Path):
    with open(md_path, "w", encoding="utf-8") as out:
        _write_header(out, report)
        if report.audit_results:
            by_file: dict[str, list[AuditResult]] = {}
            for result in report.audit_results:
                f = result.file_path
                by_file.setdefault(f, []).append(result)
            for f, list_results in sorted(by_file.items()):
                _write_file_section(out, f, list_results)


def _build_import_graph(files) -> tuple[dict, dict]:
    """Parse source files and build the import graph plus file contents cache."""
    graph: dict[str, list] = {}
    file_contents: dict[str, str] = {}
    for file_path in files:
        module_path = str(file_path.with_suffix("")).replace("/", ".")
        path_str = str(file_path)
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                file_contents[path_str] = content
            tree = ast.parse(content, filename=path_str)
            extractor = ImportExtractor(file_path)
            extractor.visit(tree)
            graph[module_path] = extractor.imports
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
            print(f"Error parsing {path_str}: {e}", file=sys.stderr)
    return graph, file_contents


def _load_existing_results(json_path: Path) -> dict:
    """Load existing audit results from JSON report if it exists."""
    existing_results: dict = {}
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                existing_data = json.load(f)
                for res in existing_data.get("audit_results", []):
                    existing_results[(res.get("file_path"), res.get("line"), res.get("name"))] = res
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
            print(f"WARNING: Failed to load existing JSON report: {e}", file=sys.stderr)
    return existing_results


def _handle_scripts_mode(candidates: list[CircularDepCandidate], total: int):
    """Handle the --scripts flag: print candidates and exit."""
    import argparse
    parser = argparse.ArgumentParser(description="Circular Dependencies Scanner")
    parser.add_argument("--scripts", action="store_true", help="Run only static checks and print candidates")
    args = parser.parse_args()
    if args.scripts:
        print("\nCandidates found:")
        for idx, cand in enumerate(candidates, 1):
            mapped_file = cand.file_path.replace(".", "/") + ".py"
            print(f"[{idx}] {cand.name} in {mapped_file}:{cand.line}")
        sys.exit(0)


def _audit_candidates(candidates, file_contents, json_path, existing_results):
    """Iterate over candidates and audit each one."""
    total_candidates = len(candidates)
    print(f"Scan complete. Found {total_candidates} candidate circular dependency import loops to audit.")
    _handle_scripts_mode(candidates, total_candidates)

    report = AuditReport(scanned_files_count=0)
    for index, candidate in enumerate(candidates, 1):
        mapped_file = candidate.file_path.replace(".", "/") + ".py"
        key = (mapped_file, candidate.line, candidate.name)
        if key in existing_results:
            print(f"[{index}/{total_candidates}] Skipping already audited cycle: {candidate.name}")
            res_data = existing_results[key]
            audit = AuditResult(**res_data)
            audit.updated_at = datetime.now().astimezone().isoformat()
            report.audit_results.append(audit)
            continue
        print(f"[{index}/{total_candidates}] Auditing cycle {candidate.name}...")
        try:
            candidate.file_path = mapped_file
            audit = audit_candidate_with_llm(candidate, file_contents)
            audit.file_path = mapped_file
            audit.line = candidate.line
            report.audit_results.append(audit)
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(report.model_dump_json(indent=2))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
            print(f"WARNING: Auditing failed for cycle: {e}", file=sys.stderr)
    return report


def main():
    files = get_src_files()
    graph, file_contents = _build_import_graph(files)
    candidates = find_cycles(graph)

    output_dir = pkg_root / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "circular_deps_audit.json"
    existing_results = _load_existing_results(json_path)
    md_path = output_dir / "circular_deps_audit.md"

    report = _audit_candidates(candidates, file_contents, json_path, existing_results)
    report.scanned_files_count = len(files)

    generate_markdown_report(report, md_path)
    print(f"Rendered Markdown report saved to {md_path}")


if __name__ == "__main__":
    main()
