# 📚 Demo Case Studies (`opencode/`)

> **Reproducible case studies proving `clean_python` + `clean_ts` quality gates reject monolithic, loosely-typed, and slop-handling code in favor of modular, strictly-typed, policy-compliant output.**

This directory contains language-specific case studies under `opencode/python/` and `opencode/typescript/`. Each demo is a self-contained scenario: a single natural-language prompt fed to a subagent that must produce code passing AST anti-slop checks, strict type checking (MyPy / TSC), linters (Ruff / ESLint), and cyclomatic complexity < 6. The results are captured here as evidence.

---

## Included Demos

| Demo | Language | Proof Target | Quick Run |
|---|---|---|---|
| Python anti-slop case study | Python | `clean_python` intercepts monolithic functions (CC ≥ 6), loose typing, and swallowed exceptions | `cd demo/opencode/python && uv run python find_bad_style.py generate_report.py` |
| TypeScript anti-slop case study | TypeScript | `clean_ts` intercepts monolithic functions (`ts/complexity < 6`), loose typing, and swallowed catch blocks | `cd demo/opencode/typescript && npx tsx find_bad_style.ts find_bad_style.ts` |

---

## Directory Layout

```
demo/opencode/
├── README.md             # This file — overview of both demos
├── GUIDE.md              # Step-by-step setup + execution for both languages
├── FAQ.md                # Troubleshooting + cost + extension questions
├── python/               # Python anti-slop case study (clean_python)
│   ├── case_generate.md  # Case specification with rationale
│   ├── find_bad_style.py # AST scanner for mutable defaults, missing types, unsafe open()
│   ├── find_cc_nested.py # Radon cyclomatic complexity checker
│   ├── generate_report.py# Clean output that passed every gate
│   └── ...               # Hallucination detectors, test_daily_pillar.py
└── typescript/           # TypeScript anti-slop case study (clean_ts)
    ├── case_generate.md  # Case specification with rationale
    ├── find_bad_style.ts # Anti-slop & style checker (CC, swallowed catch, ESLint)
    ├── generate_report.ts# Clean output (generated on demand)
    ├── tsconfig.json     # Strict TypeScript configuration
    └── ...               # VSCode workspace pointer, CC checker stub
```

---

## Quick Execution

### Python Demo

```bash
cd demo/opencode/python
uv run python find_bad_style.py generate_report.py
uv run python find_cc_nested.py --min-cc 6 generate_report.py
```

The scanner reports zero violations — `generate_report.py` was produced by a subagent that could only write code if `clean_python` accepted it (CC < 6, full type annotations, no bare `except:`).

### TypeScript Demo

```bash
cd demo/opencode/typescript
npm install
npx tsx find_bad_style.ts find_bad_style.ts
npx tsc --strict --noEmit find_bad_style.ts
```

---

## Related Documentation

| Doc | Scope |
|---|---|
| [`GUIDE.md`](./GUIDE.md) | Full setup, file inspection, verification steps, env var tables for both Python and TypeScript |
| [`FAQ.md`](./FAQ.md) | Why separate, API key needs, adding JS demos, and how `clean_python` / `clean_ts` prevent slop |
| [Hygiene README](../../hygiene/README.md) | Architecture and overview of the `kit-hygiene` static + LLM audit pipeline |
