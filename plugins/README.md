# 🧹 Codebase Quality Plugins (`kit-plugins`)

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)

> **AST-Based Code Quality Gate Plugins for Python, TypeScript, and OpenCode**  
> Deterministically verifies code against strict quality constraints (AST anti-slop policy, Ruff/MyPy strict, tsc strict, ESLint-equivalent rules, Radon cyclomatic complexity < 6) before atomically writing to disk.

---

## Plugin Capabilities

| # | Plugin | Language | Quality Gate Summary |
|---|---|---|---|
| 1 | `clean_py` / `clean_python.ts` | Python | AST policy (no bare except, no swallowed exceptions) + Ruff + MyPy strict + Radon CC < 6 |
| 2 | `clean_ts` / `clean_ts.ts` | TypeScript | AST policy (no eval, no swallowed exceptions) + tsc --strict --noEmit + ESLint-equivalent rules + CC < 6 |
| 3 | `opencode/clean_python.ts` | OpenCode | Security-gated wrapper that delegates to `clean_py`, enforces temp-file hygiene, and tracks retry attempts |
| 4 | `opencode/clean_ts.ts` | OpenCode | Security-gated wrapper that delegates to `clean_ts` CLI, enforces temp-file hygiene, and tracks retry attempts |

---

## Directory Structure

```
plugins/
├── README.md                     # Architecture and overview (this file)
├── GUIDE.md                      # Installation, configuration, and usage guide
├── FAQ.md                        # Frequently asked questions and troubleshooting
├── opencode/                     # OpenCode tool wrappers
│   ├── clean_python.ts           # Validated .py file writer (delegates to clean_py)
│   └── clean_ts.ts               # Validated .ts/.tsx file writer (delegates to clean_ts)
├── python/
│   ├── clean_py/                 # Python validator package
│   │   ├── cli.py                # CLI entry point (`clean_py validate <file>`)
│   │   ├── validator.py          # AST + Ruff + MyPy + Radon orchestration
│   │   └── ...
│   └── pyproject.toml            # Hatchling build config, pip-installable
└── typescript/
    └── clean_ts/                 # TypeScript validator package
        ├── src/
        │   ├── cli.ts            # CLI entry point (`clean_ts validate <file>`)
        │   ├── validator.ts      # AST + tsc + ESLint-equivalent orchestration
        │   ├── ast-policy.ts     # AST anti-slop policy checks
        │   └── index.ts          # Module exports
        ├── tsconfig.json         # Strict TypeScript config
        ├── eslint.config.ts      # ESLint flat config mirroring clean_py rules
        └── package.json          # Node package config
```

---

## Quick Start

```bash
# Python: install the clean_py package
cd plugins/python
pip install -e .

# TypeScript: install and build the clean_ts package
cd plugins/typescript/clean_ts
npm install
npm run build
```

For complete installation, configuration, and CI integration details, refer to:

- **[`GUIDE.md`](./GUIDE.md)** — Step-by-step installation, `clean_py` config, `clean_ts` config, usage, env vars, and CI setup.
- **[`FAQ.md`](./FAQ.md)** — Frequently asked questions on architecture, dependencies, env vars, and bypass options.
