# Status Report Agent

A Python-based CLI agent that generates daily or periodic status reports by aggregating read-only activity data from your workplace tools — Jira, GitHub, Slack, Google Calendar, Google Drive, and Gmail — and synthesising them into a readable report using Claude.

## Quick Start

```bash
# 1. Install dependencies
cp .env.example .env   # fill in your credentials
uv sync

# 2. One-time Google OAuth consent (if using Calendar / Drive / Gmail)
uv run python -m status_report.auth.google --consent

# 3. Generate your first report
python -m status_report.main --user you@example.com
```

The first run defaults to "today". Every subsequent run without `--period` automatically covers the period since your last run.

---

## Installation

**Requirements**: Python 3.12+ and [`uv`](https://docs.astral.sh/uv/)

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

---

## Configuration

All configuration is via environment variables in `.env`. The file is git-ignored — never commit it.

### Required

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API key (Anthropic) |
| `LANGFUSE_PUBLIC_KEY` | LangFuse observability public key |
| `LANGFUSE_SECRET_KEY` | LangFuse observability secret key |

At least one data source credential is also required (otherwise exit code 2).

### Data Sources

| Variable(s) | Source |
|-------------|--------|
| `JIRA_BASE_URL` + `JIRA_USER_EMAIL` + `JIRA_API_TOKEN` | Jira Cloud |
| `SLACK_BOT_TOKEN` | Slack |
| `GITHUB_TOKEN` | GitHub |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `GOOGLE_PROJECT_ID` | Calendar, Drive, Gmail |

### Optional

| Variable | Default | Purpose |
|----------|---------|---------|
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Self-hosted LangFuse endpoint |
| `SKILL_FETCH_LIMIT` | `100` | Max activity items per source per run |

---

## Usage

```
python -m status_report.main --user <email> [OPTIONS]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--user` | Yes | — | Target user (email or username) |
| `--period` | No | Auto from run history | Time range (see Period Formats) |
| `--sources` | No | All configured | Comma-separated source names |
| `--format` | No | `text` | Output format: `text`, `markdown`, `json` |

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
| `2` | Failure — no data retrieved; all sources failed or none configured |
| `3` | Invalid arguments — bad `--period`, unknown format, future date |

---

## Project Structure

```
src/status_report/
├── main.py           # CLI entry point
├── agent.py          # Orchestration: concurrent fetch + Claude synthesis
├── config.py         # Pydantic settings + period parsing
├── report.py         # Report model + text/markdown/json formatters
├── run_history.py    # Per-user run history (auto-period)
├── run_log.py        # Audit log (runs.log)
├── tracing.py        # LangFuse client
├── skills/           # One module per data source
└── auth/             # Google OAuth + token management
```

---

## Further Reading

- **[User Guide](docs/user-guide.md)** — full feature documentation, multi-user setup, Docker details, custom skills, troubleshooting

---

## Security

- **Read-only**: No skill ever writes, modifies, or deletes data in any external system.
- **No secrets in code or logs**: All credentials come from environment variables. LangFuse traces are scrubbed of secrets.
- **Local token storage**: Google OAuth tokens are stored in `~/.status-report/google_credentials.json` (permissions 600).
- **`.env` is git-ignored** — never commit it.
