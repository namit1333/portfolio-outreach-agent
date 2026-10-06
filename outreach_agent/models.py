"""Data models for the portfolio outreach pipeline."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TargetKind(str, Enum):
    BUSINESS = "business"
    TALENT = "talent"


class SourceQuality(str, Enum):
    """Where a piece of evidence came from. Ranks trust for scoring."""

    OWN_SITE = "own_site"      # the business's / person's own website
    SOCIAL = "social"          # their own social profile (evidence, not a website)
    DIRECTORY = "directory"    # trade association, chamber, listing
    PRESS = "press"            # press release / news outlet
    UNKNOWN = "unknown"


@dataclass
class EvidenceQuote:
    text: str
    url: str = ""
    title: str = ""

    def short(self, limit: int = 220) -> str:
        text = " ".join(self.text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class Sender:
    """Who the outreach is from. Extracted from the request, overridable via CLI."""

    name: str = ""
    role: str = ""
    organization: str = ""
    voice: str = ""

    def signature(self) -> str:
        lines = [p for p in (self.name, self.role, self.organization) if p]
        return "\n".join(lines)


@dataclass
class ResearchPlan:
    kind: TargetKind
    request: str
    target_description: str = ""
    criteria: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    geography: str = ""
    exclusions: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    message_goal: str = ""
    sender: Sender = field(default_factory=Sender)
    target_count: int = 10


@dataclass
class EmailDraft:
    subject: str
    body: str
    send_via: str = "email"  # email | linkedin | contact_form
    personalization_notes: str = ""


@dataclass
class Candidate:
    kind: TargetKind
    name: str
    headline: str = ""            # talent: current role; business: category line
    organization: str = ""        # talent: employer
    website: str = ""
    profile_url: str = ""
    location: str = ""
    email: str = ""
    phone: str = ""
    contact_person: str = ""
    contact_role: str = ""
    fit_reason: str = ""
    criteria_matched: list[str] = field(default_factory=list)
    evidence: list[EvidenceQuote] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    draft: Optional[EmailDraft] = None
    warnings: list[str] = field(default_factory=list)
    scout_query: str = ""

    def evidence_text(self) -> str:
        return "\n".join(q.text for q in self.evidence)


@dataclass
class AgentEvent:
    stage: str          # plan | scout | curate | write | assemble
    agent: str          # e.g. "scout[2/6]"
    status: str         # started | ok | error
    detail: str = ""
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0


@dataclass
class RunResult:
    request: str
    plan: ResearchPlan
    candidates: list[Candidate]
    events: list[AgentEvent]
    warnings: list[str] = field(default_factory=list)
    providers: dict = field(default_factory=dict)
    created_at: str = ""
    out_dir: str = ""


def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses/enums into JSON-serializable values."""
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    return obj
