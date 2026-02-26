# Status Report Agent

## Project Overview

A Python-based agent that generates daily/periodic status reports for an individual by aggregating READ-ONLY activity data from multiple workplace systems. The agent uses Claude as the LLM backbone and LangFuse for observability and tracing.

## Tech Stack

- **Language**: Python 3.12+
- **Package Manager**: uv
- **LLM**: Claude (Anthropic SDK)
- **Observability**: LangFuse (tracing, prompt management, evaluation)
- **Authentication**: OAuth 2.0 (Google Suite), API tokens (Jira, GitHub, Slack)
- **Configuration**: Environment variables via `.env` file

## Architecture

```
status-report/
├── claude.md
├── pyproject.toml
├── .env                     # secrets - NEVER commit
├── .env.example             # template with placeholder keys
├── src/
│   └── status_report/
│       ├── __init__.py
│       ├── main.py          # CLI entrypoint
│       ├── agent.py         # core agent orchestration with Claude
│       ├── config.py        # settings and env var loading
│       ├── tracing.py       # LangFuse instrumentation setup
│       ├── report.py        # report formatting and output
│       ├── sources/         # one module per data source
│       │   ├── __init__.py
│       │   ├── base.py      # abstract base class for sources
│       │   ├── jira.py      # Jira Cloud REST API
│       │   ├── slack.py     # Slack Web API
│       │   ├── github.py    # GitHub REST API
│       │   ├── calendar.py  # Google Calendar API
│       │   └── gdrive.py    # Google Drive API (docs created/viewed)
│       └── auth/
│           ├── __init__.py
│           ├── google.py    # Google OAuth 2.0 flow + token refresh
│           └── tokens.py    # API token management for Jira/GitHub/Slack
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── sources/
        ├── test_jira.py
        ├── test_slack.py
        ├── test_github.py
        ├── test_calendar.py
        └── test_gdrive.py
```

## Data Sources and Access Methods

### Jira (Atlassian Cloud)
- **API**: Jira Cloud REST API v3
- **Auth**: API token (email + token pair) via Basic Auth header
- **Data pulled**: Issues updated/created/transitioned, comments authored, worklogs
- **Scope**: READ ONLY - `read:jira-work`, `read:jira-user`
- **Key endpoints**: `/rest/api/3/search` (JQL with `updatedBy = currentUser()`)

### Slack
- **API**: Slack Web API
- **Auth**: Bot/User OAuth token
- **Data pulled**: Messages sent in channels, threads participated in, reactions given
- **Scope**: READ ONLY - `search:read`, `channels:history`, `channels:read`, `users:read`
- **Key methods**: `search.messages`, `conversations.history`

### GitHub
- **API**: GitHub REST API v3 / GraphQL v4
- **Auth**: Personal Access Token (classic) or Fine-grained PAT
- **Data pulled**: PRs opened/reviewed/merged, commits pushed, code review comments
- **Scope**: READ ONLY - `repo:read`, `read:org`
- **Key endpoints**: `/search/issues?q=author:{user}+type:pr`, `/users/{user}/events`

### Google Calendar
- **API**: Google Calendar API v3
- **Auth**: OAuth 2.0 with offline refresh tokens
- **Data pulled**: Meetings attended, meeting titles, duration, attendee count
- **Scope**: READ ONLY - `https://www.googleapis.com/auth/calendar.readonly`
- **Privacy**: Only pull meeting metadata (title, time, attendees), never meeting notes or attachments unless explicitly configured

### Google Drive
- **API**: Google Drive API v3
- **Auth**: OAuth 2.0 (same credentials as Calendar)
- **Data pulled**: Documents created, documents modified, documents viewed (via activity API)
- **Scope**: READ ONLY - `https://www.googleapis.com/auth/drive.metadata.readonly`, `https://www.googleapis.com/auth/drive.activity.readonly`

## Authentication Strategy

