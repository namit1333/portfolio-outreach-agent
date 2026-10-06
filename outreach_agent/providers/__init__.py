"""Provider factory: pick LLM + research backends from settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import Settings
from ..http import ProviderError
from .base import LLMClient, SearchClient


@dataclass
class ProviderStack:
    llm: LLMClient
    search_client: Optional[SearchClient]
    provider_name: str          # anthropic | openai | mock
    research_mode: str          # web_tool | search_api | mock
    model: str = ""
    notes: list = None          # type: ignore[assignment]

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


def build_stack(settings: Settings) -> ProviderStack:
    """Resolve --provider/--search into concrete clients.

    auto: ANTHROPIC_API_KEY > OPENAI_API_KEY > mock (offline demo).
    Research uses the LLM provider's built-in web search tool unless an
    explicit --search backend is configured.
    """
    from .anthropic_provider import AnthropicLLM
    from .mock_provider import MockLLM
    from .openai_provider import OpenAILLM
    from .search_provider import SerperSearch, TavilySearch

    notes: list = []
    provider = settings.provider
    if provider == "auto":
        if settings.anthropic_api_key:
            provider = "anthropic"
        elif settings.openai_api_key:
            provider = "openai"
        else:
            provider = "mock"
            notes.append("no LLM API key found - running offline mock providers (demo data)")

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ProviderError("provider=anthropic but ANTHROPIC_API_KEY is not set")
        llm: LLMClient = AnthropicLLM(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout=settings.timeout,
        )
        model = settings.anthropic_model
    elif provider == "openai":
        if not settings.openai_api_key:
            raise ProviderError("provider=openai but OPENAI_API_KEY is not set")
        llm = OpenAILLM(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout=settings.timeout,
        )
        model = settings.openai_model
    elif provider == "mock":
        llm = MockLLM()
        model = "mock"
    else:
        raise ProviderError(f"unknown provider '{provider}' (use auto|anthropic|openai|mock)")

    search_client: Optional[SearchClient] = None
    search = settings.search
    if search == "auto":
        search = "tavily" if settings.tavily_api_key else ("serper" if settings.serper_api_key else "none")

    if search == "tavily":
        if not settings.tavily_api_key:
            raise ProviderError("search=tavily but TAVILY_API_KEY is not set")
        search_client = TavilySearch(api_key=settings.tavily_api_key, timeout=settings.timeout)
    elif search == "serper":
        if not settings.serper_api_key:
            raise ProviderError("search=serper but SERPER_API_KEY is not set")
        search_client = SerperSearch(api_key=settings.serper_api_key, timeout=settings.timeout)
    elif search not in ("none", ""):
        raise ProviderError(f"unknown search backend '{search}' (use auto|tavily|serper|none)")

    if provider == "mock":
        research_mode = "mock"
    elif search_client is not None:
        research_mode = "search_api"
    elif llm.web_research_tools() is not None:
        research_mode = "web_tool"
    else:
        raise ProviderError(
            "no research capability: set a search API key (TAVILY_API_KEY/SERPER_API_KEY) "
            "or use a provider with built-in web search"
        )

    return ProviderStack(
        llm=llm,
        search_client=search_client,
        provider_name=provider,
        research_mode=research_mode,
        model=model,
        notes=notes,
    )
