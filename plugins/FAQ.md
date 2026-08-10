# FAQ — kit-plugins Code Quality Gates

> **Frequently Asked Questions for `clean_py`, `clean_ts`, and OpenCode wrappers.**

---

## Technical Questions & Answers

### Q1: What is kit-plugins and what quality constraints do the validators enforce?
`kit-plugins` provides two AST-based code validators — `clean_py` (Python) and `clean_ts` (TypeScript) — plus Thin OpenCode wrapper tools (`clean_python.ts`, `clean_ts.ts`). Each validator enforces:

- **AST anti-slop policy**: No bare `except:` handlers, no swallowed exceptions (empty or comment-only `catch` bodies), no `eval()` calls.
- **Linter checks**: Ruff for Python; ESLint-equivalent rules (no-explicit-any, unused-vars, import ordering) for TypeScript.
- **Strict type checking**: MyPy `--strict` for Python; `tsc --strict --noEmit` for TypeScript.
- **Cyclomatic complexity**: Radon CC < 6 for Python; ESLint `complexity: ["error", 5]` for TypeScript.

Code is only written to disk after passing all gates, using an atomic temp-file + rename pattern.

### Q2: How do I install the dependencies for clean_py and clean_ts?
**clean_py** requires Python 3.11+. Install it as a pip package:

```bash
cd plugins/python
pip install -e .

# Or with uv
uv pip install -e .
```

This pulls in `ruff`, `mypy`, and `radon` as transitive dependencies via the package's runtime requirements.

**clean_ts** requires Node.js 18+. Install and build:

```bash
cd plugins/typescript/clean_ts
npm install
npm run build

# Verify
clean_ts --help
```

The `npm run build` step compiles `src/*.ts` to `dist/cli.js` and makes the `clean_ts` bin executable.

### Q3: What environment variables control plugin behavior?
| Variable | Scope | Purpose |
|---|---|---|
| `DISABLE_CLEAN_PYTHON` | OpenCode wrapper only | Set to `true` to bypass `clean_py` validation entirely and write code directly to disk |
| `DISABLE_CLEAN_TS` | OpenCode wrapper only | Set to `true` to bypass `clean_ts` validation entirely and write code directly to disk |
| `VIRTUAL_ENV` | `clean_py` discovery | Path to the Python virtual environment; used to locate the `python` binary and `ruff`/`mypy`/`radon` |
| `PYTHONIOENCODING` | `clean_py` subprocess | Forced to `utf-8` to ensure consistent output encoding |
| `PYTHONDONTWRITEBYTECODE` | `clean_py` subprocess | Forced to `1` to prevent `.pyc` file creation |
| `NODE_NO_WARNINGS` | `clean_ts` subprocess | Forced to `1` to suppress Node.js deprecation warnings |

### Q4: How do I bypass validation if my code cannot satisfy the quality gates?
There are two escape hatches:

**For OpenCode wrappers**, set the bypass flag as an environment variable before invoking the tool:

```bash
# Bypass clean_py (Python)
DISABLE_CLEAN_PYTHON=true

# Bypass clean_ts (TypeScript)
DISABLE_CLEAN_TS=true
```

When the bypass flag is active, the wrapper writes code directly to the target path without running any linter or type checks, and returns a `[BYPASS ACTIVE]` confirmation message.

**For direct CLI usage**, there is no bypass flag — you must fix the validation errors. Re-run `clean_py validate <file>` or `clean_ts validate <file>` after addressing issues to confirm the code passes.

### Q5: How are validation retries tracked and what happens after repeated failures?
The OpenCode wrappers enforce a maximum of **10 validation attempts** per target file path. Each failure increments an in-memory retry counter (stored in a `Map` keyed by the absolute target path). After 10 consecutive failures, the wrapper returns a `FATAL QUALITY FAILURE` message and refuses to write the file. The counter resets on success or after exceeding the limit.

### Q6: Can clean_py and clean_ts run directly without OpenCode?
Yes. Both validators expose a standalone CLI:

```bash
# Python
clean_py validate src/module.py

# TypeScript
clean_ts validate src/module.ts

# Output (JSON on stdout)
{
  "valid": true,
  "errors": []
}
```

The CLI reads a file path argument, runs all quality gates, and emits JSON `{"valid": bool, "errors": str[]}` to stdout. Exit code is `0` on success, `1` on validation failure, and `2` on infrastructure error.
