# Status Report Agent

An agentic CLI tool that generates daily or periodic status reports by using Claude as an autonomous sub-agent with MCP (Model Context Protocol) tools connected to your workplace systems — Jira, GitHub, Slack, Google Calendar, Google Drive, and Gmail. Claude investigates your activity, drills into significant items, and produces a rich, detailed report.

## Quick Start

```bash
# 1. Authenticate with Google Cloud (one-time per machine)
gcloud auth application-default login

# 2. Install dependencies
cp .env.example .env   # set VERTEX_PROJECT_ID and any data-source credentials
uv sync

# 3. One-time Slack setup — extract browser session tokens (no admin approval needed)
uv run python -m status_report.auth.slack --extract

# 4. One-time Google OAuth consent (if using Calendar / Drive / Gmail)
uv run python -m status_report.auth.google --consent

# 5. Generate your first report
python -m status_report.main --user you@example.com
```

The first run defaults to "today". Every subsequent run without `--period` automatically covers the period since your last run.

---

## How It Works

Unlike traditional data aggregation tools, this agent uses Claude as the **autonomous brain**:

1. **Python starts MCP servers** as subprocesses — each server connects to a workplace tool (GitHub, Jira, Slack, etc.)
2. **Claude investigates** — it searches across all available tools, finds your activity, and drills into significant items (reads PR diffs, ticket descriptions, thread context)
3. **Claude writes the report** — with genuine insight, not just a list of titles
4. **Python enforces safety** — read-only tool allowlist, Gmail body scrubbing, turn limits

```
Python wrapper → start MCP servers → Claude agent loop:
  ├── Claude decides what to investigate
  ├── Claude calls MCP tools (search, get details, follow threads)
  ├── Claude receives results, decides next action
  ├── Claude drills into significant items for rich detail
  └── Claude produces the final report with full context
```

---

## Installation

**Requirements**: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), Node.js 20+ (for npm-based MCP servers), and Docker (for GitHub and Slack MCP servers)

```bash
git clone <repo-url> status-report
cd status-report
cp .env.example .env      # copy template
# Edit .env with your credentials (see Configuration below)
uv sync                   # install dependencies
```

### Docker (alternative)

```bash
docker build -t status-report .

docker run --rm \
  --env-file .env \
  -v ~/.status-report:/root/.status-report \
  status-report --user you@example.com
```

The Docker image includes Python, Node.js, all MCP server packages, and Playwright for browser fallback.

---

## Configuration

All configuration is via environment variables in `.env`. The file is git-ignored — never commit it.

### Required

| Variable | Purpose |
|----------|---------|
| `VERTEX_PROJECT_ID` | GCP project where Claude is deployed on Vertex AI |
| `VERTEX_REGION` | Vertex AI region (default: `us-east5`) |

Authentication uses [Google Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) — no API key needed. Run `gcloud auth application-default login` once on your machine, or attach a service account in GKE/Cloud Run.

At least one data source credential is also required (otherwise exit code 2).

### Data Sources (MCP Servers)

Each data source is accessed via an MCP server that starts as a subprocess. Credentials are passed as environment variables to the server process — they never flow through Claude.

| Variable(s) | Source | MCP Server |
|-------------|--------|-----------|
| `GITHUB_TOKEN` | GitHub | `ghcr.io/github/github-mcp-server` (official Go binary, run via Docker) |
| `JIRA_BASE_URL` + `JIRA_USER_EMAIL` + `JIRA_API_TOKEN` | Jira Cloud | `@sooperset/mcp-atlassian` (npm) |
| `SLACK_MCP_XOXC_TOKEN` + `SLACK_MCP_XOXD_TOKEN` | Slack | `ghcr.io/korotovsky/slack-mcp-server` (Docker) — no admin approval needed |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Calendar, Drive, Gmail | `workspace-mcp` (run via `uvx`) |

**Slack tokens** are browser session tokens extracted automatically from the Slack web app — no app registration or workspace admin approval required. Run `uv run python -m status_report.auth.slack --extract` to set them up.

A Playwright browser fallback MCP server is always available; it doubles as a Slack fallback when `~/.status-report/playwright-state.json` exists (created by `uv run python -m status_report.auth.slack --login`).

### Optional

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model deployed in your Vertex AI project |
| `MAX_AGENT_TURNS` | `50` | Max agent loop iterations (Claude tool_use cycles) per report |
| `MAX_RESPONSE_TOKENS` | `8096` | Max tokens per Claude response (must be ≥ 1024) |

---

## Usage

```
python -m status_report.main --user <email> [OPTIONS]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--user` | Yes | — | Target user (email or username) |
| `--period` | No | Auto from run history | Time range (see Period Formats) |
| `--sources` | No | All configured | Comma-separated source labels |
| `--format` | No | `text` | Output format: `text`, `markdown`, `json` |

