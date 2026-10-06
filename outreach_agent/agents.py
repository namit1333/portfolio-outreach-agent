"""Agent layer: planner, scout, and writer agents + prompt contracts.

Each agent is a single focused worker. The pipeline fans scouts and writers out
in parallel. System prompts carry the [PLAN]/[SCOUT]/[WRITE] stage markers,
which the mock provider routes on (harmless for real providers).
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .models import (
    Candidate,
    EmailDraft,
    EvidenceQuote,
    ResearchPlan,
    Sender,
    TargetKind,
)
from .providers.base import LLMClient, SearchClient

PLAN_CONTRACT = """{
  "kind": "business" | "talent",
  "target_description": "one paragraph restating who we are looking for",
  "criteria": ["3-6 fit criteria, each short and checkable"],
  "nice_to_have": ["bonus signals"],
  "geography": "region or empty string",
  "exclusions": ["what to skip"],
  "queries": ["5-8 web search queries covering different angles"],
  "message_goal": "what the outreach should achieve",
  "sender": {"name": "", "role": "", "organization": "", "voice": "tone guidance"}
}"""

CANDIDATE_CONTRACT = """{
  "candidates": [
    {
      "name": "person or business name",
      "headline": "role/category line",
      "organization": "employer (talent mode) or empty",
      "website": "their OWN website URL or empty",
      "profile_url": "public profile URL or empty",
      "location": "city, region or empty",
      "email": "ONLY an email literally published on a source page, else empty",
      "phone": "ONLY a phone literally published on a source page, else empty",
      "contact_person": "named person if a source names them, else empty",
      "contact_role": "their role if named, else empty",
      "fit_reason": "1-2 sentences on why they fit, grounded in the evidence",
      "criteria_matched": ["criteria from the plan this candidate satisfies"],
      "evidence": [{"text": "verbatim supporting quote", "url": "source URL", "title": "page title"}]
    }
  ]
}"""

PLANNER_SYSTEM = (
    "[PLAN] You are a research planner for a venture platform team. Given a portfolio "
    "support request, produce a research plan that other agents will execute.\n"
    "- 'business' mode finds companies/partners to reach out to; 'talent' mode finds "
    "individual professionals and the companies that employ them.\n"
    "- Queries must cover different angles: industry terms, trade associations and "
    "directories, geography, project/portfolios pages, news, and profile pages.\n"
    "- Criteria must be checkable from public web pages.\n"
    "Reply with ONLY strict JSON matching this contract, no commentary:\n"
    + PLAN_CONTRACT
)

SCOUT_SYSTEM = (
    "[SCOUT] You are a sourcing scout agent. Find real, current organizations or "
    "people matching the research plan for your assigned query.\n"
    "HARD RULES (sourcing policy):\n"
    "- NEVER invent or guess contact data. No guessed email patterns (info@, "
    "first.last@), no inferred phones. If a contact is not literally published on a "
    "source page, leave the field empty. Empty is always acceptable.\n"
    "- Every claim needs a verbatim evidence quote with its source URL. Prefer the "
    "subject's OWN website; aggregator/profile pages are fine as evidence but never "
    "as their website.\n"
    "- Only include real entities you found in search results. If results are thin, "
    "return fewer candidates rather than padding.\n"
    "Reply with ONLY strict JSON matching this contract, no commentary:\n"
    + CANDIDATE_CONTRACT
)

WRITER_SYSTEM = (
    "[WRITE] You write short, personal outreach messages for a venture platform "
    "professional helping portfolio companies.\n"
    "Rules:\n"
    "- Reference only facts that appear in the provided evidence. Never invent "
    "details, names, or history.\n"
    "- 80-130 words. Specific opening line grounded in the evidence, one clear "
    "low-friction ask, no cliches ('I hope this finds you well', 'game-changing'), "
    "no flattery padding.\n"
    "- Subject: max 60 characters, specific, not clickbait.\n"
    "- If sending to someone with no verified email, write it as a short note that "
    "works as a LinkedIn message or contact-form entry.\n"
    "Reply with ONLY strict JSON: "
    '{"subject": "...", "body": "...", "personalization_notes": "..."}'
)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def extract_json(text: str):
    """Pull the first JSON object/array out of possibly-fenced model output."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    decoder = json.JSONDecoder()
    for chunk in candidates:
        for index, char in enumerate(chunk):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(chunk[index:])
                return value
            except json.JSONDecodeError:
                continue
    return None


def _evidence_from(items) -> list[EvidenceQuote]:
    quotes: list[EvidenceQuote] = []
    for item in items or []:
        if isinstance(item, dict):
            quotes.append(EvidenceQuote(
                text=str(item.get("text") or ""),
                url=str(item.get("url") or ""),
                title=str(item.get("title") or ""),
            ))
    return quotes


