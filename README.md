# Tooling & Testing Kit (`tooling-testing-kit`)

[![CI](https://github.com/Acivar-Digital/tooling-testing-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/Acivar-Digital/tooling-testing-kit/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> **Enterprise-grade AI Engineering, Static Analysis, and Harness Testing Toolkit for Python Workflows**  
> Portable, zero-dependency runnable modules for technical debt scanning, AST refactoring, test harness design, and codebase intelligence.

---

## 🌟 Overview

The **Tooling & Testing Kit** is a production-grade Python engineering toolkit designed for developers, AI coding agents, and enterprise technical auditors. It breaks complex Python repositories down into portable, runnable modules that can be executed offline or paired with LLMs via standard `KIT_*` environment variables.

### 📦 Toolkit Modules & Capabilities

| Module | Purpose | Execution Mode | Quick Command |
|---|---|---|---|
| **[`hygiene/`](./hygiene)** | Technical debt & security scanner (11 static + LLM analysis passes) | Static or LLM-assisted | `python hygiene/scanners/run_all.py --scripts` |
| **[`tools/`](./tools)** | AST code refactoring, codebase search, and RAG retrieval utilities | Portable via `KIT_TARGET_ROOT` | `python tools/test/run_all.py` |
| **[`tests/`](./tests)** | Golden snapshot, property-based fuzzing, and harness test patterns | Offline or live mode | `pytest tests/examples/` |
| **[`examples/`](./examples)** | Worked examples, sample targets, and generated audit report samples | Quick demonstration | `python hygiene/scanners/run_all.py --scripts` |

---

## ⚡ Quick Start

### 1. Installation

Install all toolkit modules at once with optional dependencies:

```bash
# Clone the repository
git clone https://github.com/Acivar-Digital/tooling-testing-kit.git
cd tooling-testing-kit

# Install with all optional suites (hygiene, tools, tests)
pip install -e ".[all]"
```

### 2. Run All Verification Suites

```bash
# 1. Run codebase hygiene static scanners
python hygiene/scanners/run_all.py --scripts

# 2. Run AST code-mod unit test suite
python tools/test/run_all.py

# 3. Run pytest harness suite
pytest tests/examples/
```

---

## 📂 Repository Architecture

```text
tooling-testing-kit/
├── .github/workflows/       # GitHub Actions CI/CD workflows
│   └── ci.yml               # Automated scanner & pytest verification pipeline
├── hygiene/                 # Technical debt scanner suite (AST + LLM audit)
│   ├── scanners/            # 11 static and LLM scanner scripts
│   ├── reports/             # Generated audit reports (JSON + Markdown)
│   ├── README.md            # Hygiene architecture & overview
│   └── GUIDE.md             # Scanner configuration guide
├── tools/                   # Codebase intelligence & AST code modifications
│   ├── test/                # Unit test suite runner for codebase tools
│   ├── rag/                 # Portable BaziRAG domain retrieval pipeline
│   └── README.md            # Tools suite overview & AST tool list
├── tests/                   # Production test patterns & harness stubs
│   ├── examples/            # Self-contained test harness examples
│   └── README.md            # Test suite layer breakdown
├── examples/                # Worked examples & sample scanner outputs
│   ├── sample_target.py     # Sample target module with intentional code smells
│   └── scanner_output_example.md # Formatted audit output demonstration
├── CONTRIBUTING.md          # Open collaboration & contribution guidelines
├── pyproject.toml           # Unified root package configuration
└── README.md                # Main repository guide
```

---

## ⚙️ Configuration Contract (`KIT_*`)

LLM-enabled tools share a fail-closed configuration contract:

```env
# Target codebase path
KIT_TARGET_ROOT=/path/to/target/repository

# LLM Endpoint Configuration
KIT_BASE_URL=http://localhost:8000/v1
KIT_API_KEY=sk-your-api-key
KIT_MODEL=gemma-2-27b-it

# Test mode toggle
KIT_LIVE=false
```

---

## 🤝 Contributing

Contributions are welcome! Please read [`CONTRIBUTING.md`](./CONTRIBUTING.md) for details on testing, code style, and submission process.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE) for full details.
