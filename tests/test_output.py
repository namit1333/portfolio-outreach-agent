"""Artifact assembly tests: CSV, Markdown package, drafts, JSON."""

import csv
import json
import tempfile
import unittest
from email import policy as email_policy
from email.parser import BytesParser
from pathlib import Path

from outreach_agent.config import Settings
from outreach_agent.models import Sender
from outreach_agent.output import BUSINESS_COLUMNS, TALENT_COLUMNS, write_run
from outreach_agent.pipeline import run_pipeline

BUSINESS_REQUEST = "Meet general contractor and construction businesses for our robotics portfolio company"
TALENT_REQUEST = "Surface systems engineer profiles with robotics commissioning experience"


def mock_settings(**kwargs) -> Settings:
    base = dict(provider="mock", search="none", limit=10, concurrency=4, min_score=20.0)
    base.update(kwargs)
    return Settings(**base)


class TestBusinessArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.result = run_pipeline(BUSINESS_REQUEST, mock_settings(),
                                  sender=Sender(name="Namit Tatipigari"))
        cls.out_dir = write_run(cls.result, cls.tmp.name, run_name="business-test")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_json_artifacts_parse(self):
        plan = json.loads((self.out_dir / "plan.json").read_text(encoding="utf-8"))
        run = json.loads((self.out_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["kind"], "business")
        self.assertEqual(run["providers"]["llm"], "mock")
        self.assertTrue(run["events"])

    def test_csv_rows_match_candidates(self):
        with (self.out_dir / "prospects.csv").open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, BUSINESS_COLUMNS)
            rows = list(reader)
        self.assertEqual(len(rows), len(self.result.candidates))
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Bay Crest Builders Inc"]["email"], "")
        self.assertEqual(by_name["Northgate Electric Systems"]["website"], "")
        self.assertEqual(by_name["Northgate Electric Systems"]["email"],
                         "office@northgateelectric.example")

    def test_eml_drafts_are_sendable(self):
        draft_dir = self.out_dir / "drafts"
        eml_files = list(draft_dir.glob("*.eml"))
        txt_files = list(draft_dir.glob("*.txt"))
        self.assertEqual(len(eml_files) + len(txt_files), len(self.result.candidates))
        self.assertGreaterEqual(len(eml_files), 2)
        for path in eml_files:
            message = BytesParser(policy=email_policy.default).parsebytes(path.read_bytes())
            self.assertIn("@", message["To"])
            self.assertTrue(message["Subject"])
            body = message.get_body(preferencelist=("plain",)).get_content()
            self.assertGreater(len(body.split()), 15)

    def test_markdown_package_has_everything(self):
        text = (self.out_dir / "outreach.md").read_text(encoding="utf-8")
        self.assertIn("# Outreach package", text)
        for candidate in self.result.candidates:
            self.assertIn(candidate.name, text)
        self.assertIn("**Subject:**", text)
        self.assertIn("Evidence:", text)
        # the aggregator-sourced candidate must surface its policy warning
        self.assertIn("Policy warnings", text)

    def test_csv_draft_file_paths_resolve(self):
        with (self.out_dir / "prospects.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            if row["draft_file"]:
                self.assertTrue((self.out_dir / row["draft_file"]).is_file(), row["draft_file"])


class TestTalentArtifacts(unittest.TestCase):
    def test_talent_csv_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(TALENT_REQUEST, mock_settings())
            out_dir = write_run(result, tmp, run_name="talent-test")
            with (out_dir / "prospects.csv").open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, TALENT_COLUMNS)
                rows = list(reader)
            self.assertEqual(len(rows), 3)
            linkedin_rows = [r for r in rows if r["send_via"] == "linkedin"]
            self.assertGreaterEqual(len(linkedin_rows), 1)
            for row in rows:
                self.assertTrue(row["profile_url"])


if __name__ == "__main__":
    unittest.main()
