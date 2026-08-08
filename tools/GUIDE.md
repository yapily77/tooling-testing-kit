# kit-tools Guide — Unified Usage

> **Step-by-step guide for codebase intelligence, AST modification, and RAG tools.**

---

## Tool Suites Overview

`kit-tools` provides two primary toolkits:

| Subdirectory | Focus | Primary Use Case |
|---|---|---|
| **`codebase/`** | Codebase Search & AST Code-Mod | Search, analyze, and refactor any target Python codebase specified by `KIT_TARGET_ROOT`. |
| **`rag/`** | Domain RAG Retrieval Engine | Query-expansion and vector search demonstration for domain-specific text analysis. |

---

## Environment Configuration

Both toolkits share a standardized environment variable schema (`KIT_*`):

```env
# Target Codebase Configuration
KIT_TARGET_ROOT=/path/to/target/repository

# LLM & Embedding Settings (Optional)
KIT_BASE_URL=http://localhost:8000/v1
KIT_API_KEY=sk-your-api-key
KIT_MODEL=gemma-2-27b-it
```

---

## Common Workflows

### 1. Codebase Search & Analysis
```bash
# Regex search across python files
cd tools/codebase
uv run python grep_codebase.py "def main" "" --extension-filter ".py"

# Inspect symbol hierarchy in a file
uv run python get_file_symbols.py --filename src/main.py
```

### 2. Domain RAG Querying
```bash
cd tools/rag
cp .env.example .env
uv run python query_cli.py "Query question"
```

---

## Frequently Asked Questions

| Question | Answer |
|---|---|
| How do I set the target codebase? | Set `KIT_TARGET_ROOT` in your `tools/.env` or `tools/codebase/.env` file. |
| Can search tools run without Qdrant/Vector DBs? | Yes. Text-based grep and AST analysis tools work offline without vector indexes. |
| Do I need external credentials for AST code modifications? | No. AST modifications (`add_function.py`, `replace_function.py`) execute locally using Python's `ast` parser. |
