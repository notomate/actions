# Notomate Actions

GitHub Actions-compatible actions that run on a schedule in a Notomate workspace through Notomate's `act` runner. Content actions produce a note's title and body as step outputs; an optional `claude` step can translate or rewrite them; a separate `write-note` step renders them through a template you can customize and publishes the note.

| Action | Purpose | AI credentials |
| --- | --- | --- |
| [rss](actions/rss/action.yml) | Collect the latest RSS/Atom entries, preserving their original language | Not required |
| [daily-meal-plan](actions/daily-meal-plan/action.yml) | Generate lunch and dinner recipes, ingredient quantities, cooking steps, and a shopping list | Claude |
| [stocks](actions/stocks/action.yml) | Fetch the latest available daily bars for configured symbols with yfinance | Not required |
| [claude](actions/claude/action.yml) | Process another step's `data` with your instructions, e.g. translate or summarize | Claude |
| [write-note](actions/write-note/action.yml) | Render a Jinja2 template with another step's `data` and publish one note | Not required |

```yaml
steps:
  - uses: notomate/actions/actions/stocks@v1
    id: stocks
    with:
      symbols: ${{ vars.STOCK_SYMBOLS }}
  - uses: notomate/actions/actions/write-note@v1
    with:
      notomate-base-url: ${{ vars.NM_API_BASE_URL }}
      notomate-api-key: ${{ secrets.NM_API_KEY }}
      data: ${{ steps.stocks.outputs.data }}
      # Optional; omit title/template to publish the action's default note.
      template: |
        {% for q in quotes %}
        - {{ q.symbol | md }}: {{ q.close | number }} {{ q.currency }}
        {% endfor %}
```

## Quick start

The examples reference `notomate/actions/...@v1`. If using a different owner, repository, or ref, update `uses:` accordingly. A fork must include the entire repository: the actions reference shared `scripts/` and `requirements/` directories.

1. Configure the following secrets and variables in your Notomate workspace.
2. Copy the [RSS](examples/rss-digest.yml), [translated RSS](examples/rss-translated.yml), [meal plan](examples/daily-meal-plan.yml), or [stock](examples/stocks-digest.yml) workflow into Notomate's workflow editor.
3. Adjust the settings, run the workflow manually to verify the note, then enable its schedule.

| Name | Type | Value |
| --- | --- | --- |
| `NM_API_BASE_URL` | Variable | The Notomate origin reachable from the runner, such as `https://notes.example.com`; use the nginx entry point without `/api/v1` |
| `NM_API_KEY` | Secret | A Notomate personal API key belonging to a workspace member, created under User Settings → API Keys |
| `ANTHROPIC_API_KEY` | Secret | Required only for meal plans and the `claude` step; alternatively use `CLAUDE_CODE_OAUTH_TOKEN` |
| `STOCK_SYMBOLS` | Variable | Required only for stocks, for example `AAPL,MSFT,2330.TW` |

Inside the runner container, `localhost` refers to the container itself. Use a Notomate service name or URL that the runner can resolve and reach.

These examples belong in **Notomate**, rather than github.com's scheduler. Notomate supplies workspace information through `GITHUB_EVENT_PATH`; ordinary GitHub events lack `workspace.id` and cannot publish notes directly. Users do not need to check out the repository or install Python: each action prepares its dependencies. Linux runners using `ubuntu-latest` are supported and need access to GitHub, PyPI, and the data sources.

## Content action outputs

The RSS, meal, and stock actions take an optional `timezone` input (default `Asia/Taipei`, used for the note date and retrieval timestamp) and never contact Notomate. Give the step an `id` and pass its outputs to `write-note`:

| Output | Description |
| --- | --- |
| `title` | Default note title |
| `content` | Default Markdown note body, the same text these actions previously published |
| `data` | JSON object for templates: `title`, `content`, `date`, plus action-specific fields listed below |
| `conclusion` | `success`, `skipped` (RSS only: empty feed, no content), or `failure`; dependency installation and configuration errors also result in failure |

A failing step stops the job, so `write-note` does not run. RSS can conclude `skipped` while the step still succeeds, so guard its `write-note` step with `if: steps.<id>.outputs.conclusion == 'success'`.

## Writing the note

| Input | Required | Default / description |
| --- | --- | --- |
| `notomate-base-url` | Yes | Notomate origin |
| `notomate-api-key` | Yes | Personal API key used for Bearer authentication |
| `note-visibility` | No | `private`; also accepts `workspace` or `public` |
| `data` | No | JSON object of template variables, usually `${{ steps.<id>.outputs.data }}`; defaults to `{}` |
| `title` | No | Jinja2 template for the title; defaults to `{{ title }}`. Whitespace is collapsed to one line |
| `template` | No | Jinja2 template for the Markdown body; defaults to `{{ content }}` |

