# FAQ — kit-hygiene Technical Debt Scanner

> **Frequently Asked Questions for Technical Debt Scanning & Codebase Hygiene**

---

## Technical Questions & Answers

### Q1: What is kit-hygiene and how does it differ from Linters like Ruff or Pylint?
`kit-hygiene` is a **hybrid static-AST + LLM audit scanner**. Traditional linters like `ruff` or `pylint` produce hundreds of stylistic warnings (e.g. whitespace, variable casing) while missing critical logic bugs. `kit-hygiene` targets high-severity runtime defects—such as swallowed exceptions, async deadlocks, schema crashes, and hardcoded secrets—using a two-tier pipeline that filters out false positives.

### Q2: Can kit-hygiene run 100% offline without API keys?
**Yes.** Tier 1 static AST scanning runs 100% offline with zero network calls or API keys. Pass `--scripts` to `run_all.py` to run static AST analysis locally.

### Q3: What specific defect types does kit-hygiene detect?
- **Swallowed Exceptions**: Bare `except:` and `except: pass` blocks (`find_silent_killers.py`).
- **Async Hazards**: Synchronous blocking calls (e.g., `requests.get`) inside `async def` functions (`find_async_hazards.py`).
- **Schema Hazards**: Direct dictionary/list instantiation passed to Pydantic models (`find_engine_schemas.py`).
- **Hardcoded Secrets**: Plaintext API keys, passwords, and tokens (`find_secrets.py`).
- **Environment Drift**: `os.getenv()` calls referencing keys missing from `.env.example` (`find_env_drift.py`).
- **Circular Dependencies**: Import cycles that trigger `ImportError` on application startup (`find_circular_deps.py`).
- **Model Dict Access**: Post-migration calls like `.get()` or `.keys()` on Pydantic objects (`find_registry_clashes.py`).

### Q4: How does kit-hygiene prevent high API costs?
`kit-hygiene` uses a two-tier architecture:
1. **Tier 1 (Static AST)** filters candidates locally at zero cost.
2. **Tier 2 (LLM)** receives only small code snippets for flagged candidates (typically 3–5 API calls per scan across a codebase), preventing full-repository context costs.

### Q5: How can kit-hygiene be integrated into CI/CD pipelines?
Run `run_all.py --scripts` in CI scripts. Configure `HARD_FAIL_THRESHOLD` in `.env`:
- `0`: Ignore findings (always exit 0).
- `1`: Warn on findings (exit 0).
- `2+`: Fail fast (exit 1 if high-severity findings are detected).

### Q6: Does kit-hygiene modify source code files directly?
**No.** By default, all scanners are read-only and write findings to `hygiene/reports/`. Modifications are only applied when explicitly running `cleanup.py` or `kill_tries_apply.py`.

### Q7: Which LLM providers and endpoints are supported?
`kit-hygiene` uses standard OpenAI-compatible endpoints configured via `KIT_BASE_URL`, `KIT_API_KEY`, and `KIT_MODEL`. Compatible endpoints include Ollama, vLLM, LM Studio, Anthropic/OpenAI proxies, and Google Gemini gateways.

### Q8: How do I scan only git-modified files?
Use the `--diff` flag:
```bash
uv run hygiene/scanners/run_all.py --diff
```
