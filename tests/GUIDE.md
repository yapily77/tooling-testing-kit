# Guide: How to Use and Configure `kit-tests`

> **Comprehensive guide to running, configuring, and extending the test kit.**

---

## 1. Prerequisites

| Tool | Minimum Version | Purpose |
|---|---|---|
| Python | 3.11+ | Modern language runtime |
| `uv` | latest | Dependency resolution (`pytest`, `hypothesis`) |

Install `uv`:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 2. Quick Run (Offline Stubs)

Run the self-contained pattern stubs in `examples/`:

```bash
cd tests
uv run pytest examples -q
```

No network access, API keys, or databases are required.

---

## 3. Directory & Visibility Structure

### Default Collection Surface
By default, pytest is constrained to collect tests inside `examples/` via `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["examples"]
```

Additionally, `tests/conftest.py` declares `collect_ignore` rules for external layers (`01_gold_snapshots/` through `10_harness_suite/`).

---

## 4. Configuring Live Mode (`KIT_LIVE=true`)

Copy the configuration template:

```bash
cp tests/.env.example tests/.env
```

### Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `KIT_LIVE` | Live integration master switch | `false` |
| `KIT_PATH` | Path to target codebase root | (empty) |
| `KIT_BASE_URL` | LLM endpoint URL | `http://localhost:8000/v1` |
| `KIT_MODEL` | Chronomancer layer model name | `gemma-2-27b-it` |
| `KIT_MEM0_MODEL` | Mem0 synthesis layer model name | `gemma-2-27b-it` |
| `KIT_API_KEY` | LLM provider API key | `sk-your-key` |

### Fail-Fast Behavior
When `KIT_LIVE=true`, `config.py` validates all required parameters at import time. Unset variables trigger an immediate `RuntimeError`.

---

## 5. Studying Test Patterns

Each file in `examples/` illustrates a specific test design pattern:

1. **`01_frozen_clock.py`**: Deterministic time-freezing pattern using pytest fixtures.
2. **`02_snapshot_regression.py`**: Golden file snapshot assertions.
3. **`03_mutation_target.py`**: Mutation testing targets with `mutmut`.
4. **`04_silent_swallow_scanner.py`**: AST-based static exception handler linting.
5. **`05_hypothesis_fuzz.py`**: Property-based fuzz testing with `hypothesis`.
6. **`06_kit_mem0_model.py`**: Granular model configuration validation.
7. **`test_kit_live_smoke.py`**: Attestation test for fail-fast configuration checks.

---

## 6. Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` | Attempting to run internal benchmark layers without target source tree | Stick to `examples/` or set `KIT_PATH` to target codebase in `.env` |
| `RuntimeError: KIT_LIVE=true but missing required env` | Live mode enabled with missing credentials | Complete missing `KIT_*` variables in `tests/.env` |
| Pytest skips `01_` through `10_` layers | Intentionally excluded from default collection | Run specific paths explicitly: `uv run pytest 01_gold_snapshots/` |
