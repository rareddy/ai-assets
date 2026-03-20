---
description: Generate a status report for your contributions from connected workplace tools
argument-hint: --user <email> [--period yesterday|today|last-7d] [--sources github,jira,slack,google]
---

<!--
=============================================================================
SETUP — one-time configuration to use this skill
=============================================================================

PREREQUISITES
  - Docker (GitHub + Slack MCP servers)
  - Node.js / npx (Jira MCP server)
  - Python uv / uvx (Google Workspace MCP server)

─────────────────────────────────────────────────────────────────────────────
STEP 1 — Add credentials to ~/.claude/settings.json
─────────────────────────────────────────────────────────────────────────────
Claude Code loads this at startup and substitutes ${VAR} references in .mcp.json.
Merge the "env" block into your existing settings.json if you already have one.

{
  "env": {
    "GITHUB_TOKEN": "ghp_...",
    "JIRA_BASE_URL": "https://yourorg.atlassian.net",
    "JIRA_USER_EMAIL": "you@example.com",
    "JIRA_API_TOKEN": "...",
    "SLACK_MCP_XOXC_TOKEN": "xoxc-...",
    "SLACK_MCP_XOXD_TOKEN": "xoxd-...",
    "GOOGLE_CLIENT_ID": "...",
    "GOOGLE_CLIENT_SECRET": "..."
  }
}

  GitHub token scopes: repo (read), read:org
  Jira API token: https://id.atlassian.com/manage-profile/security/api-tokens
  Slack tokens (no admin approval — browser session tokens, re-extract when session expires):
    SLACK_MCP_XOXC_TOKEN → Slack web app DevTools → localStorage key "localConfig_v2" (xoxc-...)
    SLACK_MCP_XOXD_TOKEN → Slack web app DevTools → Application → Cookies → "d" (xoxd-...)
  Google OAuth: create an OAuth 2.0 Desktop client in Google Cloud Console.
    On first run the MCP server opens a browser for consent; tokens cached at
    ~/.config/workspace-mcp/ and reused automatically.

─────────────────────────────────────────────────────────────────────────────
STEP 2 — Create .mcp.json in your project root (or ~/.claude/.mcp.json globally)
─────────────────────────────────────────────────────────────────────────────

{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
        "-e", "GITHUB_READ_ONLY",
        "ghcr.io/github/github-mcp-server"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}",
        "GITHUB_READ_ONLY": "1"
      }
    },
    "jira": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@sooperset/mcp-atlassian"],
      "env": {
        "JIRA_URL": "${JIRA_BASE_URL}",
        "JIRA_USERNAME": "${JIRA_USER_EMAIL}",
        "JIRA_API_TOKEN": "${JIRA_API_TOKEN}"
      }
    },
    "slack": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "SLACK_MCP_XOXC_TOKEN",
        "-e", "SLACK_MCP_XOXD_TOKEN",
        "ghcr.io/korotovsky/slack-mcp-server:latest"
      ],
      "env": {
        "SLACK_MCP_XOXC_TOKEN": "${SLACK_MCP_XOXC_TOKEN}",
        "SLACK_MCP_XOXD_TOKEN": "${SLACK_MCP_XOXD_TOKEN}"
      }
    },
    "google": {
      "type": "stdio",
      "command": "uvx",
      "args": ["workspace-mcp", "--read-only"],
      "env": {
        "GOOGLE_OAUTH_CLIENT_ID": "${GOOGLE_CLIENT_ID}",
        "GOOGLE_OAUTH_CLIENT_SECRET": "${GOOGLE_CLIENT_SECRET}"
      }
    }
  }
}

─────────────────────────────────────────────────────────────────────────────
STEP 3 — Place this file at ~/.claude/commands/status-report.md
─────────────────────────────────────────────────────────────────────────────
That makes /status-report available globally in every Claude Code project.
Alternatively place it at <project>/.claude/commands/status-report.md for
project-local use only.

─────────────────────────────────────────────────────────────────────────────
USAGE
─────────────────────────────────────────────────────────────────────────────
/status-report --user you@example.com
/status-report --user you@example.com --period today
/status-report --user you@example.com --period last-7d --sources github,jira
/status-report --user you@example.com --period 2026-03-01:2026-03-14
=============================================================================
-->

