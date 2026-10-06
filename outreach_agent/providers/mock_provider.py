"""Offline mock provider: deterministic planning, fixtures, and drafts.

Everything here is clearly synthetic. Domains use the reserved `.example` TLD
(RFC 2606) so mock output can never be mistaken for real findings. This is what
powers `--provider mock` (the default when no API keys are set) and the tests.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .base import LLMResult

# ---------------------------------------------------------------------------
# Deterministic request heuristics (shared by mock planning + CLI fallback)
# ---------------------------------------------------------------------------

TALENT_HINTS = (
    "engineer", "developer", "hire", "hiring", "talent", "candidate", "recruiter",
    "recruiting", "cto", "vp engineering", "profiles", "resume", "specialist",
    "technician", "mechanic", "operator", "designer", "architect", "scientist",
)
BUSINESS_HINTS = (
    "businesses", "companies", "company", "contractors", "construction",
    "customers", "pipeline", "meet", "introduction", "partners", "vendors",
    "suppliers", "firms", "agencies", "operators", "shippers", "3pl", "logistics",
)
GEO_TOKENS = (
    "bay area", "san francisco", "oakland", "san jose", "sacramento", "los angeles",
    "san diego", "california", "seattle", "portland", "denver", "austin", "dallas",
    "houston", "texas", "chicago", "boston", "new york", "nyc", "atlanta", "miami",
    "nashville", "phoenix", "remote", "united states", "usa",
)
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "they", "their", "them", "have",
    "want", "would", "like", "more", "some", "any", "into", "from", "our", "your",
    "you", "are", "was", "were", "been", "being", "who", "what", "when", "where",
    "how", "can", "could", "should", "would", "will", "just", "also", "than",
    "then", "very", "about", "over", "under", "out", "get", "give", "find", "need",
    "looking", "help", "helping", "please", "build", "building", "pipeline", "chat",
    "talk", "meet", "each", "other", "type", "kind", "similar", "personal", "email",
    "message", "businesses", "companies", "company", "across", "internet", "automatically",
    "output", "send", "right", "away", "start", "specific", "had", "example",
    "another", "one", "them", "it", "its", "my", "portfolio", "support", "request",
}


def detect_kind(request: str, kind_hint: str = "auto") -> str:
    if kind_hint in ("business", "talent"):
        return kind_hint
    text = request.lower()
    talent = sum(text.count(h) for h in TALENT_HINTS)
    business = sum(text.count(h) for h in BUSINESS_HINTS)
    return "talent" if talent > business else "business"


def detect_geography(request: str) -> str:
    text = request.lower()
    for token in GEO_TOKENS:
        if token in text:
            return token
    return ""


def extract_keywords(request: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", request.lower())
    out: list[str] = []
    for word in words:
        if word in STOPWORDS or word in out:
            continue
        out.append(word)
        if len(out) >= 6:
            break
    return out


def heuristic_plan_dict(request: str, kind_hint: str = "auto", target_count: int = 10) -> dict:
    """A reasonable research plan built without any LLM call."""
    kind = detect_kind(request, kind_hint)
    keywords = extract_keywords(request)
    topic = " ".join(keywords[:3]) if keywords else "relevant"
    role = " ".join(keywords[:2]) if keywords else "relevant"
    geo = detect_geography(request)

    if kind == "business":
        queries = [
            f"{topic} companies {geo}".strip(),
            f"{topic} contractors {geo}".strip(),
            f"{topic} trade association member directory",
            f"top {topic} firms {geo}".strip(),
            f"{topic} vendors supply chain projects",
        ]
        criteria = [
            f"Is an operating business related to {topic}",
            "Works with the kind of customer or project described in the request",
            "Has a verifiable own website or published contact channel",
        ]
        goal = "Get a reply and book a short intro call about a potential fit"
    else:
        queries = [
            f"{role} engineer {geo}".strip(),
            f"companies with {role} engineering teams",
            f"{role} systems engineer profile experience",
            f"automation integrators hiring {role}",
            f"{role} commissioning deployment experience",
        ]
        criteria = [
            f"Has hands-on experience matching {role} or the role described",
            "Career history is publicly verifiable",
            "Plausibly open to a new opportunity or industry conversation",
        ]
        goal = "Get a reply and start a conversation about a role or opportunity"
    if geo:
        criteria.append(f"Based in or operating near {geo}")

    return {
        "kind": kind,
        "target_description": request.strip(),
        "criteria": criteria,
        "nice_to_have": ["Growing team", "Recent project wins or hiring activity"],
        "geography": geo,
        "exclusions": ["Aggregators and lead-gen sites", "Businesses with no verifiable presence"],
        "queries": queries,
        "message_goal": goal,
        "sender": {"name": "", "role": "", "organization": "", "voice": "concise, warm, peer-to-peer"},
        "target_count": target_count,
    }


# ---------------------------------------------------------------------------
# Synthetic fixtures (reserved .example domains; emails appear in evidence text)
# ---------------------------------------------------------------------------

BUSINESS_FIXTURES = [
    {
        "name": "Ridgeline Construction Group",
        "headline": "General contractor — commercial & industrial builds",
        "organization": "",
        "website": "https://ridgelinebuild.example/",
        "profile_url": "",
        "location": "Concord, CA",
        "email": "estimating@ridgelinebuild.example",
        "phone": "(925) 555-0142",
        "contact_person": "Dana Whitfield",
        "contact_role": "Director of Operations",
        "fit_reason": "Mid-size GC doing warehouse and distribution-center builds; already lists material-handling fit-outs in project portfolio.",
        "criteria_matched": [],
        "evidence": [
            {"text": "Ridgeline Construction Group - general contractor for commercial and industrial projects, including warehouse and distribution center build-outs. Project inquiries: estimating@ridgelinebuild.example, phone (925) 555-0142.",
             "url": "https://ridgelinebuild.example/", "title": "Ridgeline Construction Group - About"},
            {"text": "Dana Whitfield, Director of Operations, oversees preconstruction and vendor partnerships.",
             "url": "https://ridgelinebuild.example/team", "title": "Our Team"},
        ],
    },
    {
        "name": "Bay Crest Builders Inc",
        "headline": "Design-build contractor — industrial facilities",
        "organization": "",
        "website": "https://baycrestbuilders.example/",
        "profile_url": "",
        "location": "Hayward, CA",
        "email": "",
        "phone": "(510) 555-0177",
        "contact_person": "Miguel Alvarez",
        "contact_role": "Preconstruction Manager",
        "fit_reason": "Design-build firm focused on industrial facilities; publicly describes self-perform concrete work and automation-ready remodels.",
        "criteria_matched": [],
        "evidence": [
            {"text": "Bay Crest Builders Inc - design-build contractor specializing in industrial facilities and automation-ready remodels. Call (510) 555-0177.",
             "url": "https://baycrestbuilders.example/", "title": "Bay Crest Builders"},
            {"text": "Miguel Alvarez leads preconstruction and is the listed contact for new project inquiries.",
             "url": "https://baycrestbuilders.example/contact", "title": "Contact"},
        ],
    },
    {
        "name": "Harbor & Steel Construction Co.",
        "headline": "Structural steel & plant construction",
        "organization": "",
        "website": "https://harborgsteel.example/",
        "profile_url": "",
        "location": "Oakland, CA",
        "email": "bids@harborgsteel.example",
        "phone": "(510) 555-0190",
        "contact_person": "",
        "contact_role": "",
        "fit_reason": "Plant and port construction specialist; bid portal shows recurring work at logistics facilities.",
        "criteria_matched": [],
        "evidence": [
            {"text": "Harbor & Steel Construction Co. - structural steel and plant construction for ports and logistics facilities. Bid invitations: bids@harborgsteel.example, (510) 555-0190.",
             "url": "https://harborgsteel.example/bids", "title": "Bid Opportunities"},
        ],
    },
    {
        "name": "Northgate Electric Systems",
        "headline": "Electrical contractor — controls & panels",
        "organization": "",
        "website": "https://www.yelp.com/biz/northgate-electric-systems-oakland",
        "profile_url": "",
        "location": "Oakland, CA",
        "email": "office@northgateelectric.example",
        "phone": "(510) 555-0121",
        "contact_person": "",
        "contact_role": "",
        "fit_reason": "Controls-focused electrical contractor serving warehouse automation installs; only third-party listings found so far.",
        "criteria_matched": [],
        "evidence": [
            {"text": "Northgate Electric Systems - electrical contractor for industrial controls and panels. office@northgateelectric.example, phone (510) 555-0121. Listed under electrical contractors in Oakland.",
             "url": "https://www.yelp.com/biz/northgate-electric-systems-oakland", "title": "Northgate Electric Systems - Yelp"},
        ],
    },
]

TALENT_FIXTURES = [
    {
        "name": "Priya Raghavan",
        "headline": "Senior Systems Engineer — PLC & motion control",
        "organization": "Cordell Robotics",
        "website": "",
        "profile_url": "https://profiles.example/priya-raghavan",
        "location": "Bay Area, CA",
        "email": "",
        "phone": "",
        "contact_person": "",
        "contact_role": "",
        "fit_reason": "8 years commissioning conveyor and AMR systems; PLC programming (Allen-Bradley) and industrial safety systems.",
        "criteria_matched": [],
        "evidence": [
            {"text": "Priya Raghavan - Senior Systems Engineer at Cordell Robotics. 8 years commissioning conveyor and AMR systems; Allen-Bradley PLC programming, motion control, and industrial safety systems. Bay Area, CA.",
             "url": "https://profiles.example/priya-raghavan", "title": "Priya Raghavan - Profile"},
        ],
    },
    {
        "name": "Tomas Beckett",
        "headline": "Controls & Systems Engineer — warehouse automation",
        "organization": "Meridian Automation",
        "website": "",
        "profile_url": "https://profiles.example/tomas-beckett",
        "location": "Sacramento, CA",
        "email": "t.beckett@meridianautomation.example",
        "phone": "",
        "contact_person": "",
        "contact_role": "",
        "fit_reason": "Leads on-site commissioning for warehouse automation deployments; systems integration and PLC/SCADA background.",
        "criteria_matched": [],
        "evidence": [
            {"text": "Tomas Beckett - Controls & Systems Engineer at Meridian Automation. Leads on-site commissioning for warehouse automation deployments; PLC/SCADA and systems integration. Contact: t.beckett@meridianautomation.example. Sacramento, CA.",
             "url": "https://profiles.example/tomas-beckett", "title": "Tomas Beckett - Profile"},
        ],
    },
    {
        "name": "Alex Okafor",
        "headline": "Staff Systems Engineer — robotics deployment",
        "organization": "Vector Logistics Systems",
        "website": "",
        "profile_url": "https://profiles.example/alex-okafor",
        "location": "Remote, USA",
        "email": "",
        "phone": "",
        "contact_person": "",
        "contact_role": "",
        "fit_reason": "Owns deployment engineering for robotics fleets at customer sites; strong travel-based commissioning record.",
        "criteria_matched": [],
        "evidence": [
            {"text": "Alex Okafor - Staff Systems Engineer at Vector Logistics Systems. Owns deployment engineering for robotics fleets at customer sites, including commissioning, acceptance testing, and field support. Remote, USA.",
             "url": "https://profiles.example/alex-okafor", "title": "Alex Okafor - Profile"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Mock LLM: routes on the [PLAN]/[SCOUT]/[WRITE] markers in the system prompt
# ---------------------------------------------------------------------------

class MockLLM:
    def web_research_tools(self) -> Optional[list]:
        return [{"type": "web_search_mock"}]

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 2048,
        tools: Optional[list] = None,
    ) -> LLMResult:
        if "[PLAN]" in system:
            return self._plan(user)
        if "[SCOUT]" in system:
            return self._scout(user)
        if "[WRITE]" in system:
            return self._write(user)
        return LLMResult(text=json.dumps({"message": "mock response"}))

    def _plan(self, user: str) -> LLMResult:
        request_match = re.search(r"REQUEST:\s*(.*?)\s*kind_hint=", user, re.DOTALL)
        request = (request_match.group(1).strip() if request_match else user.strip())
        target_count = 10
        count_match = re.search(r"target_count=[\"']?(\d+)", user)
        if count_match:
            target_count = int(count_match.group(1))
        hint_match = re.search(r"kind_hint=(\w+)", user)
        kind_hint = hint_match.group(1) if hint_match else "auto"
        return LLMResult(text=json.dumps(heuristic_plan_dict(request, kind_hint, target_count)))

    def _scout(self, user: str) -> LLMResult:
        kind = "talent" if "[KIND:talent]" in user else "business"
        fixtures = TALENT_FIXTURES if kind == "talent" else BUSINESS_FIXTURES
        return LLMResult(text=json.dumps({"candidates": fixtures}))

    def _write(self, user: str) -> LLMResult:
        kind = "talent" if "[KIND:talent]" in user else "business"
        name = _field(user, "name") or "your team"
        goal = _field(user, "message_goal") or "explore whether there's a fit"
        sender_name = _field(user, "sender_name") or "[Your name]"
        fit_reason = (_field(user, "fit_reason") or "").rstrip(". ")
        contact = _field(user, "contact_person")

        goal_line = goal[0].lower() + goal[1:] if goal else "explore whether there's a fit"
        if kind == "talent":
            first = name.split()[0]
            subject = f"Quick question, {first}?"
            opener = (f"Your background stood out: {fit_reason[0].lower() + fit_reason[1:]}."
                      if fit_reason else "Your background stood out.")
            ask = "Would you be open to a quick chat about what's next for you?"
        else:
            first = contact.split()[0] if contact else "there"
            subject = f"Exploring a fit with {name}"[:60]
            opener = (f"I came across {name} — {fit_reason[0].lower() + fit_reason[1:]}."
                      if fit_reason else f"I came across {name}.")
            ask = "Would you be open to a 20-minute call in the next couple of weeks?"

        body = (
            f"Hi {first},\n\n"
            f"{opener}\n\n"
            f"I'm reaching out to {goal_line}. {ask}\n\n"
            f"Best,\n{sender_name}"
        )
        draft = {
            "subject": subject,
            "body": body,
            "send_via": "email" if _field(user, "email") else ("linkedin" if _field(user, "profile_url") else "contact_form"),
            "personalization_notes": "Mock draft: replace with real research before sending.",
        }
        return LLMResult(text=json.dumps(draft))


def _field(user: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}=(.*)$", user, re.MULTILINE)
    return match.group(1).strip() if match else ""
