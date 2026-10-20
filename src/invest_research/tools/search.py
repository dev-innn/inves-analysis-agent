from __future__ import annotations

import random
import time
import os
import re
from datetime import date, timedelta
from urllib.parse import urlparse

import httpx

from ..schemas import Source


def relevant_results(company: dict, summary: str, sources: list[Source]) -> tuple[str, list[Source]]:
    """Company-name screening is discovery filtering, not factual verification."""
    words = re.findall(r"[a-z0-9]+", company["legal_name"].lower())
    terms = [w for w in words if w not in {"inc", "corp", "corporation", "company", "co", "ltd", "plc", "the", "and", "holdings"}]
    ticker = company.get("ticker", "").lower()
    if len(ticker) > 1:
        terms.append(ticker)
    kept, lines = [], []
    for source in sources:
        # Do not let another result's company mention validate this URL.
        matching = [line for line in summary.splitlines() if f"[{source.source_id}]" in line or str(source.url) in line]
        haystack = " ".join([source.title, str(source.url), *matching]).lower()
        if any(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", haystack) for term in terms):
            kept.append(source)
            lines.extend(matching or [f"[{source.source_id}] {source.title} ({source.url})；仅链接，未读取正文"])
    return "\n".join(lines) or "未找到与公司相关的可引用网页结果。", kept


class SerpApiSearchTool:
    """Return Google organic results for a separate analysis agent to review."""

    def __init__(self, api_key: str, max_queries: int = 3, max_results: int = 8, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise ValueError("SERPAPI_API_KEY is required when SEARCH_PROVIDER=serpapi")
        if max_queries < 1 or max_results < 1:
            raise ValueError("Search query and result limits must be positive")
        self.api_key = api_key
        self.max_queries = max_queries
        self.max_results = max_results
        self.used = 0
        self.client = httpx.Client(timeout=httpx.Timeout(30, connect=10), transport=transport)

    def search(self, query: str, as_of_date: str) -> tuple[str, list[Source]]:
        if self.used >= self.max_queries:
            raise ValueError("Search query budget exhausted")
        cutoff = date.fromisoformat(as_of_date)
        self.used += 1
        params = {
            "engine": "google",
            "q": f"{query} before:{(cutoff + timedelta(days=1)).isoformat()}",
            "api_key": self.api_key,
            "hl": "en",
            "gl": "us",
            "num": self.max_results,
        }
        for attempt in range(3):
            try:
                response = self.client.get("https://serpapi.com/search.json", params=params)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep((2**attempt) + random.random())
                    continue
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict) or body.get("error"):
                    raise RuntimeError("SerpApi search failed or returned invalid JSON")
                results = body.get("organic_results")
                if not isinstance(results, list):
                    raise RuntimeError("SerpApi response has no organic_results list")
                sources: list[Source] = []
                snippets: list[dict[str, str]] = []
                seen_urls: set[str] = set()
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    link = item.get("link", "")
                    parsed = urlparse(link) if isinstance(link, str) else None
                    if not parsed or parsed.scheme != "https" or not parsed.netloc or link in seen_urls:
                        continue
                    seen_urls.add(link)
                    source_id = f"web-{self.used}-{len(sources) + 1}"
                    title = str(item.get("title") or link)[:300]
                    sources.append(Source(source_id=source_id, type="web", title=title, url=link, publisher=str(item.get("source") or parsed.hostname)[:120]))
                    snippets.append({"source_id": source_id, "title": title, "snippet": str(item.get("snippet") or "")[:800], "url": link})
                    if len(sources) >= self.max_results:
                        break
                if not sources:
                    raise RuntimeError("SerpApi returned no usable HTTPS organic results")
                # Search snippets are discovery data, not verified page contents.
                summary = "Google organic search results (unverified snippets):\n" + "\n".join(
                    f"[{row['source_id']}] {row['title']} — {row['snippet']} ({row['url']})" for row in snippets
                )
                return summary, sources
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                retryable = status in {429, 500, 502, 503, 504}
                if not retryable:
                    raise RuntimeError(f"SerpApi rejected the request (HTTP {status})") from None
                if attempt == 2:
                    raise TimeoutError(f"SerpApi temporarily unavailable (HTTP {status})") from None
                time.sleep((2**attempt) + random.random())
            except httpx.TransportError:
                if attempt == 2:
                    raise TimeoutError("SerpApi network request failed") from None
                time.sleep((2**attempt) + random.random())
        raise RuntimeError("SerpApi search unavailable")


class GoogleSearchTool:
    """Google Search Grounding via Gemini; returns attributable summaries, not raw SERP."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", max_queries: int = 3, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for Google Search Grounding")
        self.api_key = api_key
        self.model = model
        self.max_queries = max_queries
        self.used = 0
        self.client = httpx.Client(timeout=httpx.Timeout(45, connect=10), transport=transport)

    def search(self, query: str, as_of_date: str) -> tuple[str, list[Source]]:
        if self.used >= self.max_queries:
            raise ValueError("Search query budget exhausted")
        self.used += 1
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {"contents": [{"parts": [{"text": f"Research this public company as of {as_of_date}. Search: {query}. Summarize only supported facts and retain citations."}]}], "tools": [{"google_search": {}}]}
        for attempt in range(3):
            try:
                response = self.client.post(url, params={"key": self.api_key}, json=payload)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep((2**attempt) + random.random())
                    continue
                response.raise_for_status()
                body = response.json()
                candidate = body["candidates"][0]
                summary = "\n".join(p.get("text", "") for p in candidate["content"]["parts"])
                chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", [])
                sources = []
                for i, chunk in enumerate(chunks):
                    web = chunk.get("web", {})
                    link = web.get("uri", "")
                    if link.startswith("https://"):
                        sources.append(Source(source_id=f"web-{self.used}-{i}", type="web", title=web.get("title") or link, url=link, publisher=web.get("title") or "Google Search"))
                return summary, sources
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt == 2:
                    raise
                time.sleep((2**attempt) + random.random())
        raise RuntimeError("Search unavailable")


def search_tool_from_env() -> SerpApiSearchTool | GoogleSearchTool:
    """Select a web search backend independently of the CrewAI model provider."""
    provider = os.getenv("SEARCH_PROVIDER", "serpapi").strip().lower()
    if provider == "serpapi":
        return SerpApiSearchTool(os.getenv("SERPAPI_API_KEY", "").strip())
    if provider == "gemini_grounding":
        return GoogleSearchTool(os.getenv("GEMINI_API_KEY", "").strip(), os.getenv("GEMINI_SEARCH_MODEL", "gemini-2.5-flash"))
    raise ValueError("SEARCH_PROVIDER must be serpapi or gemini_grounding")
