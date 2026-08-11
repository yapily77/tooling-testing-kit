import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import trafilatura
import yaml
from control import ControlSheet, SystemSettings
from pydantic import BaseModel, Field
from pydantic_ai import Agent

# =====================================================================
# 1. MODELS & SCHEMAS
# =====================================================================


class WebResponse(BaseModel):
    """The final synthesized result of a web search operation."""

    answer: str = Field(description="The comprehensive answer to the query, with inline citations [1], [2], etc.")
    citations: list[str] = Field(
        description="List of URLs used as evidence, ordered by their appearance in the answer."
    )
    evidence_paths: list[str] = Field(description="Paths to the cleaned markdown files in scratch/web_results/.")
    confidence: float = Field(description="Confidence score from 0.0 to 1.0 based on evidence quality and consistency.")


class SynthesisOutput(BaseModel):
    """The raw output from the LLM synthesizer."""

    answer: str = Field(description="The comprehensive answer to the query, with inline citations [1], [2], etc.")
    citations: list[str] = Field(
        description="List of URLs used as evidence, ordered by their appearance in the answer."
    )
    confidence: float = Field(description="Confidence score from 0.0 to 1.0 based on evidence quality and consistency.")


@dataclass
class SearchResult:
    url: str
    title: str
    provider: str
    rank: int
    snippet: str | None = None


# =====================================================================
# 2. SEARCH PROVIDERS
# =====================================================================


async def search_exa(query: str) -> list[SearchResult]:
    if not SystemSettings.exa_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": SystemSettings.exa_api_key},
                json={"query": query, "useAutoprompt": True, "numResults": 10},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                SearchResult(url=r["url"], title=r.get("title", "No Title"), provider="Exa", rank=i + 1)
                for i, r in enumerate(data.get("results", []))
            ]
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"Exa Search Error: {e}")
        raise
        return []


async def search_tavily(query: str) -> list[SearchResult]:
    if not SystemSettings.tavily_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": SystemSettings.tavily_api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": 10,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                SearchResult(url=r["url"], title=r.get("title", "No Title"), provider="Tavily", rank=i + 1)
                for i, r in enumerate(data.get("results", []))
            ]
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"Tavily Search Error: {e}")
        raise
        return []


async def search_searxng(query: str) -> list[SearchResult]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                SystemSettings.searxng_url,
                params={"q": query, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                SearchResult(url=r["url"], title=r.get("title", "No Title"), provider="SearXNG", rank=i + 1)
                for i, r in enumerate(data.get("results", [])[:30])
            ]
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"SearXNG Search Error: {e}")
        raise
        return []



def _fire_cleanup(orchestrator: "WebOrchestrator") -> None:
    task = asyncio.create_task(orchestrator.cleanup())
    orchestrator._background_tasks.add(task)
    task.add_done_callback(orchestrator._background_tasks.discard)


def _build_empty_response(evidence_files: list[Path]) -> WebResponse:
    return WebResponse(
        answer="No readable content was found for this query.",
        citations=[],
        evidence_paths=[str(p) for p in evidence_files],
        confidence=0.0,
    )


def _build_synthesized_response(evidence_files: list[Path], synthesis: SynthesisOutput) -> WebResponse:
    return WebResponse(
        answer=synthesis.answer,
        citations=synthesis.citations,
        evidence_paths=[str(p) for p in evidence_files],
        confidence=synthesis.confidence,
    )


# =====================================================================
# 3. ORCHESTRATOR
# =====================================================================



def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen_urls = set()
    unique_results = []
    for r in results:
        if r.url not in seen_urls:
            unique_results.append(r)
            seen_urls.add(r.url)
    return unique_results


def _extract_content(downloaded: str) -> tuple[str, bool]:
    if not downloaded:
        return "[This page returned empty content. It might require JavaScript to render.]", False
    content = _run_trafilatura(downloaded)
    if not content:
        return "[This page returned empty content. It might require JavaScript to render.]", False
    return content, True


def _run_trafilatura(downloaded: str) -> str | None:
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, lambda: trafilatura.extract(downloaded, include_comments=False, include_tables=True))


def _truncate_content(content: str) -> str:
    if len(content) > 15000:
        return content[:15000] + "\n\n... [Truncated for length] ..."
    return content


def _build_metadata(res: SearchResult, has_actual: bool) -> dict:
    return {
        "url": res.url,
        "title": res.title,
        "provider": res.provider,
        "rank": res.rank,
        "status": "extracted" if has_actual else "empty / potentially JS-rendered"
    }



