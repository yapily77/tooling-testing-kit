# kit-tools

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)

> **Portable Codebase Intelligence, AST Modification, and RAG Utilities**  
> Extracted utility scripts for searching, analyzing, refactoring, and retrieving codebase context.

---

## Tool Categories & Capabilities

All tools operate portably on target repositories specified by `KIT_TARGET_ROOT`.

| Category | Key Tool Scripts | Purpose & Notes |
|---|---|---|
| **Codebase Search & Analysis** | `search.py`, `grep_codebase.py`, `investigate.py`, `get_file_symbols.py`, `get_repo_structure.py` | Semantic search, regex code search, symbol hierarchy extraction, and repository topology. |
| **AST Code Modification** | `add_function.py`, `add_class.py`, `add_import.py`, `replace_function.py`, `move_symbol.py` | AST-aware code editing, import insertion, and symbol refactoring. |
| **File Operations** | `read_file.py`, `write_file.py`, `rename_file.py`, `delete_file.py` | Safe file manipulation with path validation. |
| **Index & Schema Management** | `index_repository.py`, `verify_file_path.py`, `load_schema_gate.py` | Vector index construction and schema verification gates. |
| **RAG Demonstration** | `rag/bazirag.py`, `rag/query_cli.py`, `rag/mcp_bazirag.py` | Domain-specific RAG pipeline demonstrating query expansion and vector retrieval. |

---

## Quick Start

```bash
# 1. Navigate to tools workspace
cd tools

# 2. Copy configuration template
cp .env.example .env

# 3. Configure target repository path
# Edit .env and set: KIT_TARGET_ROOT=/path/to/target/repository

# 4. Run semantic search or codebase tools
uv run python search.py "Where is authentication handled?"
uv run python get_repo_structure.py
```

---

## Subfolder Navigation

- **[`GUIDE.md`](GUIDE.md)** — Unified usage guide for codebase tools and RAG modules.
- **[`codebase/README.md`](codebase/README.md)** — Detailed codebase search and AST refactoring tool docs.
- **[`codebase/FAQ.md`](codebase/FAQ.md)** — Frequently asked questions for codebase analysis tools.
- **[`rag/README.md`](rag/README.md)** — BaziRAG retrieval engine documentation.
- **[`rag/FAQ.md`](rag/FAQ.md)** — RAG system FAQ and caching strategies.