Generate a status report for my own contributions.

Arguments: $ARGUMENTS

## Argument Parsing

Parse the following from the arguments above:
- `--user <email>` — required; the GitHub/workplace identity to investigate
- `--period <value>` — default: `yesterday`; options: `today`, `yesterday`, `last-24h`, `last-7d`, `last-30d`, `YYYY-MM-DD`, `YYYY-MM-DD:YYYY-MM-DD`
- `--sources <list>` — default: all connected MCP servers; options: `github`, `jira`, `slack`, `google`

Resolve the period to exact UTC start and end timestamps before calling any tools. Use today's date to calculate relative periods.

---

## What to Report (contributions only)

Focus EXCLUSIVELY on things the user did themselves:

- **GitHub**: PRs they OPENED (`author:USER`), commits they PUSHED (`committer:USER`),
  issues they FILED (`author:USER`), code review comments they WROTE (`commenter:USER`),
  and issue comments they POSTED.
  **DO NOT** report PRs where they are only a requested reviewer, assignee, or mention.
  Review queues (`review-requested:USER`, `involves:USER`) are NOT their contributions.

- **Jira**: Tickets they CREATED, tickets they moved to a new status, comments they added.

- **Slack**: Messages they SENT in channels or threads.

- **Google Calendar**: Meetings they ATTENDED or ORGANIZED.

- **Google Drive / Docs**: Documents they CREATED or EDITED.

- **Gmail**: Emails they SENT or REPLIED to (subject and action type only — do NOT include email body content).

---

## Your Process

1. **Identify the GitHub user first**: If GitHub tools are available, call `get_me`
   as your very first tool call. This returns the authenticated GitHub login (e.g.
   `rareddy`) — use it for every subsequent filter and search. Do NOT guess the
   username from the email address.

2. **Discover personal repos**: Call `search_repositories` with `user:LOGIN` to find
   the user's personal repositories. Then call `list_commits`, `list_pull_requests`,
   and `list_issues` on each repo scoped to the period.
   **Check personal repos before any organisation repos.**

3. **Search authored activity broadly**: After personal repos, search with
   `author:LOGIN`, `committer:LOGIN`, `commenter:LOGIN` filters across all accessible
   repos. Do NOT use `involves:LOGIN` or `review-requested:LOGIN`.

4. **Investigate**: For each authored PR, commit, or issue found — drill deeper. Read
   the PR diff and description (`get_pull_request_diff`, `get_pull_request`), the
   commit message, the issue body and comments. Understand WHAT changed and WHY.

5. **Report**: Write rich, detailed descriptions of each contribution. Include: what was
   changed, why it was important, the outcome (merged/open/closed), and key context.

---

## Report Sections (include only sections with data)

1. **Key Accomplishments** — Most impactful work completed in the period
2. **Code Contributions** — PRs opened/merged by the user, commits pushed, with diffs and context
3. **Issues Filed** — New bugs reported or features proposed by the user
4. **Discussion & Reviews** — Substantive comments or reviews the user wrote on others' PRs/issues
5. **Meetings & Collaboration** — Meetings the user attended or organized
6. **Documents** — Docs the user created or significantly edited
7. **Messages & Threads** — Key Slack messages or email threads the user drove
8. **Suggested Follow-ups** — Open PRs awaiting merge, pending decisions, upcoming deadlines

---

## Rules

- **All sources use the same date range.** Every tool call — regardless of source —
  must be filtered to the resolved period start and end dates. Never include items
  from outside this window.
- Write in first person ("I opened PR #42 to fix...", "I pushed a commit that...")
- Be SPECIFIC and DETAILED — describe what the code change does, what the issue addresses,
  what was decided in the meeting. Not just titles.
- Do NOT list items the user did not author (review requests, assignments, mentions)
- Do NOT invent information not present in tool results
- Do NOT include raw credentials, tokens, or email body content
- Omit any section that has no data
- When you have enough information to write a comprehensive report, stop calling tools
  and write the report directly
