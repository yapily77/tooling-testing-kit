# 🧭 Demo Guide — Setup, Run & Verify

![Python](https://img.shields.io/badge/python-3.12+-blue?logo=python)
![TypeScript](https://img.shields.io/badge/typescript-5.9+-blue?logo=typescript)
![License](https://img.shields.io/badge/license-MIT-green)

> **Complete guide to installing, configuring, and executing the Python and TypeScript anti-slop case studies + example scripts.**

---

## 1. Prerequisites

> ⚠️ You do not need a single `kit` package install to follow this guide — each case study directory is self-contained with its own dependencies.

### Shared (all demos)

| Requirement | Version | Notes |
|---|---|---|
| `uv` | latest | Required for Python demo + script runs |
| Node.js | >= 18 | Ships with `npx`; required for TypeScript demo + script runs |
| `kit` repo | latest | Contains `demo/opencode/` and `demo/scripts/` |

### Python demo only

| Requirement | Version | Purpose |
|---|---|---|
| Python | 3.12+ | Runtime for `find_bad_style.py`, `generate_report.py`, `example-clean-script.py` |
| `radon` | latest | Cyclomatic complexity analysis (`uv pip install radon`) |
| `mypy` | latest | Strict type checking (`uv pip install mypy`) |
| `ruff` | latest | Lint enforcement (`uv pip install ruff`) |

### TypeScript demo only

| Requirement | Version | Notes |
|---|---|---|
| TypeScript | ^5.9 | `npm install typescript` (local devDependency) or global |
| `tsx` | latest | `npm install tsx` (local) or `npm install -g tsx` |
| ESLint + `@typescript-eslint` | latest | Enforced via `clean_ts` / `eslint.config.ts` |
| `clean_ts` plugin | installed | See `plugins/typescript/` — the gate that intercepts `.ts` writes |

---

## 2. Python Demo (clean_python anti-slop)

This is the canonical case study. A subagent was given the prompt in `case_generate.md`:

> Write a python script `generate_report.py` that reads JSON test logs from a directory, calculates statistics, and outputs a formatted Markdown summary report.

The subagent **must** route every `.py` file through the `clean_python` tool (`verify_and_commit_code`), which enforces:

| Gate | Enforced By | Threshold |
|---|---|---|
| Cyclomatic complexity | Radon CC | < 6 |
| Strict type checking | MyPy `--strict` | `--disallow-untyped-defs`, `--no-implicit-optional` |
| AST anti-slop | `find_bad_style.py` AST policy | No bare `except:` or `except Exception: pass` |
| Lint | Ruff (E/F/W) | Clean imports, modern Python |

### Inspect the evidence

```bash
cd demo/opencode/python
ls case_generate.md find_bad_style.py find_cc_nested.py generate_report.py
```

- `case_generate.md` — the case specification with 4-problem rationale.
- `find_bad_style.py` — AST scanner for mutable defaults, missing type hints, and unsafe `open()`.
- `find_cc_nested.py` — Radon cyclomatic complexity checker.
- `generate_report.py` — the clean output that passed every gate.
- `test_daily_pillar.py` — pytest suite covering cross-year pillar resolution (Dec → Jan edge cases).
- `find_hallucinations.py` / `find_hallucinations_slop.py` — paired LLM-output validators (clean vs slop).

### Verify the output

```bash
cd demo/opencode/python

# AST + style violations — should report ZERO
uv run python find_bad_style.py generate_report.py

# Cyclomatic complexity — should report NO functions >= 6
uv run python find_cc_nested.py --min-cc 6 generate_report.py

# Run the test suite
uv run pytest test_daily_pillar.py -v
```

---

## 3. TypeScript Demo (clean_ts anti-slop)

This case study mirrors the Python scenario. A subagent is given the prompt in `case_generate.md`:

> Write a TypeScript script `generate_report.ts` that reads JSON test logs from a directory, calculates statistics (total tests, pass/fail counts, average execution time, and error distribution), and outputs a formatted Markdown summary report. Make sure it includes robust error handling and CLI argument parsing.

The subagent **must** route every `.ts` file through the `clean_ts` tool (`verify_and_commit_code`), which enforces:

| Gate | Enforced By | Threshold |
|---|---|---|
| Cyclomatic complexity | `ts/complexity` rule | < 6 (configured as `[[2, 5]]`) |
| Strict type checking | `tsc --strict` | `--noImplicitAny`, `--strictNullChecks` |
| AST anti-slop | `no-empty` + `no-useless-catch` | No empty/comment-only catch bodies |
| ESLint | `eslint:recommended` + `@typescript-eslint/recommended` strict | `no-explicit-any`, `explicit-function-return-type`, `no-unused-vars` |

### Inspect the evidence

```bash
cd demo/opencode/typescript
ls case_generate.md find_bad_style.ts tsconfig.json
```

- `case_generate.md` — the case specification with 4-problem rationale.
- `find_bad_style.ts` — TS scanner for high CC, swallowed catch, missing types, and ESLint violations.
- `tsconfig.json` — strict TypeScript compiler configuration.

### Verify the output

```bash
cd demo/opencode/typescript

# Install deps (once)
npm install

# AST + CC + style violations — should report ZERO
npx tsx find_bad_style.ts find_bad_style.ts

# Strict type checking
npx tsc --strict --noEmit find_bad_style.ts

# Lint (if eslint is configured)
npx eslint find_bad_style.ts
```

---

## 4. Example Scripts (`scripts/`)

The `scripts/` directory contains:

- `01-install-plugins.md` — step-by-step plugin installation walkthrough (`remind-workflow`, `clean_python`, `clean_ts`).
- `example-clean-script.py` — Python word-frequency analyzer that passes all quality gates.
- `example-clean-script.ts` — TypeScript mirror of the same, passing `tsc --strict` + ESLint.

### Run them

```bash
cd demo/scripts

# Python example
uv run python example-clean-script.py README.md

# TypeScript example
npx tsx example-clean-script.ts README.md
```

---

## 5. Re-running the Scanners

### Scanning an arbitrary Python file

```bash
cd demo/opencode/python
uv run python find_bad_style.py <file>
```

### Scanning an arbitrary TypeScript file

```bash
cd demo/opencode/typescript
npx tsx find_bad_style.ts <file>
```

### Checking cyclomatic complexity of any Python file

```bash
cd demo/opencode/python
uv run python find_cc_nested.py --min-cc 6 <file>
```

---

## 6. Environment Variables

| Variable | Default | Scope | Description |
|---|---|---|---|
| `DISABLE_CLEAN_PYTHON` | (unset) | Python | Set to `true` to bypass `clean_python` linter verification |
| `DISABLE_CLEAN_TS` | (unset) | TypeScript | Set to `true` to bypass `clean_ts` linter verification |
| `KIT_API_KEY` | (unset) | Both | Optional — only needed if an LLM-audit tier is enabled (e.g. `find_hallucinations.py`) |
| `KIT_BASE_URL` | (unset) | Both | Optional — LLM endpoint for hallucination verification |
| `KIT_LIVE` | `false` | Both | Offline mode; set to `true` only when an LLM tier is configured |

---

## 7. Cache Management

| Cache Directory | Contents | Safe to delete? |
|---|---|---|
| `demo/opencode/python/.mypy_cache/` | MyPy type-checking results | Yes — regenerates on each run |
| `demo/opencode/python/.ruff_cache/` | Ruff lint scan results | Yes — regenerates on each run |

```bash
rm -rf demo/opencode/python/.mypy_cache demo/opencode/python/.ruff_cache
```

---

## 8. Related Resources

| Resource | Scope |
|---|---|
| [README.md](./README.md) | Overview of all demos, quality gates, and directory layout |
| [FAQ.md](./FAQ.md) | Troubleshooting, cost questions, and parity comparison |
| `demo/opencode/python/case_generate.md` | Python case specification with 4-problem rationale |
| `demo/opencode/typescript/case_generate.md` | TypeScript case specification with 4-problem rationale |
| `demo/scripts/01-install-plugins.md` | Plugin installation walkthrough |
| `demo/scripts/example-clean-script.py` | Python example: passes all quality gates |
| `demo/scripts/example-clean-script.ts` | TypeScript example: passes all quality gates |
| [`plugins/python/clean_python/`](../../plugins/python/clean_python/) | The `clean_python` quality gate source |
| [`plugins/typescript/clean_ts/`](../../plugins/typescript/clean_ts/) | The `clean_ts` quality gate source |
| [Hygiene README](../../hygiene/README.md) | Architecture and overview of the `kit-hygiene` static + LLM audit pipeline |
