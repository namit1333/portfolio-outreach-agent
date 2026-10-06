"""Settings: .env + environment + CLI overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def load_dotenv(path: str = ".env") -> dict:
    """Tiny .env parser (KEY=VALUE lines, # comments). Never overrides real env."""
    values: dict = {}
    env_path = Path(path)
    if not env_path.is_file():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            values.setdefault(key, value)
    return values


@dataclass
class Settings:
    provider: str = "auto"          # auto | anthropic | openai | mock
    search: str = "auto"            # auto | tavily | serper | none
    limit: int = 10
    concurrency: int = 4
    min_score: float = 35.0
    out_root: str = "runs"
    timeout: float = 90.0
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.1"
    tavily_api_key: str = ""
    serper_api_key: str = ""
    extra: dict = field(default_factory=dict)


def _env(dotenv: dict, key: str, default: str = "") -> str:
    return os.environ.get(key) or dotenv.get(key) or default


def build_settings(
    *,
    provider: Optional[str] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
    concurrency: Optional[int] = None,
    min_score: Optional[float] = None,
    out_root: Optional[str] = None,
    dotenv_path: str = ".env",
) -> Settings:
    dotenv = load_dotenv(dotenv_path)
    settings = Settings(
        provider=(provider or _env(dotenv, "OUTREACH_PROVIDER", "auto")).lower(),
        search=(search or _env(dotenv, "OUTREACH_SEARCH", "auto")).lower(),
        limit=int(limit or _env(dotenv, "OUTREACH_LIMIT", "10")),
        concurrency=int(concurrency or _env(dotenv, "OUTREACH_CONCURRENCY", "4")),
        min_score=float(min_score or _env(dotenv, "OUTREACH_MIN_SCORE", "35")),
        out_root=out_root or _env(dotenv, "OUTREACH_OUT_ROOT", "runs"),
        anthropic_api_key=_env(dotenv, "ANTHROPIC_API_KEY"),
        anthropic_model=_env(dotenv, "ANTHROPIC_MODEL", "claude-opus-5-5"),
        openai_api_key=_env(dotenv, "OPENAI_API_KEY"),
        openai_model=_env(dotenv, "OPENAI_MODEL", "gpt-5.1"),
        tavily_api_key=_env(dotenv, "TAVILY_API_KEY"),
        serper_api_key=_env(dotenv, "SERPER_API_KEY"),
    )
    return settings


def describe_settings(settings: Settings) -> list[tuple[str, str]]:
    """Human-readable provider/key status lines for the `providers` command."""
    def masked(value: str) -> str:
        return f"set ({value[:4]}…{value[-4:]})" if len(value) > 12 else ("set" if value else "not set")

    return [
        ("ANTHROPIC_API_KEY", masked(settings.anthropic_api_key)),
        ("ANTHROPIC_MODEL", settings.anthropic_model),
        ("OPENAI_API_KEY", masked(settings.openai_api_key)),
        ("OPENAI_MODEL", settings.openai_model),
        ("TAVILY_API_KEY", masked(settings.tavily_api_key)),
        ("SERPER_API_KEY", masked(settings.serper_api_key)),
        ("provider", settings.provider),
        ("search", settings.search),
    ]