| Output | Description |
| --- | --- |
| `note-id` | Created note ID; empty when publication cannot be confirmed |
| `conclusion` | `success` or `failure` |

Each run creates a new note. It does not overwrite previous notes or deduplicate across runs. Manual reruns on the same day may create separate notes with identical titles.

Templates use [Jinja2](https://jinja.palletsprojects.com/en/stable/templates/) in a sandbox. Workflow expressions use `${{ }}` and Jinja uses `{{ }}`, so both can appear in the same file. Lists such as RSS `items` and stock `quotes` are iterated with `{% for %}`. Block tags on their own line leave no blank line behind, so a loop can emit Markdown table rows. Undefined variables fail the step instead of rendering as empty text. Template output is not escaped automatically; these filters are available:

| Filter | Effect |
| --- | --- |
| `md` | Escape Markdown punctuation in source text, e.g. `{{ item.title \| md }}` |
| `md_cell` | `md` plus newlines collapsed, for table cells |
| `number(spec=',.2f', missing='N/A')` | Format a number with a Python format spec; `null` becomes `missing`, e.g. `{{ q.percent \| number('+.2f') }}` |

Pass source text through `data`, not by interpolating `${{ steps.<id>.outputs.content }}` into `template`: text in `template` is parsed as Jinja, so a stray `{{` in a feed would break the step. Data values are never evaluated as templates.

## RSS news digest

```yaml
- uses: notomate/actions/actions/rss@v1
  id: rss
  with:
    feed-url: https://www.usnews.com/rss/news
    max-items: '10'
```

`data` fields: `date`, `retrieved_at`, `feed_title`, `source`, and `items`, a list of `{title, summary, link, published}`. Titles and summaries are plain text without Markdown escaping. `link` is empty when missing or unsafe, and `published` is an ISO timestamp or `null`.

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
| `language` | `English`; the language Claude writes the menu in, e.g. `Traditional Chinese (Taiwan)` (at most 100 characters) |
| `instructions` | None; extra instructions such as cooking time, budget, cuisine, number of dishes, or a different note format |
| `model` | `claude-sonnet-5`; override with a model available to your account |

`instructions` can change the default sections and format, but the prompt tells Claude never to use excluded ingredients. The default `title` stays in English (`<date> Lunch and Dinner Menu`). To match another language, set `title` on `write-note`, e.g. `'{{ date }} 午餐與晚餐菜單'`, as in [the example](examples/daily-meal-plan.yml).

By default, the action generates one English menu per day, covering lunch and dinner with a staple, main dish, vegetables, ingredient quantities, simple cooking steps, and one combined shopping list. It calculates the date in `timezone` before calling Claude. Preferences and excluded ingredients are included as JSON in the prompt, without shell interpolation. `content` is Claude's Markdown without a top-level heading; `title` is `<date> Lunch and Dinner Menu`.

`data` fields: `date`, `servings`, `dietary_preferences`, `excluded_ingredients`, `language`, and `instructions`.

The action runs Claude through the [Claude Agent SDK](sdk/claude.mjs) (pinned in `sdk/package.json`, Node.js 22) with `tools: []`, no MCP servers, and no filesystem settings, so Claude can only return text. `node_modules` is cached by SDK version with `actions/cache`. Credentials are passed only to that process. The SDK bridge is shared with the `claude` action. Dietary constraints are followed by the model without separate deterministic validation, and menus are not guaranteed to differ across days.

If Claude returns an error or an empty response, the action fails without content and no note is written, consistent with the RSS and stock actions. Claude's error text is not logged; only the result type is reported.

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

`data` fields: `date`, `retrieved_at`, `quotes`, a list of `{symbol, currency, date, close, change, percent, volume}` (missing numbers are `null`; use the `number` filter), and `failures`, a list of `{symbol, error}`. [examples/stocks-digest.yml](examples/stocks-digest.yml) loops over both lists to build a custom table.

If some symbols fail, the action outputs the successful data with a failure list, emits log warnings, and returns `conclusion=success`. If all symbols fail, it returns `conclusion=failure` without content, so no note is created. Use Yahoo Finance symbol formats; the action does not search for symbols or infer their market.

## Processing with Claude

Place `claude` between a content action and `write-note` to translate, summarize, or rewrite the data. Claude runs through the same Agent SDK bridge as the meal plan, with all tools disabled, and only returns text.

| Input | Default / description |
| --- | --- |
| `anthropic-api-key` / `claude-code-oauth-token` | Provide one |
| `prompt` | Required; your instructions, e.g. `Translate every item's title and summary into Traditional Chinese (Taiwan).` |
| `data` | `{}`; the JSON to process, usually `${{ steps.<id>.outputs.data }}` |
| `output-format` | `markdown` (default without `json-schema`): Claude writes the note body, which replaces `content` in the input data. `json`: Claude returns a JSON object that becomes `data`, keeping the input's structure unless your prompt says otherwise |
| `json-schema` | None; a JSON Schema whose root is `"type": "object"`. The Agent SDK's structured output validates Claude's output against it, and the step fails if no matching object is returned. Implies `output-format: json` |
| `model` | `claude-sonnet-5` |

Outputs match the content actions: `title`, `content`, `data`, and `conclusion`. Use `json` when the `write-note` template loops over fields such as RSS `items`. [examples/rss-translated.yml](examples/rss-translated.yml) translates each item and keeps the same loop template. Use `markdown` for a free-form summary published with the default `{{ content }}` template.

Without `json-schema`, `json` mode relies on the prompt: the step fails only if the reply is not a JSON object, so a renamed or missing field surfaces later as a `write-note` template error. Add `json-schema` listing the fields your template uses, as the example does, so the structure is enforced by the Agent SDK's structured output instead.

The data is sent to Claude in full, including the default `content`. Ask Claude to drop fields you do not need, as the example does, to save tokens. Feed text is sent to Claude as data, and the prompt tells Claude to ignore instructions inside it. That is not a guarantee: a malicious feed can still steer the generated text, though with no tools it cannot do anything else. Invalid JSON in `json` mode fails the step before `write-note` runs. Guard `claude` with the same `if:` as `write-note` when the source can conclude `skipped`.

## Scheduling and error handling

| Example | UTC cron | Taipei time |
| --- | --- | --- |
| RSS and translated RSS | `0 23 * * *` | 07:00 the following day |
| Meal plan | `0 0 * * *` | 08:00 daily |
| Stocks | `0 1 * * *` | 09:00 daily |

Cron is evaluated in UTC. `timezone` affects the note date, not the schedule; adjust cron for other regions or daylight saving time. All examples include `workflow_dispatch` for manual execution in Notomate.

RSS retrieval makes up to three attempts for connection timeouts, HTTP 429, and transient 5xx responses. Stocks make up to three attempts for rate limits or connection timeouts reported by yfinance; other failures appear in the note. HTTP requests have timeouts. `write-note` POSTs are not automatically retried: if the connection drops or the response lacks a note ID, check Notomate before rerunning. A template error fails `write-note` before anything is posted.

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

`requirements/*.in` lists direct dependencies; corresponding `.txt` files pin the full dependency set. To update them, run `uv pip compile requirements/<name>.in --python-version 3.12 --universal --output-file requirements/<name>.txt` for each of `rss`, `stocks`, `note`, and `dev`, then rerun tests.

Tests use a local HTTP mock server to verify template → Note POST and that content actions publish nothing. They also cover the example templates' loops against real RSS and stock data, missing stock data, non-trading days, partial failures, meal dates and constraints (with a fake `claude` executable), action inputs/outputs, example schedules, and execution from unrelated working directories. Tests require no real credentials and do not call Claude.

Run `python tests/act_smoke.py --act /path/to/act` to execute the RSS and write-note composites through real `act`, verify `note-id` and `conclusion`, and create exactly one note on a local mock server. This requires Docker, act, and the `catthehacker/ubuntu:act-latest` image. Docker Desktop uses `host.docker.internal` to reach the host mock server; native Linux requires an appropriate `--runner-host` or Docker host mapping.

For a real Notomate smoke test, publish an action ref, configure the variables and secrets in a test workspace, paste the examples, and run them manually. Verify that each creates one note with the expected visibility and note ID, correct stock dates, and the requested meal constraints. Use an invalid stock symbol to verify that total failure creates no note. This requires a real workspace and credentials; mock tests do not replace this verification.

### Initial verification record (2026-10-06)

- Windows Python 3.12: 57 tests passed.
- Linux `catthehacker/ubuntu:act-latest`: the same 57 tests passed.
- `act` 0.2.89: the RSS composite passed Python/dependency installation, creation of one mock note, and output verification.
- Live yfinance: successfully fetched `AAPL` and `2330.TW` without publishing to a real workspace.
- The specified US News URL timed out on all three attempts from the current network. Mock feed tests do not establish availability of that source.
- Real Claude generation and publication to a Notomate workspace have not been tested. The repository has not been pushed or tagged as `v1`.

These results predate the split into content actions and `write-note`. Since then, the 97 Windows tests pass; the Linux, `act`, and live checks above have not been rerun.
