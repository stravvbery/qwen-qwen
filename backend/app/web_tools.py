"""Web-search and page-scraping tools for LLM tool-calling.

Provides three providers:
- Tavily  – AI-optimised web search
- Serper  – Google SERP results
- Firecrawl – clean markdown scrape of a URL

The module exposes:
- ``TOOL_DEFINITIONS``  – OpenAI-compatible tool specs to send to Fireworks
- ``execute_tool_call`` – dispatcher that runs a tool by name and returns text
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the internet for current information on any topic. "
                "Use this when you need up-to-date facts, recent events, "
                "real-time data, or anything beyond your training cutoff."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to look up on the web.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_webpage",
            "description": (
                "Fetch and read the full content of a specific web page URL. "
                "Use this when you have a URL and need to read its contents "
                "in detail — for example a link from search results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL of the page to read.",
                    },
                },
                "required": ["url"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


async def _tavily_search(query: str) -> str:
    """Run a search via Tavily and return a text summary."""
    key = settings.tavily_api_key
    if not key:
        return "[Tavily API key not configured]"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": True,
            },
        )
        if resp.status_code >= 400:
            log.warning("Tavily error %s: %s", resp.status_code, resp.text[:300])
            return f"[Tavily search failed: HTTP {resp.status_code}]"
        data = resp.json()

    parts: list[str] = []
    answer = data.get("answer")
    if answer:
        parts.append(f"Summary: {answer}\n")
    results = data.get("results") or []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        parts.append(f"{i}. [{title}]({url})\n{content}\n")
    return "\n".join(parts) if parts else "[No results found]"


async def _serper_search(query: str) -> str:
    """Run a Google search via Serper.dev and return formatted results."""
    key = settings.serper_api_key
    if not key:
        return "[Serper API key not configured]"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": key,
                "Content-Type": "application/json",
            },
            json={"q": query, "num": 5},
        )
        if resp.status_code >= 400:
            log.warning("Serper error %s: %s", resp.status_code, resp.text[:300])
            return f"[Serper search failed: HTTP {resp.status_code}]"
        data = resp.json()

    parts: list[str] = []
    kg = data.get("knowledgeGraph")
    if kg:
        parts.append(
            f"Knowledge Graph: {kg.get('title', '')} — {kg.get('description', '')}\n"
        )
    answer_box = data.get("answerBox")
    if answer_box:
        parts.append(f"Answer: {answer_box.get('answer') or answer_box.get('snippet', '')}\n")
    organic = data.get("organic") or []
    for i, r in enumerate(organic, 1):
        title = r.get("title", "")
        link = r.get("link", "")
        snippet = r.get("snippet", "")
        parts.append(f"{i}. [{title}]({link})\n{snippet}\n")
    return "\n".join(parts) if parts else "[No results found]"


async def _firecrawl_scrape(url: str) -> str:
    """Scrape a URL via Firecrawl and return markdown content."""
    key = settings.firecrawl_api_key
    if not key:
        return "[Firecrawl API key not configured]"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        resp = await client.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={"url": url, "formats": ["markdown"]},
        )
        if resp.status_code >= 400:
            log.warning("Firecrawl error %s: %s", resp.status_code, resp.text[:300])
            return f"[Firecrawl scrape failed: HTTP {resp.status_code}]"
        data = resp.json()

    fc_data = data.get("data") or {}
    markdown = fc_data.get("markdown") or ""
    if not markdown:
        return "[Page returned no content]"
    if len(markdown) > 12000:
        markdown = markdown[:12000] + "\n\n[... content truncated for context length ...]"
    return markdown


async def _combined_search(query: str) -> str:
    """Run search through available providers and merge results."""
    results: list[str] = []

    if settings.tavily_api_key:
        tavily_result = await _tavily_search(query)
        results.append(f"=== Tavily Search Results ===\n{tavily_result}")

    if settings.serper_api_key:
        serper_result = await _serper_search(query)
        results.append(f"=== Google Search Results (Serper) ===\n{serper_result}")

    if not results:
        return "[No search providers configured. Set TAVILY_API_KEY or SERPER_API_KEY.]"

    return "\n\n".join(results)


async def execute_tool_call(name: str, arguments: str) -> str:
    """Execute a tool call and return the result as a string."""
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return f"[Invalid arguments: {arguments}]"

    if name == "web_search":
        query = args.get("query", "")
        if not query:
            return "[Missing 'query' argument]"
        return await _combined_search(query)

    if name == "read_webpage":
        url = args.get("url", "")
        if not url:
            return "[Missing 'url' argument]"
        return await _firecrawl_scrape(url)

    return f"[Unknown tool: {name}]"


def has_any_provider() -> bool:
    """Return True if at least one search provider is configured."""
    return bool(
        settings.tavily_api_key
        or settings.serper_api_key
        or settings.firecrawl_api_key
    )
