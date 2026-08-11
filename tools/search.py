#!/usr/bin/env python3
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx
from control import ControlSheet
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from qdrant_client import AsyncQdrantClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INFRA_ROOT = Path(os.getenv("KIT_INFRA_ROOT", str(PROJECT_ROOT.parent)))
GRAPH_JSON = INFRA_ROOT / "infra" / "graph" / "code_knowledge_graph.json"
DIRECTIVES_DB = INFRA_ROOT / ".ctx" / "agents_graph.db"

KIT_QDRANT_URL = os.getenv("KIT_QDRANT_URL", "http://localhost:6333")
KIT_EMBEDDING_URL = os.getenv("KIT_EMBEDDING_URL", "http://localhost:8002")
KIT_EMBEDDING_TOKEN = os.getenv("KIT_EMBEDDING_TOKEN", "")
COLLECTION_NAME = os.getenv("KIT_COLLECTION_NAME", "codebase_index")


class StructuredCodeQuery(BaseModel):
    semantic_concepts: list[str] = Field(
        description="Key conceptual terms or themes to search semantically (e.g. 'session handling', 'timezone correction')."
    )
    literal_symbols: list[str] = Field(
        default_factory=list,
        description="Exact variable, class, function, or method names detected (e.g. 'UserProfile', 'db')."
    )
    target_directory: str | None = Field(
        None,
        description="If the query targets a specific directory, extract it (e.g., 'src/bot', 'src/engine')."
    )
    file_extensions: list[str] = Field(
        default_factory=lambda: ["*.py"],
        description="List of target file extensions (e.g., '*.py', '*.md', '*.json')."
    )


model = ControlSheet.codebase_model
agent = Agent(
    model,
    output_type=StructuredCodeQuery,
    system_prompt="Parse this codebase search query into structured fields.",
)


