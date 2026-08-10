import json
import subprocess
import sys
from pathlib import Path


def run_tool(args):
    cmd = [sys.executable, str(Path(__file__).parents[1] / f"{args[0]}.py")] + args[1:]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"Error running {args[0]}.py: {result.stderr}")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Failed to decode JSON from {args[0]}.py: {result.stdout}")
        return None

def test_verify_file_path():
    print("Testing verify_file_path...")
    res = run_tool(["verify_file_path", "README.md"])
    return res is not None and res.get("exists") is True

def test_query_knowledge_graph():
    print("Testing query_knowledge_graph...")
    res = run_tool(["query_knowledge_graph", "architecture"])
    return res is not None

def test_graph_health():
    print("Testing graph_health...")
    res = run_tool(["graph_health"])
    return res is not None

if __name__ == "__main__":
    tests = [test_verify_file_path, test_query_knowledge_graph, test_graph_health]
    results = []
    for test in tests:
        results.append((test.__name__, test()))

    for name, res in results:
        print(f"{name}: {'PASS' if res else 'FAIL'}")
