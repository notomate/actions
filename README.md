# Notomate Actions

Three GitHub Actions-compatible actions that run on a schedule in a Notomate workspace. Based on [claude-notomate-action](https://github.com/notomate/claude-notomate-action), they run through Notomate's `act` runner.

| Action | Purpose | AI credentials |
| --- | --- | --- |
| [rss-to-note](actions/rss-to-note/action.yml) | Collect the latest RSS/Atom entries into one note, preserving their original language | Not required |
| [daily-meal-plan](actions/daily-meal-plan/action.yml) | Generate lunch and dinner recipes, ingredient quantities, cooking steps, and a shopping list | Claude |
| [stocks-to-note](actions/stocks-to-note/action.yml) | Fetch the latest available daily bars for configured symbols with yfinance and publish one note | Not required |

## Quick start

**Publication status: this project has not been pushed or tagged as `v1`.** The examples use the planned location `notomate/actions/...@v1`. Once the maintainer publishes the complete repository and creates that ref, the examples can reference it. If using a different owner, repository, or ref, update `uses:` accordingly. Publish the entire repository: the actions reference shared `scripts/` and `requirements/` directories.

1. Configure the following secrets and variables in your Notomate workspace.
2. Copy the [RSS](examples/rss-digest.yml), [meal plan](examples/daily-meal-plan.yml), or [stock](examples/stocks-digest.yml) workflow into Notomate's workflow editor.
3. Adjust the settings, run the workflow manually to verify the note, then enable its schedule.

| Name | Type | Value |
| --- | --- | --- |
| `NM_API_BASE_URL` | Variable | The Notomate origin reachable from the runner, such as `https://notes.example.com`; use the nginx entry point without `/api/v1` |
| `NM_API_KEY` | Secret | A Notomate personal API key belonging to a workspace member, created under User Settings → API Keys |
| `ANTHROPIC_API_KEY` | Secret | Required only for meal plans; alternatively use `CLAUDE_CODE_OAUTH_TOKEN` |
| `STOCK_SYMBOLS` | Variable | Required only for stocks, for example `AAPL,MSFT,2330.TW` |

Inside the runner container, `localhost` refers to the container itself. Use a Notomate service name or URL that the runner can resolve and reach.

These examples belong in **Notomate**, rather than github.com's scheduler. Notomate supplies workspace information through `GITHUB_EVENT_PATH`; ordinary GitHub events lack `workspace.id` and cannot publish notes directly. Users do not need to check out the repository or install Python: each action prepares its dependencies. Linux runners using `ubuntu-latest` are supported and need access to GitHub, PyPI, and the data sources.

## Shared inputs and outputs

| Input | Required | Default / description |
| --- | --- | --- |
| `notomate-base-url` | Yes | Notomate origin |
| `notomate-api-key` | Yes | Personal API key used for Bearer authentication |
| `note-visibility` | No | `private`; also accepts `workspace` or `public` |
| `timezone` | No | `Asia/Taipei`, used for the note date and retrieval timestamp |

Each run creates a new note. It does not overwrite previous notes or deduplicate across runs. Manual reruns on the same day may create separate notes with identical titles.

| Output | Description |
| --- | --- |
| `note-id` | Created note ID; empty when skipped or publication cannot be confirmed |
| `conclusion` | `success`, `skipped`, or `failure`; dependency installation and configuration errors also result in failure |

Add `id: digest` to an action step to reference `${{ steps.digest.outputs.note-id }}` later. The upstream meal action may publish an error explanation and then return `failure`; in that case, `note-id` is still available.

## RSS news digest

```yaml
- uses: notomate/actions/actions/rss-to-note@v1
  with:
    notomate-base-url: ${{ vars.NM_API_BASE_URL }}
    notomate-api-key: ${{ secrets.NM_API_KEY }}
    feed-url: https://www.usnews.com/rss/news
    max-items: '10'
```

- `feed-url` defaults to the US News URL above and can be replaced with another HTTP(S) RSS or Atom URL.
- `max-items` defaults to 10 and accepts values from 1 to 100.
- Each entry includes its original title, source summary, publication/update timestamp, and article link. HTML summaries are converted to plain text; the action neither fetches full articles nor calls AI. Note labels are in English; source text is not translated.
- Dated entries appear newest first. Undated entries follow in their original source order. Entries are deduplicated by ID or link within each run.
- A valid empty feed returns `skipped` without creating a note. HTTP errors, HTML error pages, and invalid XML return `failure` without creating a blank note. US News availability depends on the source and runner network; change `feed-url` if needed.

## Daily lunch and dinner

| Input | Default / description |
| --- | --- |
| `anthropic-api-key` | Provide this or an OAuth token |
| `claude-code-oauth-token` | Alternative to an API key; obtained through `claude setup-token` |
| `servings` | `2`, with a supported range of 1–20 |
| `dietary-preferences` | Taiwanese home cooking with meat and vegetables; alternatives include "vegan" or "low oil" |
| `excluded-ingredients` | None; specify ingredients such as "peanuts, shrimp" |
| `model` | `claude-sonnet-5`, matching the pinned upstream default; override with a model available to your account |

The action generates one English note per day, covering lunch and dinner with a staple, main dish, vegetables, ingredient quantities, simple cooking steps, and one combined shopping list. It calculates the date in `timezone` before calling Claude. Preferences and excluded ingredients are included as JSON in the prompt, without shell interpolation.

This action wraps a pinned commit of [claude-notomate-action](https://github.com/notomate/claude-notomate-action/tree/8012f4faf8cb0efcaabdef2f1dc84071c8d6eb99), which automatically publishes the final Markdown. No additional MCP server is required. The prompt requests no tool use, and `allowed-tools` receives `,`, which resolves to an empty list. The upstream action still uses `bypassPermissions`, so this is not a tool isolation guarantee. Dietary constraints are followed by the model without separate deterministic validation, and menus are not guaranteed to differ across days.

Upstream behavior: if the model returns error text, the action may publish that explanation as a note and return failure. If it throws before returning a response, no note is created. This differs from the RSS and stock actions' handling of data retrieval failures.

## Stock watchlist

`symbols` is required and accepts 1–50 Yahoo Finance symbols separated by commas or newlines. Duplicates are removed and symbols are converted to uppercase. For example:

```yaml
symbols: |
  AAPL
  MSFT
  2330.TW
  6488.TWO
```

The stock note includes symbol, currency, exchange data date, daily price, absolute and percentage change from the preceding daily bar, and volume. It uses `Ticker.history(period="1mo", interval="1d", auto_adjust=False)` without AI analysis.

Daily bars may be incomplete before the market closes. On non-trading days, the latest trading day is shown; these are **not real-time quotes**. Changes compare against the preceding daily bar, rather than implying a quote exists for the note date. Missing previous prices leave changes unavailable. Missing values display `N/A`, not zero. Data dates retain the exchange date, while note titles use the configured time zone.

If some symbols fail, the action creates one note containing successful data and a failure list, emits log warnings, and returns `conclusion=success`. If all symbols fail, it returns `conclusion=failure` without creating a note. Use Yahoo Finance symbol formats; the action does not search for symbols or infer their market.

## Scheduling and error handling

| Example | UTC cron | Taipei time |
| --- | --- | --- |
| RSS | `0 23 * * *` | 07:00 the following day |
| Meal plan | `0 0 * * *` | 08:00 daily |
| Stocks | `0 1 * * *` | 09:00 daily |

Cron is evaluated in UTC. `timezone` affects the note date, not the schedule; adjust cron for other regions or daylight saving time. All three examples include `workflow_dispatch` for manual execution in Notomate.

RSS retrieval makes up to three attempts for connection timeouts, HTTP 429, and transient 5xx responses. Stocks make up to three attempts for rate limits or connection timeouts reported by yfinance; other failures appear in the note. HTTP requests have timeouts. Note creation POSTs are not automatically retried: if the connection drops or the response lacks a note ID, check Notomate before rerunning.

## Development and verification

```powershell
uv venv --python 3.12 .venv
uv pip sync --python .venv/Scripts/python.exe requirements/dev.txt
.venv/Scripts/python.exe -m pytest
```

Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements/dev.txt
.venv/bin/python -m pytest
```

`requirements/*.in` lists direct dependencies; corresponding `.txt` files pin the full dependency set. To update them, run `uv pip compile requirements/<name>.in --python-version 3.12 --universal --output-file requirements/<name>.txt` for each of `rss`, `stocks`, and `dev`, then rerun tests.

Tests use a local HTTP mock server to verify RSS → Markdown → Note POST. They also cover missing stock data, non-trading days, partial failures, meal dates and constraints, action inputs/outputs, example schedules, and execution from unrelated working directories. Tests require no real credentials and do not call Claude.

Run `python tests/act_smoke.py --act /path/to/act` to execute the RSS composite through real `act`, verify `note-id` and `conclusion`, and create exactly one note on a local mock server. This requires Docker, act, and the `catthehacker/ubuntu:act-latest` image. Docker Desktop uses `host.docker.internal` to reach the host mock server; native Linux requires an appropriate `--runner-host` or Docker host mapping.

For a real Notomate smoke test, publish an action ref, configure the variables and secrets in a test workspace, paste the three examples, and run them manually. Verify that each creates one note with the expected visibility and note ID, correct stock dates, and the requested meal constraints. Use an invalid stock symbol to verify that total failure creates no note. This requires a real workspace and credentials; mock tests do not replace this verification.

### Initial verification record (2026-10-06)

- Windows Python 3.12: 57 tests passed.
- Linux `catthehacker/ubuntu:act-latest`: the same 57 tests passed.
- `act` 0.2.89: the RSS composite passed Python/dependency installation, creation of one mock note, and output verification.
- Live yfinance: successfully fetched `AAPL` and `2330.TW` without publishing to a real workspace.
- The specified US News URL timed out on all three attempts from the current network. Mock feed tests do not establish availability of that source.
- Real Claude generation and publication to a Notomate workspace have not been tested. The repository has not been pushed or tagged as `v1`.