async def get_embedding(text: str, async_client: httpx.AsyncClient) -> list[float]:
    is_openai = "v1/embeddings" in KIT_EMBEDDING_URL
    payload = {"input": text} if is_openai else [text]
    headers = {"Authorization": f"Bearer {KIT_EMBEDDING_TOKEN}"} if KIT_EMBEDDING_TOKEN else {}

    resp = await async_client.post(KIT_EMBEDDING_URL, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    return _parse_embedding_response(data)


def _parse_embedding_response(data: Any) -> list[float]:
    """Parse embedding response from various formats."""
    import numpy as np
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
            return data["data"][0]["embedding"]
        return data["embeddings"][0]
    return data[0]


def _resolve_secure_path(relative_path: str) -> Path:
    try:
        root = PROJECT_ROOT.resolve()
        if relative_path.startswith(f"{root.name}/"):
            relative_path = relative_path[len(f"{root.name}/") :]
        elif relative_path == root.name:
            relative_path = ""
        target = (root / relative_path).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Path escape detected: {relative_path}")
        return target
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid path: {relative_path} ({e!s})")


def _find_match_line(lines: list[str], match_text: str) -> int:
    """Find the 1-indexed line number containing match_text."""
    for i, line in enumerate(lines):
        if match_text in line:
            return i + 1
    return -1


def _find_parent_header(tree, lines, match_line: int) -> str:
    """Find the enclosing function/class header for a match line."""
    import ast
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.lineno <= match_line <= (node.end_lineno or node.lineno):
                header_line = lines[node.lineno - 1].strip()
                return f"[{header_line}] "
    return ""


def _get_scope_expanded_snippet(rel_path: str, match_text: str) -> str:
    import ast
    try:
        path = _resolve_secure_path(rel_path)
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return match_text[:300] + "..."

    tree = ast.parse(content)
    lines = content.splitlines()
    match_line = _find_match_line(lines, match_text)
    if match_line == -1:
        return match_text[:300] + "..."

    parent_header = _find_parent_header(tree, lines, match_line)
    snippet = lines[max(0, match_line - 3) : match_line + 5]
    return parent_header + "\n".join(snippet)


def _score_entity(ent, q_vec, q_norm) -> tuple[int, float] | None:
    """Compute cosine similarity for a single entity, return (index, score) or None."""
    import numpy as np
    if "embedding" not in ent:
        return None
    e_vec = np.array(ent["embedding"])
    e_norm = np.linalg.norm(e_vec)
    if e_norm < 1e-10:
        return None
    score = float(np.dot(q_vec, e_vec) / (q_norm * e_norm))
    if np.isnan(score):
        return None
    return ent.get("_idx", -1), score


def _load_knowledge_graph():
    """Load the knowledge graph JSON file."""
    if not GRAPH_JSON.exists():
        return None
    try:
        return json.loads(GRAPH_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"_error": str(e)}


def _filter_related_rels(graph, matched_names: set) -> list:
    """Filter relationships to those connected to matched entities."""
    related_rels = []
    for rel in graph.get("relationships", []):
        src_low = rel["source"].lower()
        tgt_low = rel["target"].lower()
        if src_low in matched_names or tgt_low in matched_names:
            related_rels.append(rel)
    return related_rels


def _get_top_matched_entities(entities, q_vec, q_norm, max_entities) -> list:
    """Get top matching entities by cosine similarity."""
    import numpy as np
    if q_norm < 1e-10:
        return []
    scored = _score_entities(entities, q_vec, q_norm)
    scored.sort(key=lambda x: x[1], reverse=True)
    top_indices = [idx for idx, _ in scored[:max_entities]]
    return [entities[idx] for idx in top_indices]


def _score_entities(entities, q_vec, q_norm) -> list[tuple[int, float]]:
    """Score each entity by cosine similarity, filtering out zero-norm and NaN results."""
    import numpy as np
    scored: list[tuple[int, float]] = []
    for i, ent in enumerate(entities):
        score = _compute_entity_score(ent, q_vec, q_norm)
        if score is not None:
            scored.append((i, score))
    return scored


def _compute_entity_score(ent, q_vec, q_norm) -> float | None:
    """Compute cosine similarity for a single entity, or None if invalid."""
    import numpy as np
    if "embedding" not in ent:
        return None
    e_vec = np.array(ent["embedding"])
    e_norm = np.linalg.norm(e_vec)
    if e_norm < 1e-10:
        return None
    score = float(np.dot(q_vec, e_vec) / (q_norm * e_norm))
    if np.isnan(score):
        return None
    return score


async def query_knowledge_graph(query: str, query_vec: list[float], max_entities: int = 10) -> dict[str, Any]:
    graph = _load_knowledge_graph()
    if graph is None:
        return {"success": False, "message": "Knowledge graph not found.", "data": {}}
    if "_error" in graph:
        return {"success": False, "message": f"Failed to load graph: {graph['_error']}", "data": {}}

    entities = graph.get("entities", [])
    if not entities:
        return {"success": True, "message": "Graph has no entities.", "data": {"entities": [], "relationships": []}}

    import numpy as np
    q_vec = np.array(query_vec)
    q_norm = np.linalg.norm(q_vec)
    matched_entities = _get_top_matched_entities(entities, q_vec, q_norm, max_entities)

    matched_names = {e["name"].lower() for e in matched_entities}
    related_rels = _filter_related_rels(graph, matched_names)

    return {
        "success": True,
        "data": {
            "entities": matched_entities,
            "relationships": related_rels[: max_entities * 5],
        },
    }


def _compute_directive_score(row, query_vec) -> dict | None:
    """Compute cosine similarity score for a single directive row."""
    import numpy as np
    import json as json_mod
    emb_json = row["embedding_json"]
    if not emb_json:
        return None
    try:
        emb = np.array(json_mod.loads(emb_json))
        e_norm = np.linalg.norm(emb)
        if e_norm < 1e-10:
            return None
        score = float(np.dot(query_vec, emb) / (np.linalg.norm(query_vec) * e_norm))
        if score < 0.6:
            return None
        return {
            "section_title": row["section_title"],
            "content": row["content"][:500],
            "score": round(score, 4),
        }
    except (ValueError, TypeError, json_mod.JSONDecodeError):
        return None


async def inject_directives(query_vec: list[float], top_k: int = 2, threshold: float = 0.6) -> list[dict]:
    if not DIRECTIVES_DB.exists():
        return []

    conn = sqlite3.connect(str(DIRECTIVES_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, section_title, content, embedding_json FROM directives").fetchall()
    conn.close()

    results = [_compute_directive_score(row, query_vec) for row in rows]
    results = [r for r in results if r is not None]
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _norm_extensions(file_extensions: list[str]) -> list[str]:
    """Normalize file extension patterns to bare extensions."""
    return [e for e in (ext.replace("*", "").strip() for ext in file_extensions) if e]


def _match_directory(rel_path: str, target_dir: str | None) -> bool:
    """Check if a path matches the target directory filter."""
    if not target_dir:
        return True
    return target_dir in rel_path


def _match_extension(rel_path: str, file_extensions: list[str]) -> bool:
    """Check if a path matches any of the target extensions."""
    exts = _norm_extensions(file_extensions)
    return all(rel_path.endswith(ext) for ext in exts) if exts else True


def _build_match_entry(res, structured_query, rel_path: str, raw_content: str) -> dict:
    """Build a single match entry for the search results."""
    snippet = _get_scope_expanded_snippet(rel_path, raw_content)
    score = res.score
    if structured_query.literal_symbols:
        for sym in structured_query.literal_symbols:
            if sym in snippet or sym in raw_content:
                score = min(1.0, score + 0.15)
    return {
        "file_path": rel_path,
        "score": round(score, 4),
        "snippet": snippet,
        "source": "vector",
    }


async def _search_qdrant(query_vector, limit: int) -> list:
    """Query Qdrant for vector search results."""
    qdrant = AsyncQdrantClient(url=KIT_QDRANT_URL)
    try:
        raw_limit = limit * 3
        results = await qdrant.query_points(
            collection_name=COLLECTION_NAME, query=query_vector, limit=raw_limit, with_payload=True
        )
        return results.points
    finally:
        await qdrant.close()


def _should_include_result(res, target_dir, file_extensions) -> bool:
    """Check if a search result should be included based on filters."""
    if not res.payload:
        return False
    rel_path = res.payload.get("file_path", "unknown")
    return _match_directory(rel_path, target_dir) and _match_extension(rel_path, file_extensions)


def _process_search_results(points, structured_query, limit: int) -> list[dict]:
    """Process Qdrant results and apply filters."""
    target_dir = structured_query.target_directory.strip("/") if structured_query.target_directory else None
    matches = []
    for res in points:
        if not _should_include_result(res, target_dir, structured_query.file_extensions):
            continue
        rel_path = res.payload.get("file_path", "unknown")
        raw_content = res.payload.get("content", "")
        matches.append(_build_match_entry(res, structured_query, rel_path, raw_content))

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:limit]


async def mcp_search(query: str, limit: int = 10):
    try:
        async with httpx.AsyncClient() as async_client:
            result = await agent.run(f"Parse this codebase search query: {query}")
            structured_query = result.output
            search_str = " ".join(structured_query.semantic_concepts) if structured_query.semantic_concepts else query
            query_vector = await get_embedding(search_str, async_client)

            points = await _search_qdrant(query_vector, limit)
            matches = _process_search_results(points, structured_query, limit)

            graph_resp = await query_knowledge_graph(query, query_vector, max_entities=limit)
            directives = await inject_directives(query_vector, top_k=2, threshold=0.6)

            _print_report(query, matches, graph_resp, directives)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as e:
        print(f"Error during search: {e}", file=sys.stderr)
        raise


def _print_vector_matches(matches: list[dict]) -> None:
    """Print top vector search matches."""
    print(f"## Top Vector Matches ({len(matches)})\n")
    for i, match in enumerate(matches, 1):
        print(f"### {i}. `{match['file_path']}` (Score: {match['score']})")
        print("```python")
        print(match['snippet'])
        print("```\n")


def _print_graph_context(graph_resp: dict) -> None:
    """Print knowledge graph entities and relationships."""
    print("## Key Knowledge Graph Context\n")
    print("### Entities")
    for ent in graph_resp["data"]["entities"][:5]:
        print(f"- **{ent['name']}**: {ent.get('description', '')}")

    rels = graph_resp["data"].get("relationships", [])
    if rels:
        print("\n### Relationships")
        for rel in rels[:5]:
            print(f"- {rel['source']} --[{rel.get('rel_type', 'related')}]--> {rel['target']}")
    print()


def _print_directives(directives: list[dict]) -> None:
    """Print auto-injected directives."""
    print("## Auto-Injected Directives\n")
    for d in directives:
        print(f"### {d['section_title']} (Score: {d['score']})")
        print(f"{d['content']}...\n")


def _print_report(query: str, matches: list[dict], graph_resp: dict, directives: list[dict]) -> None:
    """Print the Markdown search report."""
    print(f"# Search Report for: '{query}'\n")
    _print_vector_matches(matches)
    if graph_resp.get("success") and graph_resp["data"].get("entities"):
        _print_graph_context(graph_resp)
    if directives:
        _print_directives(directives)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python search.py <query>")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    asyncio.run(mcp_search(query))
