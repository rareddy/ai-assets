# Status Report Agent

## Project Overview

A Python-based agent that generates daily/periodic status reports for an individual by
aggregating READ-ONLY activity data from multiple workplace systems. The Python
orchestrator runs all skills concurrently and passes the aggregated results to Claude
once for synthesis. Structured logging via structlog provides observability.

## Tech Stack

- **Language**: Python 3.12+
- **Package Manager**: uv
- **LLM**: Claude via Vertex AI (`anthropic[vertex]` SDK — `AnthropicVertex` client)
- **HTTP Client**: httpx (async)
- **Browser Automation**: Playwright (async, for skill API-fallback paths)
- **Observability**: structlog (JSON in containers, console in TTY)
- **Authentication**: Google ADC for Vertex AI, OAuth 2.0 (Google Suite), API tokens (Jira, GitHub, Slack)
- **Configuration**: Environment variables via `.env` file
- **Runtime**: Docker container (standalone, stateless)

## Architecture

```
status-report/
├── CLAUDE.md
├── Dockerfile                    # container build; includes Playwright browsers
├── pyproject.toml
├── .env                          # secrets — NEVER commit
├── .env.example                  # placeholder keys for all required env vars
├── src/
│   └── status_report/
│       ├── __init__.py
│       ├── main.py               # CLI entrypoint
│       ├── agent.py              # orchestrator: runs skills concurrently, calls Claude once
│       ├── config.py             # settings and env var loading
│       ├── tracing.py            # structlog configuration
│       ├── report.py             # report formatting and output
│       ├── skills/               # one skill per data source
│       │   ├── __init__.py
│       │   ├── base.py           # ActivitySkill ABC + ActivityItem model
│       │   ├── jira.py           # Jira skill (REST API → Playwright fallback)
│       │   ├── slack.py          # Slack skill (Web API → Playwright fallback)
│       │   ├── github.py         # GitHub skill (REST/GraphQL → Playwright fallback)
│       │   ├── calendar.py       # Google Calendar skill (API → Playwright fallback)
│       │   ├── gdrive.py         # Google Drive skill (API → Playwright fallback)
│       │   └── gmail.py          # Gmail skill (API → Playwright fallback)
│       └── auth/
│           ├── __init__.py
│           ├── google.py         # Google OAuth 2.0 flow + token refresh
│           └── tokens.py         # API token management for Jira/GitHub/Slack
└── tests/
    ├── __init__.py
    ├── conftest.py               # shared fixtures: mock clients, sample ActivityItems, date ranges
    ├── test_agent.py             # orchestrator tests: concurrent dispatch, partial failure, aggregation
    └── skills/
        ├── test_jira.py
        ├── test_slack.py
        ├── test_github.py
        ├── test_calendar.py
        ├── test_gdrive.py
        └── test_gmail.py
```

## Skill Model

Each data source is a **skill** — a Python module implementing the `ActivitySkill`
abstract base class. Skills are the only place platform-specific logic lives.

```python
class ActivitySkill(ABC):
    @abstractmethod
    async def fetch_activity(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]: ...

    @abstractmethod
    def is_configured(self) -> bool: ...
```

Each skill internally manages its own access method, falling back in priority order:

1. **Official REST or GraphQL API** — preferred; fastest and most structured
2. **Authenticated browser scraping via Playwright** — when the API is unavailable
   or insufficient
3. **Unauthenticated web scraping** — last resort, only where permitted

The fallback decision lives entirely inside the skill. The orchestrator does not know
or care which access method was used.

## Data Sources

### Jira (Atlassian Cloud)
- **Primary**: Jira Cloud REST API v3 — Basic Auth (email + API token)
- **Fallback**: Playwright authenticated browser session
- **Data**: Issues updated/created/transitioned, comments authored, worklogs
- **Scope**: READ ONLY — `read:jira-work`, `read:jira-user`
- **Key endpoint**: `/rest/api/3/search` (JQL: `updatedBy = currentUser()`)

