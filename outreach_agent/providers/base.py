"""Provider interfaces: LLM clients and search clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from ..models import EvidenceQuote


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass
class LLMResult:
    text: str
    citations: list[EvidenceQuote] = field(default_factory=list)
    raw: Any = None


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 2048,
        tools: Optional[list] = None,
    ) -> LLMResult:
        """Run one completion. `tools` are provider-native tool descriptors."""
        ...

    def web_research_tools(self) -> Optional[list]:
        """Tool descriptors that give the model live web search, or None if the
        provider cannot search the web itself."""
        ...


@runtime_checkable
class SearchClient(Protocol):
    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        ...
