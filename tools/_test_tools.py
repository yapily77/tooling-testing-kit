#!/usr/bin/env python3
import asyncio
import subprocess
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(WORKSPACE_ROOT))

from mcp_git_guardrail import mcp

GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _check_result(condition: bool, pass_msg: str, fail_msg: str) -> bool:
    """Print pass/fail message based on condition and return boolean."""
    if condition:
        print(f"{GREEN}✅ {pass_msg}{RESET}")
        return True
    print(f"{RED}❌ {fail_msg}{RESET}")
    return False


def test_investigate_cli():
    print(f"\n{BOLD}🧪 Testing investigate.py CLI...{RESET}")
    cmd = [
        "uv", "run", "python",
        str(WORKSPACE_ROOT / "kit-tools" / "investigate.py"),
        "--filename", "admin/controls/controls.py", "--lines", "218-225",
    ]
    res = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, check=False)
    return _check_result(
        res.returncode == 0 and "CONTROL_SHEET" in res.stdout,
        "investigate.py CLI test passed successfully!",
        "investigate.py CLI test failed!",
    )


def test_mcp_git_guardrail_imports():
    print(f"\n{BOLD}🧪 Testing mcp_git_guardrail.py tools registration...{RESET}")
    try:
        tools = asyncio.run(mcp.list_tools())
        tool_names = [t.name for t in tools]
        expected = ["checkpoint_file", "validate_file", "git_release_push"]
        missing = [t for t in expected if t not in tool_names]
        return _check_result(
            not missing,
            f"mcp_git_guardrail.py registered all expected tools: {tool_names}",
            f"mcp_git_guardrail.py is missing tools: {missing}",
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"{RED}❌ mcp_git_guardrail.py import/registration test failed: {e}{RESET}")
        raise


def main():
    print("=" * 60)
    print(f"      {BOLD}kit-tools Integration Tests{RESET}  🛠️")
    print("=" * 60)

    r1 = test_investigate_cli()
    r2 = test_mcp_git_guardrail_imports()

    print("=" * 60)
    if r1 and r2:
        print(f"{GREEN}🎉 All integration tests passed!{RESET}")
        sys.exit(0)
    print(f"{RED}❌ Some integration tests failed.{RESET}")
    sys.exit(1)


if __name__ == "__main__":
    main()
