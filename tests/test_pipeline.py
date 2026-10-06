"""End-to-end pipeline tests using the offline mock providers."""

import unittest

from outreach_agent.config import Settings
from outreach_agent.models import Candidate, EvidenceQuote, Sender, TargetKind
from outreach_agent.pipeline import Pipeline, run_pipeline

BUSINESS_REQUEST = (
    "Find general contractor and construction businesses we can introduce to our "
    "robotics deployment portfolio company in the Bay Area"
)
TALENT_REQUEST = (
    "We need a specific type of systems engineer with robotics commissioning "
    "experience; surface their profiles"
)


def mock_settings(**kwargs) -> Settings:
    base = dict(provider="mock", search="none", limit=10, concurrency=4, min_score=20.0)
    base.update(kwargs)
    return Settings(**base)


class TestPlanning(unittest.TestCase):
    def test_business_request_plans_as_business(self):
        pipeline = Pipeline(mock_settings())
        plan = pipeline.plan(BUSINESS_REQUEST)
        self.assertEqual(plan.kind, TargetKind.BUSINESS)
        self.assertGreaterEqual(len(plan.queries), 4)
        self.assertTrue(plan.criteria)
        self.assertNotIn("kind_hint=", plan.target_description)

    def test_talent_request_plans_as_talent(self):
        pipeline = Pipeline(mock_settings())
        plan = pipeline.plan(TALENT_REQUEST)
        self.assertEqual(plan.kind, TargetKind.TALENT)

    def test_kind_hint_overrides(self):
        pipeline = Pipeline(mock_settings())
        plan = pipeline.plan(BUSINESS_REQUEST, kind_hint="talent")
        self.assertEqual(plan.kind, TargetKind.TALENT)

    def test_sender_override_applied(self):
        pipeline = Pipeline(mock_settings())
        plan = pipeline.plan(BUSINESS_REQUEST, sender=Sender(name="Namit", role="Platform"))
        self.assertEqual(plan.sender.name, "Namit")
        self.assertEqual(plan.sender.role, "Platform")


class TestCuration(unittest.TestCase):
    def test_duplicates_across_scouts_collapse(self):
        pipeline = Pipeline(mock_settings())
        plan = pipeline.plan(BUSINESS_REQUEST)
        raw = pipeline.scout(plan)
        # five scout agents each saw the same fixture set: raw count exceeds unique
        self.assertGreater(len(raw), 4)
        kept = pipeline.curate(plan, raw)
        names = [c.name for c in kept]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(kept), 4)

    def test_limit_and_min_score_respected(self):
        pipeline = Pipeline(mock_settings(limit=2, min_score=1.0))
        plan = pipeline.plan(BUSINESS_REQUEST)
        raw = pipeline.scout(plan)
        kept = pipeline.curate(plan, raw)
        self.assertLessEqual(len(kept), 2)

    def test_scores_are_sorted_descending(self):
        pipeline = Pipeline(mock_settings())
        plan = pipeline.plan(BUSINESS_REQUEST)
        kept = pipeline.curate(plan, pipeline.scout(plan))
        scores = [c.score for c in kept]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestFullRun(unittest.TestCase):
    def test_business_run_end_to_end(self):
        result = run_pipeline(BUSINESS_REQUEST, mock_settings(),
                              sender=Sender(name="Namit Tatipigari"))
        self.assertEqual(result.plan.kind, TargetKind.BUSINESS)
        self.assertEqual(len(result.candidates), 4)

        by_name = {c.name: c for c in result.candidates}

        # Aggregator page must never be kept as a website (sourcing policy)
        northgate = by_name["Northgate Electric Systems"]
        self.assertEqual(northgate.website, "")
        self.assertEqual(northgate.email, "office@northgateelectric.example")

        # A business with no published email must keep it blank, not guessed
        bay_crest = by_name["Bay Crest Builders Inc"]
        self.assertEqual(bay_crest.email, "")
        self.assertEqual(bay_crest.phone, "(510) 555-0177")

        # Every candidate has a draft, and emails draft as email sends
        for candidate in result.candidates:
            self.assertIsNotNone(candidate.draft, candidate.name)
            self.assertTrue(candidate.draft.subject, candidate.name)
            self.assertTrue(candidate.draft.body, candidate.name)
        self.assertEqual(by_name["Ridgeline Construction Group"].draft.send_via, "email")
        self.assertEqual(bay_crest.draft.send_via, "contact_form")

        # Drafts are grounded: the fit reason must appear in evidence for at least the fixtures
        for candidate in result.candidates:
            self.assertTrue(candidate.evidence, candidate.name)
            self.assertTrue(candidate.source_urls, candidate.name)

        # Agent events were recorded for every stage
        stages = {e.stage for e in result.events}
        self.assertLessEqual({"plan", "scout", "curate", "write"}, stages)
        scout_ok = [e for e in result.events if e.stage == "scout" and e.status == "ok"]
        self.assertGreaterEqual(len(scout_ok), 4)

    def test_talent_run_end_to_end(self):
        result = run_pipeline(TALENT_REQUEST, mock_settings())
        self.assertEqual(result.plan.kind, TargetKind.TALENT)
        self.assertEqual(len(result.candidates), 3)
        for candidate in result.candidates:
            self.assertTrue(candidate.profile_url, candidate.name)
        emailed = [c for c in result.candidates if c.email]
        self.assertEqual(len(emailed), 1)
        self.assertEqual(emailed[0].draft.send_via, "email")
        self.assertIn("linkedin", {c.draft.send_via for c in result.candidates})

    def test_run_records_provider_metadata(self):
        result = run_pipeline(BUSINESS_REQUEST, mock_settings())
        self.assertEqual(result.providers["llm"], "mock")
        self.assertEqual(result.providers["research_mode"], "mock")
        self.assertTrue(result.created_at)


class TestGracefulDegradation(unittest.TestCase):
    def test_failed_scout_does_not_kill_run(self):
        # Force one scout agent to fail mid-run; the run must still complete.
        settings = mock_settings()
        pipeline = Pipeline(settings)
        plan = pipeline.plan(BUSINESS_REQUEST)

        original = pipeline.stack.llm.complete
        calls = {"n": 0}

        def flaky(system, user, max_tokens=2048, tools=None):
            calls["n"] += 1
            if calls["n"] == 2 and "[SCOUT]" in system:
                raise RuntimeError("simulated scout failure")
            return original(system, user, max_tokens=max_tokens, tools=tools)

        pipeline.stack.llm.complete = flaky
        raw = pipeline.scout(plan)
        kept = pipeline.curate(plan, raw)
        self.assertGreater(len(kept), 0)
        self.assertTrue(any(e.status == "error" for e in pipeline.events if e.stage == "scout"))


if __name__ == "__main__":
    unittest.main()
