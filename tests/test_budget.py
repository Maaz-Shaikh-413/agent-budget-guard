import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from agent_budget_guard.budget import (
    calculate_token_budget_status,
    load_monthly_budget,
    monthly_token_usage,
    set_monthly_budget,
)
from agent_budget_guard.cli import app


class TokenBudgetTests(unittest.TestCase):
    def test_budget_not_configured(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            self.assertIsNone(load_monthly_budget(config))
            result = CliRunner().invoke(app, ["budget-status", "--config-file", str(config)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("No monthly token budget configured", result.output)

    def test_set_and_load_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            set_monthly_budget(1_000_000, config)
            self.assertEqual(load_monthly_budget(config), 1_000_000)
            self.assertEqual(json.loads(config.read_text()), {"monthly_token_budget": 1_000_000})

    def test_status_below_80_percent(self):
        result = calculate_token_budget_status(79, 100)
        self.assertEqual(result["remaining"], 21)
        self.assertFalse(result["warning"])
        self.assertFalse(result["exceeded"])

    def test_status_at_80_percent(self):
        result = calculate_token_budget_status(80, 100)
        self.assertTrue(result["warning"])
        self.assertFalse(result["exceeded"])

    def test_status_at_100_percent(self):
        result = calculate_token_budget_status(100, 100)
        self.assertEqual(result["remaining"], 0)
        self.assertTrue(result["exceeded"])

    def test_status_above_100_percent(self):
        result = calculate_token_budget_status(125, 100)
        self.assertEqual(result["remaining"], 0)
        self.assertTrue(result["exceeded"])
        self.assertEqual(result["percentage"], 125)

    def test_monthly_usage_calculation(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "usage.sqlite"
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE usage (input_tokens INTEGER, output_tokens INTEGER, event_timestamp TEXT)")
                conn.executemany("INSERT INTO usage VALUES (?, ?, ?)", [
                    (10, 2, "2026-05-01T00:00:00Z"),
                    (30, 8, "2026-05-31T23:59:59Z"),
                    (100, 100, "2026-06-01T00:00:00Z"),
                    (500, 500, None),
                ])
            self.assertEqual(monthly_token_usage(database, date(2026, 5, 19)), 50)

    def test_dashboard_displays_budget_when_configured(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            database = Path(temp) / "usage.sqlite"
            set_monthly_budget(100, config)
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE usage (model TEXT, input_tokens INTEGER, output_tokens INTEGER, cached_input_tokens INTEGER, event_timestamp TEXT)")
                today = datetime.now(timezone.utc).date()
                conn.execute("INSERT INTO usage VALUES ('m', 80, 0, 0, ?)", (f"{today.isoformat()}T00:00:00Z",))
            result = CliRunner().invoke(app, [
                "dashboard", "--database", str(database), "--config-file", str(config),
                "--pricing-file", str(Path(temp) / "missing-prices.json"),
            ])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Monthly token budget: 100", result.output)
            self.assertIn("Warning", result.output)


if __name__ == "__main__":
    unittest.main()
