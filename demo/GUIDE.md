# 🧭 Demo Guide — Running & Verifying Case Studies

> **Step-by-step. 5 minutes to run your first case study.**

> **Related docs:** `README.md` (overview & file index) · `FAQ.md` (troubleshooting & design rationale)

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | All scripts use `pathlib` and modern type syntax |
| `uv` | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `clean_python` plugin | installed | See root `README.md` for plugin installation |

---

## 2. Running Individual Case Studies

### find_cc_nested.py — Cyclomatic Complexity Scanner

```bash
# Find functions with CC >= 6 (default threshold)
uv run demo/python/find_cc_nested.py --min-cc 6 demo/python/find_bad_style.py

# Show all functions sorted by CC
uv run demo/python/find_cc_nested.py --min-cc 1 demo/python/*.py
```

Scans use `radon.complexity.cc_visit()` to compute cyclomatic complexity. Functions exceeding the threshold are sorted descending and printed in a formatted table.

### find_bad_style.py — Style Violation Scanner

```bash
# Check for mutable defaults, missing type hints, unsafe open()
uv run demo/python/find_bad_style.py --files demo/python/find_cc_nested.py
```

Uses a custom `ast.NodeVisitor` (`GoogleStyleVisitor`) to detect:
- `mutable_defaults` — `def func(x=[])` or `def func(x={})`
- `unsafe_open` — `open()` without `with` context manager
- `missing_type_hints` — function args or return type missing annotations

**Exit code:** `1` if violations found, `0` if clean.

### find_hallucinations.py — LLM Output Validator

```bash
# Compare original vs refactored code for API drift
uv run demo/python/find_hallucinations.py original.py refactored.py
```

Validates LLM-refactored code against the original by checking:
1. **Pydantic field mismatches** — field names/types changed
2. **Invalid imports** — imports that don't resolve or don't exist in original
3. **Suspicious API usage** — `.get()` on non-dict objects (enums, Pydantic models)
4. **Call signature drift** — argument count changed from original
5. **Try/except count** — flags ≥ 3 try blocks (CC bloat pattern)

### generate_report.py — Generated Report Generator

```bash
# Read JSON test logs and produce a Markdown summary
uv run demo/python/generate_report.py --input ./logs/ --output ./report.md
```

Reads JSON log files from a directory, calculates statistics (total tests, pass/fail counts, average execution time, error distribution), and outputs a formatted Markdown summary report.

### test_daily_pillar.py — Cross-Year Pillar Tests

```bash
# Run the full test suite
uv run pytest demo/python/test_daily_pillar.py -v

# Run a specific test class
uv run pytest demo/python/test_daily_pillar.py::TestResolveDailyPillarRange -v
```

Tests `resolve_daily_pillar_range()` and `get_month_anchor_for_date()` for correct behavior across year boundaries (Dec → Jan transitions).

---

## 3. Running with clean_python Plugin

The `clean_python` plugin enforces quality gates before code reaches disk. All `.py` files in `demo/python/` must pass:

- **Radon CC < 6** for every function
- **MyPy strict** type annotations
- **AST anti-slop**: no bare `except:` or `except Exception: pass`
- **Ruff**: clean imports, modern Python standards

```bash
# The plugin intercepts writes automatically when used via OpenCode
# For manual verification:
.venv/bin/ruff check demo/python/*.py
.venv/bin/mypy --strict demo/python/*.py
.venv/bin/python -m radon cc demo/python/*.py
```

---

## 4. Understanding Cache Files

| Cache Directory | Contents |
|---|---|
| `.mypy_cache/` | MyPy type-checking results |
| `.ruff_cache/` | Ruff lint scan results |

These are safe to delete — they regenerate on each run:

```bash
rm -rf demo/python/.mypy_cache demo/python/.ruff_cache
```

---

## 5. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'radon'` | Install deps: `uv pip install radon mypy ruff` |
| `--files` argument rejected | Ensure you're passing actual file paths, not a directory |
| Tests fail with `ImportError` | The test file imports from `kit_python` — ensure the package is installed |
| CC values seem wrong | Check if `radon` is installed in the active virtualenv |

---

## 6. Case Study: case_generate.md

The `case_generate.md` file contains a prompt specification for generating `generate_report.py`. It tests whether the subagent:

1. Uses the `clean_python` tool (not raw `write`/`edit`) for `.py` files
2. Passes all quality gates (CC < 6, MyPy strict, AST anti-slop, Ruff)
3. Produces a working, modular script on the first attempt

Read it to understand the anti-slop validation workflow:

```bash
.venv/bin/python -c "print(open('demo/python/case_generate.md').read())"
```

---

## Related Documentation

- **[README.md](./README.md)** — Overview, file index, and directory structure
- **[FAQ.md](./FAQ.md)** — Design rationale, cost questions, and CI/CD guidance
