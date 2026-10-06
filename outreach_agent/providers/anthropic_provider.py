"""Anthropic Messages API provider with the server-side web search tool."""

from __future__ import annotations

from typing import Optional

from ..http import request_json
from ..models import EvidenceQuote
from .base import LLMResult

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicLLM:
    def __init__(self, api_key: str, model: str, timeout: float = 90.0, max_searches: int = 6):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_searches = max_searches

    def web_research_tools(self) -> Optional[list]:
        return [{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": self.max_searches,
        }]

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 2048,
        tools: Optional[list] = None,
    ) -> LLMResult:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
        }
        messages = [{"role": "user", "content": user}]
        text_parts: list[str] = []
        citations: list[EvidenceQuote] = []
        raw_last: dict = {}

        # The server-side search loop can pause with stop_reason "pause_turn";
        # continue by sending the assistant content back unchanged.
        for _ in range(4):
            body = {
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": messages,
            }
            if tools:
                body["tools"] = tools
            resp = request_json("POST", API_URL, headers=headers, payload=body, timeout=self.timeout)
            raw_last = resp
            blocks = resp.get("content") or []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text") or ""))
                    for citation in block.get("citations") or []:
                        quote = EvidenceQuote(
                            text=str(citation.get("cited_text") or ""),
                            url=str(citation.get("url") or ""),
                            title=str(citation.get("title") or ""),
                        )
                        if quote.url and (quote.url, quote.text[:40]) not in {
                            (c.url, c.text[:40]) for c in citations
                        }:
                            citations.append(quote)
            if resp.get("stop_reason") == "pause_turn":
                messages.append({"role": "assistant", "content": blocks})
                continue
            break

        return LLMResult(text="\n".join(p for p in text_parts if p).strip(), citations=citations, raw=raw_last)
