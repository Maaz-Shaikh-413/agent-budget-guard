import csv
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from agent_budget_guard.cli import app


class ExportCommandTests(unittest.TestCase):
    def make_ledger(self, path):
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE usage (source TEXT, event_id TEXT, model TEXT, "
                "input_tokens INTEGER, output_tokens INTEGER, cached_input_tokens INTEGER, event_timestamp TEXT)"
            )
            conn.executemany(
                "INSERT INTO usage VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("rollout", "1", 'model, "one"', 100, 25, 40, "2026-01-02T01:30:00+05:30"),
                    ("rollout", "2", "model-two", 10, 3, 0, None),
                ],
            )

    def test_exports_headers_values_utc_and_escaped_model(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "usage.sqlite"
            output = Path(temp) / "reports" / "usage.csv"
            self.make_ledger(ledger)
            result = runner.invoke(app, ["export", "--format", "csv", "--database", str(ledger), "--output", str(output)])

            self.assertEqual(result.exit_code, 0, result.output)
            with output.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(list(rows[0]), ["event_timestamp_utc", "date_utc", "model", "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"])
            by_model = {row["model"]: row for row in rows}
            self.assertEqual(by_model['model, "one"'], {
                "event_timestamp_utc": "2026-01-01T20:00:00Z", "date_utc": "2026-01-01",
                "model": 'model, "one"', "input_tokens": "100", "cached_input_tokens": "40",
                "output_tokens": "25", "total_tokens": "125",
            })
            self.assertEqual(by_model["model-two"]["event_timestamp_utc"], "")
            self.assertEqual(by_model["model-two"]["date_utc"], "")
            self.assertEqual(by_model["model-two"]["total_tokens"], "13")

    def test_empty_ledger_writes_headers_and_default_path(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "usage.sqlite"
            with sqlite3.connect(ledger) as conn:
                conn.execute("CREATE TABLE usage (model TEXT, input_tokens INTEGER, output_tokens INTEGER)")
            old_cwd = Path.cwd()
            os.chdir(temp)
            try:
                result = runner.invoke(app, ["export", "--database", str(ledger)])
            finally:
                os.chdir(old_cwd)
            self.assertEqual(result.exit_code, 0, result.output)
            output = Path(temp) / "codex-usage.csv"
            self.assertTrue(output.exists())
            with output.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "event_timestamp_utc")


if __name__ == "__main__":
    unittest.main()
