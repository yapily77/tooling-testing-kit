# Quick Start: `kit-tests`

> **60-Second Fast Path for Running Test Stubs & Live Scenarios**

---

## 1. Offline Stubs (Zero Setup)

Run the self-contained pattern stubs with no `.env` or API key required:

```bash
cd tests
KIT_LIVE=false uv run pytest examples -q
```

Output:
```text
8 passed in 0.18s
```

---

## 2. Live Mode (LLM Enabled)

Copy `.env.example` and set your endpoint parameters:

```bash
cp tests/.env.example tests/.env

# Configure tests/.env:
# KIT_LIVE=true
# KIT_PATH=/path/to/target
# KIT_BASE_URL=http://localhost:8000/v1
# KIT_MODEL=gemma-2-27b-it
# KIT_API_KEY=sk-your-key

uv run pytest examples/test_kit_live_smoke.py -q
```

---

## 3. Key Concepts

- **Default Isolation**: `pyproject.toml` pins `testpaths = ["examples"]` so running `uv run pytest` executes only the standalone example stubs.
- **Fail-Fast Configuration**: Setting `KIT_LIVE=true` validates required environment variables at import time, failing loudly if credentials are missing.
- **Independent Model Knobs**: `KIT_MODEL` and `KIT_MEM0_MODEL` allow separate model selections for different test layers.

---

## 4. Documentation Links

- **[`README.md`](README.md)** — Test suite overview and layer matrix.
- **[`GUIDE.md`](GUIDE.md)** — Detailed configuration and troubleshooting guide.
- **[`STRUCTURE.md`](STRUCTURE.md)** — Repository layout and curation rules.
