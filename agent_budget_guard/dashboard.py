"""Read-only dashboard data for the Codex usage ledger."""

from typing import Tuple

from agent_budget_guard.codex_reader import calculate_codex_cost


def dashboard_totals(totals: dict, pricing: dict) -> Tuple[float, bool]:
    """Return a cost only when every model and token category is priced."""
    return calculate_codex_cost(totals, pricing)


def total_tokens(totals: dict) -> Tuple[int, int, int]:
    """Return aggregate input, cached input, and output token counts."""
    return (
        sum(value[0] for value in totals.values()),
        sum(value[2] for value in totals.values()),
        sum(value[1] for value in totals.values()),
    )


def daily_token_chart(daily_usage: list) -> str:
    """Format input and output token counts as a compact terminal bar chart."""
    if not daily_usage:
        return "No daily usage to chart."

    max_tokens = max(max(row[1], row[3]) for row in daily_usage)
    scale = max(max_tokens, 1)
    lines = ["Daily token chart (UTC)", "I = input, O = output"]
    for day, inputs, _cached, outputs, _records in daily_usage:
        input_bar = "█" * (inputs * 20 // scale)
        output_bar = "█" * (outputs * 20 // scale)
        lines.append(f"{day} I {input_bar or '·'} {inputs} | O {output_bar or '·'} {outputs}")
    return "\n".join(lines)
