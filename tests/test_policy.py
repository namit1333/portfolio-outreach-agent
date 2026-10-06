"""Tests for the evidence-only sourcing policy."""

import unittest

from outreach_agent.models import Candidate, EvidenceQuote, ResearchPlan, TargetKind
from outreach_agent.policy import (
    clean_value,
    dedupe_key,
    enforce_evidence,
    match_criteria,
    merge_candidates,
    normalize_email,
    normalize_phone,
    score_candidate,
)


def make_candidate(**kwargs) -> Candidate:
    base = dict(
        kind=TargetKind.BUSINESS,
        name="Acme Construction",
        headline="General contractor",
        website="https://acmeconstruction.example/",
        email="bids@acmeconstruction.example",
        phone="(925) 555-0100",
        contact_person="Jane Doe",
        contact_role="Ops Lead",
        fit_reason="Builds warehouses",
        evidence=[EvidenceQuote(
            text="Acme Construction - general contractor. bids@acmeconstruction.example, (925) 555-0100. Jane Doe, Ops Lead builds warehouses.",
            url="https://acmeconstruction.example/",
            title="Acme",
        )],
    )
    base.update(kwargs)
    return Candidate(**base)


class TestCleaning(unittest.TestCase):
    def test_placeholders_become_empty(self):
        for value in ("unconfirmed", "N/A", "unknown", "", "  ", "none"):
            self.assertEqual(clean_value(value), "")

    def test_real_values_survive(self):
        self.assertEqual(clean_value("  Acme  "), "Acme")

    def test_email_normalization(self):
        self.assertEqual(normalize_email("Bids@Acme.Example.com"), "bids@acme.example.com")
        self.assertEqual(normalize_email("not-an-email"), "")
        self.assertEqual(normalize_email(None), "")

    def test_phone_normalization(self):
        self.assertEqual(normalize_phone("(925) 555-0100"), "(925) 555-0100")
        self.assertEqual(normalize_phone("12345"), "")
        self.assertEqual(normalize_phone("call me"), "")


class TestEvidenceEnforcement(unittest.TestCase):
    def test_fully_evidenced_candidate_keeps_fields(self):
        candidate = make_candidate()
        warnings = enforce_evidence(candidate)
        self.assertEqual(warnings, [])
        self.assertEqual(candidate.email, "bids@acmeconstruction.example")
        self.assertEqual(candidate.phone, "(925) 555-0100")
        self.assertEqual(candidate.contact_person, "Jane Doe")

    def test_unevidenced_email_is_blanked(self):
        candidate = make_candidate(email="info@acmeconstruction.example")
        warnings = enforce_evidence(candidate)
        self.assertEqual(candidate.email, "")
        self.assertTrue(any("email blanked" in w for w in warnings))

    def test_guessed_pattern_without_evidence_is_blanked(self):
        candidate = make_candidate(email="jane.doe@acmeconstruction.example")
        warnings = enforce_evidence(candidate)
        self.assertEqual(candidate.email, "")
        self.assertTrue(any("email blanked" in w for w in warnings))

    def test_aggregator_page_is_never_a_website(self):
        candidate = make_candidate(website="https://www.yelp.com/biz/acme-oakland")
        warnings = enforce_evidence(candidate)
        self.assertEqual(candidate.website, "")
        self.assertIn("https://www.yelp.com/biz/acme-oakland", candidate.source_urls)
        self.assertTrue(any("own site" in w for w in warnings))

    def test_unevidenced_phone_and_contact_are_blanked(self):
        candidate = make_candidate(
            phone="(415) 555-0999",
            contact_person="John Smith",
        )
        warnings = enforce_evidence(candidate)
        self.assertEqual(candidate.phone, "")
        self.assertEqual(candidate.contact_person, "")
        self.assertTrue(any("phone blanked" in w for w in warnings))
        self.assertTrue(any("contact_person blanked" in w for w in warnings))

    def test_candidate_without_name_gets_warning(self):
        candidate = make_candidate(name="  ")
        warnings = enforce_evidence(candidate)
        self.assertTrue(any("no name" in w for w in warnings))


class TestCriteriaAndScoring(unittest.TestCase):
    def setUp(self):
        self.plan = ResearchPlan(
            kind=TargetKind.BUSINESS,
            request="find contractors",
            criteria=["Is a general contractor", "Has a verifiable website"],
        )

    def test_match_criteria_finds_supported_criteria(self):
        candidate = make_candidate()
        matched = match_criteria(candidate, self.plan)
        self.assertIn("Is a general contractor", matched)

    def test_scoring_rewards_verified_contact_info(self):
        full = make_candidate()
        enforce_evidence(full)
        full.criteria_matched = match_criteria(full, self.plan)
        score_full, _ = score_candidate(full, self.plan)

        no_email = make_candidate(email="")
        enforce_evidence(no_email)
        no_email.criteria_matched = match_criteria(no_email, self.plan)
        score_bare, _ = score_candidate(no_email, self.plan)

        self.assertGreater(score_full, score_bare)
        self.assertLessEqual(score_full, 100.0)
        self.assertGreaterEqual(score_bare, 0.0)

    def test_dedupe_key_prefers_domain(self):
        candidate = make_candidate()
        self.assertEqual(dedupe_key(candidate), "domain:acmeconstruction.example")
        candidate2 = make_candidate(website="", profile_url="")
        self.assertTrue(dedupe_key(candidate2).startswith("name:"))

    def test_merge_keeps_richest_fields_and_unions_evidence(self):
        primary = make_candidate(email="")
        other = make_candidate(
            email="bids@acmeconstruction.example",
            location="Oakland, CA",
            evidence=[EvidenceQuote(text="extra quote", url="https://news.example/acme")],
        )
        merged = merge_candidates(primary, other)
        self.assertEqual(merged.email, "bids@acmeconstruction.example")
        self.assertEqual(merged.location, "Oakland, CA")
        self.assertEqual(len(merged.evidence), 2)


if __name__ == "__main__":
    unittest.main()
