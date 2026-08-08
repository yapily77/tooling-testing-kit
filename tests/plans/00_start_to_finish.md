# 📋 OpenCode Execution Plan: Complete Autonomous E2E Validation (Chronomancer, Auto Monthly, Input Monthly)

## 1. 🔍 Context, Tooling & AST Strategy
*Map out the codebase before writing a single line of code.*
- **Target Files:**
  - `tests/01_gold_snapshots/05_chronomancer/` (Chronomancer E2E Test)
  - `tests/01_gold_snapshots/02_auto/` (Auto Monthly E2E Test)
  - `tests/01_gold_snapshots/03_input/` (Input Monthly E2E Test)
  - `src2/interfaces/telegram/intake/calendar_node.py` (Auto engine ingress seam)
  - `src2/interfaces/telegram/bridge.py` & `src2/core/schemas/unified.py` (C5/C4 schema boundary & tailoring threading)
  - `src2/interfaces/telegram/chronomancer/coordinator.py`, `state_writer.py`, `forecast_store.py` (Chronomancer runtime & BaziCache)
- **Exploration Tools:** 
  - `/investigate`: `_run_auto_engine`, `map_profile_to_k3`, `handle_ask`, `handle_daily`, `run_pydantic_engine`
  - `Codebase Indexing`: `ChartProfile`, `UserProfile`, `UserState`, `BaziCache`
  - `/search`: `tailoring_context`, `tailoring_concerns`, `statewriter_model`, `bazi_mini_library.jsonl`
- **AST Pre-Check:** 
  - We will perform AST analysis on any file where test failures occur (e.g., if schema mismatches occur between `UserProfile` and `ChartProfile` during tailoring injection, or if background async tasks in Chronomancer fail to drain). Specifically, we will verify that `tailoring_context` is properly preserved across C5 -> C4 boundaries and that `StateWriter` model attributes strictly conform to `ControlSheetSchema`.

## 2. 🎯 Scope & Key Decisions to Lock (`bd`)
*These are the foundational decisions. Once agreed upon, they will be locked into memory using `bd`.*
- **Objective:** Execute a unified, autonomous `test > fix > loop` validation suite sequentially across all three core E2E pipelines (`chronomancer`, `auto_monthly`, and `input_monthly`) until 100% test pass rates are achieved, confirming 0ms BaziCache latency, 100% Pydantic V2 Zero-Dicts compliance, and seamless memory threading.
- **Architecture Decisions (Locked from /grill-me Interview):** 
  - **Sequential Execution Order:** Run the test suites strictly in sequence (Chronomancer -> Auto Monthly -> Input Monthly) in a single worker to guarantee clean DB/Redis isolation and avoid OpenRouter API rate limits.
  - **Auto-Flush State Isolation:** Automatically flush Redis key `user_state:999998` and wipe transient Postgres session records for test user `999998` before executing Chronomancer to ensure 100% deterministic, reproducible assertions.
  - **Metaphysical Drift Accepted:** Explicitly accept **"Mild Strong"** Day Master strength as canonical algorithmic behavior for the `/auto` pipeline (compared to manual "Strong" in `/input`), leaving `lunar-python` classical math rules untouched.
  - **Zero-Dicts & Pydantic Only:** All payloads crossing the C5 ingress boundary into the C4 engine must strictly instantiate Pydantic V2 schemas (`ChartProfile`, `UserProfile`). No legacy `.dict()` or `.get()` calls are permitted.
  - **Live Services & No Mocks:** All tests must hit live Redis, Qdrant BaziRAG, and OpenRouter/Google LLM endpoints.
  - **Subagent Orchestration:** Long-running monthly report generators (`auto_monthly` and `input_monthly`) and complex multi-turn tests (`chronomancer`) will be delegated to subagents to prevent main thread context bloat and memory degradation.
- **Context Lock-in:** 
  - 🛑 *Action:* I will execute `bd` to log the scope, architecture decisions, and target schema so I do not lose this context during execution.

## 3. 🛡️ Pre-Mortem & Threat Model
*Identify failures before they happen.*
- **Input Edge Cases:** 
  - **Timeout Risks:** Monthly report generation calls LLMs for 12 successive months. Default 120s CLI timeouts will abort the test; subagent execution with extended timeouts (300s+) must be enforced.
  - **Async Race Conditions:** `asyncio.create_task` for background `StateWriter` in Chronomancer can be silently destroyed by Python's garbage collector if the main test script exits prematurely. Scripts must await background task draining before assertion completion.
- **UX Feedback Loop:** Fail fast and loudly with full tracebacks. No silent `except: pass` exception swallowing. If an LLM output is malformed or a cache hit fails, let the error propagate immediately.
- **Concurrency & State:** Redis keys (`user_state:999998`) and session state in Postgres must be cleanly isolated or pre-cleared before test runs so stale data does not pollute assertions.

## 4. 🛠️ Step-by-Step Implementation
*Atomic steps. Must include validation. Executed sequentially as agreed.*

- [ ] **Phase 1: Environment & Config Pre-Flight**
  - **Action:** Run `uv run pytest tests/infra/` to confirm test framework setup and configuration.
  - **Validation:** Confirm green pass for environment setup.

- [ ] **Phase 2: Offline Unit & Static Verification**
  - **Action:** Run static analysis gates, Pydantic strictness checks, and AST swallow detectors (`uv run pytest tests/08_static_gates`).
  - **Validation:** Confirm 0 errors and 0 silent swallows detected.

- [ ] **Phase 3: Integration & Live Smoke Test**
  - **Action:** Run `uv run pytest tests/05_integration_e2e` and `uv run pytest tests/examples`.
  - **Validation:** Confirm integration pipelines pass cleanly.

## 5. 🔄 Test & Resolution Protocol
- **Initial Test Phase:** Execute unit and integration tests sequentially.
- **Failure Protocol:** If a test fails:
  1. Inspect traceback for root cause.
  2. Use AST analysis or targeted debugging to locate schema mismatch or logic bug.
  3. Apply minimal targeted fix and re-run test suite.

## 6. 🚀 Quality Assurance & Validation
- **Pre-Flight Checks:** Verify environment variables and database connections.
- **Rollback Steps:** If an unrecoverable regression occurs, run `git checkout -- <files>` to restore the last stable state.

