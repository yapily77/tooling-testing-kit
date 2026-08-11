import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from qdrant_client import AsyncQdrantClient

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
RAG_DIR = Path(os.getenv("RAG_DATA_DIR", str(Path(__file__).resolve().parent / "data")))
QDRANT_PATH = os.path.join(os.getenv("QDRANT_PATH", os.path.join(RAG_DIR, "qdrant_db")))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "bazi_classical")

EMBEDDING_SERVICE_URL = os.getenv("EMBEDDING_SERVICE_URL", "http://localhost:8002/v1/embeddings")
EMBEDDING_API_KEY     = os.getenv("EMBEDDING_API_KEY", "")

RETRIEVE_K   = int(os.getenv("RETRIEVE_K", "30"))
RETURN_TOP_N = 15
SUB_QUERY_LIMIT = 5

EMBED_TIMEOUT  = 30

# ── MCP app ───────────────────────────────────────────────────────────────────
mcp = FastMCP(
    name="BaziRAG",
    instructions=(
        "Search classical Bazi (八字) texts. "
        "Use the search_bazi tool to retrieve relevant passages from the classical corpus. "
        "CRITICAL: keywords MUST be in Simplified Chinese (e.g. 戊土 财运) — "
        "English keywords return zero results. "
        "Pass exactly 3 Chinese terms targeting different metaphysical aspects."
    ),
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _auth_headers() -> dict:
    h = {"accept": "application/json", "Content-Type": "application/json"}
    if EMBEDDING_API_KEY:
        h["Authorization"] = f"Bearer {EMBEDDING_API_KEY}"
    return h


def _build_embed_payload(texts: list[str]) -> dict | list[str]:
    is_openai = "v1/embeddings" in EMBEDDING_SERVICE_URL
    if is_openai:
        return {"input": texts}
    return texts


def _is_valid_data_array(data: dict) -> bool:
    if "data" not in data:
        return False
    return isinstance(data["data"], list) and len(data["data"]) > 0


def _extract_vectors(data: Any) -> list[list[float]]:
    if not isinstance(data, dict):
        return data  # type: ignore

    if _is_valid_data_array(data):
        return [item["embedding"] for item in data["data"]]
        
    if "embeddings" in data:
        return data["embeddings"]
        
    raise ValueError(f"Unexpected response structure from embedding server: {data}")


async def _embed(texts: list[str]) -> list[list[float]]:
    payload = _build_embed_payload(texts)
    r = await asyncio.to_thread(
        requests.post,
        EMBEDDING_SERVICE_URL,
        json=payload,
        headers=_auth_headers(),
        timeout=EMBED_TIMEOUT,
    )
    r.raise_for_status()
    return _extract_vectors(r.json())


def _extract_candidate_fields(r: Any) -> dict:
    return {
        "text": r.payload["text"],
        "source": r.payload["source"],
        "chunk_index": r.payload["chunk_index"],
        "_distance": 1.0 - r.score,
    }


def _format_candidate(c: dict) -> dict:
    return {
        "score": c["_distance"],
        "source": c["source"],
        "chunk_index": c["chunk_index"],
        "text": c["text"],
    }


def _build_single_results(points: list) -> list[dict]:
    candidates = [_extract_candidate_fields(r) for r in points]
    return [_format_candidate(c) for c in candidates[:SUB_QUERY_LIMIT]]


async def _search_single(client: AsyncQdrantClient, keyword: str) -> list[dict]:
    """Search Qdrant and rerank for a single keyword, returning top results."""
    try:
        query_vector = (await _embed([keyword]))[0]
    except (OSError, ValueError, TypeError, RuntimeError) as e:
        sys.stderr.write(f"Embedding failed for keyword '{keyword}': {e}\n")
        return []

    try:
        response = await client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=RETRIEVE_K,
            with_payload=True,
        )
    except (OSError, ValueError, TypeError, RuntimeError) as e:
        sys.stderr.write(f"Qdrant query failed for keyword '{keyword}': {e}\n")
        return []

    return _build_single_results(response.points)


def _has_ascii(text: str) -> bool:
    for c in text:
        if ord(c) < 128:
            return True
    return False


