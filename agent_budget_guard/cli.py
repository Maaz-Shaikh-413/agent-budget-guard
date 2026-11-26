
import json
import subprocess
from pathlib import Path
from typing import List

import typer
from rich.console import Console

from agent_budget_guard.tracker import (
    DEFAULT_USAGE_FILE,
    UsageEvent,
    budget_status,
    calculate_total_cost,
    load_usage,
    record_usage,
)
from agent_budget_guard.codex_reader import (
    DEFAULT_IMPORT_DB,
    calculate_codex_cost,
    import_codex_usage,
    load_codex_usage_daily,
    load_codex_usage_totals,
)
from agent_budget_guard.dashboard import daily_token_chart, total_tokens
from agent_budget_guard.budget import (
    DEFAULT_CONFIG_FILE,
    calculate_token_budget_status,
    load_monthly_budget,
    monthly_token_usage,
    set_monthly_budget,
)

app = typer.Typer(
    help="Monitor AI coding agent budgets.",
    no_args_is_help=True,
)

console = Console()

DEFAULT_PRICING_FILE = (
    Path.home() / ".agent-budget-guard" / "pricing.json"
)


@app.callback()
def main():
    """Agent Budget Guard CLI."""
    pass


@app.command()
def run(
    max_cost: float = typer.Option(
        2.00,
        "--max-cost",
        help="Maximum allowed budget in USD",
    ),
    command: List[str] = typer.Argument(
        ...,
        help="Command to execute",
    ),
):
    """Run a command under Agent Budget Guard."""

    if max_cost <= 0:
        console.print("[red]Budget must be greater than zero.[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold blue]Budget limit: ${max_cost:.2f}[/bold blue]")
    console.print(f"[yellow]Running:[/yellow] {' '.join(command)}")

    try:
        result = subprocess.run(command, check=False)

        console.print(
            f"[green]Process finished with exit code "
            f"{result.returncode}[/green]"
        )
        raise typer.Exit(code=result.returncode)

    except KeyboardInterrupt:
        console.print("[red]Process interrupted.[/red]")
        raise typer.Exit(code=130)


@app.command()
def record(
    model: str = typer.Argument(..., help="Model name"),
    input_tokens: int = typer.Argument(..., help="Input token count"),
    output_tokens: int = typer.Argument(..., help="Output token count"),
):
    """Record token usage for a model."""

    try:
        record_usage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[green]Recorded usage:[/green] {model} | "
        f"input={input_tokens} | output={output_tokens}"
    )


def _print_token_budget_status(budget: int, used: int) -> None:
    result = calculate_token_budget_status(used, budget)
    console.print(f"[bold]Monthly token budget:[/bold] {budget}")
    console.print(f"[bold]Current month input + output tokens:[/bold] {used}")
    console.print(f"[bold]Remaining tokens:[/bold] {result['remaining']}")
    console.print(f"[bold]Percentage used:[/bold] {result['percentage']:.1f}%")
    if result["exceeded"]:
        console.print("[bold red]Monthly token budget exceeded.[/bold red]")
    elif result["warning"]:
        console.print("[bold yellow]Warning: monthly token usage has reached 80% of the budget.[/bold yellow]")
    else:
        console.print("[green]Monthly token usage is below 80% of the budget.[/green]")


