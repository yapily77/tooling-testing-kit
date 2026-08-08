# 📋 OpenCode Execution Plan: Chronomancer E2E Test Plan (V34hb Pipeline)

## 1. 🔍 Context, Tooling & AST Strategy
*Map out the codebase before writing a single line of code.*
- **Target Files:** `tests/01_gold_snapshots/05_chronomancer/`, `src/engine/agents.py`, `src/interfaces/telegram/chronomancer/coordinator.py`
- **Exploration Tools:** 
  - `/investigate`: `handle_ask`, `handle_daily`, `DailyDeps`
  - `Codebase Indexing`: `infrastructure/mem0`, `UserState` Redis caching
- **AST Pre-Check:** N/A for this test script implementation phase, as we rely on the existing 30-day rejection rule (`has_future_dates`).

## 2. 🎯 Scope & Key Decisions to Lock (`bd`)
*These are the foundational decisions. Once agreed upon, they will be locked into memory using `bd`.*
- **Objective:** Execute a sequential, 6-step conversational E2E test to validate the new Chronomancer `/ask` pipeline, memory threading, and background `StateWriter`.
- **Architecture Decisions:** 
  - **Live Services:** Prioritize quality by hitting real Redis, Qdrant, and LLM endpoints. No hermetic mocks.
  - **Test Subject:** Use existing test user `999998` in the database.
  - **Background Timing:** Use `asyncio.sleep()` between test turns to organically allow the background `StateWriter` to populate Redis `UserState`.
- **Context Lock-in:** 
  - 🛑 *Action:* I will execute `bd` to log the scope, architecture decisions, and target schema so I do not lose this context during execution.

## 3. 🛡️ Pre-Mortem & Threat Model
*Identify failures before they happen.*
- **Input Edge Cases:** The test script must explicitly wait for the background tasks to complete; otherwise, subsequent steps will read an empty/stale `UserState`.
- **UX Feedback Loop:** Step 3 must fail loud and instantly via the 30-day boundary check.
- **Concurrency & State:** The `StateWriter` task must not crash on missing keys when Redis is empty on Turn 1.

## 4. 🛠️ Step-by-Step Implementation
*Atomic steps. Must include validation.*

- [ ] **Phase 1: Implement 6-Step Conversational Script**
## 4. 🚀 Execution & Verification
- Run `uv run pytest tests/examples` or relevant test suite.
- Ensure all multi-turn assertions pass cleanly without exception swallowing.