class WebOrchestrator:
    def __init__(self):
        self.results_dir = Path("scratch/web_results")
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.model = ControlSheet.web_model
        self._background_tasks = set()

        # Load system prompt from external YAML file
        prompt_yaml_path = Path("infrastructure/prompt/web.yaml")
        if prompt_yaml_path.exists():
            with open(prompt_yaml_path, encoding="utf-8") as f:
                prompt_data = yaml.safe_load(f)
                sys_prompt = prompt_data.get("system_prompt", "")
        else:
            sys_prompt = "You are a high-fidelity knowledge synthesizer."

        self.agent = Agent(
            model=self.model,
            output_type=SynthesisOutput,
            system_prompt=sys_prompt,
        )

    def _get_query_hash(self, query: str) -> str:
        return hashlib.sha256(query.encode()).hexdigest()[:12]

    def _sanitize_domain(self, url: str) -> str:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            domain = domain.split(":")[0]  # remove port if any
            domain = re.sub(r"[^a-zA-Z0-9_]", "_", domain)
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
            return f"{domain}_{url_hash}"
        except (OSError, ValueError, AttributeError):
            return f"unknown_domain_{hashlib.sha256(url.encode()).hexdigest()[:8]}"

    async def fetch_and_extract(self, results: list[SearchResult], query_hash: str) -> tuple[list[Path], bool]:
        unique_results = _dedupe_results(results)
        targets = unique_results[:10]
        query_dir = self.results_dir / query_hash
        await asyncio.to_thread(query_dir.mkdir, exist_ok=True)

        semaphore = asyncio.Semaphore(5)
        tasks = [self._process_url(r, query_dir, semaphore) for r in targets]
        results_paths = await asyncio.gather(*tasks)

        evidence_files: list[Path] = []
        has_any_actual_content = False
        for item in results_paths:
            if item is not None:
                path, actual = item
                evidence_files.append(path)
                has_any_actual_content = has_any_actual_content or actual
        return evidence_files, has_any_actual_content

    async def _process_url(self, res: SearchResult, query_dir: Path, semaphore: asyncio.Semaphore) -> tuple[Path, bool] | None:
        async with semaphore:
            try:
                downloaded = await self._fetch_url_content(res.url)
                content, has_actual = _extract_content(downloaded)
                content = _truncate_content(content)
                metadata = _build_metadata(res, has_actual)
                file_content = f"---\n{yaml.dump(metadata)}---\n\n{content}"
                file_path = query_dir / f"{self._sanitize_domain(res.url)}.md"
                await asyncio.to_thread(file_path.write_text, file_content, encoding="utf-8")
                return file_path, has_actual
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
                print(f"Extraction Error [{res.url}]: {e}")
                raise
                return None

    async def _fetch_url_content(self, url: str) -> str:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            resp.raise_for_status()
            return resp.text

    async def synthesize(self, query: str, evidence_files: list[Path]) -> SynthesisOutput:
        if not evidence_files:
            return SynthesisOutput(
                answer="No readable content was found for this query.", citations=[], confidence=0.0
            )

        context = []
        for p in evidence_files:
            content = await asyncio.to_thread(p.read_text, encoding='utf-8')
            context.append(f"--- FILE: {p.name} ---\n{content}\n")

        full_prompt = f"Query: {query}\n\nEvidence:\n\n" + "\n".join(context)

        result = await self.agent.run(full_prompt)
        return result.output

    async def cleanup(self):
        """Prune scratch/web_results (7-day TTL / 100 folder cap)."""
        try:
            if not self.results_dir.exists():
                return

            import time
            now = time.time()

            def prune_ttl():
                import shutil
                for folder in self.results_dir.iterdir():
                    if folder.is_dir() and (now - folder.stat().st_mtime > 7 * 86400):
                        shutil.rmtree(folder)

            await asyncio.to_thread(prune_ttl)

            def prune_capacity():
                import shutil
                folders = sorted([f for f in self.results_dir.iterdir() if f.is_dir()], key=lambda x: x.stat().st_mtime)
                while len(folders) > 100:
                    shutil.rmtree(folders.pop(0))

            await asyncio.to_thread(prune_capacity)
        except (OSError, ValueError, TypeError) as e:
            print(f"Cleanup Error: {e}")

    async def run(self, query: str) -> WebResponse:
        all_results = await self._get_search_results(query)
        query_hash = self._get_query_hash(query)
        print(f"Extracting content for {len(all_results)} results...")
        evidence_files, has_any_actual = await self.fetch_and_extract(all_results, query_hash)
        response = await self._build_response(query, evidence_files, has_any_actual)
        _fire_cleanup(self)
        return response

    async def _get_search_results(self, query: str) -> list[SearchResult]:
        query_stripped = query.strip()
        if query_stripped.startswith(("http://", "https://")):
            print(f"Direct URL detected, skipping search: {query_stripped}")
            return [SearchResult(url=query_stripped, title="Direct URL", provider="Direct", rank=1)]
        print(f"Searching for: {query}...")
        search_results_lists = await asyncio.gather(search_exa(query), search_tavily(query), search_searxng(query))
        return [item for sublist in search_results_lists for item in sublist]

    async def _build_response(self, query: str, evidence_files: list[Path], has_any_actual: bool) -> WebResponse:
        if not has_any_actual:
            return _build_empty_response(evidence_files)
        print(f"Synthesizing result from {len(evidence_files)} files...")
        synthesis = await self.synthesize(query, evidence_files)
        return _build_synthesized_response(evidence_files, synthesis)


# =====================================================================
# 4. CLI ENTRY POINT
# =====================================================================


async def main():
    import sys

    if len(sys.argv) < 2:
        print('Usage: uv run python kit-tools/web.py "query"')
        sys.exit(1)

    query = sys.argv[1]
    orchestrator = WebOrchestrator()

    try:
        response = await orchestrator.run(query)

        print("\n" + "=" * 40)
        print(f"ANSWER (Confidence: {response.confidence})")
        print("=" * 40)
        print(response.answer)
        print("\n" + "=" * 40)
        print("CITATIONS")
        print("=" * 40)
        for i, url in enumerate(response.citations, 1):
            print(f"[{i}] {url}")
        print("\nEvidence stored at:", response.evidence_paths)

    except (RuntimeError, OSError, ValueError) as e:
        print(f"Fatal Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
