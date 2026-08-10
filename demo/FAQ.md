# 🧰 Demo FAQ — Python, TypeScript & Scripts

![Python](https://img.shields.io/badge/python-3.12+-blue?logo=python)
![TypeScript](https://img.shields.io/badge/typescript-5.9+-blue?logo=typescript)
![License](https://img.shields.io/badge/license-MIT-green)

> Answers to the questions developers actually ask when running the `demo/` case studies — *why is demo separate from tests?* *what's with two hallucination finders?* *do I need an API key?*

---

### Q1: Why is `demo/` a separate top-level directory instead of living in `tests/`?

**A:** `demo/` contains **self-contained, runnable scripts** — not pytest test cases. The files here are **case studies** that demonstrate the `clean_python` and `clean_ts` quality gates in action. They're executable utilities (e.g. `find_bad_style.py`, `find_bad_style.ts`, `generate_report.py`) and verification scripts (e.g. `find_hallucinations.py`), not test fixtures. Keeping them separate from `tests/` avoids polluting the pytest collection and makes the anti-slop demonstration portable and cloneable.

---

### Q2: Do I need an API key?

**A:** **No** for static analysis. All scanners (`find_bad_style.py`, `find_bad_style.ts`) and compiler type-checks (`mypy --strict`, `tsc --strict`) run fully offline — pure AST and static analysis. No API key, no internet required.

The Python demo includes `find_hallucinations.py` which optionally uses `KIT_API_KEY` for LLM-based parity verification, but the TypeScript demo's static checker is self-contained. If a future LLM-audit tier is added to the TypeScript demo (mirroring the Python `find_hallucinations.py`), it would use the same `KIT_API_KEY` + `KIT_BASE_URL` environment variables.

---

### Q3: What's the difference between `find_hallucinations.py` and `find_hallucinations_slop.py`?

**A:** They're a **paired comparison**:

| File | Style | Purpose |
|---|---|---|
| `find_hallucinations.py` (clean) | Fully typed, modular, no bare excepts | The **correct** version — passes `clean_python` |
| `find_hallucinations_slop.py` (slop) | Loose `dict` types, untyped helpers, monolithic `main()` | The **negative example** — would be rejected by `clean_python` |

The slop version has a single ~40-line `main()` (CC ≈ 12) and uses untyped `dict`/`list` returns. If you run both through `radon cc` and `mypy --strict`, the slop version fails every gate while the clean version passes. This pair demonstrates what `clean_python` prevents.

---

### Q4: What quality gates does `clean_python` enforce?

**A:** Five gates, all verified before code reaches disk:

| Gate | Tool | Rule |
|---|---|---|
| Cyclomatic complexity | `radon` | All functions must have CC < 6 |
| Type safety | `mypy --strict` | Full type annotations (`dict[str, Any]`, `Path`, `list[str]`, return types) |
| AST anti-slop | custom AST pass | No bare `except:` or `except Exception: pass` (swallowed exceptions) |
| Lint | `ruff` (E/F/W) | Clean imports, modern Python standards |
| Tool enforcement | `remind-workflow` plugin | Injects `clean_python` requirement on every turn to prevent tool drift |

`generate_report.py` was generated to pass all gates. Its `main()` is split into `_parse_args()`, `_collect_stats()`, `_format_report()` — each with CC ≤ 4 and full type annotations.

---

### Q5: What quality gates does `clean_ts` enforce?

**A:** Five gates tailored to the TypeScript ecosystem:

| Gate | Tool | Rule |
|---|---|---|
| Cyclomatic complexity | `ts/complexity` | All functions must have CC < 6 (configured as `[[2, 5]]`) |
| Type safety | `tsc --strict` | `--noImplicitAny`, `--strictNullChecks`, explicit return types |
| AST anti-slop | `no-empty` + `no-useless-catch` | No empty/comment-only catch bodies |
| Lint | ESLint `recommended` + `@typescript-eslint/recommended` strict | `no-explicit-any`, `no-unused-vars` |
| Tool enforcement | `remind-workflow` plugin | Injects `clean_ts` requirement on every turn to prevent tool drift |

The `DISABLE_CLEAN_TS=true` bypass flag mirrors `DISABLE_CLEAN_PYTHON` for controlled opt-out.

---

### Q6: Can I run the case studies as tests?

**A:** `test_daily_pillar.py` is a **pytest** file — run it with:

```bash
uv run pytest demo/opencode/python/test_daily_pillar.py -v
```

The other `.py` files (`find_bad_style.py`, `find_cc_nested.py`, `generate_report.py`) are **CLI scripts** with `--help` output. They're not test cases but verification utilities you can invoke directly.

---

### Q7: What does CC < 6 mean and why is it important?

**A:** **Cyclomatic Complexity (CC)** measures the number of linearly independent paths through a function. CC = 1 for a straight-line function; each `if`, `for`, `while`, `and`, `or` adds 1.

| CC | Assessment |
|---|---|
| 1–5 | Excellent — easy to test and reason about |
| 6–10 | Acceptable but should be reviewed |
| 11+ | High — difficult to test, refactor needed |

The **CC < 6** threshold (enforced by both `clean_python` and `clean_ts`) forces functions to be small and focused. A typical LLM-generated `main()` with nested loops and conditionals hits CC = 8–14. The case studies demonstrate breaking this into modular helpers, each CC ≤ 4.

---

### Q8: Why does `test_daily_pillar.py` test year-boundary crossings?

**A:** Solar-lunar calendar computation has a notorious edge case: when a Gregorian date falls between January 1–5 (before the solar new year begins on ~Feb 4), the "month anchor" must fall back to the **previous** solar year. Without this fallback, pillar resolution crashes or returns `None`.

The test suite covers:

- Dec 30–31 → Jan 1–5 (cross-year continuity)
- Single-date ranges
- Same-year ranges (sanity check)
- Invalid ranges (end < start → `ValueError`)
- Jan 1 specifically (the trickiest case)

---

### Q9: How does `clean_python` prevent slop? (4-problem summary)

**A:** The `remind-workflow` plugin + `clean_python` tool intercept every `.py` write. Standard LLMs violate four anti-slop rules unless the gate forces compliance:

1. **Monolithic Function Trap (CC ≥ 6)** — LLMs merge CLI parsing, file scanning, JSON parsing, aggregation, and formatting into one `main()` (CC = 8–14). `clean_python` rejects any function with Radon CC ≥ 6, forcing modular helpers on the first try.

2. **Slop Error Handling (broad exception catching)** — Prompts for "robust error handling" trigger `except:` and `except Exception: pass` blocks. AST policies forbid swallowing broad exceptions without handling or re-raising.

3. **Missing or Loose Type Annotations (MyPy Failure)** — Parsing dynamic JSON requires `dict[str, Any]`, `Path`, `list[str]`, and `isinstance()` guard checks. Strict MyPy rejects bare `dict` or omitted return types.

4. **remind-workflow Memory Persistence** — The `remind-workflow` plugin keeps the `clean_python` requirement injected on every turn, preventing tool drift where an agent switches to a raw `write` call mid-task.

See `demo/opencode/python/case_generate.md` for the full rationale.

---

### Q10: How does `clean_ts` prevent slop? (4-problem summary)

**A:** The `remind-workflow` plugin + `clean_ts` tool intercept every `.ts` write. Standard LLMs violate four anti-slop rules unless the gate forces compliance:

1. **Monolithic Function Trap (CC ≥ 6)** — LLMs merge CLI parsing, directory scanning, JSON parsing, aggregation, and Markdown formatting into one `main()` (CC = 8–14). `clean_ts` enforces `ts/complexity [[2, 5]]` (threshold < 6), rejecting any function that exceeds it.

2. **Slop Error Handling (swallowed catch blocks)** — Prompts for "robust error handling" trigger `try { … } catch (e) {}` with empty or comment-only bodies. The AST policy (`no-empty` + `no-useless-catch` via the TypeScript compiler API) detects and rejects these before the file reaches disk.

3. **Missing or Loose Type Annotations (TSC strict failure)** — Parsing dynamic JSON requires explicit types like `Record<string, unknown>`, `string[]`, and `typeof` guard checks. `tsc --strict` + `@typescript-eslint/recommended` strict rejects bare `any` or omitted return types.

4. **remind-workflow Memory Persistence** — The plugin keeps the `clean_ts` requirement in active memory on every turn, preventing tool drift where an agent switches to a raw `write` or `edit` call.

See `demo/opencode/typescript/case_generate.md` for the full rationale.

---

### Q11: How do the Python and TypeScript demos compare?

**A:** Both demos use the same 4-problem anti-slop structure applied to their respective language ecosystems.

| Aspect | Python Demo | TypeScript Demo |
|---|---|---|
| Quality gate | `clean_python` | `clean_ts` |
| CC enforcement | Radon CC < 6 | `ts/complexity` [[2, 5]] |
| Type enforcement | MyPy `--strict` | `tsc --strict` |
| Lint | Ruff (E/F/W) | ESLint `recommended` + `@typescript-eslint/recommended` strict |
| AST anti-slop | Bare `except:` / `except Exception: pass` | Empty/comment-only `catch` blocks (`no-empty`, `no-useless-catch`) |
| Bypass flag | `DISABLE_CLEAN_PYTHON` | `DISABLE_CLEAN_TS` |
| Static cost | 0 tokens / offline | 0 tokens / offline |
| LLM audit tier | `find_hallucinations.py` | Planned (parity with Python) |
| Test suite | `test_daily_pillar.py` (pytest) | N/A — static checker is self-contained |

---

### Q12: What is the token cost of running these demos?

**A:**

| Component | Token Cost |
|---|---|
| Python: Tier 1 (AST + Ruff + MyPy + Radon) | **0 tokens** (local, offline) |
| Python: Tier 2 (LLM snippet verification via `find_hallucinations.py`) | ~10–40 tokens per candidate |
| TypeScript: Tier 1 (AST + ESLint + TSC) | **0 tokens** (local, offline) |
| TypeScript: Tier 2 (planned LLM-audit parity) | ~10–40 tokens per candidate (planned) |

Both demos run unlimited static scans at zero cost; only the optional LLM tier incurs token budget.

---

### Q13: What happened to the original `box/` directory?

**A:** It was renamed to `demo/opencode/` to better reflect its purpose — these are **demonstration case studies**, not a generic "box" of files. The doc files (`README.md`, `GUIDE.md`, `FAQ.md`) at the `demo/` level were added to follow the same `README → GUIDE → FAQ` convention used in `hygiene/` and `tools/`.

---

### Q14: I see `.mypy_cache` and `.ruff_cache` — are these committed to git?

**A:** No, they're listed in `.gitignore`. They're local analysis caches that speed up repeated scanning. Safe to delete:

```bash
rm -rf demo/opencode/python/.mypy_cache demo/opencode/python/.ruff_cache
```

---

### Q15: How do I add a new case study file?

**A:**

1. Write your script following the `clean_python` or `clean_ts` rules (CC < 6, full type annotations, no swallowed exceptions, ruff/eslint-clean).
2. Add a row to the table in [README.md](./README.md).
3. Update the relevant section in [GUIDE.md](./GUIDE.md) if it has a unique CLI interface.
4. **Never** use raw `write`/`edit` for `.py` or `.ts` files — use the `clean_python` / `clean_ts` plugin (or the `clean_py` CLI tool).

```bash
# Example: verify a Python file passes all gates
uv run ruff check demo/opencode/python/my_new_file.py
uv run mypy --strict demo/opencode/python/my_new_file.py
uv run python -m radon cc demo/opencode/python/my_new_file.py
```

---

### Q16: Can I add a new language demo?

**A:** Yes. Follow these steps:

1. Create `demo/opencode/<language>/` mirroring the `demo/opencode/python/` layout (case spec, scanner script, clean output).
2. The new language must enforce the same 4 anti-slop gates: CC < 6, strict type annotations, AST-policy no-slip (no bare `except:` / empty `catch` rejections), and lint clean.
3. Add a table row to [README.md](./README.md) and a new section to [GUIDE.md](./GUIDE.md).
4. Follow the `case_generate.md` template from the Python or TypeScript demo.

---

## Related Documentation

| Doc | Scope |
|---|---|
| [README.md](./README.md) | Overview, file index, directory structure, and quality gate summary |
| [GUIDE.md](./GUIDE.md) | Full setup, file inspection, and verification steps |
