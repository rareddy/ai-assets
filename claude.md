# Status Report Agent

## Project Overview

A Claude Code skill that generates daily/periodic status reports for an individual by
autonomously investigating workplace systems via MCP (Model Context Protocol) tools.
Claude drives data collection, investigates significant items in depth, and synthesizes
rich reports. The project is Claude Code + MCP configuration — no separate Python
runtime, no Docker container.

## Tech Stack

- **Interface**: Claude Code (`/status-report` custom command)
- **MCP**: Model Context Protocol servers for data source access (stdio transport)
- **Configuration**: `.mcp.json` (server definitions), `.env` (credentials)
- **Skill**: `.claude/commands/status-report.md`

## Architecture

```
status-report/
├── claude.md                         # project instructions (this file)
├── .mcp.json                         # MCP server definitions
├── .env                              # secrets — NEVER commit
├── .env.example                      # placeholder keys for all credential vars
└── .claude/
    └── commands/
        └── status-report.md          # /status-report skill definition
```

## MCP Model

Each data source is accessed via an **MCP server** — an external process that exposes
tools over the stdio transport. Claude Code starts MCP servers automatically when the
project is opened, and Claude can call their tools directly.

### MCP Servers

| Source | MCP Server | Transport |
|--------|-----------|-----------|
| GitHub | `ghcr.io/github/github-mcp-server` (Docker) | stdio |
| Jira | `@sooperset/mcp-atlassian` (npx) | stdio |
| Slack | `ghcr.io/korotovsky/slack-mcp-server` (Docker) | stdio |
| Google Workspace | `workspace-mcp` (uvx) | stdio |

### Slack — No Admin Approval Required

The official Slack MCP is cloud-hosted and requires workspace admin approval. Instead,
`korotovsky/slack-mcp-server` runs locally via stdio using browser session tokens:
- `SLACK_MCP_XOXC_TOKEN`: from Slack web app DevTools → localStorage
- `SLACK_MCP_XOXD_TOKEN`: from Slack web app DevTools → Application → Cookies → `d`
- Full `search.messages` access. Re-extract when tokens expire.

### Read-Only Safety

- **GitHub**: `GITHUB_READ_ONLY=1` env var passed to the server
- **Google Workspace**: `--read-only` flag passed to `workspace-mcp`
- **Jira / Slack**: read-only by convention (skill instructs Claude not to write)

## Processing Flow

```
1. User runs /status-report --user <email> [--period <range>] [--sources <list>]
2. Claude parses arguments → resolves period to UTC start/end timestamps
3. Claude calls get_me (GitHub) to resolve the actual login handle
4. Claude searches each source for user-authored contributions in the period:
   ├── GitHub: author:LOGIN, committer:LOGIN, commenter:LOGIN filters
   ├── Jira: tickets created/transitioned/commented by user
   ├── Slack: messages sent by user
   └── Google: calendar events attended/organized, Drive docs created/edited
5. Claude drills into significant items (reads PR diffs, issue bodies, thread context)
6. Claude writes the final report — rich, first-person, contribution-focused
```

## Claude's Role

Claude is the **autonomous agent**. It is NOT a formatter that receives pre-collected
data. Claude IS the brain — it decides what to investigate, calls MCP tools to get
details, and synthesizes a report from real data. The skill definition in
`.claude/commands/status-report.md` provides the investigation strategy and reporting
structure.

## Skill Usage

```
/status-report --user alice@example.com --period yesterday
/status-report --user alice@example.com --period last-7d --sources github,jira
/status-report --user alice@example.com --period 2026-03-01:2026-03-07
```

## Environment Variables

```
# Jira
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_USER_EMAIL=
JIRA_API_TOKEN=

# Slack (browser session tokens — no admin approval needed)
SLACK_MCP_XOXC_TOKEN=xoxc-...
SLACK_MCP_XOXD_TOKEN=xoxd-...

# GitHub
GITHUB_TOKEN=ghp_...

# Google (OAuth client credentials)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

## Security Rules

- **READ ONLY**: MCP server flags (`GITHUB_READ_ONLY=1`, `--read-only`) prevent writes.
  The skill instructs Claude not to call any write tools.
- **No secrets in code**: All credentials from environment variables. Never hardcode.
- **MCP credential isolation**: Credentials passed as env vars to MCP server processes.
  They never flow through Claude's tool arguments or results.
- **Gmail privacy**: Skill instructs Claude to report only subject/action for email —
  never body content.
- **`.env` in `.gitignore`**: Always.
