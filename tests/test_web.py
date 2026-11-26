import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_budget_guard.budget import set_monthly_budget
from agent_budget_guard.web import create_app


class WebDashboardTests(unittest.TestCase):
    @staticmethod
    def endpoint(app, path, method="GET"):
        route = next(
            route for route in app.routes
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set())
        )
        return route.endpoint()

    def test_page_has_responsive_dashboard_structure_and_refresh_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            response = self.endpoint(create_app(root / "usage.sqlite", root / "config.json"), "/")

        body = response.body.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="viewport"', body)
        self.assertIn("@media(max-width:760px)", body)
        self.assertIn("@media(max-width:560px)", body)
        self.assertIn("Local usage", body)
        self.assertIn("Sync Codex usage", body)
        self.assertIn('id="refresh"', body)
        self.assertIn("Last refreshed", body)

    def test_empty_ledger_api_returns_aggregates_and_empty_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "usage.sqlite"
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE usage (model TEXT, input_tokens INTEGER, output_tokens INTEGER, cached_input_tokens INTEGER, event_timestamp TEXT)")
            response = self.endpoint(create_app(database, root / "config.json"), "/api/dashboard")

        data = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["tokens"], {"input": 0, "cached_input": 0, "output": 0})
        self.assertEqual(data["records"], 0)
        self.assertEqual(data["daily"], [])
        self.assertIsNone(data["budget"])
        self.assertIn("refreshed_at", data)
        self.assertNotIn("usage", data)

    def test_dashboard_api_returns_safe_aggregates_budget_and_zero_days(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database, config = root / "usage.sqlite", root / "config.json"
            set_monthly_budget(100, config)
            today = datetime.now(timezone.utc).date().isoformat()
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE usage (source TEXT, event_id TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER, cached_input_tokens INTEGER, event_timestamp TEXT)")
                conn.execute("INSERT INTO usage VALUES ('rollout-secret', 'event-secret', 'model-secret', 80, 10, 30, ?)", (today + "T12:00:00Z",))
            response = self.endpoint(create_app(database, config), "/api/dashboard")

        body = response.body.decode()
        data = json.loads(body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["tokens"], {"input": 80, "cached_input": 30, "output": 10})
        self.assertEqual(data["budget"]["used"], 90)
        self.assertTrue(data["budget"]["warning"])
        self.assertEqual(data["daily"][-1]["date"], today)
        self.assertTrue(all(not day["input"] and not day["output"] for day in data["daily"][:-1]))
        for secret in ("rollout-secret", "event-secret", "model-secret"):
            self.assertNotIn(secret, body)

    def test_sync_calls_existing_deduplicating_importer_and_returns_refreshed_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sessions = root / "sessions"
            sessions.mkdir()
            (sessions / "rollout.jsonl").write_text(
                json.dumps({"type": "turn_context", "payload": {"model": "private-model"}}) + "\n" +
                json.dumps({"timestamp": "2026-01-01T12:00:00Z", "type": "token_usage_record", "payload": {"response_id": "secret-id", "usage": {"input_tokens": 12, "output_tokens": 3}}}) + "\n",
                encoding="utf-8",
            )
            app = create_app(root / "usage.sqlite", root / "config.json", sessions)
            first = self.endpoint(app, "/api/sync", "POST")
            second = self.endpoint(app, "/api/sync", "POST")

        first_data, second_data = json.loads(first.body), json.loads(second.body)
        self.assertTrue(first_data["ok"])
        self.assertEqual(first_data["imported"], 1)
        self.assertEqual(first_data["dashboard"]["tokens"]["output"], 3)
        self.assertEqual(second_data["imported"], 0)


if __name__ == "__main__":
    unittest.main()