@app.command()
def budget(
    tokens: int = typer.Option(..., "--tokens", help="Monthly input and output token budget"),
    config_file: Path = typer.Option(DEFAULT_CONFIG_FILE, "--config-file", help="Path to local budget config JSON"),
):
    """Configure the monthly token budget."""
    try:
        set_monthly_budget(tokens, config_file)
    except (ValueError, OSError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Monthly token budget set to {tokens}.[/green]")


@app.command("budget-status")
def budget_status_command(
    database: Path = typer.Option(DEFAULT_IMPORT_DB, "--database", help="Path to the Codex usage SQLite ledger"),
    config_file: Path = typer.Option(DEFAULT_CONFIG_FILE, "--config-file", help="Path to local budget config JSON"),
):
    """Show current month's token usage against the configured budget."""
    try:
        configured = load_monthly_budget(config_file)
        if configured is None:
            console.print("No monthly token budget configured. Set one with: agent-budget-guard budget --tokens <count>")
            return
        used = monthly_token_usage(database)
        _print_token_budget_status(configured, used)
    except (ValueError, OSError) as error:
        console.print(f"[red]Could not read token budget status:[/red] {error}")
        raise typer.Exit(code=1)


@app.command()
def status(
    budget: float = typer.Option(
        2.00,
        "--budget",
        help="Budget limit in USD",
    ),
    pricing_file: Path = typer.Option(
        DEFAULT_PRICING_FILE,
        "--pricing-file",
        help="Path to model pricing JSON",
    ),
):
    """Show total spend and remaining budget."""

    if budget <= 0:
        console.print("[red]Budget must be greater than zero.[/red]")
        raise typer.Exit(code=1)

    if not pricing_file.exists():
        console.print(f"[red]Pricing file not found:[/red] {pricing_file}")
        console.print("Create a pricing JSON file first. See the example in README.")
        raise typer.Exit(code=1)
    try:
        with pricing_file.open("r", encoding="utf-8") as file:
            pricing = json.load(file)
        events = load_usage()
        total = calculate_total_cost(events, pricing)
        result = budget_status(total, budget)
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        console.print(f"[red]Could not calculate cost:[/red] {error}")
        raise typer.Exit(code=1)
    console.print(f"[bold]Usage events:[/bold] {len(events)}")
    console.print(f"[bold]Spent:[/bold] ${result['spent']:.6f}")
    console.print(f"[bold]Budget:[/bold] ${budget:.2f}")
    console.print(f"[bold]Remaining:[/bold] ${result['remaining']:.6f}")
    if result["over_budget"]:
        console.print("[bold red]Budget limit reached![/bold red]")
    else:
        console.print("[green]Within budget.[/green]")


@app.command("codex-usage")
def codex_usage(
    pricing_file: Path = typer.Option(
        DEFAULT_PRICING_FILE,
        "--pricing-file",
        help="Path to model pricing JSON",
    ),
):
    """Import local Codex CLI usage records and show estimated totals."""
    if not pricing_file.exists():
        console.print(f"[red]Pricing file not found:[/red] {pricing_file}")
        raise typer.Exit(code=1)
    try:
        with pricing_file.open("r", encoding="utf-8") as file:
            pricing = json.load(file)
        totals, event_count, imported_now = import_codex_usage()
        input_total = sum(value[0] for value in totals.values())
        output_total = sum(value[1] for value in totals.values())
        cached_input_total = sum(value[2] for value in totals.values())
        pricing_labels = set(totals).intersection(pricing)
        unpriced_models = sorted(set(totals).difference(pricing))
        cost, cost_incomplete = calculate_codex_cost(totals, pricing)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        console.print(f"[red]Could not import Codex usage:[/red] {error}")
        raise typer.Exit(code=1)

    console.print(f"[bold]Imported new records:[/bold] {imported_now}")
    console.print(f"[bold]Codex records total:[/bold] {event_count}")
    console.print(f"[bold]Input tokens:[/bold] {input_total}")
    console.print(f"[bold]Cached input tokens:[/bold] {cached_input_total}")
    console.print(f"[bold]Output tokens:[/bold] {output_total}")
    if unpriced_models and not pricing_labels:
        console.print(f"[bold]Estimated API-equivalent cost:[/bold] Unavailable (no pricing for: {', '.join(unpriced_models)})")
    else:
        reasons = []
        if unpriced_models:
            reasons.append(f"pricing missing for: {', '.join(unpriced_models)}")
        if cost_incomplete and not unpriced_models:
            reasons.append("cached-token pricing missing")
        label = "Estimated API-equivalent cost" + (f" (incomplete; {'; '.join(reasons)})" if reasons else "")
        console.print(f"[bold]{label}:[/bold] ${cost:.6f}")
    if pricing_labels:
        console.print(f"Pricing model(s): {', '.join(sorted(pricing_labels))}")


@app.command()
def dashboard(
    database: Path = typer.Option(
        DEFAULT_IMPORT_DB,
        "--database",
        help="Path to the existing Codex usage SQLite ledger",
    ),
    pricing_file: Path = typer.Option(
        DEFAULT_PRICING_FILE,
        "--pricing-file",
        help="Path to model pricing JSON",
    ),
    config_file: Path = typer.Option(DEFAULT_CONFIG_FILE, "--config-file", help="Path to local budget config JSON"),
):
    """Show aggregate Codex usage from the local usage ledger."""
    try:
        totals, event_count = load_codex_usage_totals(database)
        daily_usage = load_codex_usage_daily(database)
        pricing = {}
        if pricing_file.exists():
            with pricing_file.open("r", encoding="utf-8") as file:
                pricing = json.load(file)
            if not isinstance(pricing, dict):
                raise ValueError("Pricing JSON must be an object keyed by exact model name")
        cost, cost_incomplete = calculate_codex_cost(totals, pricing)
        configured_budget = load_monthly_budget(config_file)
        month_used = monthly_token_usage(database) if configured_budget is not None else 0
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        console.print(f"[red]Could not read Codex dashboard data:[/red] {error}")
        raise typer.Exit(code=1)

    input_total, cached_input_total, output_total = total_tokens(totals)
    console.print("[bold]Codex usage dashboard[/bold]")
    console.print(f"[bold]Codex records:[/bold] {event_count}")
    console.print(f"[bold]Input tokens:[/bold] {input_total}")
    console.print(f"[bold]Cached input tokens:[/bold] {cached_input_total}")
    console.print(f"[bold]Output tokens:[/bold] {output_total}")
    if configured_budget is not None:
        console.print("[bold]Monthly token budget status[/bold]")
        _print_token_budget_status(configured_budget, month_used)
    missing_models = sorted(set(totals).difference(pricing))
    if missing_models or cost_incomplete:
        reasons = []
        if missing_models:
            reasons.append(f"pricing missing for: {', '.join(missing_models)}")
        if cost_incomplete and not missing_models:
            reasons.append("cached-token pricing missing")
        detail = f" ({'; '.join(reasons)})" if reasons else ""
        console.print(f"[bold]Estimated API-equivalent cost:[/bold] Unavailable{detail}")
    else:
        console.print(f"[bold]Estimated API-equivalent cost:[/bold] ${cost:.6f}")
    for model, (inputs, outputs, cached) in sorted(totals.items()):
        console.print(
            f"{model}: input={inputs}, cached_input={cached}, output={outputs}"
        )
    console.print("[bold]Daily Codex Usage (UTC)[/bold]")
    if daily_usage is None:
        console.print("Daily grouping unavailable: the usage ledger has no stored event timestamp.")
    elif not daily_usage:
        console.print("No timestamped usage records.")
        console.print(daily_token_chart([]))
    else:
        console.print("Date | Input tokens | Cached input tokens | Output tokens | Records")
        for day, inputs, cached, outputs, records in daily_usage:
            console.print(f"{day} | {inputs} | {cached} | {outputs} | {records}")
        console.print(daily_token_chart(daily_usage))

if __name__ == "__main__":
    app()