async def _expand_query_via_agent(query: str) -> list[str]:
    sys.stderr.write(f"Refining natural language query via Pydantic AI: '{query}'\n")
    bazi_rag_model = os.getenv("RAG_MODEL", "google/gemini-2.0-flash")
    if not bazi_rag_model:
        sys.stderr.write("No baziRAG_model configured. Falling back to default heuristics.\n")
        return [query]

    agent = Agent(bazi_rag_model, output_type=BaziRAGQuery)

    @agent.system_prompt
    def get_sys_prompt() -> str:
        return (
            "You are an expert in Zi Ping Bazi metaphysics. "
            "Translate natural language queries into exactly 3 "
            "highly-precise classical Simplified Chinese search terms "
            "matching classical texts (like Di Tian Sui or San Ming Tong Hui)."
        )

    try:
        result = await agent.run(query)
        final_keywords = result.output.classical_terms
        sys.stderr.write(f"Pydantic AI translated terms: {final_keywords}\n")
        return final_keywords
    except (OSError, ValueError, TypeError, RuntimeError) as e:
        sys.stderr.write(f"Pydantic AI parsing failed: {e}. Falling back to default heuristics.\n")
        return [query]


async def _normalize_keywords(query: str | None, keywords: list[str] | None) -> list[str]:
    if query:
        return await _expand_query_via_agent(query)
    
    if not keywords:
        return []

    if len(keywords) == 1 and _has_ascii(keywords[0]):
        return await _expand_query_via_agent(keywords[0])

    return keywords


async def _check_collection_exists(client: AsyncQdrantClient) -> bool:
    resp = await client.get_collections()
    collections = [c.name for c in resp.collections]
    return COLLECTION_NAME in collections


def _merge_dedupe_results(all_results: list[list[dict]]) -> list[dict]:
    seen = set()
    merged = []
    for sub_res in all_results:
        for item in sub_res:
            key = (item["source"], item["chunk_index"])
            if key not in seen:
                seen.add(key)
                merged.append(item)
    return merged


def _format_final_results(merged: list[dict]) -> list[dict]:
    merged.sort(key=lambda x: x["score"], reverse=True)
    final_results = merged[:RETURN_TOP_N]
    
    return [
        {
            "rank": i + 1,
            "score": round(item["score"], 4),
            "source": item["source"],
            "chunk_index": item["chunk_index"],
            "text": item["text"],
        }
        for i, item in enumerate(final_results)
    ]


async def _search_all_keywords(client: AsyncQdrantClient, final_keywords: list[str]) -> list[dict]:
    tasks = [_search_single(client, kw) for kw in final_keywords]
    all_results = await asyncio.gather(*tasks)
    merged = _merge_dedupe_results(all_results)
    return _format_final_results(merged)


# ── MCP Tool ──────────────────────────────────────────────────────────────────
class BaziRAGQuery(BaseModel):
    classical_terms: list[str] = Field(
        min_length=3,
        max_length=3,
        description=(
            "Exactly 3 distinct technical Simplified Chinese search terms representing: "
            "1. The Day Master or Stem/Branch in Chinese (e.g. 庚金, 戊土). "
            "2. The metaphysical/structure focus in Chinese (e.g. 食神, 偏印, 官杀). "
            "3. The domain query in Chinese (e.g. 财运, 寿夭, 贵贱)."
        )
    )


@mcp.tool()
async def search_bazi(
    query: Annotated[str | None, "Natural language search query in English or Chinese. If provided, we translate/expand it into BaZi terms."] = None,
    keywords: Annotated[list[str] | None, "Alternatively, pass exactly 3 Chinese search terms directly."] = None,
) -> str:
    """
    Search classical Bazi (八字) texts for passages relevant to the query or keywords.
    Uses Pydantic AI with the configured baziRAG_model to expand natural language queries into classical Chinese terms.

    Args:
        query: Natural language query (e.g. "Find Geng Metal Day Master facing weak health when wood is strong.").
        keywords: Optional list of exactly 3 Chinese search terms directly.
    """
    if not query and not keywords:
        return json.dumps({"error": "Either query or keywords must be provided."}, ensure_ascii=False)

    final_keywords = await _normalize_keywords(query, keywords)
    sys.stderr.write(f"Executing local BaziRAG search for keywords: {final_keywords}\n")

    client = AsyncQdrantClient(path=QDRANT_PATH)
    try:
        if not await _check_collection_exists(client):
            return json.dumps(
                {"error": f"Collection '{COLLECTION_NAME}' not found in {QDRANT_PATH}."},
                ensure_ascii=False,
            )

        output = await _search_all_keywords(client, final_keywords)
        return json.dumps(output, ensure_ascii=False, indent=2)
    finally:
        await client.close()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # We enforce stdio transport since this is a local tool exclusively for OpenCode
    mcp.run(transport="stdio")