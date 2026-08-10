# ❓ Demo FAQ (`opencode/`)

---

### Q1: Why is this separate from the toolkit?

The `opencode/` directory is intentionally isolated from the live `hygiene/` and `plugins/` code paths. It is a **case study**, not a feature — its job is to prove that the quality gates work, not to be imported by production tooling. Keeping it separate means demos can be cloned, broken, and rerun without risking drift in the core kit.

---

### Q2: Do I need an API key?

No. Both demos' static checkers (`find_bad_style.py`, `find_bad_style.ts`) and compiler type-checks (`mypy --strict`, `tsc --strict`) run fully offline — they are pure AST and static analysis. No API key, no internet connection required.

The Python demo includes LLM-audit tools (`find_hallucinations.py`) that require `KIT_API_KEY` for parity, but the TypeScript demo's static checker is self-contained. If a future LLM-audit tier is added to the TypeScript demo (mirroring the Python `find_hallucinations.py`), it would use the same `KIT_API_KEY` + `KIT_BASE_URL` environment variables.

---

### Q3: How do I add a new language demo?

1. Create `demo/opencode/<language>/` mirroring the `demo/opencode/python/` layout (case spec, scanner script, clean output).
2. The new language must have the same 4 anti-slop gates enforced: CC < 6, strict type annotations, AST-policy no-slip (`except:` / empty `catch` rejections), and lint clean.
3. Add a table row to [README.md](./README.md) and a `## N. <Language> Demo` section to [GUIDE.md](./GUIDE.md).

---

### Q4: How does `clean_python` prevent slop?

`clean_python` enforces four anti-slop guarantees that standard LLMs routinely violate without a gate:

1. **Monolithic Function Trap (CC ≥ 6)** — LLMs naturally merge CLI parsing, file scanning, JSON parsing, aggregation, and formatting into one `main()` (CC 8–14). `clean_python` rejects any function with Radon CC ≥ 6, forcing the model to extract modular helpers on the first try.

2. **Slop Error Handling (broad exception catching)** — Prompts for "robust error handling" trigger `except:` and `except Exception: pass` blocks. AST policies forbid swallowing broad exceptions without handling or re-raising.

3. **Missing or Loose Type Annotations (MyPy Failure)** — Parsing dynamic JSON requires `dict[str, Any]`, `Path`, `list[str]`, and `isinstance()` guard checks. Strict MyPy rejects bare `dict` or omitted return types, which most models skip unless forced.

4. **remind-workflow Memory Persistence** — The `remind-workflow` plugin keeps the `clean_python` requirement injected on every turn, preventing tool drift where an agent switches to a raw `write` call mid-task.

See [case_generate.md](./python/case_generate.md) for the full rationale.

---

### Q5: How does `clean_ts` prevent slop?

`clean_ts` enforces four anti-slop guarantees tailored to the TypeScript ecosystem:

1. **Monolithic Function Trap (CC ≥ 6)** — LLMs naturally merge CLI parsing, directory scanning, JSON parsing, aggregation, and Markdown formatting into one `main()` function, resulting in Cyclomatic Complexity **CC = 8–14**. `clean_ts` enforces `ts/complexity [[2, 5]]` (threshold < 6), rejecting any function that exceeds it and forcing the model to extract modular helpers on the first try.

2. **Slop Error Handling (swallowed catch blocks)** — Prompts for "robust error handling" trigger `try { … } catch (e) {}` with empty or comment-only bodies. The AST policy check runs `no-empty` + `no-useless-catch` via the TypeScript compiler API, detecting catch clauses with no handling or logging and rejecting them before the file reaches disk.

3. **Missing or Loose Type Annotations (TSC strict failure)** — Parsing dynamic JSON requires explicit types like `Record<string, unknown>`, `string[]`, `number`, and `typeof` guard checks (`if (typeof x !== "number")`). `tsc --strict` + `@typescript-eslint/recommended` strict rejects bare `any` or omitted return types (`--noImplicitAny`, `explicit-function-return-type`), which most models skip unless forced.

4. **remind-workflow Memory Persistence** — The `remind-workflow` plugin keeps the `clean_ts` requirement in active memory on every turn, preventing tool drift where an agent switches to a raw `write` or `edit` call mid-task. The `DISABLE_CLEAN_TS=true` bypass flag mirrors `DISABLE_CLEAN_PYTHON` for controlled opt-out.

See [case_generate.md](./typescript/case_generate.md) for the full rationale.

---

### Q6: What is the token cost of running these demos?

| Component | Token Cost |
|---|---|
| Python: Tier 1 (AST + Ruff + MyPy + Radon) | **0 tokens** (local, offline) |
| Python: Tier 2 (LLM snippet verification via `find_hallucinations.py`) | ~10–40 tokens per candidate |
| TypeScript: Tier 1 (AST + ESLint + TSC) | **0 tokens** (local, offline) |
| TypeScript: Tier 2 (planned LLM-audit parity) | ~10–40 tokens per candidate |

Both demos run unlimited static scans at zero cost; only the optional LLM tier incurs token budget. See [GUIDE.md](./GUIDE.md) for environment variable configuration.

---

### Q7: How do the Python and TypeScript demos compare?

| Aspect | Python Demo | TypeScript Demo |
|---|---|---|
| Quality gate | `clean_python` | `clean_ts` |
| CC enforcement | Radon CC < 6 | `ts/complexity [[2, 5]]` |
| Type enforcement | MyPy `--strict` | `tsc --strict` |
| Lint | Ruff (E/F/W) | ESLint `recommended` + `@typescript-eslint/recommended` strict |
| AST anti-slop | Bare `except:` / `except Exception: pass` | Empty/comment-only `catch` blocks (`no-empty`, `no-useless-catch`) |
| Bypass flag | `DISABLE_CLEAN_PYTHON` | `DISABLE_CLEAN_TS` |
| Static cost | 0 tokens / offline | 0 tokens / offline |
| LLM audit tier | `find_hallucinations.py` | Planned (parity with Python) |

Both demos use the same 4-problem anti-slop structure applied to their respective language ecosystems.