### Priority Order
1. **API tokens / PATs** for services that support them (Jira, GitHub, Slack) - simplest, stored in `.env`
2. **Google OAuth 2.0** for Google Suite services - requires one-time browser-based consent flow, then tokens are refreshed automatically
3. **Web scraping via browser** as a last resort fallback if API access is unavailable or insufficient for a source

### Token Storage
- API tokens: `.env` file (development), environment variables (production)
- Google OAuth tokens: `~/.status-report/google_credentials.json` (auto-created after first OAuth consent)
- Never log, print, or trace tokens in LangFuse spans

## Agent Behavior

### Input
- `--user`: target user identifier (email or username)
- `--period`: time range (`today`, `yesterday`, `last-24h`, `YYYY-MM-DD`, date range)
- `--sources`: optional filter to specific sources (default: all configured)
- `--format`: output format (`text`, `markdown`, `json`)

### Processing Flow
1. Load configuration and validate auth credentials for each source
2. Initialize LangFuse trace for the session
3. Fetch raw activity data from each source in parallel (asyncio)
4. Pass aggregated raw data to Claude for synthesis
5. Claude generates a structured status report with:
   - Summary of key accomplishments
   - Tickets/issues worked on with status changes
   - Code contributions (PRs, reviews)
   - Meetings and collaboration
   - Documents produced or consumed
   - Suggested follow-ups or open items
6. Output the formatted report

### Claude's Role
Claude is used strictly for **synthesis and summarization**, not for data fetching. All API calls happen in deterministic Python code. Claude receives the structured data and produces a human-readable report. This keeps the agent predictable and auditable via LangFuse.

## LangFuse Integration

- **Tracing**: Every agent run creates a top-level trace; each source fetch and the Claude synthesis step are child spans
- **Prompt management**: Store the report generation system prompt in LangFuse prompt registry for versioning
- **Cost tracking**: Track Claude API token usage per report generation
- **Evaluation**: Log report quality scores if feedback is provided
- Use the `langfuse` Python SDK with the `@observe` decorator for automatic span creation

## Code Conventions

- Use `async/await` for all I/O-bound source fetching (httpx for HTTP calls)
- Type hints on all function signatures
- Pydantic models for configuration and API response schemas
- Each source implements the `ActivitySource` abstract base class with:
  - `async def fetch_activity(self, user: str, start: datetime, end: datetime) -> list[ActivityItem]`
  - `def is_configured(self) -> bool`
- Use `structlog` for application logging (separate from LangFuse tracing)
- Tests use `pytest` with `pytest-asyncio`; mock all external API calls

## Environment Variables

```
# Anthropic
ANTHROPIC_API_KEY=

# LangFuse
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# Jira
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_USER_EMAIL=
JIRA_API_TOKEN=

# Slack
SLACK_BOT_TOKEN=xoxb-...

# GitHub
GITHUB_TOKEN=ghp_...

# Google (OAuth - client credentials for the OAuth flow)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_PROJECT_ID=
```

## Security Rules

- **READ ONLY**: No source integration may write, modify, or delete data. All API scopes must be read-only. Enforce this at the OAuth scope level and at the code level (only GET/search requests).
- **No secrets in code**: All credentials come from environment variables or secure token storage. Never hardcode.
- **No secrets in traces**: LangFuse spans must never include raw tokens, passwords, or OAuth credentials.
- **Minimal scopes**: Request the absolute minimum OAuth scopes and API permissions needed.
- **`.env` in `.gitignore`**: Always.

## Error Handling

- If a source's credentials are missing or invalid, skip that source and include a note in the report rather than failing the entire run
- Surface API rate-limit errors clearly with retry-after guidance
- Log all errors to structlog; do not send raw error tracebacks to Claude for summarization

## Future Considerations (do not implement now)

- Scheduled runs via cron or cloud scheduler
- Team-level aggregate reports
- Slack bot interface for requesting reports
- Email delivery of reports
- Confluence/Notion as additional sources
