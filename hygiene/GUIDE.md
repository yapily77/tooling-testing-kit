# 🧭 kit-hygiene Guide — Install, Configure & Run

> **Complete guide to installing, configuring, and executing technical debt scans.**

---

## 1. Prerequisites

| Requirement | Supported Version | Purpose |
|---|---|---|
| Python | 3.14+ | Standard runtime |
| `uv` | latest | Workspace dependency and package management |
| API Key | Optional | Only required for Tier 2 LLM verification |

---

## 2. Installation & Configuration

1. Copy the `.env.example` file to create your local `.env`:

```bash
cp hygiene/.env.example hygiene/.env
```

2. Configure path settings inside `hygiene/.env`:

```env
# Path Configuration
AIB_FACTORY_ROOT=/path/to/your/repository
SCAN_ROOTS=./src
TARGET_ROOT=/path/to/your/repository

# Thresholds
HARD_FAIL_THRESHOLD=2
DUPE_THRESHOLD_PCT=100

# LLM Configuration (Tier 2)
KIT_ENABLE_REGISTRY_CLASHES=false
KIT_BASE_URL=http://localhost:8000/v1
KIT_API_KEY=sk-your-key
KIT_MODEL=gemma-2-27b-it
```

---

## 3. Execution Modes

### 3a. Offline Static Scan (`--scripts`)
Runs Tier 1 static AST scans only. No network connections or API keys required.

```bash
uv run hygiene/scanners/run_all.py --scripts
```

### 3b. Full Audit Mode (Static + LLM Verification)
Runs Tier 1 static analysis followed by Tier 2 LLM verification for flagged candidate issues.

```bash
uv run hygiene/scanners/run_all.py
```

### 3c. Single Scanner Execution
Execute a single scanner script directly:

```bash
uv run hygiene/scanners/find_silent_killers.py --scripts
```

### 3d. Git Diff Mode
Scan only files modified in the active git working directory:

```bash
uv run hygiene/scanners/run_all.py --diff
```

---

## 4. Understanding Reports & Outputs

All reports are emitted to `hygiene/reports/` in both JSON and Markdown formats:

- `hygiene/reports/<scanner_name>.json` — Structured audit data
- `hygiene/reports/<scanner_name>.md` — Summary report

### JSON Report Structure Example

```json
{
  "scanner": "find_silent_killers",
  "audit_results": [
    {
      "file_path": "src/auth/handlers.py",
      "line": 42,
      "name": "swallowed_exception",
      "type": "swallowed_exception",
      "status": "SILENT_KILLER",
      "severity": "HIGH",
      "reason": "Bare except handler swallows unexpected runtime errors."
    }
  ],
  "summary": {
    "total_candidates": 5,
    "true_positives": 1,
    "false_positives": 4
  }
}
```

---

## 5. Automated Refactoring Utilities

### AST Cleanup (`cleanup.py`)
Applies deterministic AST fixes for simple violations (e.g., converting bare `except:` to `except Exception:`):

```bash
uv run hygiene/cleanup.py
```

### High-Complexity Refactoring (`kill_tries.py`)
Batch LLM-driven refactoring for high cyclomatic complexity functions:

```bash
# 1. Specify target files in scanners/kill_tries_list.txt
echo "./src/complex_module.py" > hygiene/scanners/kill_tries_list.txt

# 2. Generate refactored candidates
uv run hygiene/scanners/kill_tries.py

# 3. Apply approved refactorings
uv run hygiene/scanners/kill_tries_apply.py
```

---

## 6. Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `RuntimeError: KIT_API_KEY required` | LLM mode enabled without API key | Set `KIT_ENABLE_REGISTRY_CLASHES=false` or provide `KIT_API_KEY` |
| `ModuleNotFoundError` | Missing Python package | Run `uv sync --all-projects` or `pip install -r hygiene/requirements.txt` |
| No findings in reports | Code is clean or scanner target paths wrong | Verify `SCAN_ROOTS` and `TARGET_ROOT` paths in `.env` |
