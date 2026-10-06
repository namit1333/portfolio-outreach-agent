"""CLI: `outreach run|plan|providers`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .config import build_settings, describe_settings
from .http import ProviderError
from .models import Sender, to_jsonable
from .output import write_run
from .pipeline import Pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outreach",
        description=(
            "Turn a portfolio support request into an evidence-grounded prospect list "
            "and ready-to-send outreach drafts."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_shared(p: argparse.ArgumentParser) -> None:
        p.add_argument("request", help="natural-language request, e.g. "
                       "'find general contractors we can intro to our robotics portfolio company'")
        p.add_argument("--kind", choices=["auto", "business", "talent"], default="auto",
                       help="what to source (default: inferred from the request)")
        p.add_argument("--provider", choices=["auto", "anthropic", "openai", "mock"],
                       default=None, help="LLM provider (default: auto)")
        p.add_argument("--search", choices=["auto", "tavily", "serper", "none"],
                       default=None, help="search backend (default: auto)")
        p.add_argument("--sender-name", default="", help="who the outreach is from")
        p.add_argument("--sender-role", default="", help="sender role/title")
        p.add_argument("--sender-org", default="", help="sender organization")

    run_p = sub.add_parser("run", help="run the full agent pipeline and write artifacts")
    add_shared(run_p)
    run_p.add_argument("--limit", type=int, default=None, help="max candidates in output (default 10)")
    run_p.add_argument("--concurrency", type=int, default=None, help="parallel scout/writer agents (default 4)")
    run_p.add_argument("--min-score", type=float, default=None, help="drop candidates below this fit score")
    run_p.add_argument("--out", default=None, help="output root directory (default runs/)")
    run_p.add_argument("--run-name", default="", help="explicit output folder name")
    run_p.add_argument("--quiet", action="store_true", help="suppress the live agent log")

    plan_p = sub.add_parser("plan", help="show the research plan for a request (no sourcing)")
    add_shared(plan_p)
    plan_p.add_argument("--limit", type=int, default=None)

    sub.add_parser("providers", help="show configured providers and keys")
    return parser


def _sender_from_args(args: argparse.Namespace) -> Optional[Sender]:
    sender = Sender(name=args.sender_name, role=args.sender_role, organization=args.sender_org)
    return sender if (sender.name or sender.role or sender.organization) else None


def _print_event(event) -> None:
    detail = f" — {event.detail}" if event.detail else ""
    error = f" — ERROR: {event.error}" if event.error else ""
    print(f"[{event.stage:<6}] {event.agent} {event.status}{detail}{error}")


def cmd_run(args: argparse.Namespace) -> int:
    settings = build_settings(
        provider=args.provider, search=args.search,
        limit=args.limit, concurrency=args.concurrency,
        min_score=args.min_score, out_root=args.out,
    )
    pipeline = Pipeline(settings, on_event=None if args.quiet else _print_event)
    if pipeline.stack.notes and not args.quiet:
        for note in pipeline.stack.notes:
            print(f"note: {note}")

    result = pipeline.run(args.request, kind_hint=args.kind, sender=_sender_from_args(args))
    out_dir = write_run(result, settings.out_root, run_name=args.run_name)

    print()
    print(f"Request: {args.request}")
    print(f"Mode:    {result.plan.kind.value}   Providers: {result.providers}")
    print(f"Kept:    {len(result.candidates)} candidates -> {out_dir}")
    print()
    for index, candidate in enumerate(result.candidates, start=1):
        draft = candidate.draft
        via = draft.send_via if draft else "no draft"
        subject = f"  |  {draft.subject}" if draft else ""
        print(f"  {index:>2}. {candidate.name:<38} fit {candidate.score:>5.1f}  via {via}{subject}")
    if result.warnings:
        print()
        print(f"{len(result.warnings)} warning(s) recorded in run.json / outreach.md")
    print()
    print(f"Open {out_dir / 'outreach.md'} for ready-to-send drafts.")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    settings = build_settings(provider=args.provider, search=args.search, limit=args.limit)
    pipeline = Pipeline(settings)
    plan = pipeline.plan(args.request, kind_hint=args.kind, sender=_sender_from_args(args))
    print(json.dumps(to_jsonable(plan), indent=2, ensure_ascii=False))
    return 0


def cmd_providers(_args: argparse.Namespace) -> int:
    settings = build_settings()
    for key, value in describe_settings(settings):
        print(f"{key:<18} {value}")
    print()
    try:
        from .providers import build_stack

        stack = build_stack(settings)
        print(f"resolved provider: {stack.provider_name} ({stack.model})")
        print(f"resolved research: {stack.research_mode}")
        for note in stack.notes:
            print(f"note: {note}")
    except ProviderError as exc:
        print(f"resolution failed: {exc}")
        return 1
    return 0


def main(argv: Optional[list] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return cmd_run(args)
        if args.command == "plan":
            return cmd_plan(args)
        if args.command == "providers":
            return cmd_providers(args)
        parser.error(f"unknown command {args.command}")
        return 2
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
