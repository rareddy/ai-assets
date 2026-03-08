# Status Report Agent

A Claude Code skill that generates daily or periodic status reports of your **own contributions** by autonomously investigating your workplace systems — Jira, GitHub, Slack, Google Calendar, Google Drive, and Gmail — via MCP (Model Context Protocol) servers. Claude calls MCP tools to search each source, drills into significant items for full context, and writes a rich, detailed report of what you actually did.

---

## Quick Start

1. **Copy and fill in credentials**:

   ```bash
   cp .env.example .env
   # Edit .env with your credentials (see Configuration below)
   ```

2. **Source credentials before opening Claude Code**:

   ```bash
   source .env
   ```

3. **Open Claude Code** in this directory — MCP servers connect automatically.
   Verify with `/mcp` to see which servers are connected.

4. **Run the skill**:

   ```
   /status-report --user you@example.com --period yesterday
   ```

---

## MCP Servers

Each data source is accessed via an MCP server configured in `.mcp.json`. Claude Code starts them automatically when you open the project.

| Source | MCP Server | What it needs |
|--------|-----------|---------------|
| GitHub | `ghcr.io/github/github-mcp-server` (Docker) | `GITHUB_TOKEN` |
| Jira | `@sooperset/mcp-atlassian` (npx) | `JIRA_BASE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` |
| Slack | `ghcr.io/korotovsky/slack-mcp-server` (Docker) | `SLACK_MCP_XOXC_TOKEN`, `SLACK_MCP_XOXD_TOKEN` |
| Google Workspace | `workspace-mcp` (uvx) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |

**Slack tokens** are browser session tokens — no app registration or workspace admin approval required. Open Slack in a browser, open DevTools, and extract:
- `SLACK_MCP_XOXC_TOKEN` — from `localStorage` (key: `localConfig_v2`, token starting with `xoxc-`)
- `SLACK_MCP_XOXD_TOKEN` — from Application → Cookies → `d` (value starting with `xoxd-`)

Re-extract when your Slack session expires.

**Google OAuth**: On first use, the Google Workspace MCP will prompt you to complete an OAuth consent flow. Tokens are stored at `~/.config/workspace-mcp/` and reused on subsequent runs.

**GitHub and Slack** require Docker running on the host.

---

## Configuration

All credentials go in `.env` (git-ignored — never commit it). Copy `.env.example` as a starting point.

| Variable | Source | Description |
|----------|--------|-------------|
| `GITHUB_TOKEN` | GitHub | Personal Access Token — scopes: `repo` (read), `read:org` |
| `JIRA_BASE_URL` | Jira | Your Atlassian instance URL, e.g. `https://yourorg.atlassian.net` |
| `JIRA_USER_EMAIL` | Jira | Your Atlassian account email |
| `JIRA_API_TOKEN` | Jira | API token from [id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `SLACK_MCP_XOXC_TOKEN` | Slack | Browser session token (`xoxc-...`) from Slack web app DevTools |
| `SLACK_MCP_XOXD_TOKEN` | Slack | Browser session cookie (`xoxd-...`) from Slack web app DevTools |
| `GOOGLE_CLIENT_ID` | Google | OAuth client ID from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | Google | OAuth client secret from Google Cloud Console |

---

## Period Formats

| Value | Covers |
|-------|--------|
| `today` | 00:00 UTC today → now |
| `yesterday` | Full previous calendar day (UTC) |
| `last-24h` | Rolling 24 hours from now |
| `last-7d` | Rolling 7 days from now |
| `last-30d` | Rolling 30 days from now |
| `YYYY-MM-DD` | Full calendar day (UTC) |
| `YYYY-MM-DD:YYYY-MM-DD` | Inclusive date range |

---

## Examples

```
# Yesterday's report (default period)
/status-report --user you@example.com

# Today so far
/status-report --user you@example.com --period today

# Last week, GitHub and Jira only
/status-report --user you@example.com --period last-7d --sources github,jira

# Custom date range
/status-report --user you@example.com --period 2026-02-24:2026-02-28

# This sprint
/status-report --user you@example.com --period 2026-03-01:2026-03-14 --sources jira,slack
```

---

## Security

- **Read-only**: GitHub MCP runs with `GITHUB_READ_ONLY=1`; Google Workspace MCP runs with `--read-only`. No write tools are invoked.
- **Credential isolation**: Credentials are passed as environment variables directly to MCP server processes. They never appear in Claude's tool arguments or results.
- **Gmail privacy**: Claude reports only subject lines and action types for email — never body content.
- **`.env` is git-ignored** — never commit it.