### Source Labels

Available source labels for `--sources`:

`github`, `jira`, `slack`, `google`, `browser`

### Period Formats

| Value | Covers |
|-------|--------|
| `today` | 00:00 UTC today → now |
| `yesterday` | Full previous calendar day (UTC) |
| `last-24h` | Rolling 24 hours from now |
| `YYYY-MM-DD` | Full calendar day (UTC) |
| `YYYY-MM-DD:YYYY-MM-DD` | Inclusive date range |
| _(omitted)_ | Since last successful run (first run: today) |

### Examples

```bash
# Auto-period — most common daily use
python -m status_report.main --user alice@example.com

# Yesterday's report in Markdown
python -m status_report.main --user alice@example.com --period yesterday --format markdown

# GitHub and Slack only, as JSON
python -m status_report.main --user alice@example.com \
  --period today --sources github,slack --format json

# Custom date range
python -m status_report.main --user alice@example.com \
  --period 2026-02-24:2026-02-28 --format markdown > report.md
```

---

## Output Formats

### Text (default)

```
Status Report — alice@example.com — 2026-02-28
============================================================

Period : since last run at 2026-02-27T09:30:00Z

KEY ACCOMPLISHMENTS
-------------------
- Merged PR #412 (auth-refactor)
- Closed JIRA-1023 (Deploy pipeline fix)

MEETINGS & COLLABORATION
------------------------
- Sprint planning with 6 attendees (45 min)
```

### Markdown

```markdown
# Status Report — alice@example.com — 2026-02-28

**Period**: since last run at 2026-02-27T09:30:00Z

## Key Accomplishments
- Merged PR #412 (auth-refactor)
- Closed JIRA-1023 (Deploy pipeline fix)
```

### JSON

```json
{
  "user": "alice@example.com",
  "period": {
    "label": "since last run at 2026-02-27T09:30:00Z",
    "start": "2026-02-27T09:30:00+00:00",
    "end": "2026-02-28T09:31:00+00:00"
  },
  "generated_at": "2026-02-28T09:31:00+00:00",
  "sections": [...]
}
```

---

## Auto-Period (Run History)

When you omit `--period`, the agent reads `~/.status-report/run_history.log` and sets the period from your last successful run to now. On the very first run it defaults to today.

```bash
# Run 1 — period: "today (first run)"
python -m status_report.main --user alice@example.com

# Run 2 next day — period: "since last run at 2026-02-28T09:00:00Z"
python -m status_report.main --user alice@example.com
```

History is stored as JSONL, scoped per user, and pruned to 90 days automatically.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success — all configured sources returned data |
| `1` | Partial — report generated; ≥1 source skipped |
| `2` | Failure — no data retrieved; all MCP servers failed or none configured |
| `3` | Invalid arguments — bad `--period`, unknown format, future date |

---

## Read-Only Safety

The agent enforces read-only access with a **3-layer defense**:

1. **MCP server flags** — servers configured with read-only environment variables where supported
2. **Tool allowlist filtering** — the registry only exposes whitelisted read-only tools to Claude
3. **Runtime validation** — the executor validates every tool call against the allowlist before dispatch

Write tools are never exposed to Claude, regardless of what the MCP server provides.

---

## Project Structure

```
src/status_report/
├── main.py           # CLI entry point + MCP server lifecycle
├── agent.py          # Claude agent loop (tool_use cycle)
├── config.py         # Pydantic settings + period parsing
├── report.py         # Report model + text/markdown/json formatters
├── run_history.py    # Per-user run history (auto-period)
├── run_log.py        # Audit log (runs.log) with MCP agentic fields
├── tracing.py        # structlog configuration
├── mcp/              # MCP infrastructure
│   ├── config.py     # Server configs + env-based building
│   ├── manager.py    # Server subprocess lifecycle
│   ├── registry.py   # Tool allowlist filtering
│   └── executor.py   # Tool dispatch + Gmail body scrubbing
└── auth/
    ├── google.py     # Google OAuth consent flow + token refresh
    └── slack.py      # Playwright-based Slack token extractor + browser session login
```

---

## Security

- **Read-only**: 3-layer defense prevents any write operation. No MCP tool can modify external systems.
- **MCP credential isolation**: Credentials are passed as env vars to MCP server subprocesses. They never flow through Claude's context, tool arguments, or tool results.
- **Gmail body scrub**: The executor removes email body content from Gmail tool results before they reach Claude. Permanent, no opt-in.
- **No secrets in logs**: All credentials are excluded from structlog output and RunTrace audit entries.
- **Local token storage**: Google OAuth tokens are stored in `~/.status-report/google_credentials.json` and Slack browser tokens in `~/.status-report/slack_tokens.json` (both permissions 600, directory 700).
- **`.env` is git-ignored** — never commit it.
