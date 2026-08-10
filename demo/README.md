# 📦 Tooling & Testing Kit - Demo Case Studies

> **Anti-slop case studies for `clean_python` and `clean_ts` plugin verification.**

> **Related docs:** `GUIDE.md` (install & configure) · `FAQ.md` (troubleshooting & cost questions)

This directory contains **paired case studies** across two language ecosystems that demonstrate and verify the `clean_python` (Python) and `clean_ts` (TypeScript) AST policy enforcement pipelines. Each language subtree contains runnable scripts and a `case_generate.md` prompt specification.

---

## What's Inside

### `opencode/python/` — Python Case Studies

| File | Purpose | Quality Gate Tested |
|---|---|---|
| `case_generate.md` | Prompt spec for generating `generate_report.py` from a natural-language prompt | Tests autonomous adherence to clean_python rules |
| `find_bad_style.py` | Scans Python files for Google Style Guide violations: mutable defaults, missing type hints, unsafe `open()` | MyPy strict, AST anti-slop, Ruff |
| `find_cc_nested.py` | Finds functions exceeding cyclomatic complexity threshold (default CC ≥ 6) | Radon CC enforcement |
| `find_hallucinations.py` | Validates LLM-refactored code against the original for API drift, invalid imports, and suspicious calls | AST anti-slop, signature validation |
| `find_hallucinations_slop.py` | Early version with known slop patterns (broad `except`, untyped `dict`) — used as a negative example | Demonstrates what clean_python rejects |
| `generate_report.py` | Generated script: reads JSON test logs, calculates stats, outputs Markdown report | CC < 6, type annotations, structured error handling |
| `test_daily_pillar.py` | Tests for `resolve_daily_pillar_range` and `get_month_anchor_for_date` across year boundaries | Full test suite, pytest-compatible |
| `kit.code-workspace` | VS Code workspace config | Editor integration |

**Cache directories:** `.mypy_cache/` and `.ruff_cache/` contain prior analysis results — safe to delete, regenerates on each run.

### `opencode/typescript/` — TypeScript Case Studies

| File | Purpose | Quality Gate Tested |
|---|---|---|
| `case_generate.md` | Prompt spec for generating `generate_report.ts` from a natural-language prompt | Tests autonomous adherence to clean_ts rules |
| `find_bad_style.ts` | Scans TypeScript files for anti-slop violations: cyclomatic complexity, swallowed catch blocks, missing types, ESLint errors | `ts/complexity` < 6, `tsc --strict`, AST anti-slop, ESLint |
| `tsconfig.json` | Strict TypeScript compiler configuration (`tsc --strict`, `noImplicitAny`, etc.) | Type safety enforcement |

### `scripts/` — Install & Examples

Currently empty. Used for shared install scripts, example data, and cross-language utilities that apply to both `opencode/python/` and `opencode/typescript/` case studies.

---

## Why This Matters

Standard LLMs, when prompted to "write a script with robust error handling," naturally produce:

1. **Monolithic functions** — CC = 8–14 (violates Radon CC < 6)
2. **Bare `except:` blocks** — swallowed exceptions that silently drop data (AST anti-slop violation)
3. **Missing type annotations** — loose `dict` types that MyPy/TSC strict rejects

The `clean_python` and `clean_ts` plugins intercept write payloads **before** they reach disk. If any gate fails, they return exact diagnostics, forcing the model to modularize and annotate correctly **on the first try**.

These case studies were built to validate that workflow end-to-end — across both Python and TypeScript.

---

## Quick Start

```bash
# Python: All scripts are runnable CLI tools
.venv/bin/python demo/opencode/python/find_bad_style.py --files demo/opencode/python/find_cc_nested.py
.venv/bin/python demo/opencode/python/find_cc_nested.py --min-cc 6 demo/opencode/python/*.py
.venv/bin/python demo/opencode/python/find_hallucinations.py original.py refactored.py

# Python: Run the test suite
.venv/bin/python -m pytest demo/opencode/python/test_daily_pillar.py -v

# TypeScript: Type-check + lint (requires node_modules)
tsc --strict demo/opencode/typescript/find_bad_style.ts
npx eslint demo/opencode/typescript/find_bad_style.ts

# The .mypy_cache and .ruff_cache directories contain prior analysis results
```

See [GUIDE.md](./GUIDE.md) for full setup and configuration.  
Common questions answered in [FAQ.md](./FAQ.md).

---

## Directory Structure

```
demo/
├── README.md                          # This file — overview & file index
├── GUIDE.md                           # How to run, configure, and interpret results
├── FAQ.md                             # Troubleshooting & design rationale
├── opencode/                          # Language-specific case studies
│   ├── python/
│   │   ├── case_generate.md           # Prompt spec for generate_report.py
│   │   ├── find_bad_style.py          # Style violation scanner
│   │   ├── find_cc_nested.py          # Cyclomatic complexity finder
│   │   ├── find_hallucinations.py     # LLM output validator (clean version)
│   │   ├── find_hallucinations_slop.py  # LLM output validator (slop version)
│   │   ├── generate_report.py         # Generated report generator
│   │   ├── test_daily_pillar.py       # Cross-year pillar resolution tests
│   │   ├── kit.code-workspace         # VS Code workspace config
│   │   ├── .mypy_cache/               # MyPy analysis cache
│   │   └── .ruff_cache/               # Ruff lint cache
│   └── typescript/
│       ├── case_generate.md           # Prompt spec for generate_report.ts
│       ├── find_bad_style.ts          # TS anti-slop & style checker
│       └── tsconfig.json              # Strict TS compiler config
└── scripts/                           # Shared install scripts & examples
```