def candidate_from_dict(data: dict, kind: TargetKind, query: str = "") -> Candidate:
    def s(key: str) -> str:
        value = data.get(key)
        return str(value).strip() if value is not None else ""

    return Candidate(
        kind=kind,
        name=s("name"),
        headline=s("headline"),
        organization=s("organization"),
        website=s("website"),
        profile_url=s("profile_url"),
        location=s("location"),
        email=s("email"),
        phone=s("phone"),
        contact_person=s("contact_person"),
        contact_role=s("contact_role"),
        fit_reason=s("fit_reason"),
        criteria_matched=[str(c) for c in data.get("criteria_matched") or []],
        evidence=_evidence_from(data.get("evidence")),
        source_urls=[str(u) for u in data.get("source_urls") or []],
        scout_query=query,
    )


# ---------------------------------------------------------------------------
# Planner agent
# ---------------------------------------------------------------------------

class PlannerAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        request: str,
        kind_hint: str = "auto",
        target_count: int = 10,
        sender: Optional[Sender] = None,
    ) -> tuple[ResearchPlan, list[str]]:
        warnings: list[str] = []
        user = (
            f"REQUEST:\n{request}\n\n"
            f"kind_hint={kind_hint}\n"
            f"target_count={target_count}\n"
        )
        payload = extract_json(self.llm.complete(PLANNER_SYSTEM, user).text)
        if not isinstance(payload, dict):
            payload = extract_json(self.llm.complete(
                PLANNER_SYSTEM, user + "\nYour previous reply was not valid JSON. Reply with ONLY the JSON object."
            ).text)
        if not isinstance(payload, dict):
            from .providers.mock_provider import heuristic_plan_dict

            warnings.append("planner: model returned no valid JSON; fell back to heuristic plan")
            payload = heuristic_plan_dict(request, kind_hint, target_count)

        try:
            kind = TargetKind(str(payload.get("kind") or "").lower())
        except ValueError:
            from .providers.mock_provider import detect_kind

            kind = TargetKind(detect_kind(request, kind_hint))
            warnings.append(f"planner: invalid kind in plan; inferred '{kind.value}'")

        plan = ResearchPlan(
            kind=kind,
            request=request,
            target_description=str(payload.get("target_description") or request),
            criteria=[str(c) for c in payload.get("criteria") or []],
            nice_to_have=[str(c) for c in payload.get("nice_to_have") or []],
            geography=str(payload.get("geography") or ""),
            exclusions=[str(c) for c in payload.get("exclusions") or []],
            queries=[str(q) for q in payload.get("queries") or [] if str(q).strip()],
            message_goal=str(payload.get("message_goal") or "get a reply and start a conversation"),
            sender=_sender_from(payload.get("sender")),
            target_count=int(payload.get("target_count") or target_count),
        )
        if not plan.queries:
            from .providers.mock_provider import heuristic_plan_dict

            plan.queries = heuristic_plan_dict(request, kind_hint, target_count)["queries"]
            warnings.append("planner: no queries produced; fell back to heuristic queries")

        if sender:
            merged = plan.sender
            plan.sender = Sender(
                name=sender.name or merged.name,
                role=sender.role or merged.role,
                organization=sender.organization or merged.organization,
                voice=merged.voice,
            )
        return plan, warnings


def _sender_from(data) -> Sender:
    if not isinstance(data, dict):
        return Sender()
    def s(key: str) -> str:
        value = data.get(key)
        return str(value).strip() if value is not None else ""
    return Sender(name=s("name"), role=s("role"), organization=s("organization"), voice=s("voice"))


# ---------------------------------------------------------------------------
# Scout agent
# ---------------------------------------------------------------------------

class ScoutAgent:
    """Researches one query and returns evidence-grounded candidates.

    research_mode:
      - web_tool:   the LLM has a built-in web search tool (Anthropic/OpenAI)
      - search_api: we run a Tavily/Serper search and the LLM extracts from SERP
      - mock:       offline fixtures
    """

    def __init__(self, llm: LLMClient, search_client: Optional[SearchClient] = None,
                 research_mode: str = "web_tool"):
        self.llm = llm
        self.search_client = search_client
        self.research_mode = research_mode

    def run(self, plan: ResearchPlan, query: str, limit: int = 6) -> list[Candidate]:
        kind = plan.kind
        plan_block = _plan_block(plan)
        user = (
            f"{plan_block}\n"
            f"ASSIGNED QUERY: {query}\n"
            f"[KIND:{kind.value}]\n"
            f"Return up to {limit} candidates as strict JSON."
        )

        citations: list[EvidenceQuote] = []
        if self.research_mode == "search_api":
            if self.search_client is None:
                return []
            results = self.search_client.search(query, limit=8)
            serp = "\n\n".join(
                f"## {r.title}\nURL: {r.url}\n{r.snippet}" for r in results if r.url
            )
            user = (
                "SEARCH RESULTS for your query (treat these as your only source):\n\n"
                + (serp or "(no results)")
                + "\n\n" + user
            )

        tools = self.llm.web_research_tools() if self.research_mode != "search_api" else None
        result = self.llm.complete(SCOUT_SYSTEM, user, max_tokens=3000, tools=tools)
        citations = result.citations

        payload = extract_json(result.text)
        if not isinstance(payload, dict):
            payload = extract_json(self.llm.complete(
                SCOUT_SYSTEM,
                user + "\nYour previous reply was not valid JSON. Reply with ONLY the JSON object.",
                max_tokens=3000,
                tools=tools,
            ).text)
        if not isinstance(payload, dict):
            return []

        candidates = []
        for item in payload.get("candidates") or []:
            if not isinstance(item, dict):
                continue
            candidate = candidate_from_dict(item, kind, query)
            _attach_citations(candidate, citations)
            if candidate.name:
                candidates.append(candidate)
        return candidates[:limit]


