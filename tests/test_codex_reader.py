import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_budget_guard.codex_reader import import_codex_usage, read_codex_records


class CodexReaderTests(unittest.TestCase):
    def write_records(self, root, records):
        file = root / "2026" / "01" / "02" / "rollout-test.jsonl"
        file.parent.mkdir(parents=True)
        file.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
        return file

    def test_imports_only_usage_and_uses_per_turn_usage_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "sessions"
            root.mkdir()
            self.write_records(root, [
                {"type": "response_item", "payload": {"content": "private prompt"}},
                {"type": "token_usage_record", "payload": {
                    "response_id": "r1", "turn_token_usage": {"input_tokens": 100, "output_tokens": 10},
                    "thread_token_usage": {"input_tokens": 100, "output_tokens": 10},
                    "usage": {"input_tokens": 100, "output_tokens": 10}},
                 "timestamp": "2026-01-02T10:00:00.000Z"},
                {"type": "token_usage_record", "payload": {
                    "response_id": "r2", "turn_token_usage": {"input_tokens": 180, "output_tokens": 25},
                    "thread_token_usage": {"input_tokens": 180, "output_tokens": 25},
                    "usage": {"input_tokens": 80, "output_tokens": 15}},
                 "timestamp": "2026-01-02T10:01:00.000Z"},
            ])
            records = list(read_codex_records(root))
            self.assertEqual([(x.event.input_tokens, x.event.output_tokens) for x in records],
                             [(100, 10), (80, 15)])
            db = Path(temp) / "state.sqlite"
            totals, count, added = import_codex_usage(root, db)
            self.assertEqual((totals["unknown"], count, added), ((180, 25, 0), 2, 2))
            with sqlite3.connect(db) as conn:
                timestamps = conn.execute(
                    "SELECT event_timestamp FROM usage ORDER BY event_id"
                ).fetchall()
            self.assertEqual(timestamps, [("2026-01-02T10:00:00.000Z",), ("2026-01-02T10:01:00.000Z",)])
            totals, count, added = import_codex_usage(root, db)
            self.assertEqual((totals["unknown"], count, added), ((180, 25, 0), 2, 0))

    def test_cumulative_fallback_uses_deltas(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "sessions"
            root.mkdir()
            self.write_records(root, [
                {"type": "token_usage_record", "payload": {
                    "response_id": "r1", "thread_id": "thread",
                    "turn_token_usage": {"input_tokens": 40, "output_tokens": 4}}},
                {"type": "token_usage_record", "payload": {
                    "response_id": "r2", "thread_id": "thread",
                    "turn_token_usage": {"input_tokens": 90, "output_tokens": 9}}},
            ])
            records = list(read_codex_records(root))
            self.assertEqual([(x.event.input_tokens, x.event.output_tokens) for x in records],
                             [(40, 4), (50, 5)])

    def test_migrates_existing_ledger_preserving_rows_and_dedupe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "sessions"
            root.mkdir()
            file = self.write_records(root, [{
                "type": "token_usage_record", "timestamp": "2026-01-03T01:00:00Z",
                "payload": {"response_id": "same-id", "usage": {"input_tokens": 7, "output_tokens": 2}},
            }])
            db = Path(temp) / "legacy.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE usage (source TEXT NOT NULL, event_id TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, PRIMARY KEY(source, event_id))")
                conn.execute("INSERT INTO usage VALUES (?, ?, ?, ?, ?)", ("old.jsonl", "old", "old-model", 11, 4))

            totals, count, added = import_codex_usage(root, db)
            self.assertEqual((totals["old-model"], count, added), ((11, 4, 0), 2, 1))
            totals, count, added = import_codex_usage(root, db)
            self.assertEqual((count, added), (2, 0))
            with sqlite3.connect(db) as conn:
                rows = conn.execute("SELECT event_id, event_timestamp FROM usage ORDER BY event_id").fetchall()
            self.assertEqual(rows, [("old", None), ("same-id", "2026-01-03T01:00:00Z")])

    def test_backfills_existing_duplicate_timestamp_without_changing_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "sessions"
            root.mkdir()
            self.write_records(root, [{
                "type": "token_usage_record", "timestamp": "2026-01-04T01:00:00Z",
                "payload": {"response_id": "already-imported", "usage": {"input_tokens": 20, "output_tokens": 5}},
            }])
            source = "2026/01/02/rollout-test.jsonl"
            db = Path(temp) / "ledger.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE usage (source TEXT NOT NULL, event_id TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cached_input_tokens INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(source, event_id))")
                conn.execute("INSERT INTO usage VALUES (?, ?, ?, ?, ?, ?)", (source, "already-imported", "preserved-model", 9, 3, 1))

            totals, count, added = import_codex_usage(root, db)

            self.assertEqual((totals["preserved-model"], count, added), ((9, 3, 1), 1, 0))
            with sqlite3.connect(db) as conn:
                timestamp = conn.execute("SELECT event_timestamp FROM usage").fetchone()[0]
            self.assertEqual(timestamp, "2026-01-04T01:00:00Z")

    def test_timestamp_missing_or_timezone_naive_is_null(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "sessions"
            root.mkdir()
            self.write_records(root, [
                {"type": "token_usage_record", "payload": {"response_id": "no-time", "usage": {"input_tokens": 1, "output_tokens": 1}}},
                {"type": "token_usage_record", "timestamp": "2026-01-02T10:00:00", "payload": {"response_id": "naive", "usage": {"input_tokens": 1, "output_tokens": 1}}},
            ])
            db = Path(temp) / "usage.sqlite"
            import_codex_usage(root, db)
            with sqlite3.connect(db) as conn:
                rows = conn.execute("SELECT event_timestamp FROM usage ORDER BY event_id").fetchall()
            self.assertEqual(rows, [(None,), (None,)])

    def test_unknown_model_and_cached_input_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "sessions"
            root.mkdir()
            self.write_records(root, [{"type": "token_usage_record", "payload": {
                "response_id": "r1", "usage": {
                    "input_tokens": 100, "output_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 60},
                },
            }}])
            records = list(read_codex_records(root))
            self.assertEqual(records[0].event.model, "unknown")
            self.assertEqual(records[0].event.cached_input_tokens, 60)
            totals, _, _ = import_codex_usage(root, Path(temp) / "usage.sqlite")
            self.assertEqual(totals["unknown"], (100, 10, 60))

    def test_unconfigured_model_imports_and_cost_is_incomplete(self):
        from agent_budget_guard.codex_reader import calculate_codex_cost

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "sessions"
            root.mkdir()
            self.write_records(root, [
                {"type": "turn_context", "payload": {"model": "gpt-6-luna"}},
                {"type": "token_usage_record", "payload": {
                    "response_id": "r1",
                    "usage": {"input_tokens": 120, "output_tokens": 30},
                }},
            ])
            totals, count, added = import_codex_usage(root, Path(temp) / "usage.sqlite")

            self.assertEqual(totals, {"gpt-6-luna": (120, 30, 0)})
            self.assertEqual((count, added), (1, 1))
            cost, incomplete = calculate_codex_cost(totals, {})
            self.assertEqual(cost, 0.0)
            self.assertTrue(incomplete)

    def test_missing_cached_pricing_excludes_cached_cost_and_marks_incomplete(self):
        from agent_budget_guard.codex_reader import calculate_codex_cost

        cost, incomplete = calculate_codex_cost(
            {"model-x": (100, 10, 60)},
            {"model-x": {"input_per_1m": 1.0, "output_per_1m": 5.0}},
        )
        self.assertEqual(cost, 40 * 1.0 / 1_000_000 + 10 * 5.0 / 1_000_000)
        self.assertTrue(incomplete)


if __name__ == "__main__":
    unittest.main()
