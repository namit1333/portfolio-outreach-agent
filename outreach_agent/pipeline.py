"""Pipeline orchestrator: spins up planner, scout, curator, and writer agents.

Scouts and writers run concurrently; failures degrade gracefully (a failed
agent yields zero candidates / no draft and a recorded event, never a crash).
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Optional

from .agents import PlannerAgent, ScoutAgent, WriterAgent
from .config import Settings
from .models import AgentEvent, Candidate, ResearchPlan, RunResult, Sender
from .policy import (
    dedupe_key,
    enforce_evidence,
    match_criteria,
    merge_candidates,
    score_candidate,
)
from .providers import ProviderStack, build_stack

EventCallback = Callable[[AgentEvent], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Pipeline:
    def __init__(self, settings: Settings, stack: Optional[ProviderStack] = None,
                 on_event: Optional[EventCallback] = None):
        self.settings = settings
        self.stack = stack or build_stack(settings)
        self.on_event = on_event
        self.events: list[AgentEvent] = []
        self.warnings: list[str] = list(self.stack.notes)

    # -- event plumbing -----------------------------------------------------

    def _emit(self, stage: str, agent: str, status: str, detail: str = "",
              error: str = "", started: Optional[float] = None) -> AgentEvent:
        event = AgentEvent(
            stage=stage,
            agent=agent,
            status=status,
            detail=detail,
            error=error,
            started_at=_now() if started is None else "",
            finished_at=_now(),
            duration_s=round(time.time() - started, 2) if started else 0.0,
        )
        self.events.append(event)
        if self.on_event:
            self.on_event(event)
        return event

    # -- stages -------------------------------------------------------------

    def plan(self, request: str, kind_hint: str = "auto",
             sender: Optional[Sender] = None) -> ResearchPlan:
        started = time.time()
        self._emit("plan", "planner[1/1]", "started")
        plan, warnings = PlannerAgent(self.stack.llm).run(
            request, kind_hint=kind_hint,
            target_count=max(self.settings.limit * 2, 10),
            sender=sender,
        )
        self.warnings.extend(warnings)
        self._emit("plan", "planner[1/1]", "ok",
                   f"{plan.kind.value} · {len(plan.queries)} queries · {len(plan.criteria)} criteria",
                   started=started)
        return plan

    def scout(self, plan: ResearchPlan) -> list[Candidate]:
        queries = plan.queries
        per_query = max(3, math.ceil((plan.target_count or self.settings.limit) / max(1, len(queries))) + 2)
        scout_agent = ScoutAgent(
            self.stack.llm,
            search_client=self.stack.search_client,
            research_mode=self.stack.research_mode,
        )
        found: list[Candidate] = []
        workers = max(1, min(self.settings.concurrency, len(queries))) or 1

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for index, query in enumerate(queries, start=1):
                agent_name = f"scout[{index}/{len(queries)}]"
                self._emit("scout", agent_name, "started", query)
                futures[pool.submit(scout_agent.run, plan, query, per_query)] = (agent_name, query, time.time())

            for future in as_completed(futures):
                agent_name, query, started = futures[future]
                try:
                    candidates = future.result()
                    found.extend(candidates)
                    self._emit("scout", agent_name, "ok",
                               f"{len(candidates)} candidates for “{query}”", started=started)
                except Exception as exc:  # degrade gracefully
                    self.warnings.append(f"{agent_name} failed: {exc}")
                    self._emit("scout", agent_name, "error", query, error=str(exc), started=started)
        return found

    def curate(self, plan: ResearchPlan, raw: list[Candidate]) -> list[Candidate]:
        started = time.time()
        self._emit("curate", "curator[1/1]", "started", f"{len(raw)} raw candidates")

        merged: dict[str, Candidate] = {}
        for candidate in raw:
            key = dedupe_key(candidate)
            if key in merged:
                merge_candidates(merged[key], candidate)
            else:
                merged[key] = candidate

        curated: list[Candidate] = []
        for candidate in merged.values():
            warnings = enforce_evidence(candidate)
            if not candidate.name:
                self.warnings.append(f"dropped unnamed candidate: warnings={warnings}")
                continue
            candidate.criteria_matched = match_criteria(candidate, plan)
            score, breakdown = score_candidate(candidate, plan)
            candidate.score = score
            candidate.score_breakdown = breakdown
            curated.append(candidate)

        curated.sort(key=lambda c: (-c.score, c.name.lower()))
        kept = [c for c in curated if c.score >= self.settings.min_score][: self.settings.limit]
        self._emit("curate", "curator[1/1]", "ok",
                   f"{len(merged)} unique · {len(kept)} kept (score ≥ {self.settings.min_score})",
                   started=started)
        return kept

    def write(self, plan: ResearchPlan, candidates: list[Candidate]) -> None:
        if not candidates:
            return
        writer = WriterAgent(self.stack.llm)
        workers = max(1, min(self.settings.concurrency, len(candidates)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for index, candidate in enumerate(candidates, start=1):
                agent_name = f"writer[{index}/{len(candidates)}]"
                self._emit("write", agent_name, "started", candidate.name)
                futures[pool.submit(writer.draft, plan, candidate)] = (agent_name, candidate, time.time())

            for future in as_completed(futures):
                agent_name, candidate, started = futures[future]
                try:
                    candidate.draft = future.result()
                    self._emit("write", agent_name, "ok",
                               f"draft for {candidate.name} ({candidate.draft.send_via})",
                               started=started)
                except Exception as exc:
                    self.warnings.append(f"{agent_name} failed: {exc}")
                    self._emit("write", agent_name, "error", candidate.name, error=str(exc), started=started)

    def run(self, request: str, kind_hint: str = "auto",
            sender: Optional[Sender] = None) -> RunResult:
        plan = self.plan(request, kind_hint, sender=sender)
        raw = self.scout(plan)
        candidates = self.curate(plan, raw)
        self.write(plan, candidates)
        return RunResult(
            request=request,
            plan=plan,
            candidates=candidates,
            events=self.events,
            warnings=self.warnings,
            providers={
                "llm": self.stack.provider_name,
                "model": self.stack.model,
                "research_mode": self.stack.research_mode,
                "search": type(self.stack.search_client).__name__ if self.stack.search_client else None,
            },
            created_at=_now(),
        )


def run_pipeline(
    request: str,
    settings: Settings,
    *,
    kind_hint: str = "auto",
    sender: Optional[Sender] = None,
    on_event: Optional[EventCallback] = None,
    stack: Optional[ProviderStack] = None,
) -> RunResult:
    return Pipeline(settings, stack=stack, on_event=on_event).run(request, kind_hint, sender=sender)
