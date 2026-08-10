# FAQ — Demo / Case Study Suite

> Answers to the questions developers actually ask when running the `demo/opencode/` case studies — *why is demo separate from tests?* *what's with the two hallucination finders?* *do I need an API key?*

---

## Q1: Why is `demo/` a separate top-level directory instead of living in `tests/`?

**A:** `demo/` contains **self-contained, runnable scripts** — not pytest test cases. The files here are **case studies** that demonstrate the `clean_python` quality gates in action. They're executable utilities (`find_cc_nested.py`, `generate_report.py`) and verification scripts (`find_hallucinations.py`), not test fixtures. Keeping them separate from `tests/` avoids polluting the test collection and makes the anti-slop demonstration portable.

---

## Q2: What's the difference between `find_hallucinations.py` and `find_hallucinations_slop.py`?

**A:** They're a **paired comparison**:

| File | Style | Purpose |
|---|---|---|
| `find_hallucinations.py` (clean) | Fully typed, modular, no bare excepts | The **correct** version — passes clean_python |
| `find_hallucinations_slop.py` (slop) | Loose `dict` types, untyped helpers, monolithic `main()` | The **negative example** — would be rejected by clean_python |

The slop version has a single 40-line `main()` (CC ≈ 12) and uses untyped `dict`/`list` returns. If you run both through `radon cc` and `mypy --strict`, the slop version fails every gate while the clean version passes. This pair demonstrates what `clean_python` prevents.

---

## Q3: Do I need an API key to run the case studies?

**A:** **No.** All scripts in `demo/opencode/python/` run **100% offline**. They use only the Python standard library (`ast`, `argparse`, `pathlib`, `sys`) plus `radon` for cyclomatic complexity analysis. No LLM, no API key, no internet required.

The case studies are designed to be cloned and run immediately:

```bash
cd demo/opencode/python
uv run find_cc_nested.py --min-cc 6 find_bad_style.py
```

---

## Q4: What quality gates does `clean_python` enforce?

**A:** Four gates, all verified before code reaches disk:

| Gate | Tool | Rule |
|---|---|---|
| Cyclomatic Complexity | `radon` | All functions must have CC < 6 |
| Type Safety | `mypy --strict` | Full type annotations (`dict[str, Any]`, `Path`, `list[str]`, return types) |
| AST Anti-Slop | custom AST pass | No bare `except:` or `except Exception: pass` (swallowed exceptions) |
| Lint | `ruff` | Clean imports, modern Python standards (no unused vars, correct formatting) |

`generate_report.py` was generated to pass all four. Its `main()` function is split into `_parse_args()`, `_collect_stats()`, `_format_report()` — each with CC ≤ 4 and full type annotations.

---

## Q5: Can I run the case studies as tests?

**A:** `test_daily_pillar.py` is a **pytest** file — run it with:

```bash
uv run pytest demo/opencode/python/test_daily_pillar.py -v
```

The other `.py` files (`find_bad_style.py`, `find_cc_nested.py`, etc.) are **CLI scripts** with `--help` output. They're not test cases but verification utilities you can invoke directly.

---

## Q6: What does CC < 6 mean and why is it important?

**A:** **Cyclomatic Complexity (CC)** measures the number of linearly independent paths through a function. CC = 1 for a straight-line function; each `if`, `for`, `while`, `and`, `or` adds 1.

| CC | Assessment |
|---|---|
| 1–5 | Excellent — easy to test and reason about |
| 6–10 | Acceptable but should be reviewed |
| 11+ | High — difficult to test, refactor needed |

The **CC < 6** threshold (enforced by `clean_python`) forces functions to be small and focused. A typical LLM-generated `main()` with nested loops and conditionals hits CC = 8–14. The `generate_report.py` case study demonstrates breaking this into 4 functions, each CC ≤ 4.

---

## Q7: Why does `test_daily_pillar.py` test year-boundary crossings?

**A:** Solar-lunar calendar computation has a notorious edge case: when a Gregorian date falls between January 1–5 (before the solar new year begins on ~Feb 4), the "month anchor" must fall back to the **previous** solar year. Without this fallback, pillar resolution crashes or returns `None`.

The test suite covers:

- Dec 30–31 → Jan 1–5 (cross-year continuity)
- Single-date ranges
- Same-year ranges (sanity check)
- Invalid ranges (end < start → `ValueError`)
- Jan 1 specifically (the trickiest case)

---

## Q8: How do I add a new case study file?

**A:**

1. Write your script following the clean_python rules (CC < 6, full type annotations, no swallowed exceptions, ruff-clean)
2. Add a line to the file table in `README.md`
3. Update `GUIDE.md` §2 if it has a unique CLI interface
4. Never use raw `write`/`edit` for `.py` files — use the `clean_python` plugin

```bash
# Example: verify your file passes all gates
.venv/bin/ruff check demo/opencode/python/my_new_file.py
.venv/bin/mypy --strict demo/opencode/python/my_new_file.py
.venv/bin/python -m radon cc demo/opencode/python/my_new_file.py
```

---

## Q9: What happened to the original `box/` directory?

**A:** It was renamed to `demo/opencode/` to better reflect its purpose — these are **demonstration case studies**, not a generic "box" of files. The 3 doc files (`README.md`, `GUIDE.md`, `FAQ.md`) were added to `demo/` following the same `README → GUIDE → FAQ` convention used in `hygiene/` and `examples/`.

---

## Q10: I see `.mypy_cache` and `.ruff_cache` — are these committed to git?

**A:** No, they're listed in `.gitignore`. They're local analysis caches that speed up repeated scanning. Safe to delete:

```bash
rm -rf demo/opencode/python/.mypy_cache demo/opencode/python/.ruff_cache
```

---

## Related Documentation

- **[README.md](./README.md)** — Overview, file index, and directory structure
- **[GUIDE.md](./GUIDE.md)** — Step-by-step running & configuration guide
