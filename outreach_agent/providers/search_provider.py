"""Dedicated search API clients (Tavily / Serper)."""

from __future__ import annotations

from ..http import request_json
from .base import SearchResult

TAVILY_URL = "https://api.tavily.com/search"
SERPER_URL = "https://google.serper.dev/search"


class TavilySearch:
    def __init__(self, api_key: str, timeout: float = 60.0):
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        resp = request_json(
            "POST",
            TAVILY_URL,
            payload={
                "api_key": self.api_key,
                "query": query,
                "max_results": max(1, min(limit, 20)),
                "include_answer": False,
                "search_depth": "basic",
            },
            timeout=self.timeout,
        )
        results = []
        for item in resp.get("results") or []:
            results.append(SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("content") or ""),
            ))
        return results[:limit]


class SerperSearch:
    def __init__(self, api_key: str, timeout: float = 60.0):
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        resp = request_json(
            "POST",
            SERPER_URL,
            headers={"X-API-KEY": self.api_key},
            payload={"q": query, "num": max(1, min(limit, 20))},
            timeout=self.timeout,
        )
        results = []
        for item in resp.get("organic") or []:
            results.append(SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("link") or ""),
                snippet=str(item.get("snippet") or ""),
            ))
        return results[:limit]
