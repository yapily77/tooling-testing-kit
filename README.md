# Tooling & Testing Kit (`tooling-testing-kit`)

[![CI](https://github.com/Acivar-Digital/tooling-testing-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/Acivar-Digital/tooling-testing-kit/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> **Enterprise-grade AI Engineering, Static Analysis, and Harness Testing Toolkit for Python Workflows**  
> Portable, runnable modules for technical debt scanning, AST refactoring, test harness design, and codebase intelligence — plus TypeScript plugins and OpenCode tool wrappers for AI agent workflows.

---

## 🌟 Overview

The **Tooling & Testing Kit** is a production-grade engineering toolkit for developers, AI coding agents, and enterprise technical auditors. It breaks complex repositories down into portable, runnable modules that can be executed offline or paired with LLMs via standard `KIT_*` environment variables.

It is a **hybrid Python + TypeScript** toolchain: the core scanners, AST refactorings, and test harnesses are written in Python; the code-quality cleaners (`clean_py`, `clean_ts`) and OpenCode plugin wrappers are written in TypeScript/Node.

### 📦 Toolkit Modules & Capabilities

| Module | Language | Purpose | Execution Mode | Quick Command |
|---|---|---|---|---|
| **[`hygiene/`](./hygiene)** | Python | Technical debt & security scanner (11 static + LLM analysis passes) | Static or LLM-assisted | `python hygiene/scanners/run_all.py --scripts` |
| **[`tools/`](./tools)** | Python | AST code refactoring, codebase search, RAG retrieval utilities | Portable via `KIT_TARGET_ROOT` | `python tools/test/run_all.py` |
| **[`tests/`](./tests)** | Python | Golden snapshot, property-based fuzzing, and harness test patterns | Offline or live mode | `pytest tests/examples/` |
| **[`examples/`](./examples)** | Python | Worked examples, sample targets, and generated audit report samples | Quick demonstration | `python hygiene/scanners/run_all.py --scripts` |
| **[`plugins/`](./plugins)** | Python + TypeScript | AST-based code quality cleaners (`clean_py`, `clean_ts`) + OpenCode tool wrappers | Static, pre-commit / CLI | `clean_py validate file.py` · `clean_ts validate file.ts` |
| **[`demo/`](./demo)** | Python + TypeScript | Case studies: `opencode/python` + `opencode/typescript` + scripts | Runnable examples | varies by case study |

The `tests/` and `tools/` trees are designed as **training data and patterns that LLMs can emulate**: they contain concrete, runnable fixtures for snapshot comparison, property-based fuzzing, and AST code-modding that AI agents can copy, adapt, and extend.

---

## ⚡ Quick Start

### 1. Installation (Python)

Install all Python toolkit modules at once with optional dependencies:

```bash
# Clone the repository
git clone https://github.com/Acivar-Digital/tooling-testing-kit.git
cd tooling-testing-kit

# Install with all optional suites (hygiene, tools, tests)
pip install -e ".[all]"
```

### 2. Install the TypeScript Plugins (optional)

The code-quality cleaners and OpenCode wrappers require Node.js (>=18):

```bash
# Python cleaner
pip install plugins/python/clean_py

# TypeScript cleaner
cd plugins/typescript/clean_ts
npm install
npm run build
```

### 3. Run All Verification Suites

```bash
# 1. Run codebase hygiene static scanners (Python)
python hygiene/scanners/run_all.py --scripts

# 2. Run AST code-mod unit test suite (Python)
python tools/test/run_all.py

# 3. Run pytest harness suite (Python)
pytest tests/examples/

# 4. Validate code quality (TypeScript, optional)
clean_ts validate file.ts
```

---

## 📂 Repository Architecture

```text
tooling-testing-kit/
├── .github/workflows/       # GitHub Actions CI/CD workflows
│   └── ci.yml               # Automated scanner & pytest verification pipeline (Python only)
├── hygiene/                 # Technical debt scanner suite (AST + LLM audit) — Python
│   ├── scanners/            # 11 static and LLM scanner scripts
│   ├── reports/             # Generated audit reports (JSON + Markdown)
│   ├── README.md            # Hygiene architecture & overview
│   └── GUIDE.md             # Scanner configuration guide
├── tools/                   # Codebase intelligence & AST code modifications — Python
│   ├── test/                # Unit test suite runner for codebase tools
│   ├── rag/                 # Portable BaziRAG domain retrieval pipeline
│   └── README.md            # Tools suite overview & AST tool list
├── tests/                   # Production test patterns & harness stubs — Python
│   ├── examples/            # Self-contained test harness examples (emulable by LLMs)
│   └── README.md            # Test suite layer breakdown
├── examples/                # Worked examples & sample scanner outputs — Python
│   ├── sample_target.py     # Sample target module with intentional code smells
│   └── scanner_output_example.md # Formatted audit output demonstration
├── plugins/                 # OpenCode & code quality cleaner tools (Python + TypeScript)
│   ├── python/              # clean_py — Python AST code-quality cleaner
│   │   └── clean_py/
│   ├── typescript/          # clean_ts — TypeScript code-quality cleaner
│   │   └── clean_ts/
│   ├── opencode/            # OpenCode tool wrappers (clean_python.ts, clean_ts.ts)
│   └── reminder/            # opencode-workflow.ts — workflow reminders
├── demo/                    # Case studies: opencode/python + opencode/typescript + scripts/
│   ├── opencode/            # Runnable AI agent case studies (Python & TypeScript)
│   ├── python/              # (legacy) Python case studies
│   └── scripts/             # Demo scripts
├── pyproject.toml           # Unified root Python package configuration
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
KIT_MODEL=gemma-4-31b-it

# Test mode toggle
KIT_LIVE=false
```

---

## 🛠️ Demo & Plugins (usable)

The `demo/` and `plugins/` trees provide runnable case studies and code-quality cleaners usable as both CLI tools and OpenCode agent integrations:

- `demo/opencode/python/` — Python AI-agent case studies (report generation, complexity/style finders)
- `demo/opencode/typescript/` — TypeScript case study (`case_generate.md`)
- `plugins/python/clean_py/` — Python AST cleaner; `clean_py validate file.py`
- `plugins/typescript/clean_ts/` — TypeScript cleaner; `clean_ts validate file.ts`
- `plugins/opencode/` — OpenCode tool wrappers for agent workflows

---

## 🧪 `tests/` & `tools/` as Training Patterns

The `tests/` and `tools/` trees serve as **training data and patterns that LLMs can emulate**. They contain:

- Concrete, runnable fixtures for golden-snapshot comparison
- Property-based fuzzing harnesses
- AST code-modding examples
- Self-contained test harness stubs

LLM agents can copy, adapt, and extend these patterns for new codebases.

---

## 🤝 Contributing

Contributions are welcome! Please read [`CONTRIBUTING.md`](./CONTRIBUTING.md) for details on testing, code style, and submission process.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE) for full details.
