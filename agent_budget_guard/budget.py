"""Monthly token budget configuration and reporting."""

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_CONFIG_FILE = Path.home() / ".agent-budget-guard" / "config.json"


def set_monthly_budget(tokens: int, config_file: Path = DEFAULT_CONFIG_FILE) -> None:
    if isinstance(tokens, bool) or tokens <= 0:
        raise ValueError("Budget tokens must be greater than zero.")
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps({"monthly_token_budget": tokens}, indent=2) + "\n", encoding="utf-8")


def load_monthly_budget(config_file: Path = DEFAULT_CONFIG_FILE) -> Optional[int]:
    if not config_file.exists():
        return None
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid budget configuration: {error}") from error
    if not isinstance(data, dict) or "monthly_token_budget" not in data:
        return None
    tokens = data["monthly_token_budget"]
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
        raise ValueError("Configured monthly_token_budget must be a positive integer.")
    return tokens


def monthly_token_usage(database: Path, month: Optional[date] = None) -> int:
    """Sum input plus output tokens for the current UTC calendar month."""
    month = month or datetime.now(timezone.utc).date()
    start = month.replace(day=1).isoformat()
    end = date(month.year + (month.month == 12), month.month % 12 + 1, 1).isoformat()
    if not database.exists():
        return 0
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(usage)")}
        if not {"input_tokens", "output_tokens", "event_timestamp"}.issubset(columns):
            return 0
        row = conn.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM usage "
            "WHERE event_timestamp IS NOT NULL AND date(event_timestamp) >= ? AND date(event_timestamp) < ?",
            (start, end),
        ).fetchone()
    return int(row[0] or 0)


def calculate_token_budget_status(used: int, budget: int) -> dict:
    if budget <= 0:
        raise ValueError("Budget tokens must be greater than zero.")
    percentage = used / budget * 100
    return {
        "used": used,
        "budget": budget,
        "remaining": max(budget - used, 0),
        "percentage": percentage,
        "warning": 80 <= percentage < 100,
        "exceeded": percentage >= 100,
    }
