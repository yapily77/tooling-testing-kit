import json
import os
import subprocess
import sys
from pathlib import Path

# ANSI colors for nice terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_exceptions(exceptions_path: Path) -> list[str]:
    if not exceptions_path.exists():
        return []
    try:
        with open(exceptions_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"{YELLOW}Warning: Failed to load exceptions.json: {e}{RESET}")
        raise
        return []


def _run_git_diff(spec: str) -> set[str]:
    """Run a single git diff --name-only command and return non-empty lines."""
    result = subprocess.run(
        ["git", "diff", "--name-only", spec],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def get_changed_files() -> list[str]:
    """Get files changed in unstaged, staged, or unpushed commits."""
    files: set[str] = set()

    # 1. Staged and unstaged changes
    files |= _run_git_diff("HEAD")

    # 2. Unpushed commits compared to upstream
    files |= _run_git_diff("@{u}")

    # Fallback to HEAD~1 if no upstream or no changes found (local commit checks)
    if not files:
        files |= _extract_git_diff("HEAD~1", "HEAD")

    return sorted(files)


def _extract_git_diff(spec_a: str, spec_b: str) -> set[str]:
    """Run git diff --name-only <spec_a> <spec_b>."""
    result = subprocess.run(
        ["git", "diff", "--name-only", spec_a, spec_b],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def filter_files_to_scan(changed_files: list[str], exceptions: list[str]) -> list[str]:
    """Filter to Python files in src/ or kit-hygiene/ not in exceptions."""
    result = []
    for f in changed_files:
        path = Path(f)
        if path.suffix == ".py" and f.startswith(("src/", "kit-hygiene/")) and f not in exceptions:
            result.append(f)
    return result


def build_scanner_env(files_to_scan: list[str]) -> dict:
    """Set up environment overrides for scanner subprocesses."""
    env = os.environ.copy()
    env["HYGENE_FILES_TO_SCAN"] = ",".join(files_to_scan)
    env["google_thinking_level"] = "off"
    env["google_include_thoughts"] = "false"
    return env


def run_scanner(scanner_path: Path, env: dict) -> bool:
    """Run a single scanner; return False if it failed, True otherwise."""
    if not scanner_path.exists():
        return True

    print(f"\n🚀 Running {scanner_path.name}...")
    res = subprocess.run(
        ["uv", "run", "python", str(scanner_path)],
        env=env, capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        return _handle_scanner_failure(scanner_path, res)

    return _print_scanner_summary(res)


def _handle_scanner_failure(scanner_path: Path, res) -> bool:
    """Print failure info for a scanner; always returns False."""
    print(f"{RED}❌ Scanner {scanner_path.name} failed with exit code {res.returncode}:{RESET}")
    print(res.stderr)
    return False


def _print_scanner_summary(res) -> bool:
    """Print filtered stdout summary lines from a scanner run."""
    lines = res.stdout.splitlines()
    summary = [
        line for line in lines if any(x in line.lower() for x in ["found", "complete", "result", "saved"])
    ]
    for s in summary:
        print(f"  {s}")
    return True


def check_async_hazards(reports_dir: Path, files_to_scan: list[str]) -> bool:
    """Check async hazards report for blocking violations; return False on failure."""
    async_report = reports_dir / "async_hazards_audit.json"
    if not async_report.exists():
        return True
    try:
        with open(async_report, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("audit_results", []):
            if _is_blocking_async_hazard(item, files_to_scan):
                print(
                    f"{RED}🚨 BLOCKING VIOLATION: High-severity Async Hazard found in {item.get('file_path')}:{item.get('line')} ({item.get('name')}){RESET}"
                )
                print(f"  Reason: {item.get('reason')}")
                return False
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
        print(f"{YELLOW}Warning: Failed to parse async hazards report: {e}{RESET}")
    return True


def _is_blocking_async_hazard(item: dict, files_to_scan: list[str]) -> bool:
    return (
        item.get("status") == "ASYNC_HAZARD"
        and item.get("severity") == "HIGH"
        and item.get("file_path") in files_to_scan
    )


def check_circular_deps(reports_dir: Path, files_to_scan: list[str]) -> bool:
    """Check circular dependencies report; return False on failure."""
    circ_report = reports_dir / "circular_deps_audit.json"
    if not circ_report.exists():
        return True
    try:
        with open(circ_report, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("circular_dependencies", []):
            if _has_scan_involved(item, files_to_scan):
                involved_files = item.get("path", [])
                print(
                    f"{RED}🚨 BLOCKING VIOLATION: Circular Dependency chain detected: {' -> '.join(involved_files)}{RESET}"
                )
                return False
    except (KeyError, TypeError, json.JSONDecodeError):
        print("DEBUG: malformed circular_dep entry skipped", file=sys.stderr)
    return True


def _has_scan_involved(item: dict, files_to_scan: list[str]) -> bool:
    involved_files = item.get("path", [])
    return any(f in files_to_scan for f in involved_files)


def check_secrets(reports_dir: Path, files_to_scan: list[str]) -> bool:
    """Check secrets report for blocking violations; return False on failure."""
    secrets_report = reports_dir / "secrets_audit.json"
    if not secrets_report.exists():
        return True
    try:
        with open(secrets_report, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("findings", []):
            if _is_scan_secreted(item, files_to_scan):
                print(
                    f"{RED}🚨 BLOCKING VIOLATION: Potential Secret/Credentials leaked in {item.get('file_path')}:{item.get('line')}{RESET}"
                )
                return False
    except (json.JSONDecodeError, KeyError, TypeError):
        print("DEBUG: malformed secrets report entry skipped", file=sys.stderr)
    return True


def _is_scan_secreted(item: dict, files_to_scan: list[str]) -> bool:
    return item.get("file_path") in files_to_scan


def check_env_drift(reports_dir: Path, files_to_scan: list[str]) -> bool:
    """Check env drift report for blocking violations; return False on failure."""
    env_report = reports_dir / "env_drift_audit.json"
    if not env_report.exists():
        return True
    try:
        with open(env_report, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("audit_results", []):
            if _is_blocking_env_drift(item, files_to_scan):
                print(
                    f"{RED}🚨 BLOCKING VIOLATION: Environment Drift / Undocumented Variable found in {item.get('file_path')}:{item.get('line')} ({item.get('name')}){RESET}"
                )
                print(f"  Reason: {item.get('reason')}")
                return False
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError, json.JSONDecodeError) as e:
        print(f"{YELLOW}Warning: Failed to parse env drift report: {e}{RESET}")
    return True


def _is_blocking_env_drift(item: dict, files_to_scan: list[str]) -> bool:
    return (
        item.get("status") == "DRIFT_VIOLATION"
        and item.get("severity") == "HIGH"
        and item.get("file_path") in files_to_scan
    )


def check_reports(reports_dir: Path, files_to_scan: list[str]) -> bool:
    """Run all report checks. Returns False if any blocking violation found."""
    checks = (
        check_async_hazards,
        check_circular_deps,
        check_secrets,
        check_env_drift,
    )
    failed = False
    for check in checks:
        if not check(reports_dir, files_to_scan):
            failed = True
    return not failed


def _get_scanner_paths() -> list:
    """Build and return the list of scanner paths."""
    names = [
        "find_async_hazards.py",
        "find_circular_deps.py",
        "find_dead_code.py",
        "find_duplication.py",
        "find_env_drift.py",
        "find_secrets.py",
        "find_silent_killers.py",
        "find_type_safety.py",
        "find_message_drift.py",
    ]
    return [Path("kit-hygiene/scanners") / name for name in names]


def _run_scanners(env: dict) -> bool:
    """Run all scanners; return False if any failed."""
    failed = False
    for scanner in _get_scanner_paths():
        if not run_scanner(scanner, env):
            failed = True
    return not failed


def _validate_changed_files(changed_files: list) -> bool:
    """Bail out early if nothing changed or no scannable files."""
    if not changed_files:
        print(f"{GREEN}✅ No changed files detected in this push. Bypassing check.{RESET}")
        sys.exit(0)
    return True


def _resolve_files_to_scan(changed_files: list) -> list:
    """Load exceptions and filter changed files."""
    exceptions_path = Path(__file__).parent.parent / "exceptions.json"
    exceptions = load_exceptions(exceptions_path)
    files_to_scan = filter_files_to_scan(changed_files, exceptions)
    if not files_to_scan:
        print(f"{GREEN}✅ No non-excepted Python files modified. Bypassing scanners.{RESET}")
        sys.exit(0)
    return files_to_scan


def main():
    print(f"{BOLD}🛡️ Running Code Hygiene Gatekeeper (dailygit-check)...{RESET}")

    changed_files = get_changed_files()
    _validate_changed_files(changed_files)

    files_to_scan = _resolve_files_to_scan(changed_files)

    print("📦 Files queued for hygiene audit:")
    for f in files_to_scan:
        print(f"  - {f}")

    env = build_scanner_env(files_to_scan)
    failed = not _run_scanners(env)

    reports_dir = Path("kit-hygiene/reports")
    if reports_dir.exists() and not check_reports(reports_dir, files_to_scan):
        failed = True

    _report_final_status(failed)


def _report_final_status(failed: bool) -> None:
    """Print final pass/fail message and exit."""
    if failed:
        print(f"\n{RED}❌ Git push rejected: Code hygiene audit failed. Please fix the violations listed above.{RESET}")
        sys.exit(1)
    else:
        print(f"\n{GREEN}✅ All code hygiene audits passed successfully! Proceeding with push.{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
