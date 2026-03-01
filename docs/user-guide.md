# Status Report Agent — User Guide

This guide covers all features of the Status Report Agent in depth. For a quick overview, see the [README](../README.md).

---

## Table of Contents

1. [Installation & Setup](#installation--setup)
2. [Configuration Reference](#configuration-reference)
3. [CLI Reference](#cli-reference)
4. [Period Formats](#period-formats)
5. [Auto-Period (Run History)](#auto-period-run-history)
6. [Output Formats](#output-formats)
7. [Exit Codes](#exit-codes)
8. [Data Sources](#data-sources)
9. [Multi-User Setup](#multi-user-setup)
10. [Docker Usage](#docker-usage)
11. [Adding Custom Skills](#adding-custom-skills)
12. [Observability & Tracing](#observability--tracing)
13. [Troubleshooting](#troubleshooting)
14. [Security & Privacy](#security--privacy)

---

## Installation & Setup

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) package manager
- API credentials for at least one data source
- (Optional) Google account for Calendar, Drive, and Gmail access

### Local Setup

```bash
git clone <repo-url> status-report
cd status-report

# Copy the env template and fill in your credentials
cp .env.example .env
# Edit .env with your values

# Install dependencies
uv sync

# (Optional) If using Google Calendar, Drive, or Gmail — one-time OAuth consent
uv run python -m status_report.auth.google --consent
```

The Google OAuth consent opens a browser window. After authorising, refresh tokens are saved to `~/.status-report/google_credentials.json` with permissions 600. You will not need to repeat this unless the token is revoked.

### Running Tests

```bash
uv run pytest --tb=short -q
```

All tests use mocked I/O — no live API credentials required.

---

## Configuration Reference

All configuration is supplied via a `.env` file (or exported environment variables). The file is git-ignored.

### Anthropic (Required)

| Variable | Format | Description |
|----------|--------|-------------|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Anthropic API key for Claude synthesis |

### LangFuse (Required)

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGFUSE_PUBLIC_KEY` | — | LangFuse public key |
| `LANGFUSE_SECRET_KEY` | — | LangFuse secret key |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Override for self-hosted LangFuse |

### Jira (Optional)

| Variable | Description |
|----------|-------------|
| `JIRA_BASE_URL` | Your Jira Cloud instance, e.g. `https://yourorg.atlassian.net` |
| `JIRA_USER_EMAIL` | Email address for Jira API auth |
| `JIRA_API_TOKEN` | Jira Cloud API token ([create one here](https://id.atlassian.com/manage-profile/security/api-tokens)) |

### Slack (Optional)

| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | Bot or user token (`xoxb-...`). Requires scopes: `search:read`, `channels:history`, `channels:read`, `users:read` |

### GitHub (Optional)

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | Personal Access Token (classic or fine-grained). Required scopes: `repo:read`, `read:org` |

### Google (Optional — shared by Calendar, Drive, Gmail)

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLIENT_ID` | OAuth 2.0 client ID from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | OAuth 2.0 client secret |
| `GOOGLE_PROJECT_ID` | Google Cloud project ID |

### Behaviour Tuning (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `SKILL_FETCH_LIMIT` | `100` | Max ActivityItems returned per source per run. Oldest items are dropped when exceeded. |

---

## CLI Reference

```
python -m status_report.main --user <email> [OPTIONS]
```

Or via the `pyproject.toml` script entry point if installed:

```
status-report --user <email> [OPTIONS]
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--user USER` | Yes | — | Target user identifier (email or username). Must be a non-empty string. |
| `--period PERIOD` | No | Auto from run history | Time range for the report. See [Period Formats](#period-formats). |
| `--sources SOURCES` | No | All configured | Comma-separated list of source names to include. Unknown names are warned and skipped. |
| `--format FORMAT` | No | `text` | Output format. One of: `text`, `markdown`, `json`. |

### Source Names

Built-in source names for `--sources`:

`jira`, `slack`, `github`, `calendar`, `gdrive`, `gmail`

Custom skills are also available by their module name. Unknown names are printed as warnings but do not cause a non-zero exit on their own.

### Common Invocations

```bash
# Auto-period (recommended daily use)
python -m status_report.main --user alice@example.com

# Explicit period
python -m status_report.main --user alice@example.com --period yesterday

# Markdown output piped to file
python -m status_report.main --user alice@example.com \
  --period 2026-02-24:2026-02-28 --format markdown > weekly.md

# Selected sources only
python -m status_report.main --user alice@example.com \
  --sources github,slack --format json | jq '.sections'

# GitHub only, last 24 hours
python -m status_report.main --user alice@example.com \
  --period last-24h --sources github
```

---

## Period Formats

The `--period` argument accepts these formats:

| Format | Example | What it covers |
|--------|---------|----------------|
| `today` | `--period today` | 00:00 UTC today → now |
| `yesterday` | `--period yesterday` | 00:00 → 23:59 UTC the previous calendar day |
| `last-24h` | `--period last-24h` | Rolling 24 hours before now |
| `YYYY-MM-DD` | `--period 2026-02-28` | 00:00 → 23:59 UTC on that date |
| `YYYY-MM-DD:YYYY-MM-DD` | `--period 2026-02-24:2026-02-28` | 00:00 UTC start date → 23:59 UTC end date (inclusive) |
| _(omitted)_ | (no flag) | Auto-computed from run history — see below |

**Future dates are rejected** with exit code 3 and an error message to stderr.

All timestamps are UTC. The agent does not adjust for local time zones.

---

## Auto-Period (Run History)

When you omit `--period`, the agent computes the period automatically from the run history stored at `~/.status-report/run_history.log`.

### How It Works

| Condition | Period Used | Period Label |
|-----------|-------------|--------------|
| First ever run (no history) | 00:00 UTC today → now | `today (first run)` |
| Subsequent runs | Last successful run timestamp → now | `since last run at YYYY-MM-DDTHH:MM:SSZ` |
| Explicit `--period` | As specified | Whatever the period string resolves to |

Explicit `--period` always takes precedence — it completely skips the history lookup.

### Typical Daily Workflow

```bash
# Monday morning
python -m status_report.main --user alice@example.com
# Period: "today (first run)"
# → covers everything from 00:00 UTC today to now

# Tuesday morning
python -m status_report.main --user alice@example.com
# Period: "since last run at 2026-02-28T09:00:00Z"
# → covers Monday morning to Tuesday morning exactly, no overlap, no gap
```

### Run History File

Location: `~/.status-report/run_history.log`

Format: JSONL (one JSON object per line)

```json
{"schema_version": "1", "user": "alice@example.com", "completed_at": "2026-02-28T09:00:00.000000Z", "period_label": "today (first run)", "outcome": "success"}
{"schema_version": "1", "user": "alice@example.com", "completed_at": "2026-03-01T09:00:00.000000Z", "period_label": "since last run at 2026-02-28T09:00:00Z", "outcome": "success"}
```

### Rules for History Recording

- **Recorded when**: outcome is `success` or `partial` (at least one source returned data)
- **Not recorded when**: all sources failed (outcome `failed`, exit code 2)
- **Retention**: Entries older than 90 days are automatically pruned on every write
- **Concurrent access**: File writes are protected with a file lock — safe for parallel invocations
- **Directory**: `~/.status-report/` is created automatically on first run

### History Resilience

| Situation | Behaviour |
|-----------|-----------|
| History file missing | Falls back to "today (first run)" |
| Malformed JSON line | Line skipped with warning; next valid entry used |
| Entry with future timestamp | Entry skipped with warning; next valid entry used |
| All entries are `failed` outcome | Falls back to "today (first run)" |

The agent never crashes due to a corrupted or missing history file.

### Inspecting Run History

```bash
# All runs
cat ~/.status-report/run_history.log

# Last 5 runs, formatted
tail -n 5 ~/.status-report/run_history.log | python -m json.tool

# Check for partial or failed runs
grep '"outcome": "partial"\|"outcome": "failed"' ~/.status-report/run_history.log
```

---

## Output Formats

### Text Format (default)

Plain-text output with ASCII separators. Suitable for terminal display, email, or plain-text notes.

```
Status Report — alice@example.com — 2026-02-28
============================================================

Period : since last run at 2026-02-27T09:30:00Z

KEY ACCOMPLISHMENTS
-------------------
- Merged PR #412 (auth-refactor) into main
- Closed JIRA-1023 (Deploy pipeline fix)

CODE CONTRIBUTIONS
------------------
- Opened PR #415: Add rate limiting middleware
- Reviewed PR #410: Update dependency versions (approved)

MEETINGS & COLLABORATION
------------------------
- Sprint planning (6 attendees, 45 min)
- 1:1 with manager (30 min)

────────────────────────────────────────────────────────────
⚠ Skipped: gdrive (credentials_missing)
```

Sections are only present when data exists. The skipped-sources footer only appears if ≥1 source was skipped.

### Markdown Format

GitHub-flavoured Markdown. Suitable for wikis, pull request descriptions, Notion, or email.

```markdown
# Status Report — alice@example.com — 2026-02-28

**Period**: since last run at 2026-02-27T09:30:00Z

## Key Accomplishments
- Merged PR #412 (auth-refactor) into main
- Closed JIRA-1023 (Deploy pipeline fix)

## Code Contributions
- Opened PR #415: Add rate limiting middleware
- Reviewed PR #410: Update dependency versions (approved)

## Meetings & Collaboration
- Sprint planning (6 attendees, 45 min)
- 1:1 with manager (30 min)

---

⚠ Skipped: gdrive (credentials_missing)
```

### JSON Format

Machine-readable. Suitable for scripting, dashboards, or piping to `jq`.

```json
{
  "user": "alice@example.com",
  "period": {
    "label": "since last run at 2026-02-27T09:30:00Z",
    "start": "2026-02-27T09:30:00+00:00",
    "end": "2026-02-28T09:31:00+00:00"
  },
  "generated_at": "2026-02-28T09:31:00+00:00",
  "sections": [
    {
      "heading": "Key Accomplishments",
      "content": "- Merged PR #412 (auth-refactor) into main\n- Closed JIRA-1023 (Deploy pipeline fix)"
    },
    {
      "heading": "Code Contributions",
      "content": "- Opened PR #415: Add rate limiting middleware\n- Reviewed PR #410: Update dependency versions (approved)"
    }
  ],
  "skipped_sources": [
    {
      "source": "gdrive",
      "reason": "credentials_missing",
      "attempts": 0
    }
  ]
}
```

### Possible Report Sections

Claude includes only sections where data exists. All possible sections:

| Section | Data from |
|---------|-----------|
| Key Accomplishments | All sources (synthesised summary) |
| Tickets & Issues | Jira |
| Code Contributions | GitHub |
| Meetings & Collaboration | Google Calendar |
| Documents | Google Drive |
| Email Activity | Gmail |
| Suggested Follow-ups | All sources (synthesised) |

---

## Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| `0` | Success — all configured sources returned data | — |
| `1` | Partial — report generated; ≥1 source was skipped | Check `skipped_sources` in output |
| `2` | Failure — no data retrieved; all sources failed or none configured | Check credentials and source config |
| `3` | Invalid arguments — bad `--period`, unknown format, future date, empty `--user` | Fix the argument and retry |

Exit codes enable scripting:

```bash
python -m status_report.main --user alice@example.com --format markdown > report.md
case $? in
  0) echo "Complete report generated" ;;
  1) echo "Partial report — some sources skipped" ;;
  2) echo "ERROR: No data retrieved" ;;
  3) echo "ERROR: Invalid arguments" ;;
esac
```

---

## Data Sources

### Jira

- **Auth**: API token via Basic Auth (email:token)
- **Data collected**: Issues updated, created, or transitioned; comments authored; worklogs
- **Scope**: Read-only (`read:jira-work`, `read:jira-user`)
- **Get an API token**: [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens)

### Slack

- **Auth**: Bot token or user token (`xoxb-...`)
- **Data collected**: Messages sent, threads replied to, reactions given
- **Required scopes**: `search:read`, `channels:history`, `channels:read`, `users:read`

### GitHub

- **Auth**: Personal Access Token
- **Data collected**: PRs opened, reviewed, merged; commits pushed; code review comments
- **Required scopes**: `repo:read`, `read:org`
- **Get a token**: GitHub Settings → Developer settings → Personal access tokens

### Google Calendar

- **Auth**: OAuth 2.0 (shared with Drive and Gmail)
- **Data collected**: Meetings attended — title, time, duration, attendee count only
- **Privacy**: Meeting notes, attachments, and event descriptions are never fetched
- **Scope**: `https://www.googleapis.com/auth/calendar.readonly`

### Google Drive

- **Auth**: OAuth 2.0 (shared)
- **Data collected**: Documents created, modified, or viewed
- **Scopes**: `drive.metadata.readonly`, `drive.activity.readonly`

### Gmail

- **Auth**: OAuth 2.0 (shared)
- **Data collected**: Sent emails, replies, emails with action items — subject and metadata only, never body content
- **Scope**: Read-only Gmail scopes

---

## Multi-User Setup

Multiple users can share the same machine. Run history is scoped per `--user` value.

```bash
# Alice generates her report
python -m status_report.main --user alice@example.com

# Bob generates his report independently — uses his own run history
python -m status_report.main --user bob@example.com
```

Each user's history is stored as separate entries (filtered by the `user` field) in the shared `~/.status-report/run_history.log` file. Access is concurrent-safe via file locking.

---

## Docker Usage

The Docker image is stateless. All credentials and state are injected at runtime.

### Build

```bash
docker build -t status-report .
```

### Run

```bash
docker run --rm \
  --env-file .env \
  -v ~/.status-report:/root/.status-report \
  status-report \
  --user alice@example.com
```

The volume mount (`-v ~/.status-report:/root/.status-report`) provides:
- Google OAuth refresh tokens (`google_credentials.json`)
- Run history for auto-period (`run_history.log`)
- Audit log (`runs.log`)

Use `:ro` (read-only) if you only want the container to read history, not update it.

### Common Docker Invocations

```bash
# Auto-period with read-write history
docker run --rm \
  --env-file .env \
  -v ~/.status-report:/root/.status-report \
  status-report --user alice@example.com

# Explicit period, markdown output saved to host
docker run --rm \
  --env-file .env \
  -v ~/.status-report:/root/.status-report:ro \
  status-report \
  --user alice@example.com \
  --period yesterday \
  --format markdown > report.md

# JSON output piped through jq
docker run --rm \
  --env-file .env \
  -v ~/.status-report:/root/.status-report:ro \
  status-report \
  --user alice@example.com \
  --format json | jq '.sections[].heading'
```

---

## Adding Custom Skills

Skills are auto-discovered Python modules in `src/status_report/skills/`. No changes to `agent.py`, `config.py`, or `main.py` are needed.

### Create a Skill Module

`src/status_report/skills/myservice.py`:

```python
from __future__ import annotations

import os
from datetime import datetime

import httpx

from status_report.skills.base import ActivityItem, ActivitySkill


class MyServiceSkill(ActivitySkill):

    def is_configured(self) -> bool:
        return bool(os.getenv("MYSERVICE_API_TOKEN"))

    async def fetch_activity(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        token = os.getenv("MYSERVICE_API_TOKEN")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.myservice.com/activity",
                headers={"Authorization": f"Bearer {token}"},
                params={"user": user, "since": start.isoformat(), "until": end.isoformat()},
            )
            response.raise_for_status()
            return [
                ActivityItem(
                    source="myservice",
                    action_type=item["type"],
                    title=item["title"],
                    timestamp=datetime.fromisoformat(item["created_at"]),
                    url=item.get("url"),
                    metadata={"status": item.get("status", "unknown")},
                )
                for item in response.json().get("items", [])
            ]
```

### Add Credentials to `.env.example`

```bash
# MyService
MYSERVICE_API_TOKEN=
```

### Select in CLI

```bash
python -m status_report.main --user alice@example.com --sources myservice
```

### ActivityItem Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | `str` | Yes | Source identifier (`"jira"`, `"myservice"`, etc.) |
| `action_type` | `str` | Yes | What happened: `"created"`, `"updated"`, `"reviewed"`, etc. |
| `title` | `str` | Yes | Human-readable brief description |
| `timestamp` | `datetime` | Yes | When the activity occurred (must be timezone-aware UTC) |
| `url` | `str \| None` | No | Link to the item |
| `metadata` | `dict[str, str]` | No | Extra key-value pairs (no sensitive field names) |

Sensitive field names are blocked in `metadata` (enforced by Pydantic): `token`, `password`, `secret`, `authorization`, `credential`, `body`, `content`.

---

## Observability & Tracing

### LangFuse

Every run creates a top-level LangFuse trace with:
- User identifier and period label
- Output format
- One child span per skill
- One child span for Claude synthesis (model, token usage, latency)
- Final outcome and duration

Traces are visible at your LangFuse dashboard ([cloud.langfuse.com](https://cloud.langfuse.com) or self-hosted).

Credentials and raw activity data are never included in spans.

### Audit Log

Every run appends to `~/.status-report/runs.log` (JSONL):

```json
{
  "timestamp": "2026-02-28T09:31:00.000000Z",
  "user": "alice@example.com",
  "period": "since last run at 2026-02-27T09:30:00Z",
  "format": "text",
  "sources_attempted": ["jira", "slack", "github"],
  "counts": {"jira": 5, "slack": 12, "github": 3},
  "outcome": "success",
  "skipped": [],
  "retries": {},
  "duration_seconds": 2.847
}
```

### Structured Logs

Application logs use `structlog` and go to stderr. To increase verbosity:

```bash
LOG_LEVEL=DEBUG python -m status_report.main --user alice@example.com
```

---

## Troubleshooting

### "No skills are configured"

Exit code 2. At least one data source credential must be set.

**Fix**: Confirm at least one of these is in `.env`:
- `JIRA_API_TOKEN` (+ `JIRA_USER_EMAIL` + `JIRA_BASE_URL`)
- `SLACK_BOT_TOKEN`
- `GITHUB_TOKEN`
- `GOOGLE_CLIENT_ID` (+ `GOOGLE_CLIENT_SECRET` + `GOOGLE_PROJECT_ID`)

### Jira returns no results

- Verify `JIRA_USER_EMAIL` matches the email on your Atlassian account.
- Verify `JIRA_API_TOKEN` is valid (they expire or can be revoked).
- Confirm your Jira user has activity in the requested period.

### Google authentication fails

Re-run the OAuth consent flow:

```bash
uv run python -m status_report.auth.google --consent
```

Then verify `~/.status-report/google_credentials.json` exists.

### Docker can't read Google credentials

Ensure the volume is mounted writable (not `:ro`) when running the OAuth consent step, and readable when running the agent:

```bash
docker run --rm \
  --env-file .env \
  -v ~/.status-report:/root/.status-report \
  status-report \
  --user alice@example.com
```

### "Skipped: github (transient_error_exhausted)"

The GitHub API was unreachable or rate-limited after 3 retries. Check:
- `GITHUB_TOKEN` is valid
- You have not exceeded GitHub's rate limit (5000 req/hr for authenticated requests)

```bash
curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/rate_limit
```

### Period is wrong on second run

If the auto-period is not what you expected, inspect the run history:

```bash
tail -n 5 ~/.status-report/run_history.log | python -m json.tool
```

To override, pass `--period` explicitly:

```bash
python -m status_report.main --user alice@example.com --period 2026-02-28
```

### Report has no sections / empty output

Exit code 2. All skills either failed or returned zero activity items.

- Check `~/.status-report/runs.log` for the last run's `counts` and `skipped` fields.
- Check LangFuse trace for per-skill span details.

---

## Security & Privacy

### What the Agent Never Does

- Writes, modifies, or deletes data in any external system (strictly read-only)
- Sends raw API tokens or credentials to Claude or LangFuse
- Fetches email body content (subjects and metadata only for Gmail)
- Fetches meeting notes or calendar event descriptions
- Stores any data outside `~/.status-report/` and your `.env` file

### File Permissions

| File | Permissions | Contents |
|------|-------------|----------|
| `.env` | `600` (set manually) | API tokens and OAuth credentials |
| `~/.status-report/google_credentials.json` | `600` (set automatically) | Google OAuth refresh token |
| `~/.status-report/run_history.log` | Default | Run timestamps and outcomes (no credentials) |
| `~/.status-report/runs.log` | Default | Audit log (no credentials) |

### What Claude Receives

Claude receives only structured `ActivityItem` data: source name, action type, title, timestamp, URL, and non-sensitive metadata. It never receives:

- Raw API responses
- OAuth tokens or API keys
- Email body content
- Calendar event descriptions
- Any field whose key matches: `token`, `password`, `secret`, `authorization`, `credential`, `body`, `content`