### Slack
- **Primary**: Slack Web API — Bot/User OAuth token
- **Fallback**: Playwright authenticated browser session
- **Data**: Messages sent in channels, threads participated in, reactions given
- **Scope**: READ ONLY — `search:read`, `channels:history`, `channels:read`, `users:read`
- **Key methods**: `search.messages`, `conversations.history`

### GitHub
- **Primary**: GitHub REST API v3 / GraphQL v4 — Personal Access Token
- **Fallback**: Playwright authenticated browser session
- **Data**: PRs opened/reviewed/merged, commits pushed, code review comments
- **Scope**: READ ONLY — `repo:read`, `read:org`
- **Key endpoints**: `/search/issues?q=author:{user}+type:pr`, `/users/{user}/events`

### Google Calendar
- **Primary**: Google Calendar API v3 — OAuth 2.0 with offline refresh tokens
- **Fallback**: Playwright authenticated browser session
- **Data**: Meetings attended, titles, duration, attendee count
- **Scope**: READ ONLY — `https://www.googleapis.com/auth/calendar.readonly`
- **Privacy**: Fetch meeting metadata only (title, time, attendees). Never fetch
  meeting notes, recordings, or attachments unless explicitly opt-in configured.

### Google Drive
- **Primary**: Google Drive API v3 — OAuth 2.0 (same credentials as Calendar)
- **Fallback**: Playwright authenticated browser session
- **Data**: Documents created, modified, viewed (via Drive Activity API)
- **Scope**: READ ONLY — `drive.metadata.readonly`, `drive.activity.readonly`

### Gmail
- **Primary**: Gmail API v1 — OAuth 2.0 (same credentials as Calendar and Drive)
- **Fallback**: Playwright authenticated browser session
- **Data**: Emails sent, email threads replied to, key received emails acted on
- **Scope**: READ ONLY — `https://www.googleapis.com/auth/gmail.readonly`
- **Privacy**: Fetch subject, sender, recipients, timestamp, and action type
  (sent / replied / key action) only. Email body content MUST NEVER be fetched,
  stored, or passed to Claude — permanently excluded with no opt-in path.

## Authentication Strategy

Credentials are resolved at skill initialization time and passed as opaque,
already-authenticated client objects into skill execution. Raw secrets never travel
past the `auth/` layer.

| Service | Method | Storage |
|---------|--------|---------|
| Vertex AI (Claude) | Google Application Default Credentials (ADC) | `gcloud auth application-default login` or service account |
| Jira, GitHub, Slack | API token / PAT | `.env` → environment variable |
| Google Calendar, Drive, Gmail | OAuth 2.0 refresh token | `~/.status-report/google_credentials.json` |

Google OAuth requires a one-time browser-based consent flow on first run; tokens
refresh automatically thereafter. The token file is mounted into the container via
a read-only volume — never baked into the image.

## Processing Flow

```
1. Load config → call is_configured() on each skill
2. asyncio.gather(*[skill.fetch_activity(...) for skill in enabled_skills])
        │
        ├── JiraSkill:     REST API  ──(fallback)──► Playwright
        ├── SlackSkill:    Web API   ──(fallback)──► Playwright
        ├── GitHubSkill:   REST API  ──(fallback)──► Playwright
        ├── CalendarSkill: OAuth API ──(fallback)──► Playwright
        ├── GDriveSkill:   OAuth API ──(fallback)──► Playwright
        └── GmailSkill:    OAuth API ──(fallback)──► Playwright
3. Aggregate list[ActivityItem] from all skills into a single structured payload
4. Call Claude once (AnthropicVertex SDK) with the aggregated payload for synthesis
5. Claude produces the formatted report:
   - Summary of key accomplishments
   - Tickets/issues worked on with status changes
   - Code contributions (PRs, reviews)
   - Meetings and collaboration
   - Documents produced or consumed
   - Email activity (sent, replied to, key threads)
   - Suggested follow-ups or open items
6. Output the formatted report
```

