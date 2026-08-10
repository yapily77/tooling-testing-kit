# 🧭 Demo Setup Guide (`opencode/`)

> **Complete guide to installing, configuring, and executing the Python and TypeScript anti-slop case studies.**

---

## 1. Prerequisites

### Shared (both demos)

| Requirement | Version | Notes |
|---|---|---|
| `kit` repo cloned | latest | Contains `opencode/python/` and `opencode/typescript/` |
| `uv` | latest | Required for Python demo runs |
| Node.js | >= 18 | Ships with `npx`; required for TypeScript demo runs |

### Python demo only

| Requirement | Version | Purpose |
|---|---|---|
| Python | 3.14+ | Runtime for `find_bad_style.py` |
| `uv` | latest | Dependency + package management |

### TypeScript demo only

| Requirement | Version | Notes |
|---|---|---|
| TypeScript | ^5.9 | `npm install typescript` (local devDependency) or global |
| `tsx` | latest | `npm install tsx` (local) or `npm install -g tsx` |
| ESLint + `@typescript-eslint` | latest | Enforced via `clean_ts` / `eslint.config.ts` |
| `clean_ts` | built | See `plugins/typescript/clean_ts/` — the gate that intercepts `.ts` writes |

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

- `case_generate.md` — the case specification with rationale.
- `find_bad_style.py` — AST scanner for mutable defaults, missing type hints, unsafe `open()`.
- `find_cc_nested.py` — Radon cyclomatic complexity checker.
- `generate_report.py` — the clean output that passed every gate.

### Verify the output

```bash
cd demo/opencode/python
uv run python find_bad_style.py generate_report.py
uv run python find_cc_nested.py --min-cc 6 generate_report.py
```

Both commands should report **no violations**.

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

- `case_generate.md` — the case specification with rationale.
- `find_bad_style.ts` — TS scanner for high CC, swallowed catch, missing types, and ESLint violations.

### Verify the output

```bash
cd demo/opencode/typescript

# AST + CC + style violations
npx tsx find_bad_style.ts find_bad_style.ts

# Strict type checking
npx tsc --strict --noEmit find_bad_style.ts
```

Both commands should report **no violations** once `find_bad_style.ts` is produced and accepted by `clean_ts`.

---

## 4. Re-running the Case Studies

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

---

## 5. Environment Variables

| Variable | Default | Scope | Description |
|---|---|---|---|
| `DISABLE_CLEAN_PYTHON` | (unset) | Python | Set to `true` to bypass `clean_python` linter verification |
| `DISABLE_CLEAN_TS` | (unset) | TypeScript | Set to `true` to bypass `clean_ts` linter verification |
| `KIT_API_KEY` | (unset) | Both | Optional — only needed if a future LLM-audit tier is enabled |
| `KIT_BASE_URL` | (unset) | Both | Optional — LLM endpoint for hallucination verification |
| `KIT_LIVE` | `false` | Both | Offline mode; set to `true` only when an LLM tier is configured |

---

## 6. Related Resources

| Resource | Scope |
|---|---|
| [README.md](./README.md) | Overview of both Python and TypeScript demos |
| [FAQ.md](./FAQ.md) | Troubleshooting, cost, and extension questions |
| [`case_generate.md`](./python/case_generate.md) | Python case specification and 4-problem rationale |
| [`case_generate.md`](./typescript/case_generate.md) | TypeScript case specification and 4-problem rationale |
| [`plugins/python/clean_python/`](../../plugins/python/clean_python/) | The `clean_python` quality gate source |
| [`plugins/typescript/clean_ts/`](../../plugins/typescript/clean_ts/) | The `clean_ts` quality gate source |
