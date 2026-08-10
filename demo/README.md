# 📚 Demo Case Studies (`demo/`)

![Python](https://img.shields.io/badge/python-3.12+-blue?logo=python)
![License](https://img.shields.io/badge/license-MIT-green)

> **Reproducible case studies proving `clean_python` + `clean_ts` quality gates reject monolithic, loosely-typed, and slop-handling code in favor of modular, strictly-typed, policy-compliant output.**

This directory contains self-contained, runnable case studies and example scripts that verify the `clean_python` (Python) and `clean_ts` (TypeScript) quality gates end-to-end. Each language subtree under `opencode/` holds a complete anti-slop case study: a natural-language prompt, a scanner, and clean output that passed every gate. The `scripts/` directory holds install walkthroughs and cross-language example scripts that pass all gates.

---

## Included Cases

| Case | Language | Quality Gate | Proof Target | Quick Run |
|---|---|---|---|---|
| Python anti-slop case study | Python | `clean_python` | `find_bad_style.py` reports zero violations on `generate_report.py` | `cd demo/opencode/python && uv run python find_bad_style.py generate_report.py` |
| TypeScript anti-slop case study | TypeScript | `clean_ts` | `find_bad_style.ts` reports zero violations on itself | `cd demo/opencode/typescript && npx tsx find_bad_style.ts find_bad_style.ts` |
| Plugin installation guide | — | — | `01-install-plugins.md` walks through copying + registering plugins | `cd demo/scripts && open 01-install-plugins.md` |
| Example clean scripts | Python + TypeScript | `clean_python` / `clean_ts` | `example-clean-script.py` and `.ts` pass CC < 6, strict types, no swallowed errors | `cd demo/scripts && uv run python example-clean-script.py README.md` |

---

## Quality Gates Enforced

| Gate | Python (via `clean_python`) | TypeScript (via `clean_ts`) | Threshold |
|---|---|---|---|
| Cyclomatic complexity | Radon CC | `ts/complexity` [[2, 5]] | < 6 |
| Strict type checking | MyPy `--strict` | `tsc --strict` | No implicit any / untyped defs |
| AST anti-slop | No bare `except:` or `except Exception: pass` | No empty/comment-only `catch` blocks (`no-empty`, `no-useless-catch`) | 0 violations |
| Lint | Ruff (E/F/W) | ESLint `recommended` + `@typescript-eslint/recommended` strict (`no-explicit-any`, `no-unused-vars`) | 0 warnings |

---

## Directory Layout

```
demo/
├── README.md                          # This file — overview of all case studies
├── GUIDE.md                           # Step-by-step setup + execution for all demos
├── FAQ.md                             # Troubleshooting + design rationale
├── opencode/                          # Language-specific case studies
│   ├── python/                        # Python anti-slop case study (clean_python)
│   │   ├── case_generate.md           # Prompt spec + 4-problem rationale
│   │   ├── find_bad_style.py          # AST scanner: mutable defaults, missing types, unsafe open()
│   │   ├── find_cc_nested.py          # Radon cyclomatic complexity checker (CC >= 6)
│   │   ├── find_hallucinations.py     # LLM output validator (clean version)
│   │   ├── find_hallucinations_slop.py  # LLM output validator (negative/slop example)
│   │   ├── generate_report.py         # Clean output that passed every gate
│   │   ├── test_daily_pillar.py       # Cross-year pillar resolution tests (pytest)
│   │   ├── kit.code-workspace         # VS Code workspace config
│   │   ├── .mypy_cache/               # MyPy analysis cache (git-ignored)
│   │   └── .ruff_cache/               # Ruff lint cache (git-ignored)
│   └── typescript/                    # TypeScript anti-slop case study (clean_ts)
│       ├── case_generate.md           # Prompt spec + 4-problem rationale
│       ├── find_bad_style.ts          # TS anti-slop & style checker
│       └── tsconfig.json              # Strict TypeScript configuration
└── scripts/                           # Shared install guides + example scripts
    ├── 01-install-plugins.md          # Plugin installation walkthrough
    ├── example-clean-script.py        # Python example: passes all quality gates
    └── example-clean-script.ts        # TypeScript example: passes all quality gates
```

---

## Quick Execution

### Python Demo

```bash
cd demo/opencode/python

# Scan an arbitrary file for anti-slop violations
uv run python find_bad_style.py generate_report.py

# Check cyclomatic complexity (find functions with CC >= 6)
uv run python find_cc_nested.py --min-cc 6 generate_report.py

# Run the pytest test suite
uv run pytest test_daily_pillar.py -v

# Validate LLM-refactored code against the original
uv run python find_hallucinations.py original.py refactored.py
```

### TypeScript Demo

```bash
cd demo/opencode/typescript

# Install deps (once)
npm install

# Run the AST + CC + style scanner
npx tsx find_bad_style.ts find_bad_style.ts

# Strict type checking
npx tsc --strict --noEmit find_bad_style.ts

# Lint (if eslint is configured)
npx eslint find_bad_style.ts
```

### Example Scripts

```bash
cd demo/scripts

# Run the clean Python example (word frequency analyzer)
uv run python example-clean-script.py README.md

# Run the clean TypeScript example
npx tsx example-clean-script.ts README.md
```

---

## Why This Matters

Standard LLMs, when prompted to "write a script with robust error handling," naturally produce:

1. **Monolithic functions** — CC = 8–14 (violates CC < 6)
2. **Bare `except:` blocks** — swallowed exceptions that silently drop data (AST anti-slop violation)
3. **Missing type annotations** — loose `dict` types that MyPy/TSC strict rejects

The `clean_python` and `clean_ts` plugins intercept write payloads **before** they reach disk. If any gate fails, they return exact diagnostics, forcing the model to modularize and annotate correctly **on the first try**. These case studies prove that workflow end-to-end — across both Python and TypeScript.

---

## Related Documentation

| Doc | Scope |
|---|---|
| [GUIDE.md](./GUIDE.md) | Full setup, file inspection, and verification steps for Python, TypeScript, and scripts demos |
| [FAQ.md](./FAQ.md) | Troubleshooting, design rationale, and parity comparison between Python and TypeScript |
| `demo/opencode/python/case_generate.md` | Python case specification with 4-problem rationale |
| `demo/opencode/typescript/case_generate.md` | TypeScript case specification with 4-problem rationale |
| `demo/scripts/01-install-plugins.md` | Plugin installation walkthrough for `remind-workflow`, `clean_python`, and `clean_ts` |
| [Hygiene README](../../hygiene/README.md) | Architecture and overview of the `kit-hygiene` static + LLM audit pipeline |