## Claude's Role

Claude is invoked **exactly once per report run**, strictly for synthesis and
summarization. Claude receives structured `ActivityItem` data and produces the
final report. Claude does not decide which skills to run, which endpoints to call,
or which access method to use — all of that is deterministic Python.

## Agent CLI

```bash
python -m status_report.main \
  --user alice@example.com \
  --period today \
  --sources jira,github,slack \   # optional; default: all configured
  --format markdown               # text | markdown | json
```

## Code Conventions

- `async/await` for all I/O — `httpx.AsyncClient` for HTTP, Playwright async API
  for browser automation
- Type hints on all function signatures
- Pydantic models for `ActivityItem`, configuration, and API response schemas
- Each skill implements `ActivitySkill` (see Skill Model above)
- `structlog` for application logging
- Tests: `pytest` + `pytest-asyncio`; mock all HTTP with `respx`, mock Playwright,
  mock Anthropic SDK; no live API calls in the test suite

## Container

The agent runs as a standalone container. The image includes Python dependencies,
Playwright, and Chromium for skill browser-fallback paths.

```bash
# Build
docker build -t status-report .

# Run
docker run --rm \
  --env-file .env \
  -v ~/.status-report:/root/.status-report:ro \
  status-report --user alice@example.com --period today
```

The container runs as a non-root user. All credentials are injected via environment
variables or the read-only volume mount — nothing is baked into the image.

## Environment Variables

```
# Vertex AI (Claude) — authentication via Google ADC, no API key needed
VERTEX_PROJECT_ID=your-gcp-project-id
VERTEX_REGION=us-east5
CLAUDE_MODEL=claude-sonnet-4-6

# Jira
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_USER_EMAIL=
JIRA_API_TOKEN=

# Slack
SLACK_BOT_TOKEN=xoxb-...

# GitHub
GITHUB_TOKEN=ghp_...

# Google (OAuth client credentials for the consent flow)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_PROJECT_ID=
```

## Security Rules

- **READ ONLY**: No skill may issue any write operation. All HTTP calls MUST be GET
  or read-equivalent. Enforced at OAuth scope level AND code level (`skills/` and
  `auth/`).
- **No secrets in code**: All credentials from environment variables or
  `~/.status-report/`. Never hardcode.
- **No secrets in logs**: Structured log output must never include raw tokens, passwords,
  or OAuth credentials.
- **Minimal scopes**: Request the absolute minimum read-only permissions per platform.
- **`.env` in `.gitignore`**: Always.
- **Secret scanning**: CI includes a secrets scanner on every PR.

## Error Handling

- If a skill's credentials are missing (`is_configured()` returns `False`), skip that
  skill, log a warning via `structlog`, and include a note in the report
- If a skill's primary API path fails, it falls back to Playwright automatically;
  fallback usage is logged at `warning` level
- If all access methods are exhausted, the skill returns a structured error; the
  orchestrator includes a note in the report and continues
- Surface rate-limit errors with retry-after guidance; never swallow silently
- Never forward raw exception tracebacks to Claude

## Future Considerations (do not implement now)

- Scheduled runs via cron or cloud scheduler
- Team-level aggregate reports
- Slack bot interface for requesting reports
- Email delivery of reports
- Confluence/Notion as additional sources

## Active Technologies
- Python 3.12+ + anthropic[vertex], httpx, playwright, tenacity, filelock, structlog, pydantic
- Claude via Vertex AI (`AnthropicVertex` client, Google ADC authentication)
- `~/.status-report/google_credentials.json` (Google OAuth tokens for Calendar/Drive/Gmail)
- JSONL file at `~/.status-report/run_history.log` + `.lock` sidecar

## Recent Changes
- Migrated from Anthropic API + LangFuse to Vertex AI (AnthropicVertex client, ADC auth, removed langfuse dependency)
