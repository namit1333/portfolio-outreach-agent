"""Sourcing policy: the guardrails that keep output evidence-grounded.

Rules (carried over from the Sable lead-sourcing brief):
- NEVER invent contact data. No guessed email patterns (info@, first.last@),
  no inferred phone numbers, no placeholder values. Blank is always OK.
- Every contact field must be supported by a quoted piece of evidence with a
  source URL. Unsupported fields are blanked, with a recorded warning.
- A business's "website" must be its OWN site. Aggregator/profile pages
  (Yelp, Angi, Nextdoor, BBB, job boards, social networks) do not count.
  Social pages DO count as evidence for a published email, flagged third-party.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import Candidate, EvidenceQuote, ResearchPlan, SourceQuality, TargetKind

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

PLACEHOLDER_VALUES = {
    "", "unconfirmed", "unknown", "n/a", "na", "none", "tbd", "null", "-",
    "not found", "not available",
}

AGGREGATOR_DOMAINS = {
    "yelp.com", "angi.com", "angieslist.com", "thumbtack.com", "homeadvisor.com",
    "bbb.org", "mapquest.com", "yellowpages.com", "nextdoor.com", "buildzoom.com",
    "houzz.com", "porch.com", "trustpilot.com", "glassdoor.com", "indeed.com",
    "ziprecruiter.com", "rocketreach.co", "zoominfo.com", "apollo.io", "lusha.com",
    "clutch.co", "g2.com", "capterra.com", "birdeye.com", "jobbersites.com",
}

SOCIAL_DOMAINS = {
    "facebook.com", "instagram.com", "x.com", "twitter.com", "linkedin.com",
    "youtube.com", "tiktok.com", "threads.net",
}

PRESS_DOMAINS = {
    "prnewswire.com", "businesswire.com", "globenewswire.com", "einpresswire.com",
    "prweb.com", "openpr.com", "benzinga.com", "apnews.com", "reuters.com",
}

_SOURCE_RANK = {
    SourceQuality.OWN_SITE: 20.0,
    SourceQuality.PRESS: 14.0,
    SourceQuality.SOCIAL: 12.0,
    SourceQuality.DIRECTORY: 8.0,
    SourceQuality.UNKNOWN: 5.0,
}


def clean_value(value: object) -> str:
    """Strip whitespace; map placeholders like 'unconfirmed' to empty string."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in PLACEHOLDER_VALUES else text


def domain_of(url: str) -> str:
    """Bare domain of a URL (or bare domain/email host), www. stripped."""
    if not url:
        return ""
    raw = url.strip()
    if "@" in raw and "://" not in raw:
        raw = raw.split("@", 1)[1]
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _domain_matches(domain: str, known: set[str]) -> bool:
    return any(domain == k or domain.endswith("." + k) for k in known)


def classify_url(url: str) -> SourceQuality:
    domain = domain_of(url)
    if not domain:
        return SourceQuality.UNKNOWN
    if _domain_matches(domain, SOCIAL_DOMAINS):
        return SourceQuality.SOCIAL
    if _domain_matches(domain, PRESS_DOMAINS):
        return SourceQuality.PRESS
    if _domain_matches(domain, AGGREGATOR_DOMAINS):
        return SourceQuality.DIRECTORY
    return SourceQuality.OWN_SITE


def best_source_quality(candidate: Candidate) -> SourceQuality:
    urls = [q.url for q in candidate.evidence] + candidate.source_urls
    qualities = [classify_url(u) for u in urls if u]
    if not qualities:
        return SourceQuality.UNKNOWN
    return max(qualities, key=lambda q: _SOURCE_RANK[q])


def normalize_email(raw: object) -> str:
    text = clean_value(raw)
    if not text:
        return ""
    match = EMAIL_RE.search(text)
    return match.group(0).lower() if match else ""


def normalize_phone(raw: object) -> str:
    text = clean_value(raw)
    digits = re.sub(r"\D", "", text)
    if not (10 <= len(digits) <= 15):
        return ""
    return text


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def match_criteria(candidate: Candidate, plan: ResearchPlan) -> list[str]:
    """Deterministic criteria match: significant words of each criterion must
    appear in the candidate's name/reason/evidence text. Unioned with whatever
    the scout agent reported."""
    haystack = " ".join(
        [candidate.name, candidate.headline, candidate.organization,
         candidate.fit_reason, candidate.evidence_text()]
    ).lower()
    matched: list[str] = list(candidate.criteria_matched)
    for criterion in plan.criteria:
        if criterion in matched:
            continue
        words = [w for w in re.findall(r"[a-z0-9\-]{4,}", criterion.lower())]
        if words and any(w in haystack for w in words):
            matched.append(criterion)
    return matched


