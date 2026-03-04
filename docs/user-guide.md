# Status Report Agent — User Guide

This guide covers all features of the Status Report Agent in depth. For a quick overview, see the [README](../README.md).

---

## Table of Contents

1. [Installation & Setup](#installation--setup)
2. [Vertex AI Setup](#vertex-ai-setup)
3. [Configuration Reference](#configuration-reference)
4. [CLI Reference](#cli-reference)
5. [Period Formats](#period-formats)
6. [Auto-Period (Run History)](#auto-period-run-history)
7. [Output Formats](#output-formats)
8. [Exit Codes](#exit-codes)
9. [Data Sources & MCP Servers](#data-sources--mcp-servers)
10. [Multi-User Setup](#multi-user-setup)
11. [Docker Usage](#docker-usage)
12. [Adding New Data Sources](#adding-new-data-sources)
13. [Audit Logging](#audit-logging)
14. [Troubleshooting](#troubleshooting)
15. [Security & Privacy](#security--privacy)

---

## Installation & Setup

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) package manager
- Node.js 20+ (for MCP servers — installed automatically in Docker)
- API credentials for at least one data source
- (Optional) Google account for Calendar, Drive, and Gmail access

### Local Setup

```bash
git clone <repo-url> status-report
cd status-report

# Authenticate with Google Cloud (one-time per machine)
gcloud auth application-default login

# Copy the env template and fill in your credentials
cp .env.example .env
# Edit .env — at minimum set VERTEX_PROJECT_ID

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

All tests use mocked MCP sessions and Claude responses — no live API credentials or MCP servers required.

---

## Vertex AI Setup

Claude is accessed via your own Google Cloud Vertex AI deployment — no Anthropic API key is required. Authentication uses [Application Default Credentials (ADC)](https://cloud.google.com/docs/authentication/application-default-credentials), which are handled automatically by the Google auth libraries.

### Step 1 — Enable Vertex AI in your GCP project

```bash
gcloud services enable aiplatform.googleapis.com --project YOUR_PROJECT_ID
```

### Step 2 — Request access to Claude models

Open the [Vertex AI Model Garden](https://console.cloud.google.com/vertex-ai/model-garden) in your project, find the Claude model you want, and click **Enable**.

### Step 3 — Grant IAM permissions

Your user account or service account needs the **Vertex AI User** role:

```bash
# For a user account
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="user:you@example.com" \
  --role="roles/aiplatform.user"

# For a service account (GKE / Cloud Run)
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### Step 4 — Authenticate locally

```bash
# One-time per machine — opens browser for Google sign-in
gcloud auth application-default login
```

In GKE or Cloud Run no extra auth is needed — the pod/container's service account is used automatically.

### Step 5 — Configure `.env`

```env
VERTEX_PROJECT_ID=your-gcp-project-id
VERTEX_REGION=us-east5
CLAUDE_MODEL=claude-sonnet-4-6
```

Available regions for Claude on Vertex AI: `us-east5`, `europe-west1`, `us-central1`.

---

## Configuration Reference

All configuration is supplied via a `.env` file (or exported environment variables). The file is git-ignored.

### Vertex AI (Required)

| Variable | Default | Description |
|----------|---------|-------------|
| `VERTEX_PROJECT_ID` | — | GCP project ID where Claude is deployed |
| `VERTEX_REGION` | `us-east5` | Vertex AI region |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model name as listed in Vertex AI Model Garden |

### Data Source Credentials

| Variable(s) | Source | MCP Server |
|-------------|--------|-----------|
| `GITHUB_TOKEN` | GitHub | `@modelcontextprotocol/server-github` |
| `JIRA_BASE_URL` + `JIRA_USER_EMAIL` + `JIRA_API_TOKEN` | Jira Cloud | `@sooperset/mcp-atlassian` |
| `SLACK_BOT_TOKEN` | Slack | `@modelcontextprotocol/server-slack` |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `GOOGLE_PROJECT_ID` | Calendar, Drive, Gmail | `@anthropic/google-workspace-mcp` |

### Agent Tuning (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_AGENT_TURNS` | `50` | Max agent loop iterations (Claude tool_use cycles) per report. When reached, Claude is asked to write its best report with data collected so far. |

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
| `--sources SOURCES` | No | All configured | Comma-separated list of source labels to include. |
| `--format FORMAT` | No | `text` | Output format. One of: `text`, `markdown`, `json`. |

### Source Labels

Source labels for `--sources`:

| Label | MCP Server |
|-------|-----------|
| `github` | GitHub MCP server |
| `jira` | Jira Atlassian MCP server |
| `slack` | Slack MCP server |
| `google` | Google Workspace MCP server (Calendar, Drive, Gmail) |
| `browser` | Playwright browser fallback |

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

### Rules for History Recording

- **Recorded when**: outcome is `success` or `partial` (at least one source returned data)
- **Not recorded when**: all sources failed (outcome `failed`, exit code 2)
- **Retention**: Entries older than 90 days are automatically pruned on every write
- **Concurrent access**: File writes are protected with a file lock — safe for parallel invocations

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
```

### Markdown Format

GitHub-flavoured Markdown. Suitable for wikis, pull request descriptions, Notion, or email.

```markdown
# Status Report — alice@example.com — 2026-02-28

**Period**: since last run at 2026-02-27T09:30:00Z

## Key Accomplishments
- Merged PR #412 (auth-refactor) into main

## Code Contributions
- Opened PR #415: Add rate limiting middleware
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
  "sections": [...],
  "skipped_sources": [...]
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
| Email Activity | Gmail (subject and action type only — body never collected) |
| Suggested Follow-ups | All sources (synthesised) |

---

## Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| `0` | Success — all configured sources returned data | — |
| `1` | Partial — report generated; ≥1 source was skipped | Check `skipped_sources` in output |
| `2` | Failure — no data retrieved; all MCP servers failed or none configured | Check credentials and MCP server config |
| `3` | Invalid arguments — bad `--period`, unknown format, future date, empty `--user` | Fix the argument and retry |

---

## Data Sources & MCP Servers

Each data source is accessed via an MCP (Model Context Protocol) server — an external process that exposes tools over the stdio transport. The agent starts these servers as subprocesses and Claude calls their tools directly.

### Read-Only Safety (3-Layer Defense)

1. **MCP server flags**: Servers configured with read-only environment variables where supported
2. **Tool allowlist filtering**: The registry only exposes whitelisted read-only tools to Claude
3. **Runtime validation**: The executor validates every tool call against the allowlist before dispatch

---

### GitHub

**MCP Server**: `@modelcontextprotocol/server-github`

**What Claude can do**: Search repositories, read file contents, list and inspect pull requests (including diffs and reviews), list commits, search and read issues and comments.

**Credentials needed**: `GITHUB_TOKEN`

Create a Personal Access Token at [github.com/settings/tokens](https://github.com/settings/tokens). Required scopes: `repo` (read), `read:org`.

---

### Jira Cloud

**MCP Server**: `@sooperset/mcp-atlassian`

**What Claude can do**: Search issues via JQL, read issue details and comments, view transitions, read worklogs, list board issues.

**Credentials needed**: `JIRA_BASE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`

Create an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

---

### Slack

**MCP Server**: [`korotovsky/slack-mcp-server`](https://github.com/korotovsky/slack-mcp-server) (stdio)

**What Claude can do**: Search your messages by date range, read channel history, get thread context, look up user info.

**Why not the official Slack MCP?** The official Slack MCP server is cloud-hosted (HTTP transport only) and requires workspace admin approval. This project uses `korotovsky/slack-mcp-server` instead — it runs locally via stdio and requires no app registration or admin involvement.

**Credentials needed**: `SLACK_MCP_XOXC_TOKEN`, `SLACK_MCP_XOXD_TOKEN` (browser session tokens)

These are extracted directly from your logged-in Slack web session. There are two ways to get them:

---

#### Option A — Automated (recommended)

A one-time script opens Slack in a browser, waits for you to log in, then extracts both tokens automatically. It also saves your browser session for the Playwright MCP fallback.

```bash
# First-time setup or token refresh
uv run python -m status_report.auth.slack --extract
```

What happens:
1. A Chromium browser opens and navigates to `app.slack.com`
2. If you're not already logged in, sign into your workspace as normal
3. Press Enter in the terminal when you can see your messages
4. The script extracts your `xoxc` and `xoxd` tokens automatically
5. Tokens are printed for you to add to `.env`, and also saved to `~/.status-report/slack_tokens.json`
6. Your browser session is saved to `~/.status-report/playwright-state.json` (used by the Playwright MCP fallback)

Add the printed tokens to `.env`:

```env
SLACK_MCP_XOXC_TOKEN=xoxc-...
SLACK_MCP_XOXD_TOKEN=xoxd-...
```

---

#### Option B — Manual (DevTools)

If you prefer not to run the script:

1. Open [app.slack.com](https://app.slack.com) in your browser and log in
2. Open DevTools (F12 or Cmd+Option+I)

**Get `SLACK_MCP_XOXC_TOKEN`:**

3. Go to the **Console** tab
4. If prompted, type `allow pasting` and press Enter
5. Paste and run:
   ```js
   JSON.parse(localStorage.localConfig_v2).teams[document.location.pathname.match(/\/client\/([A-Z0-9]+)/)[1]].token
   ```
6. Copy the value starting with `xoxc-`

**Get `SLACK_MCP_XOXD_TOKEN`:**

7. Go to the **Application** tab → **Cookies** → `https://app.slack.com`
8. Find the cookie named `d`
9. Double-click its value and copy it

Add both to `.env`:
```env
SLACK_MCP_XOXC_TOKEN=xoxc-...
SLACK_MCP_XOXD_TOKEN=xoxd-...
```

---

#### When to refresh

These tokens are your Slack browser session — they expire when Slack logs you out (typically after weeks of inactivity or when you explicitly sign out). Signs your tokens have expired:

- The agent reports a Slack authentication error
- Claude falls back to the Playwright MCP for Slack

To refresh, run the automated script again (`--extract`) or repeat the manual steps.

---

#### Playwright MCP fallback for Slack

If the primary Slack MCP fails (expired tokens, connection error), the Playwright MCP server automatically takes over, navigating `slack.com` in a browser as a logged-in user. It uses the session saved at `~/.status-report/playwright-state.json`.

To set up the Playwright fallback without extracting tokens (e.g., if you only want the browser fallback):

```bash
uv run python -m status_report.auth.slack --login
```

This opens Slack in a browser, waits for login, saves the session, and exits. **Note**: The Playwright fallback also requires an active Slack session — it will not work if `playwright-state.json` is missing or expired. Re-run `--login` (or `--extract`) to refresh it.

---

### Google Calendar, Drive, and Gmail

**MCP Server**: `@anthropic/google-workspace-mcp`

All three Google sources share a single OAuth 2.0 client. You set it up once and run the consent flow once.

**What Claude can do**:
- **Calendar**: List and read events (title, time, attendee count — no notes or descriptions)
- **Drive**: Search files, read file metadata
- **Gmail**: Search messages, read message metadata (subject, sender, recipients, timestamp). **Email body content is scrubbed by the executor before reaching Claude** — this is permanent with no opt-in.

**Credentials needed**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_PROJECT_ID`

Create OAuth credentials at the [Google Cloud Console](https://console.cloud.google.com/apis/credentials). Then run the one-time consent flow:

```bash
uv run python -m status_report.auth.google --consent
```

---

### Browser Fallback

**MCP Server**: `@playwright/mcp`

The Playwright browser MCP server is always available as a fallback. It provides browser navigation, screenshots, and interaction tools. Claude can use it when a native MCP server is unconfigured or unavailable.

---

## Multi-User Setup

Multiple users can share the same machine. Run history is scoped per `--user` value.

```bash
# Alice generates her report
python -m status_report.main --user alice@example.com

# Bob generates his report independently — uses his own run history
python -m status_report.main --user bob@example.com
```

---

## Docker Usage

The Docker image is stateless and includes Python, Node.js, all MCP server packages, and Playwright with Chromium.

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

---

## Adding New Data Sources

To add a new data source, you only need to add an MCP server configuration — no changes to the agent loop, registry, executor, or output logic.

In `src/status_report/mcp/config.py`, add a new entry in `build_mcp_configs()`:

```python
# MyService
myservice_token = _env_or_none("MYSERVICE_TOKEN", env)
if myservice_token:
    configs.append(
        MCPServerConfig(
            name="myservice",
            command="npx",
            args=["-y", "@myorg/mcp-myservice"],
            env={"MYSERVICE_TOKEN": myservice_token},
            read_only_tools=[
                "myservice_search",
                "myservice_get_item",
            ],
            source_label="myservice",
        )
    )
```

Then add `MYSERVICE_TOKEN` to `.env.example` and the allowlist will automatically filter the tools.

---

## Audit Logging

### Audit Log (RunTrace v2.0)

Every run appends to `~/.status-report/runs.log` (JSONL):

```json
{
  "schema_version": "2.0",
  "timestamp": "2026-03-01T09:31:00.000000Z",
  "user": "alice@example.com",
  "period": "since last run at 2026-02-28T09:30:00Z",
  "format": "text",
  "sources_attempted": ["github", "jira"],
  "counts": {},
  "outcome": "success",
  "skipped": [],
  "retries": {},
  "duration_seconds": 12.847,
  "agent_turns": 5,
  "tool_calls_count": 14,
  "total_tokens": 8500,
  "mcp_servers_started": ["github", "jira"]
}
```

### Structured Logs

Application logs use `structlog` and go to stderr. To increase verbosity:

```bash
LOG_LEVEL=DEBUG python -m status_report.main --user alice@example.com
```

---

## Troubleshooting

### Claude / Vertex AI errors

**`VERTEX_PROJECT_ID` missing**
Set `VERTEX_PROJECT_ID` in `.env` to your GCP project ID.

**`google.auth.exceptions.DefaultCredentialsError`**
Run `gcloud auth application-default login` to create local credentials.

**`403 Permission denied` on Vertex AI**
Your account does not have the `roles/aiplatform.user` role, or Claude model access has not been enabled in Model Garden.

### "No MCP servers can be configured"

Exit code 2. At least one data source credential must be set.

**Fix**: Confirm at least one of these is in `.env`:
- `GITHUB_TOKEN`
- `JIRA_API_TOKEN` (+ `JIRA_USER_EMAIL` + `JIRA_BASE_URL`)
- `SLACK_BOT_TOKEN`
- `GOOGLE_CLIENT_ID` (+ `GOOGLE_CLIENT_SECRET`)

### "All MCP servers failed to start"

Exit code 2. The MCP server subprocesses could not start.

**Fix**: Ensure Node.js 20+ is installed and npx is available. Run `npx -y @modelcontextprotocol/server-github` manually to test.

### Google authentication fails

Re-run the OAuth consent flow:

```bash
uv run python -m status_report.auth.google --consent
```

### Report has no sections / empty output

Exit code 2. Claude couldn't find activity or all tools returned errors.

- Check `~/.status-report/runs.log` for the last run's `tool_calls_count` and `skipped` fields.
- Run with `LOG_LEVEL=DEBUG` to see tool call details in stderr.

---

## Security & Privacy

### What the Agent Never Does

- Writes, modifies, or deletes data in any external system (3-layer read-only defense)
- Sends raw API tokens or credentials to Claude (MCP credential isolation)
- Passes email body content to Claude (executor scrubbing, permanent, no opt-in)
- Stores any data outside `~/.status-report/` and your `.env` file

### Read-Only Safety

| Layer | Mechanism |
|-------|-----------|
| MCP server config | Read-only flags where supported |
| Tool allowlist | Registry filters out write tools before exposing to Claude |
| Runtime validation | Executor validates every tool call before dispatch |

### File Permissions

| File | Permissions | Contents |
|------|-------------|----------|
| `.env` | `600` (set manually) | API tokens and OAuth credentials |
| `~/.status-report/google_credentials.json` | `600` (set automatically) | Google OAuth refresh token |
| `~/.status-report/run_history.log` | Default | Run timestamps and outcomes (no credentials) |
| `~/.status-report/runs.log` | Default | Audit log (no credentials) |

### What Claude Receives

Claude receives MCP tool results — structured data from workplace APIs. The executor ensures:

- Credentials never appear in tool results (they're env vars for the MCP server subprocess)
- Gmail email body content is scrubbed before reaching Claude
- Only allowlisted read-only tools are callable
- RunTrace audit entries are validated against a credential sentinel before writing
