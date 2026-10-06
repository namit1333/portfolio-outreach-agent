"""CLI-level tests through the public interface (main)."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from outreach_agent.cli import main

REQUEST = "Find construction businesses for our robotics portfolio company"


class TestCliRun(unittest.TestCase):
    def test_run_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main([
                "run", REQUEST,
                "--provider", "mock", "--search", "none",
                "--out", tmp, "--run-name", "cli-test",
                "--sender-name", "Namit", "--quiet",
            ])
            self.assertEqual(code, 0)
            out_dir = Path(tmp) / "cli-test"
            for artifact in ("prospects.csv", "outreach.md", "plan.json", "run.json"):
                self.assertTrue((out_dir / artifact).is_file(), artifact)

    def test_run_prints_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main([
                    "run", REQUEST, "--provider", "mock", "--search", "none",
                    "--out", tmp, "--run-name", "summary-test", "--quiet",
                ])
            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("Kept:", output)
            self.assertIn("outreach.md", output)


class TestCliPlan(unittest.TestCase):
    def test_plan_prints_json(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["plan", REQUEST, "--provider", "mock", "--search", "none"])
        self.assertEqual(code, 0)
        plan = json.loads(buffer.getvalue())
        self.assertEqual(plan["kind"], "business")
        self.assertGreaterEqual(len(plan["queries"]), 4)
        self.assertTrue(plan["criteria"])


class TestCliProviders(unittest.TestCase):
    def test_providers_command(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["providers"])
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("ANTHROPIC_API_KEY", output)
        self.assertIn("resolved provider", output)


if __name__ == "__main__":
    unittest.main()
