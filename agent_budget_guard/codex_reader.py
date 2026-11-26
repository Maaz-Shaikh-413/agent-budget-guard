"""Import token usage records from local Codex CLI rollout files."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, Optional

from agent_budget_guard.tracker import UsageEvent


DEFAULT_CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
DEFAULT_IMPORT_DB = Path(__file__).resolve().parent.parent / ".agent-budget-guard" / "codex_usage.sqlite"


def calculate_codex_cost(totals: dict, pricing: dict) -> tuple:
    """Return known API-equivalent cost and whether any pricing is incomplete."""
    cost = 0.0
    incomplete = False
    for model, (inputs, outputs, cached_inputs) in totals.items():
        if model not in pricing:
            incomplete = True
            continue
        prices = pricing[model]
        cached_inputs = min(cached_inputs, inputs)
        cost += (inputs - cached_inputs) * prices["input_per_1m"] / 1_000_000
        cost += outputs * prices["output_per_1m"] / 1_000_000
        if cached_inputs:
            cached_price = prices.get("cached_input_per_1m")
            if cached_price is None:
                incomplete = True
            else:
                cost += cached_inputs * cached_price / 1_000_000
    return cost, incomplete


def load_codex_usage_totals(database: Path = DEFAULT_IMPORT_DB) -> tuple:
    """Read the aggregate counts and record count from the Codex usage ledger."""
    if not database.exists():
        return {}, 0
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(usage)")}
        required = {"model", "input_tokens", "output_tokens"}
        if not required.issubset(columns):
            raise ValueError("Codex usage ledger has an unexpected schema")
        cached_column = "cached_input_tokens" if "cached_input_tokens" in columns else "0"
        rows = conn.execute(
            "SELECT model, SUM(input_tokens), SUM(output_tokens), "
            f"SUM({cached_column}) FROM usage GROUP BY model"
        ).fetchall()
        count = conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
    totals = {
        model: (int(inputs or 0), int(outputs or 0), int(cached or 0))
        for model, inputs, outputs, cached in rows
    }
    return totals, int(count)


def load_codex_usage_daily(database: Path = DEFAULT_IMPORT_DB, limit: int = 7) -> Optional[list]:
    """Return a recent UTC-date window, or None when the ledger lacks timestamps."""
    if not database.exists():
        return []
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(usage)")}
        if "event_timestamp" not in columns:
            return None
        cached_column = "cached_input_tokens" if "cached_input_tokens" in columns else "0"
        rows = conn.execute(
            "SELECT date(event_timestamp), SUM(input_tokens), "
            f"SUM({cached_column}), SUM(output_tokens), COUNT(*) "
            "FROM usage WHERE event_timestamp IS NOT NULL "
            "AND date(event_timestamp) IS NOT NULL "
            "GROUP BY date(event_timestamp) ORDER BY date(event_timestamp) DESC LIMIT ?",
            (limit,),
        ).fetchall()
    if not rows:
        return []
    by_day = {
        day: (int(inputs or 0), int(cached or 0), int(outputs or 0), int(count))
        for day, inputs, cached, outputs, count in rows
    }
    latest = date.fromisoformat(rows[0][0])
    return [
        (day.isoformat(), *by_day.get(day.isoformat(), (0, 0, 0, 0)))
        for day in (latest - timedelta(days=offset) for offset in range(limit))
    ]


@dataclass(frozen=True)
class CodexUsage:
    event_id: str
    event: UsageEvent
    timestamp: Optional[str] = None


def _counts(data: object) -> Optional[tuple]:
    if not isinstance(data, dict):
        return None
    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    if (not isinstance(input_tokens, int) or isinstance(input_tokens, bool)
            or not isinstance(output_tokens, int) or isinstance(output_tokens, bool)
            or input_tokens < 0 or output_tokens < 0):
        return None
    details = data.get("input_tokens_details")
    cached = data.get("cached_input_tokens")
    if cached is None and isinstance(details, dict):
        cached = details.get("cached_tokens")
    if cached is None:
        cached = 0
    if not isinstance(cached, int) or isinstance(cached, bool) or cached < 0:
        cached = 0
    return input_tokens, output_tokens, min(cached, input_tokens)


def read_codex_records(sessions_dir: Path = DEFAULT_CODEX_SESSIONS) -> Iterator[CodexUsage]:
    """Yield per-response Codex usage, without exposing transcript content."""
    if not sessions_dir.exists():
        return
    for path in sorted(sessions_dir.rglob("*.jsonl")):
        yield from _read_one_file(path)


def import_codex_usage(
    sessions_dir: Path = DEFAULT_CODEX_SESSIONS,
    database: Path = DEFAULT_IMPORT_DB,
) -> tuple:
    """Persist previously unseen rollout records and return totals and new count."""
    database.parent.mkdir(parents=True, exist_ok=True)
    imported_now = 0
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS usage (
            source TEXT NOT NULL, event_id TEXT NOT NULL, model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
            cached_input_tokens INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(source, event_id))""")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(usage)")}
        if "cached_input_tokens" not in columns:
            conn.execute("ALTER TABLE usage ADD COLUMN cached_input_tokens INTEGER NOT NULL DEFAULT 0")
        if "event_timestamp" not in columns:
            conn.execute("ALTER TABLE usage ADD COLUMN event_timestamp TEXT")
        for path in sorted(sessions_dir.rglob("*.jsonl")) if sessions_dir.exists() else []:
            # Parse each file independently so event IDs are scoped to a rollout.
            relative_source = str(path.relative_to(sessions_dir))
            for item in _read_one_file(path):
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO usage "
                    "(source, event_id, model, input_tokens, output_tokens, cached_input_tokens, event_timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (relative_source, item.event_id, item.event.model,
                     item.event.input_tokens, item.event.output_tokens, item.event.cached_input_tokens,
                     item.timestamp),
                )
                imported_now += cursor.rowcount
                if cursor.rowcount == 0 and item.timestamp is not None:
                    # Backfill timestamps for rows imported by older versions,
                    # without changing their existing token counts or IDs.
                    conn.execute(
                        "UPDATE usage SET event_timestamp = ? "
                        "WHERE source = ? AND event_id = ? AND event_timestamp IS NULL",
                        (item.timestamp, relative_source, item.event_id),
                    )
        conn.commit()
        rows = conn.execute(
            "SELECT model, SUM(input_tokens), SUM(output_tokens), SUM(cached_input_tokens) "
            "FROM usage GROUP BY model"
        ).fetchall()
        count = conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
    totals = {model: (int(inputs), int(outputs), int(cached)) for model, inputs, outputs, cached in rows}
    return totals, count, imported_now


