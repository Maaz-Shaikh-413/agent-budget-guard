# Agent Budget Guard

Agent Budget Guard is a local command-line tool for reviewing token usage recorded by the Codex CLI. It imports usage records from Codex session files into a SQLite ledger, then summarizes usage, shows a terminal dashboard, compares monthly tokens with a configured limit, and exports token counts to CSV.

It is intended to make coding-agent usage easier to inspect and track over time. It does not read or export prompt and response text.

## Features

- **Codex usage import:** Reads token usage records from `~/.codex/sessions` and avoids importing the same rollout record more than once.
- **SQLite usage ledger:** Stores imported usage locally in `.agent-budget-guard/codex_usage.sqlite` in the project directory.
- **Terminal dashboard:** Shows record, input, cached input, and output totals, per-model totals, and an estimated API-equivalent cost when pricing is available.
- **Seven-day chart:** Shows input and output token bars for the seven-day window ending on the latest timestamped usage date, in UTC.
- **Monthly token budget alerts:** Configure a monthly input-plus-output token limit. The dashboard and budget status command report a warning at 80% and an exceeded state at 100%. Monthly totals use timestamped records in the current UTC calendar month.
- **CSV export:** Writes timestamp, UTC date, model, and token counts from the SQLite ledger to a spreadsheet-friendly CSV file.

## Cost estimates and privacy

Token counts are imported from local Codex CLI usage records. Any displayed cost is an API-equivalent estimate calculated from the local pricing JSON supplied by the user. It is not an actual ChatGPT subscription charge, invoice, or billing record; missing model or cached-token prices can make an estimate incomplete or unavailable.

The ledger and budget configuration are stored locally. The importer reads usage metadata and token counts; prompts and messages are not exported. CSV export contains usage metadata and counts only, not conversation content.

## Tech stack

- Python 3
- Typer for the CLI and Rich for terminal output
- SQLite and Python's standard library for local storage, JSONL parsing, and CSV export
- `unittest` tests, runnable through `pytest`

## Installation

From the project root on macOS or Linux, create and activate a virtual environment, then install the listed dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The project currently has no package installer or console-script entry point. Run commands from the project root with `python -m agent_budget_guard.cli`.

### Optional pricing file

To see cost estimates, create `~/.agent-budget-guard/pricing.json`. Keys must match model names in the imported usage records. Prices are per million tokens; cached input pricing is optional unless cached tokens are present and you want a complete estimate.

```json
{
  "model-name": {
    "input_per_1m": 1.0,
    "cached_input_per_1m": 0.5,
    "output_per_1m": 4.0
  }
}
```

No pricing file is included in the repository. The dashboard can still show token usage without one.

## CLI commands

Run `python -m agent_budget_guard.cli --help` for the root help and `python -m agent_budget_guard.cli COMMAND --help` for command options. These are the commands implemented by the current CLI:

| Command | Purpose |
| --- | --- |
| `codex-usage` | Import local Codex session usage and print aggregate token totals and estimated cost. |
| `dashboard` | Display ledger totals, available monthly budget status, daily usage, and the chart. |
| `budget --tokens COUNT` | Save a positive monthly input-plus-output token budget. |
| `budget-status` | Show current UTC month's usage against the configured budget. |
| `export` | Export token-only usage records as CSV. |
| `record MODEL INPUT OUTPUT` | Append a manually supplied usage event to the separate JSONL usage file. |
| `status` | Compare manually recorded JSONL usage with a dollar budget using the pricing file. |
| `run COMMAND...` | Run a subprocess and return its exit status. The `--max-cost` option currently prints a limit but does not measure or stop the subprocess based on cost. |

Examples (run from the project root):

```bash
python -m agent_budget_guard.cli codex-usage
python -m agent_budget_guard.cli dashboard
python -m agent_budget_guard.cli budget --tokens 1000000
python -m agent_budget_guard.cli budget-status
python -m agent_budget_guard.cli export --format csv --output codex-usage.csv
```

The Codex commands use `~/.codex/sessions` as their import source and `.agent-budget-guard/codex_usage.sqlite` as their ledger by default. `dashboard`, `budget-status`, and `export` accept `--database` to select another ledger. `dashboard` and the budget commands also accept `--config-file`; `codex-usage` and `dashboard` accept `--pricing-file`. Use each command's `--help` to see the exact options.

`record` and `status` use a separate JSONL file at `~/.agent-budget-guard/usage.jsonl`; `status` requires a pricing JSON file and accepts `--budget` and `--pricing-file` options.

## Example output

The following output is **illustrative sample data**, not output from a real account. Exact totals, cost, and chart bars depend on the local ledger and pricing file.

```text
Codex usage dashboard
Codex records: 18
Input tokens: 184200
Cached input tokens: 62100
Output tokens: 32750
Monthly token budget status
Monthly token budget: 1000000
Current month input + output tokens: 216950
Remaining tokens: 783050
Percentage used: 21.7%
Monthly token usage is below 80% of the budget.
Estimated API-equivalent cost: $0.384200
example-model: input=184200, cached_input=62100, output=32750
Daily Codex Usage (UTC)
Date | Input tokens | Cached input tokens | Output tokens | Records
2026-11-27 | 42000 | 16000 | 8500 | 5
2026-11-26 | 31800 | 9400 | 6200 | 4
Daily token chart (UTC)
I = input, O = output
2026-11-27 I ████████████████████ 42000 | O ████ 8500
2026-11-26 I ███████████████ 31800 | O ██ 6200
```

An **illustrative CSV excerpt** (the exported file includes a header and one row per usage record):

```csv
event_timestamp_utc,date_utc,model,input_tokens,cached_input_tokens,output_tokens,total_tokens
2026-11-27T09:15:00Z,2026-11-27,example-model,12000,4000,2500,14500
2026-11-26T16:42:00Z,2026-11-26,example-model,8500,2000,1800,10300
```

## Tests

With the virtual environment active and dependencies installed, run the test suite from the project root:

```bash
python -m pytest
```

## Roadmap

- Improve setup and first-run guidance for local pricing and ledger paths.
- Continue refining usage summaries and portability of exported reports.

## Contributing

Contributions are welcome. Please keep changes focused, document behavior that users can verify from the CLI, and include or update tests when changing functionality. Before opening a pull request, run `python -m pytest` and review `git diff --check`.