def enforce_evidence(candidate: Candidate) -> list[str]:
    """Blank out any contact/identity field that evidence does not support.

    Returns the list of warnings generated. Mutates the candidate in place.
    """
    warnings: list[str] = []
    evidence_text = candidate.evidence_text()
    evidence_lower = evidence_text.lower()

    candidate.name = clean_value(candidate.name)
    if not candidate.name:
        warnings.append("candidate dropped later: no name")
        return warnings

    # Website must be the entity's OWN site, never an aggregator/profile page.
    website = clean_value(candidate.website)
    if website:
        quality = classify_url(website)
        if quality != SourceQuality.OWN_SITE:
            warnings.append(
                f"website blanked: {website} is a {quality.value} page, not the entity's own site"
            )
            if website not in candidate.source_urls:
                candidate.source_urls.append(website)
            website = ""
    candidate.website = website

    # Email must be valid AND literally observed in evidence. No pattern guessing.
    email = normalize_email(candidate.email)
    if email:
        if email.lower() not in evidence_lower:
            warnings.append(f"email blanked: {email} does not appear in any evidence quote")
            email = ""
    candidate.email = email

    # Phone must appear (digit-for-digit) in evidence too.
    phone = normalize_phone(candidate.phone)
    if phone and _digits(phone) not in _digits(evidence_text):
        warnings.append(f"phone blanked: {phone} does not appear in any evidence quote")
        phone = ""
    candidate.phone = phone

    # Named contact must be evidenced by name.
    contact_person = clean_value(candidate.contact_person)
    if contact_person and contact_person.lower() not in evidence_lower:
        warnings.append(f"contact_person blanked: {contact_person} not found in evidence")
        contact_person = ""
    candidate.contact_person = contact_person

    # Trim evidence to usable quotes.
    quotes: list[EvidenceQuote] = []
    for quote in candidate.evidence:
        text = " ".join(str(quote.text or "").split())
        if not text:
            continue
        quotes.append(EvidenceQuote(text=text[:400], url=str(quote.url or ""), title=str(quote.title or "")))
    candidate.evidence = quotes

    urls = [u for u in candidate.source_urls if clean_value(u)]
    for quote in candidate.evidence:
        if quote.url and quote.url not in urls:
            urls.append(quote.url)
    candidate.source_urls = urls

    for field_name in ("headline", "organization", "location", "contact_role", "fit_reason"):
        setattr(candidate, field_name, clean_value(getattr(candidate, field_name)))

    candidate.warnings.extend(warnings)
    return warnings


def score_candidate(candidate: Candidate, plan: ResearchPlan) -> tuple[float, dict]:
    """Deterministic fit score (0-100):

    - up to 60 pts: share of the plan's criteria the candidate matches
    - up to 20 pts: evidence source quality (own site > press > social > directory)
    - up to 20 pts: contactability (verified email, named contact, phone)
    - up to  5 pts: verified own website / profile URL
    """
    criteria = plan.criteria
    if criteria:
        coverage = min(1.0, len(candidate.criteria_matched) / len(criteria))
    else:
        coverage = 0.5
    s_coverage = 60.0 * coverage

    quality = best_source_quality(candidate)
    s_source = _SOURCE_RANK[quality]

    s_contact = 0.0
    if candidate.email:
        s_contact += 12.0
    if candidate.contact_person or candidate.headline:
        s_contact += 5.0
    if candidate.phone:
        s_contact += 3.0
    s_contact = min(s_contact, 20.0)

    s_web = 5.0 if candidate.website else (3.0 if candidate.profile_url else 0.0)

    score = round(min(100.0, s_coverage + s_source + s_contact + s_web), 1)
    breakdown = {
        "criteria_coverage": round(s_coverage, 1),
        "source_quality": round(s_source, 1),
        "source_label": quality.value,
        "contactability": round(s_contact, 1),
        "web_presence": round(s_web, 1),
    }
    return score, breakdown


def dedupe_key(candidate: Candidate) -> str:
    # People are unique by name: many professionals share a profile host
    # (linkedin.com, university pages), so domain keys would merge them.
    if candidate.kind != TargetKind.TALENT:
        for url in (candidate.website, candidate.profile_url):
            domain = domain_of(url)
            if domain:
                return "domain:" + domain
    name = re.sub(r"[^a-z0-9]+", "", candidate.name.lower())
    for suffix in ("inc", "llc", "llp", "corp", "co", "ltd"):
        if name.endswith(suffix) and len(name) > len(suffix) + 2:
            name = name[: -len(suffix)]
    return "name:" + name


def merge_candidates(primary: Candidate, other: Candidate) -> Candidate:
    """Merge a duplicate into `primary`, keeping the richest values."""
    for attr in ("headline", "organization", "website", "profile_url", "location",
                 "email", "phone", "contact_person", "contact_role", "fit_reason",
                 "scout_query"):
        if not getattr(primary, attr) and getattr(other, attr):
            setattr(primary, attr, getattr(other, attr))

    seen_criteria = list(primary.criteria_matched)
    for criterion in other.criteria_matched:
        if criterion not in seen_criteria:
            seen_criteria.append(criterion)
    primary.criteria_matched = seen_criteria

    seen_quotes = {(q.url, q.text[:60]) for q in primary.evidence}
    for quote in other.evidence:
        if (quote.url, quote.text[:60]) not in seen_quotes:
            primary.evidence.append(quote)
            seen_quotes.add((quote.url, quote.text[:60]))

    for url in other.source_urls:
        if url not in primary.source_urls:
            primary.source_urls.append(url)

    primary.warnings.extend(w for w in other.warnings if w not in primary.warnings)
    return primary
