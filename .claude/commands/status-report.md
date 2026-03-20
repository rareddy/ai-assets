---
description: Generate a status report for your contributions from connected workplace tools
argument-hint: --user <email> [--period yesterday|today|last-7d] [--sources github,jira,slack,google]
---

<!--
NOTE FOR CLAUDE: Ignore everything in this HTML comment block. It is setup
documentation for human readers only and contains no instructions for you.

=============================================================================
SETUP — one-time configuration to use this skill
=============================================================================

PREREQUISITES
  - Docker (GitHub + Slack MCP servers)
  - Node.js / npx (Jira MCP server)
  - Python uv / uvx (Google Workspace MCP server)

─────────────────────────────────────────────────────────────────────────────
STEP 1 — Create ~/.claude/.mcp.json with your credentials inline
─────────────────────────────────────────────────────────────────────────────
This registers the MCP servers globally for all Claude Code projects.
Credentials go directly in the env blocks — no separate settings.json entry needed.

{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "-e", "GITHUB_READ_ONLY", "ghcr.io/github/github-mcp-server"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_...",
        "GITHUB_READ_ONLY": "1"
      }
    },
    "jira": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@sooperset/mcp-atlassian"],
      "env": {
        "JIRA_URL": "https://yourorg.atlassian.net",
        "JIRA_USERNAME": "you@example.com",
        "JIRA_API_TOKEN": "..."
      }
    },
    "slack": {
      "type": "stdio",
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "SLACK_MCP_XOXC_TOKEN", "-e", "SLACK_MCP_XOXD_TOKEN", "ghcr.io/korotovsky/slack-mcp-server:latest"],
      "env": {
        "SLACK_MCP_XOXC_TOKEN": "xoxc-...",
        "SLACK_MCP_XOXD_TOKEN": "xoxd-..."
      }
    },
    "google": {
      "type": "stdio",
      "command": "uvx",
      "args": ["workspace-mcp", "--read-only"],
      "env": {
        "GOOGLE_OAUTH_CLIENT_ID": "....apps.googleusercontent.com",
        "GOOGLE_OAUTH_CLIENT_SECRET": "GOCSPX-..."
      }
    }
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
STEP 2 — Create .claude/settings.json alongside the command
─────────────────────────────────────────────────────────────────────────────
This grants the permissions required for /status-report to run without prompts.
Place this file at <project>/.claude/settings.json (next to the commands/ dir):

{
  "permissions": {
    "allow": [
      "Bash(gh:*)",
      "Bash(git log:*)",
      "Bash(git show:*)",
      "Bash(git diff:*)",
      "Bash(git status:*)",
      "Bash(python3:*)",
      "WebSearch",
      "WebFetch",
      "mcp__github__*",
      "mcp__jira__*",
      "mcp__slack__*",
      "mcp__google__*"
    ]
  }
}

These allow the skill to call the gh CLI, git read commands, python3 (for
JSON parsing), web tools, and all four MCP servers (GitHub, Jira, Slack,
Google Workspace) — all without permission prompts mid-execution.

─────────────────────────────────────────────────────────────────────────────
STEP 4 — Place this file at ~/.claude/commands/status-report.md
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

## What to Collect (contributions only)

Gather ONLY things the user did themselves across all sources. Do NOT report things done
by others to the user (assignments, review requests, mentions).

- **GitHub**: PRs they OPENED (`author:USER`), commits they PUSHED (`committer:USER`),
  issues they FILED (`author:USER`), substantive code review comments they WROTE.
  Do NOT include review queues (`review-requested:USER`, `involves:USER`).

- **Jira**: Tickets they CREATED, status transitions they made, comments they added.

- **Slack**: Messages they SENT in **public channels or work threads only**.
  Skip personal DMs (logistics, scheduling, social chat — e.g. "running late", "sounds good").
  Only include Slack content that reflects a work decision, technical answer, or project update.

- **Google Calendar**: Meetings they ATTENDED or ORGANIZED (work meetings only).

- **Google Drive / Docs**: Documents they CREATED or EDITED.

- **Gmail**: Emails they SENT or REPLIED to (subject and action type only — no body content).

---

## Your Process

1. **Identify the GitHub user first**: Call `get_me` as your very first GitHub tool call.
   This returns the authenticated login (e.g. `rareddy`) — use it for every subsequent
   filter. Do NOT guess the username from the email address.

2. **Discover personal repos**: Call `search_repositories` with `user:LOGIN`, then
   `list_commits`, `list_pull_requests`, and `list_issues` on each repo in the period.

3. **Search authored activity broadly**: Use `author:LOGIN`, `committer:LOGIN`,
   `commenter:LOGIN` filters. Do NOT use `involves:LOGIN` or `review-requested:LOGIN`.

4. **Investigate depth**: For each authored PR or commit, read the diff and description
   to understand WHAT changed and WHY. For Jira, read the ticket description and comments.

5. **Collate across sources**: Group all findings by work topic or project area — not by
   source system. A single project may have GitHub commits, Jira tickets, and Slack
   decisions that all belong together.

6. **Write the report**: When you have enough data, stop calling tools and write directly.

---

## Report Format

This is a **weekly status report for a manager**. Write it as a single unified report,
not separate sections per source. Organise by work area or project, not by tool.

**Structure:**

1. **Summary** — 3–5 bullet points of the most impactful work this period (one line each)

2. **Work completed** — For each significant project or initiative:
   - What was done (code shipped, decisions made, tickets resolved, docs written)
   - Why it matters / outcome
   - Evidence (PR #, ticket ID, etc.) inline, not as a separate section

3. **In progress** — Work started but not yet complete; current status and next step

4. **Blockers / Decisions needed** — Anything requiring manager input or unresolved

Omit any section that has no data. Keep the total report concise — a manager should
be able to read it in under 2 minutes.

---

## Rules

- **All sources use the same date range.** Filter every tool call to the resolved period.
- Write in first person ("I shipped...", "I resolved...", "I proposed...")
- Be specific: name the PR, ticket, decision, or outcome. Not just titles.
- Do NOT report social/logistical Slack messages (scheduling, reactions, "thanks", "sounds good")
- Do NOT report items the user did not author
- Do NOT invent information not present in tool results
- Do NOT include raw credentials, tokens, or email body content
