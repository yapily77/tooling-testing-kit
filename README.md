# Tools Test Kit (kit)

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![Package Manager: uv](https://img.shields.io/badge/package%20manager-uv-purple.svg)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

> **Portable, runnable Python slices for technical debt analysis, test design, AST refactoring, and domain RAG.**  
> Self-contained tools and test patterns extracted into clean, zero-dependency runnable modules.

---

## Overview

The **Tools Test Kit** (`kit`) is a production-grade Python engineering toolkit designed for developers, AI coding agents, and technical auditors. It breaks complex enterprise codebases down into portable, runnable modules that can be executed offline or paired with LLMs via standard `KIT_*` environment variables.

### Key Capabilities & Suites

| Suite | Focus & Purpose | Execution Mode | Quick Run |
|---|---|---|---|
| **[`hygiene/`](./hygiene)** | Hybrid static-AST + LLM technical debt scanner (11 detection passes) | Offline static or LLM-assisted | `cd hygiene && cp .env.example .env && uv run scanners/run_all.py --scripts` |
| **[`tests/`](./tests)** | Interview-ready test pattern stubs (golden snapshots, property/fuzz, mutation targets) | Offline stubs (`KIT_LIVE=false`) | `cd tests && uv run pytest examples -q` |
| **[`tools/`](./tools)** | Codebase search, AST code modification, and BaziRAG domain retrieval | Portable via `KIT_TARGET_ROOT` | `cd tools && uv run python search.py "query"` |

---

## Quick Start (Workspace Setup)

You can run each subfolder independently or manage the entire workspace with [`uv`](https://docs.astral.sh/uv/):

```bash
# Clone repository
git clone https://github.com/Acivar-Digital/tools-test-kit.git
cd tools-test-kit

# Install all dependencies across workspace projects
uv sync --all-projects

# Run test stubs
cd tests && uv run pytest examples -q

# Run static hygiene scans
cd ../hygiene && cp .env.example .env && uv run scanners/run_all.py --scripts
```

---

## Architecture & Directory Layout

```
tools-test-kit/
├── hygiene/                  # Technical debt scanner suite (AST + LLM audit)
│   ├── scanners/              # 11 static and LLM scanner scripts
│   ├── reports/               # Output audit reports (JSON + Markdown)
│   ├── README.md              # Hygiene architecture & overview
│   ├── GUIDE.md               # Installation & configuration guide
│   └── FAQ.md                 # Technical debt FAQ & cost optimization
├── tests/                    # Production test patterns & stubs
│   ├── examples/              # Self-contained cloner-safe stubs (START HERE)
│   ├── 01_gold_snapshots/     # Golden snapshot test suites
│   ├── 06_property_fuzz/      # Property-based Hypothesis fuzz tests
│   ├── README.md              # Test suite design & layer breakdown
│   ├── GUIDE.md               # Execution & LLM mode configuration
│   └── QUICKSTART.md          # Fast-path user quickstart
├── tools/                    # Codebase intelligence & AST code-mods
│   ├── codebase/              # Search, AST refactoring, and analysis tools
│   ├── rag/                   # Domain-specific BaziRAG demonstration
│   ├── README.md              # Tools suite overview & portability matrix
│   └── GUIDE.md               # Unified usage guide for codebase & RAG tools
├── .env.example              # Central environment template
├── AGENTS.md                 # AI agent system instructions & issue tracking rules
└── pyproject.toml            # Root workspace project definition
```

---

## LLM Configuration Contract (`KIT_*`)

All LLM-enabled tools share a standardized, fail-closed configuration interface:

```env
# Target codebase path
KIT_TARGET_ROOT=/path/to/target/codebase

# LLM Endpoint Configuration
KIT_BASE_URL=http://localhost:8000/v1
KIT_API_KEY=sk-your-api-key
KIT_MODEL=gemma-2-27b-it

# Live test switch
KIT_LIVE=false
```

If an LLM feature is enabled without required credentials, the tools **fail closed** immediately with a clear error message rather than silently dropping checks.

---

## Search Engine & LLM Answer Engine Index

- **What is kit-hygiene?** See [`hygiene/FAQ.md`](./hygiene/FAQ.md)
- **How to run tests without external dependencies?** See [`tests/QUICKSTART.md`](./tests/QUICKSTART.md)
- **How to perform AST-driven code modifications?** See [`tools/README.md`](./tools/README.md)
- **How to configure LLM models and local endpoints?** See [`hygiene/GUIDE.md`](./hygiene/GUIDE.md)

---

## License & Contribution

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE) for details.
