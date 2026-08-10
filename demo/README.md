# 📦 Tooling & Testing Kit - Demo Case Studies

> **Anti-slop case studies for `clean_python` and `clean_python.ts` plugin verification.**

> **Related docs:** `GUIDE.md` (install & configure) · `FAQ.md` (troubleshooting & cost questions)

This directory contains **7 case-study files** (moved from the original `box/` folder) that demonstrate and verify the `clean_python` AST policy enforcement pipeline. Each file was crafted to trigger specific quality gates — cyclomatic complexity limits, type-annotation strictness, and silent-exception detection.

---

## What's Inside

| File | Purpose | Quality Gate Tested |
|---|---|---|
| `case_generate.md` | Case specification: generates a new script (`generate_report.py`) from a natural-language prompt | Tests autonomous adherence to clean_python rules |
| `find_bad_style.py` | Scans Python files for Google Style Guide violations: mutable defaults, missing type hints, unsafe `open()` | MyPy strict, AST anti-slop, Ruff |
| `find_cc_nested.py` | Finds functions exceeding cyclomatic complexity threshold (default CC ≥ 6) | Radon CC enforcement |
| `find_hallucinations.py` | Validates LLM-refactored code against the original for API drift, invalid imports, and suspicious calls | AST anti-slop, signature validation |
| `find_hallucinations_slop.py` | Early version with known slop patterns (broad `except`, untyped `dict`) — used as a negative example | Demonstrates what clean_python rejects |
| `generate_report.py` | Generated script: reads JSON test logs, calculates stats, outputs Markdown report | CC < 6, type annotations, structured error handling |
| `test_daily_pillar.py` | Tests for `resolve_daily_pillar_range` and `get_month_anchor_for_date` across year boundaries | Full test suite, pytest-compatible |

---

## Why This Matters

Standard LLMs, when prompted to "write a script with robust error handling," naturally produce:

1. **Monolithic functions** — CC = 8–14 (violates Radon CC < 6)
2. **Bare `except:` blocks** — swallowed exceptions that silently drop data (AST anti-slop violation)
3. **Missing type annotations** — loose `dict` types that MyPy strict rejects

The `clean_python` plugin intercepts write payloads **before** they reach disk. If any gate fails, it returns exact diagnostics, forcing the model to modularize and annotate correctly **on the first try**.

These case studies were built to validate that workflow end-to-end.

---

## Quick Start

```bash
# All Python files are runnable scripts with CLI arguments
.venv/bin/python demo/python/find_bad_style.py --files demo/python/find_cc_nested.py
.venv/bin/python demo/python/find_cc_nested.py --min-cc 6 demo/python/*.py
.venv/bin/python demo/python/find_hallucinations.py original.py refactored.py

# Run the test suite
.venv/bin/python -m pytest demo/python/test_daily_pillar.py -v

# The .mypy_cache and .ruff_cache directories contain prior analysis results
```

See [GUIDE.md](./GUIDE.md) for full setup and configuration.  
Common questions answered in [FAQ.md](./FAQ.md).

---

## Directory Structure

```
demo/
├── README.md           # This file — overview & file index
├── GUIDE.md            # How to run, configure, and interpret results
├── FAQ.md              # Troubleshooting & design rationale
└── python/             # 7 case-study files + caches
    ├── case_generate.md             # Prompt spec for generate_report.py
    ├── find_bad_style.py            # Style violation scanner
    ├── find_cc_nested.py            # Cyclomatic complexity finder
    ├── find_hallucinations.py       # LLM output validator (clean version)
    ├── find_hallucinations_slop.py  # LLM output validator (slop version)
    ├── generate_report.py           # Generated report generator
    ├── test_daily_pillar.py         # Cross-year pillar resolution tests
    ├── kit.code-workspace           # VS Code workspace config
    ├── .mypy_cache/                 # MyPy analysis cache
    └── .ruff_cache/                 # Ruff lint cache
```
