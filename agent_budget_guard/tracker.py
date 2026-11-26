
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List


DEFAULT_USAGE_FILE = Path.home() / ".agent-budget-guard" / "usage.jsonl"


@dataclass
class UsageEvent:
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


def record_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    usage_file: Path = DEFAULT_USAGE_FILE,
) -> None:
    """Save one token-usage event to a JSONL file."""

    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts cannot be negative.")

    event = UsageEvent(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    usage_file.parent.mkdir(parents=True, exist_ok=True)

    with usage_file.open("a", encoding="utf-8") as file:
        file.write(json.dumps(asdict(event)) + "\n")


def load_usage(
    usage_file: Path = DEFAULT_USAGE_FILE,
) -> List[UsageEvent]:
    """Load saved usage events."""

    if not usage_file.exists():
        return []

    events = []

    with usage_file.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            data = json.loads(line)
            events.append(UsageEvent(**data))

    return events


def calculate_cost(
    event: UsageEvent,
    pricing: Dict[str, Dict[str, float]],
) -> float:
    """
    Calculate cost using per-million-token prices.

    Example pricing:
    {
        "model-name": {
            "input_per_1m": 1.00,
            "output_per_1m": 5.00
        }
    }
    """

    if event.model not in pricing:
        raise ValueError(f"No pricing configured for model: {event.model}")

    model_prices = pricing[event.model]

    input_price = model_prices["input_per_1m"]
    output_price = model_prices["output_per_1m"]

    cached_tokens = min(event.cached_input_tokens, event.input_tokens)
    cached_price = model_prices.get("cached_input_per_1m")
    if cached_tokens and cached_price is None:
        raise ValueError("Cached input tokens present but cached_input_per_1m is not configured")
    input_cost = (event.input_tokens - cached_tokens) * input_price / 1_000_000
    if cached_tokens:
        input_cost += cached_tokens * cached_price / 1_000_000
    output_cost = event.output_tokens * output_price / 1_000_000

    return input_cost + output_cost


def calculate_total_cost(
    events: List[UsageEvent],
    pricing: Dict[str, Dict[str, float]],
) -> float:
    """Calculate total cost for all usage events."""

    return sum(calculate_cost(event, pricing) for event in events)


def budget_status(
    total_cost: float,
    budget: float,
) -> Dict[str, object]:
    """Return spent amount, remaining budget, and limit status."""

    if budget <= 0:
        raise ValueError("Budget must be greater than zero.")

    remaining = max(budget - total_cost, 0.0)

    return {
        "spent": round(total_cost, 6),
        "remaining": round(remaining, 6),
        "over_budget": total_cost >= budget,
    }
