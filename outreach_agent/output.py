"""Artifact assembly: prospects.csv, outreach.md, drafts/, plan.json, run.json."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from .models import Candidate, RunResult, to_jsonable

BUSINESS_COLUMNS = [
    "rank", "name", "category", "location", "website", "email", "phone",
    "contact_person", "contact_role", "fit_score", "fit_reason",
    "criteria_matched", "source_urls", "subject", "email_body", "send_via",
    "draft_file", "warnings",
]
TALENT_COLUMNS = [
    "rank", "name", "role", "organization", "location", "profile_url", "email",
    "fit_score", "fit_reason", "criteria_matched", "source_urls", "subject",
    "message_body", "send_via", "draft_file", "warnings",
]


def slugify(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "run"


def _draft_filename(index: int, candidate: Candidate, send_via: str) -> str:
    ext = "eml" if send_via == "email" else "txt"
    return f"{index:02d}-{slugify(candidate.name, 32)}.{ext}"


def write_run(result: RunResult, out_root: str, run_name: str = "") -> Path:
    timestamp = result.created_at or datetime.now().isoformat(timespec="seconds")
    name = run_name or f"{timestamp[:19].replace(':', '').replace('-', '')}-{slugify(result.request)}"
    out_dir = Path(out_root) / name
    (out_dir / "drafts").mkdir(parents=True, exist_ok=True)
    result.out_dir = str(out_dir)

    (out_dir / "plan.json").write_text(
        json.dumps(to_jsonable(result.plan), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "run.json").write_text(
        json.dumps(to_jsonable(result), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    draft_files = _write_drafts(result, out_dir)
    _write_csv(result, out_dir, draft_files)
    _write_markdown(result, out_dir, draft_files)
    return out_dir


def _write_drafts(result: RunResult, out_dir: Path) -> dict:
    files: dict = {}
    sender = result.plan.sender
    from_header = sender.signature().splitlines()[0] if sender.signature() else "me"
    for index, candidate in enumerate(result.candidates, start=1):
        draft = candidate.draft
        if draft is None:
            continue
        filename = _draft_filename(index, candidate, draft.send_via)
        path = out_dir / "drafts" / filename
        if draft.send_via == "email":
            message = EmailMessage()
            message["From"] = from_header
            message["To"] = candidate.email
            message["Subject"] = draft.subject
            message.set_content(draft.body)
            path.write_bytes(message.as_bytes())
        else:
            target = candidate.profile_url or candidate.website or "(find their contact form)"
            path.write_text(
                f"Send via: {draft.send_via}\nTarget: {target}\nSubject: {draft.subject}\n\n{draft.body}\n",
                encoding="utf-8",
            )
        files[id(candidate)] = filename
    return files


def _write_csv(result: RunResult, out_dir: Path, draft_files: dict) -> None:
    kind = result.plan.kind.value
    columns = BUSINESS_COLUMNS if kind == "business" else TALENT_COLUMNS
    # utf-8-sig so Excel on Windows opens it cleanly
    with (out_dir / "prospects.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for index, candidate in enumerate(result.candidates, start=1):
            draft = candidate.draft
            row = {
                "rank": index,
                "name": candidate.name,
                "category": candidate.headline,
                "role": candidate.headline,
                "organization": candidate.organization,
                "location": candidate.location,
                "website": candidate.website,
                "profile_url": candidate.profile_url,
                "email": candidate.email,
                "phone": candidate.phone,
                "contact_person": candidate.contact_person,
                "contact_role": candidate.contact_role,
                "fit_score": candidate.score,
                "fit_reason": candidate.fit_reason,
                "criteria_matched": "; ".join(candidate.criteria_matched),
                "source_urls": "; ".join(candidate.source_urls),
                "subject": draft.subject if draft else "",
                "email_body": draft.body if draft else "",
                "message_body": draft.body if draft else "",
                "send_via": draft.send_via if draft else "",
                "draft_file": f"drafts/{draft_files.get(id(candidate), '')}" if draft else "",
                "warnings": "; ".join(candidate.warnings),
            }
            writer.writerow(row)


def _write_markdown(result: RunResult, out_dir: Path, draft_files: dict) -> None:
    plan = result.plan
    lines: list[str] = []
    lines.append("# Outreach package")
    lines.append("")
    lines.append(f"**Request:** {result.request}")
    lines.append(f"**Mode:** {plan.kind.value} · **Generated:** {result.created_at}")
    lines.append(
        f"**Providers:** {result.providers.get('llm')} ({result.providers.get('model')}) · "
        f"research: {result.providers.get('research_mode')} · candidates: {len(result.candidates)}"
    )
    lines.append("")
    lines.append("> Verify each draft before sending. Contact fields are only populated")
    lines.append("> when literally published on a cited page; blanks are intentional.")
    lines.append("")
    lines.append("## Plan")
    lines.append("")
    lines.append(f"- **Looking for:** {plan.target_description}")
    if plan.geography:
        lines.append(f"- **Geography:** {plan.geography}")
    if plan.criteria:
        lines.append("- **Fit criteria:** " + "; ".join(plan.criteria))
    lines.append(f"- **Goal:** {plan.message_goal}")
    lines.append("")

    for index, candidate in enumerate(result.candidates, start=1):
        draft = candidate.draft
        lines.append(f"## {index}. {candidate.name} — fit {candidate.score:.0f}")
        lines.append("")
        if candidate.headline:
            label = "Role" if plan.kind.value == "talent" else "Category"
            org = f" — {candidate.organization}" if candidate.organization else ""
            lines.append(f"- **{label}:** {candidate.headline}{org}")
        if candidate.location:
            lines.append(f"- **Location:** {candidate.location}")
        if candidate.website:
            lines.append(f"- **Website:** {candidate.website}")
        if candidate.profile_url:
            lines.append(f"- **Profile:** {candidate.profile_url}")
        contact = candidate.email or "(no verified email — leave blank)"
        lines.append(f"- **Email:** {contact}")
        if candidate.phone:
            lines.append(f"- **Phone:** {candidate.phone}")
        if candidate.contact_person:
            role = f", {candidate.contact_role}" if candidate.contact_role else ""
            lines.append(f"- **Contact:** {candidate.contact_person}{role}")
        lines.append(f"- **Why:** {candidate.fit_reason or '(no reason recorded)'}")
        if candidate.score_breakdown:
            breakdown = ", ".join(f"{k} {v}" for k, v in candidate.score_breakdown.items())
            lines.append(f"- **Score breakdown:** {breakdown}")
        if candidate.evidence:
            lines.append("- **Evidence:**")
            for quote in candidate.evidence[:4]:
                title = quote.title or quote.url or "source"
                lines.append(f"  - [{title}]({quote.url}) — “{quote.short()}”")
        if candidate.warnings:
            lines.append("- **Policy warnings:** " + "; ".join(candidate.warnings))
        lines.append("")
        if draft:
            lines.append(f"**Send via:** {draft.send_via} · **Draft file:** drafts/{draft_files.get(id(candidate), '')}")
            lines.append("")
            lines.append(f"**Subject:** {draft.subject}")
            lines.append("")
            lines.append("```")
            lines.append(draft.body)
            lines.append("```")
            if draft.personalization_notes:
                lines.append(f"*Notes: {draft.personalization_notes}*")
            lines.append("")
        else:
            lines.append("*No draft generated for this candidate.*")
            lines.append("")
        lines.append("---")
        lines.append("")

    if result.warnings:
        lines.append("## Run warnings")
        lines.append("")
        for warning in result.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    (out_dir / "outreach.md").write_text("\n".join(lines), encoding="utf-8")
