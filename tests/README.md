# Community Test Kit (`kit-tests`)

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)

> **Curated, runnable Python test design patterns and interview stubs**  
> Standalone, cloner-safe test suites demonstrating golden snapshot testing, property/fuzz scanning, mutation testing, and AST static guardrails.

---

## Executive Summary

`kit-tests` extracts production test design patterns into clean, self-contained, runnable slices. Every candidate or developer can clone and execute the core test patterns without monorepo dependencies, Docker, or mandatory external API keys.

---

## Test Suite Layer Breakdown

| Layer | Path | Description & Contents |
|---|---|---|
| **00** | [`examples/`](./examples) | **5 self-contained, cloner-safe stubs** (START HERE - offline runnable) |
| **01** | `01_gold_snapshots/` | Golden snapshot output suites (`final_report.json`, `snapshot*.json`, UI docs) |
| **02** | `02_unit_bedrock/` | Unit and feature bedrock test suites across engine logic |
| **03** | `03_regression_locks/` | Pinned regression benchmarks and calibration suites |
| **04** | `04_bug_repros/` | Isolated regression bug reproduction test cases |
| **05** | `05_integration_e2e/` | Multi-step integration pipelines |
| **06** | [`06_property_fuzz/`](./06_property_fuzz) | Property-based Hypothesis fuzz tests |
| **07** | `07_mutation_testing/` | Mutation targets and `mutmut` configuration |
| **08** | `08_static_gates/` | AST guardrails, sanitizers, and swallowed exception linters |
| **09** | `09_tech_debt_audit/` | Technical debt audit tools and report artifacts |
| **10** | `10_harness_suite/` | Regression suite reference copies |

---

## Quick Start

### 1. Offline Stubs (Zero External Dependencies)

Execute the 8 self-contained pattern stubs in `examples/`:

```bash
cd tests
KIT_LIVE=false uv run pytest examples -q
```

Output:
```text
8 passed in 0.18s
```

### 2. Live LLM Integration Mode (Optional)

To enable live LLM integration tests, copy `.env.example` to `.env` and set environment variables:

```bash
cp tests/.env.example tests/.env

# Set environment variables:
# KIT_LIVE=true
# KIT_PATH=/path/to/target
# KIT_BASE_URL=http://localhost:8000/v1
# KIT_MODEL=gemma-2-27b-it
# KIT_API_KEY=sk-your-key

KIT_LIVE=true uv run pytest examples/test_kit_live_smoke.py -q
```

---

## Fail-Fast Environment Contract

When `KIT_LIVE=true`, the configuration validator checks all required variables at import time:
- If `KIT_PATH`, `KIT_BASE_URL`, `KIT_MODEL`, or `KIT_API_KEY` are missing or empty, execution fails immediately with a `RuntimeError`.
- Misconfigurations fail loudly before any test logic executes.

---

## Related Documentation

- **[`GUIDE.md`](./GUIDE.md)** — Step-by-step test kit configuration and execution guide.
- **[`QUICKSTART.md`](./QUICKSTART.md)** — 60-second fast-path quickstart guide.
- **[`STRUCTURE.md`](./STRUCTURE.md)** — Full layout breakdown and per-layer curation rules.
