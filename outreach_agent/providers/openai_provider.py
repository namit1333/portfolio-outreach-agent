"""OpenAI Responses API provider with the web_search tool."""

from __future__ import annotations

from typing import Optional

from ..http import request_json
from ..models import EvidenceQuote
from .base import LLMResult

API_URL = "https://api.openai.com/v1/responses"


class OpenAILLM:
    def __init__(self, api_key: str, model: str, timeout: float = 90.0, max_searches: int = 6):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_searches = max_searches

    def web_research_tools(self) -> Optional[list]:
        return [{"type": "web_search"}]

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 2048,
        tools: Optional[list] = None,
    ) -> LLMResult:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
        resp = request_json("POST", API_URL, headers=headers, payload=body, timeout=self.timeout)

        text_parts: list[str] = []
        citations: list[EvidenceQuote] = []
        for item in resp.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict) or content.get("type") != "output_text":
                    continue
                text = str(content.get("text") or "")
                text_parts.append(text)
                for annotation in content.get("annotations") or []:
                    if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                        continue
                    start = annotation.get("start_index")
                    end = annotation.get("end_index")
                    cited = text[start:end] if isinstance(start, int) and isinstance(end, int) else ""
                    quote = EvidenceQuote(
                        text=str(cited or annotation.get("title") or ""),
                        url=str(annotation.get("url") or ""),
                        title=str(annotation.get("title") or ""),
                    )
                    if quote.url and quote.url not in {c.url for c in citations}:
                        citations.append(quote)

        return LLMResult(text="\n".join(p for p in text_parts if p).strip(), citations=citations, raw=resp)
