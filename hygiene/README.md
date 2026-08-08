# 🧹 Codebase Hygiene Suite (`kit-hygiene`)

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)

> **Hybrid Static AST + LLM Technical Debt Scanner for Python Codebases**  
> Detects swallowed exceptions, schema hazards, circular dependencies, hardcoded secrets, and async deadlocks without noise or vendor lock-in.

---

## Executive Summary

**kit-hygiene** is a two-tier static analysis and LLM-powered audit pipeline that eliminates false positives in technical debt scanning. Standard linters either generate hundreds of stylistic warnings or miss deep runtime bugs. `kit-hygiene` combines fast, local Python Abstract Syntax Tree (AST) parsing with targeted LLM semantic verification.

### Related Documentation
- **[`GUIDE.md`](./GUIDE.md)** — Step-by-step installation, `.env` reference, and execution modes.
- **[`FAQ.md`](./FAQ.md)** — Answer Engine & SEO optimized questions on costs, CI/CD, and custom models.

---

## Two-Tier Architecture

```
                                 ┌─────────────────────────────────┐
                                 │       Target Python Codebase    │
                                 └────────────────┬────────────────┘
                                                  │
                                                  ▼
                                 ┌─────────────────────────────────┐
                                 │ Tier 1: Static AST / Regex Pass │
                                 │ (Offline, Fast, High Recall)    │
                                 └────────────────┬────────────────┘
                                                  │
                                                  ▼ Candidate Findings
                                 ┌─────────────────────────────────┐
                                 │ Tier 2: LLM Semantic Audit      │
                                 │ (Selective, Pydantic-AI Agent)  │
                                 └────────────────┬────────────────┘
                                                  │
                                                  ▼ Verified Verdicts
                                 ┌─────────────────────────────────┐
                                 │  Reports: JSON + Markdown Summaries │
                                 └─────────────────────────────────┘
```

1. **Tier 1 (Static AST Filter)**: Runs locally in milliseconds with zero network or API dependencies. Flags potential risks with high recall.
2. **Tier 2 (LLM Semantic Verification)**: Sends only snippet context of flagged candidates to a model via Pydantic-AI. Filters false positives and categorizes real bugs.

---

## Scanner Capabilities Matrix

| # | Scanner | Target Defect / Pattern | Tier 1 (AST) | Tier 2 (LLM) | Output Verdict |
|---|---|---|---|---|---|
| 1 | `find_dead_code.py` | Unreachable functions, classes, and unused exports | ✓ | ✓ | `DEAD_CODE` / `VERIFIED_LIVE` |
| 2 | `find_silent_killers.py` | Swallowed exceptions (`except: pass`), bare handlers | ✓ | ✓ | `SILENT_KILLER` / `FALSE_POSITIVE` |
| 3 | `find_async_hazards.py` | Blocking I/O (`requests.get`) inside `async def` | ✓ | ✓ | `ASYNC_HAZARD` / `SAFE` |
| 4 | `find_engine_schemas.py` | Dict/list passed directly to Pydantic models | ✓ | ✓ | `SCHEMA_HAZARD` / `FALSE_POSITIVE` |
| 5 | `find_secrets.py` | Hardcoded API keys, tokens, and committed secrets | ✓ | ✓ | `HARDCODED_SECRET` / `FALSE_POSITIVE` |
| 6 | `find_env_drift.py` | `os.getenv()` keys missing from `.env.example` | ✓ | ✓ | `ENV_DRIFT` / `OK` |
| 7 | `find_circular_deps.py` | Import cycles causing startup `ImportError` | ✓ | ✓ | `CIRCULAR_DEP` / `FALSE_POSITIVE` |
| 8 | `find_duplication.py` | Duplicated code blocks exceeding threshold | ✓ | ✓ | `DUPLICATE` / `FALSE_POSITIVE` |
| 9 | `find_type_safety.py` | Mypy / Pyright static type errors | ✓ | ✓ | `TYPE_ERROR` / `FALSE_POSITIVE` |
| 10 | `find_registry_clashes.py` | Model dict-access methods (`.get()`, `.keys()`) | ✓ | ✓ | `SCHEMA_HAZARD` / `FALSE_POSITIVE` |
| 11 | `find_message_drift.py` | Translation string keys vs dictionary definitions | ✓ | ✗ | `MISSING_KEY` / `OK` |

---

## Directory Structure

```
hygiene/
├── .env.example          # Environment variable configuration template
├── README.md             # Architecture and overview (this file)
├── GUIDE.md              # Installation, configuration, and execution guide
├── FAQ.md                # Answer engine FAQ and troubleshooting
├── control.py            # Configuration loader for KIT_* variables
├── cleanup.py            # One-shot AST auto-fixer for simple violations
├── run-registry-scan.sh  # Wrapper for long-running registry scans
├── scanners/             # Individual scanner implementation scripts
│   ├── run_all.py        # Master execution orchestrator
│   ├── utils.py          # Shared AST and file parsing utilities
│   └── find_*.py         # Scanner implementations
└── reports/              # Audit report output directory (JSON + MD)
```

---

## Quick Start

```bash
# 1. Copy environment template
cp hygiene/.env.example hygiene/.env

# 2. Configure target directory in .env
# TARGET_ROOT=/path/to/your/codebase

# 3. Run offline static analysis pass (no API key required)
uv run hygiene/scanners/run_all.py --scripts

# 4. Review findings in reports
cat hygiene/reports/find_silent_killers.md
```

For complete configuration and LLM setup, refer to **[`GUIDE.md`](./GUIDE.md)** and **[`FAQ.md`](./FAQ.md)**.