def _read_one_file(path: Path) -> Iterator[CodexUsage]:
    model = "unknown"
    last_cumulative: Dict[str, tuple] = {}
    try:
        stream = path.open("r", encoding="utf-8")
    except OSError:
        return
    with stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            kind, payload = record.get("type"), record.get("payload")
            if kind == "turn_context" and isinstance(payload, dict):
                candidate = payload.get("model")
                if isinstance(candidate, str) and candidate:
                    model = candidate
                continue
            if kind != "token_usage_record" or not isinstance(payload, dict):
                continue
            # Current `usage` values are per-response. The other fields are
            # cumulative totals, so use a delta only for the legacy fallback.
            counts = _counts(payload.get("usage"))
            cumulative = _counts(payload.get("turn_token_usage"))
            usage = payload.get("usage")
            candidate = payload.get("model")
            if not isinstance(candidate, str) or not candidate:
                candidate = usage.get("model") if isinstance(usage, dict) else None
            if isinstance(candidate, str) and candidate:
                model = candidate
            thread = str(payload.get("thread_id") or payload.get("session_id") or "")
            previous = last_cumulative.get(thread, (0, 0, 0))
            if cumulative is not None:
                last_cumulative[thread] = cumulative
            if counts is None:
                counts = cumulative
                if counts is not None:
                    delta = tuple(max(0, counts[i] - previous[i]) for i in range(3))
                    counts = delta
            if counts is None:
                continue
            response_id = payload.get("response_id")
            thread_id, turn_id = payload.get("thread_id"), payload.get("turn_id")
            fallback = f"{thread_id}:{turn_id}" if thread_id and turn_id else f"line:{line_number}"
            event_id = str(response_id or fallback)
            timestamp = record.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    # A zone-less timestamp cannot be safely assigned a calendar day.
                    if parsed_timestamp.tzinfo is None:
                        timestamp = None
                except ValueError:
                    timestamp = None
            else:
                timestamp = None
            yield CodexUsage(event_id, UsageEvent(model, counts[0], counts[1], counts[2]), timestamp)
