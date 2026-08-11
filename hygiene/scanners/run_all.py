import argparse
import subprocess
import sys
from pathlib import Path

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

SCANNERS = [
    "scanners/find_dead_code.py",
    "scanners/find_silent_killers.py",
    "scanners/find_async_hazards.py",
    "scanners/find_engine_schemas.py",
    "scanners/find_secrets.py",
    "scanners/find_env_drift.py",
    "scanners/find_circular_deps.py",
    "scanners/find_duplication.py",
    "scanners/find_type_safety.py",
    "scanners/find_message_drift.py",
    "scanners/find_registry_clashes.py",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Codebase Hygiene Runner")
    parser.add_argument("--scripts", action="store_true", help="Run only the static check parts of all scanners")
    parser.add_argument("--diff", action="store_true", help="Scan only git modified/untracked files under src/")
    return parser.parse_args()


def build_scanner_command(scanner_path, args):
    cmd = [sys.executable, str(scanner_path)]
    if args.scripts:
        cmd.append("--scripts")
    if args.diff:
        cmd.append("--diff")
    return cmd


def run_scanner(scanner_path, args, base_dir):
    print(f"\n🚀 Running {scanner_path.name}...")
    cmd = build_scanner_command(scanner_path, args)
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(base_dir), check=False)
    if res.returncode != 0:
        print(f"{RED}❌ Scanner {scanner_path.name} failed with exit code {res.returncode}.{RESET}")
        return False
    print(f"{GREEN}✅ Scanner {scanner_path.name} completed successfully.{RESET}")
    return True


def main():
    args = parse_args()

    print(f"{BOLD}🧹 Running All Codebase Hygiene Scanners...{RESET}")
    base_dir = Path(__file__).resolve().parents[1]

    failed = False

    for scanner_rel in SCANNERS:
        scanner_path = base_dir / scanner_rel
        if not scanner_path.exists():
            print(f"{YELLOW}Warning: Scanner {scanner_rel} not found.{RESET}")
            continue
        if not run_scanner(scanner_path, args, base_dir):
            failed = True

    if failed:
        print(f"\n{RED}❌ Some scanners failed. Review reports in kit-hygiene/reports/.{RESET}")
        sys.exit(1)
    else:
        print(f"\n{GREEN}✅ All scanners completed successfully!{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