def _attach_citations(candidate: Candidate, citations: list[EvidenceQuote]) -> None:
    """Ground the candidate in the model's cited sources: attach any citation
    that names the candidate or shares one of its URLs."""
    if not citations:
        return
    name = candidate.name.lower()
    known_urls = {q.url for q in candidate.evidence} | set(candidate.source_urls)
    for quote in citations:
        if quote.url in known_urls:
            continue
        haystack = (quote.text + " " + quote.title).lower()
        if name and name in haystack:
            candidate.evidence.append(quote)
            candidate.source_urls.append(quote.url)


def _plan_block(plan: ResearchPlan) -> str:
    lines = [
        f"TARGET: {plan.target_description}",
        f"MODE: {plan.kind.value}",
    ]
    if plan.geography:
        lines.append(f"GEOGRAPHY: {plan.geography}")
    if plan.criteria:
        lines.append("FIT CRITERIA: " + "; ".join(plan.criteria))
    if plan.nice_to_have:
        lines.append("NICE TO HAVE: " + "; ".join(plan.nice_to_have))
    if plan.exclusions:
        lines.append("EXCLUDE: " + "; ".join(plan.exclusions))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Writer agent
# ---------------------------------------------------------------------------

class WriterAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def draft(self, plan: ResearchPlan, candidate: Candidate) -> EmailDraft:
        sender = plan.sender
        facts = "\n".join([
            f"name={candidate.name}",
            f"headline={candidate.headline}",
            f"organization={candidate.organization}",
            f"contact_person={candidate.contact_person}",
            f"location={candidate.location}",
            f"email={candidate.email}",
            f"profile_url={candidate.profile_url}",
            f"fit_reason={candidate.fit_reason}",
            f"message_goal={plan.message_goal}",
            f"sender_name={sender.name or '[Your name]'}",
            f"sender_role={sender.role}",
            f"sender_organization={sender.organization}",
            f"sender_voice={sender.voice or 'concise, warm, peer-to-peer'}",
            f"[KIND:{plan.kind.value}]",
        ])
        evidence_block = "\n".join(
            f"- ({q.url}) \"{q.short()}\"" for q in candidate.evidence[:6]
        ) or "(none)"
        criteria_block = "\n".join(f"- {c}" for c in candidate.criteria_matched) or "(none)"
        user = (
            f"{facts}\n"
            f"EVIDENCE (the only facts you may reference):\n{evidence_block}\n"
            f"CRITERIA THIS CANDIDATE MATCHES:\n{criteria_block}\n"
            f"Write the outreach message as strict JSON."
        )

        payload = extract_json(self.llm.complete(WRITER_SYSTEM, user, max_tokens=1200).text)
        if not isinstance(payload, dict):
            payload = extract_json(self.llm.complete(
                WRITER_SYSTEM,
                user + "\nYour previous reply was not valid JSON. Reply with ONLY the JSON object.",
                max_tokens=1200,
            ).text)
        if not isinstance(payload, dict):
            payload = _fallback_draft(plan, candidate)

        body = str(payload.get("body") or "").strip() or f"Hi,\n\n{candidate.fit_reason}\n\nBest,\n{sender.name or '[Your name]'}"
        subject = str(payload.get("subject") or "").strip() or "Quick question"
        notes = str(payload.get("personalization_notes") or "").strip()
        send_via = (
            "email" if candidate.email
            else "linkedin" if candidate.profile_url
            else "contact_form"
        )
        return EmailDraft(subject=subject[:100], body=body, send_via=send_via, personalization_notes=notes)


def _fallback_draft(plan: ResearchPlan, candidate: Candidate) -> dict:
    sender = plan.sender
    first = candidate.contact_person.split()[0] if candidate.contact_person else "there"
    return {
        "subject": f"Quick intro — {candidate.name}"[:60],
        "body": (
            f"Hi {first},\n\n"
            f"I came across {candidate.name} and {candidate.fit_reason or 'wanted to reach out'}.\n\n"
            f"I'm reaching out to {plan.message_goal}. Open to a short call?\n\n"
            f"Best,\n{sender.name or '[Your name]'}"
        ),
        "personalization_notes": "Fallback draft: model output was unusable.",
    }
