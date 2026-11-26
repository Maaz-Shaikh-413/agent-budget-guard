import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from agent_budget_guard.cli import app
from agent_budget_guard.codex_reader import load_codex_usage_daily
from agent_budget_guard.dashboard import daily_token_chart


class DashboardCommandTests(unittest.TestCase):
    def make_ledger(self, path):
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE usage (source TEXT NOT NULL, event_id TEXT NOT NULL, "
                "model TEXT NOT NULL, input_tokens INTEGER NOT NULL, "
                "output_tokens INTEGER NOT NULL, cached_input_tokens INTEGER NOT NULL DEFAULT 0, "
                "event_timestamp TEXT, "
                "PRIMARY KEY(source, event_id))"
            )
            conn.executemany(
                "INSERT INTO usage VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("rollout.jsonl", "1", "gpt-6-luna", 100, 20, 40, "2026-01-02T10:00:00Z"),
                    ("rollout.jsonl", "2", "sample-model", 50, 10, 0, "2026-01-01T10:00:00Z"),
                ],
            )

    def test_shows_totals_and_marks_unpriced_model_unavailable(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "usage.sqlite"
            pricing = Path(temp) / "pricing.json"
            self.make_ledger(ledger)
            pricing.write_text(json.dumps({
                "sample-model": {"input_per_1m": 1.0, "output_per_1m": 2.0},
            }), encoding="utf-8")

            result = runner.invoke(app, [
                "dashboard", "--database", str(ledger), "--pricing-file", str(pricing),
            ])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Codex records: 2", result.output)
        self.assertIn("Input tokens: 150", result.output)
        self.assertIn("Cached input tokens: 40", result.output)
        self.assertIn("Output tokens: 30", result.output)
        self.assertIn("cost", result.output)
        self.assertIn("Unavailable", result.output)
        self.assertIn("gpt-6-luna", result.output)
        self.assertNotIn("$0.", result.output)

    def test_calculates_cost_when_every_model_is_priced(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "usage.sqlite"
            pricing = Path(temp) / "pricing.json"
            self.make_ledger(ledger)
            pricing.write_text(json.dumps({
                "gpt-6-luna": {
                    "input_per_1m": 2.0,
                    "cached_input_per_1m": 1.0,
                    "output_per_1m": 4.0,
                },
                "sample-model": {"input_per_1m": 1.0, "output_per_1m": 2.0},
            }), encoding="utf-8")

            result = runner.invoke(app, [
                "dashboard", "--database", str(ledger), "--pricing-file", str(pricing),
            ])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Estimated API-equivalent cost: $0.000310", result.output)

    def test_dashboard_without_pricing_file_still_shows_usage(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "usage.sqlite"
            missing_pricing = Path(temp) / "missing.json"
            self.make_ledger(ledger)

            result = runner.invoke(app, [
                "dashboard", "--database", str(ledger), "--pricing-file", str(missing_pricing),
            ])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Input tokens: 150", result.output)
        self.assertIn("Unavailable", result.output)

    def test_daily_section_shows_records_by_event_date(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "usage.sqlite"
            pricing = Path(temp) / "pricing.json"
            self.make_ledger(ledger)

            result = runner.invoke(app, [
                "dashboard", "--database", str(ledger), "--pricing-file", str(pricing),
            ])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Daily Codex Usage", result.output)
        self.assertIn("2026-01-02 | 100 | 40 | 20 | 1", result.output)
        self.assertIn("2026-01-01 | 50 | 0 | 10 | 1", result.output)

    def test_daily_aggregates_cached_tokens_converts_offsets_and_limits_to_seven_dates(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "usage.sqlite"
            with sqlite3.connect(ledger) as conn:
                conn.execute(
                    "CREATE TABLE usage (source TEXT, event_id TEXT, model TEXT, input_tokens INTEGER, "
                    "output_tokens INTEGER, cached_input_tokens INTEGER, event_timestamp TEXT)"
                )
                conn.executemany(
                    "INSERT INTO usage VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        ("r", str(day), "m", 10, 2, day, f"2026-02-{day:02d}T12:00:00Z")
                        for day in range(1, 9)
                    ] + [
                        ("r", "offset", "m", 5, 1, 3, "2026-02-08T01:00:00+05:00"),
                        ("r", "null", "m", 100, 100, 50, None),
                    ],
                )

            daily = load_codex_usage_daily(ledger)

        self.assertEqual(len(daily), 7)
        self.assertEqual(daily[0], ("2026-02-08", 10, 8, 2, 1))
        self.assertEqual(daily[1], ("2026-02-07", 15, 10, 3, 2))
        self.assertEqual(daily[-1][0], "2026-02-02")
        self.assertEqual([row[0] for row in daily], sorted((row[0] for row in daily), reverse=True))

    def test_empty_ledger_shows_zero_totals_and_daily_unavailable(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "usage.sqlite"
            pricing = Path(temp) / "pricing.json"
            with sqlite3.connect(ledger) as conn:
                conn.execute(
                    "CREATE TABLE usage (source TEXT, event_id TEXT, model TEXT, "
                    "input_tokens INTEGER, output_tokens INTEGER, cached_input_tokens INTEGER)"
                )

            result = runner.invoke(app, [
                "dashboard", "--database", str(ledger), "--pricing-file", str(pricing),
            ])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Codex records: 0", result.output)
        self.assertIn("Input tokens: 0", result.output)
        self.assertIn("Cached input tokens: 0", result.output)
        self.assertIn("Output tokens: 0", result.output)
        self.assertIn("Daily grouping unavailable", result.output)

    def test_daily_chart_formats_input_and_output_bars(self):
        chart = daily_token_chart([
            ("2026-03-02", 100, 20, 50, 1),
            ("2026-03-01", 0, 0, 0, 0),
        ])
        self.assertIn("Daily token chart (UTC)", chart)
        self.assertIn("2026-03-02 I", chart)
        self.assertIn("O", chart)
        self.assertIn("2026-03-01 I · 0 | O · 0", chart)

    def test_daily_chart_handles_empty_data(self):
        self.assertEqual(daily_token_chart([]), "No daily usage to chart.")

    def test_daily_chart_handles_single_day_usage(self):
        chart = daily_token_chart([("2026-03-02", 12, 3, 4, 1)])
        self.assertIn("2026-03-02 I", chart)
        self.assertIn("| O", chart)
        self.assertNotIn("None", chart)


if __name__ == "__main__":
    unittest.main()
