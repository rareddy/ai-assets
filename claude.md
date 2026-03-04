# Status Report Agent

## Project Overview

A Python-based agentic system that generates daily/periodic status reports for an
individual by using Claude as an autonomous sub-agent with MCP (Model Context Protocol)
tools connected to workplace systems. Claude drives data collection, investigates
significant items in depth, and synthesizes rich reports. Python is minimal
infrastructure: it starts MCP servers, enforces read-only safety, and formats output.

## Tech Stack

- **Language**: Python 3.12+
- **Package Manager**: uv
- **LLM**: Claude via Vertex AI (`anthropic[vertex]` SDK — `AnthropicVertex` client)
- **MCP**: Model Context Protocol servers for data source access (stdio transport)
- **MCP SDK**: `mcp` Python package for stdio client sessions
- **Observability**: structlog (JSON in containers, console in TTY)
- **Authentication**: Google ADC for Vertex AI, env vars passed to MCP servers
- **Configuration**: Environment variables via `.env` file
- **Runtime**: Docker container (standalone, stateless)

## Architecture

```
status-report/
├── CLAUDE.md
├── Dockerfile                    # container build; includes Node.js + MCP servers + Playwright
├── pyproject.toml
├── .env                          # secrets — NEVER commit
├── .env.example                  # placeholder keys for all required env vars
├── src/
│   └── status_report/
│       ├── __init__.py
│       ├── main.py               # CLI entrypoint, MCP server lifecycle
│       ├── agent.py              # Claude agent loop (tool_use cycle)
│       ├── config.py             # settings and env var loading
│       ├── tracing.py            # structlog configuration
│       ├── report.py             # report formatting and output
│       ├── run_log.py            # JSONL audit trail
│       ├── run_history.py        # per-user run history for auto-period
│       ├── mcp/                  # MCP infrastructure
│       │   ├── __init__.py
│       │   ├── config.py         # MCPServerConfig + MCPConfig models + server definitions
│       │   ├── manager.py        # Start/stop MCP server subprocesses
│       │   ├── registry.py       # Collect + filter tool schemas (read-only allowlist)
│       │   └── executor.py       # Route tool_use to MCP sessions, Gmail body scrub, safety
│       └── auth/
│           ├── __init__.py
│           └── google.py         # Google OAuth 2.0 flow + token refresh
└── tests/
    ├── __init__.py
    ├── conftest.py               # MCP session mocks, Claude tool_use factories, config fixtures
    ├── test_agent.py             # agent loop tests with staged Claude responses
    ├── test_config.py            # period parsing tests (preserved)
    ├── test_report.py            # report formatting tests (preserved)
    ├── test_run_log.py           # audit log tests
    ├── test_run_history.py       # run history tests (preserved)
    ├── test_mcp_manager.py       # MCP server lifecycle tests
    ├── test_mcp_registry.py      # tool allowlist filtering tests
    └── test_mcp_executor.py      # tool dispatch + scrubbing tests
```

## MCP Model

Each data source is accessed via an **MCP server** — an external process that exposes
tools over the stdio transport. The agent starts MCP servers as subprocesses,
collects their tool schemas, filters them through a read-only allowlist, and exposes
them to Claude's agent loop.

### MCP Servers

| Source | MCP Server | Transport |
|--------|-----------|-----------|
| GitHub | `github/github-mcp-server` (official) | stdio |
| Jira | `sooperset/mcp-atlassian` | stdio |
| Slack (primary) | `korotovsky/slack-mcp-server` | stdio |
| Slack (fallback) | Playwright MCP (persisted browser session) | stdio |
| Google Workspace | `taylorwilsdon/google_workspace_mcp` | stdio |
| Browser fallback | Playwright MCP server | stdio |

### Slack — No Admin Approval Required

The official Slack MCP is cloud-hosted and requires workspace admin approval. Instead,
`korotovsky/slack-mcp-server` runs locally via stdio using browser session tokens:
- **Primary**: browser tokens (`SLACK_MCP_XOXC_TOKEN`, `SLACK_MCP_XOXD_TOKEN`) extracted
  from Slack web app DevTools. Full `search.messages` access. Re-extract when tokens expire.
- **Fallback**: Playwright MCP navigates `slack.com` as a logged-in user. One-time login:
  `python -m status_report.auth.slack --login`. Session persisted to
  `~/.status-report/playwright-state.json`.

### Read-Only Safety (3-Layer Defense)

1. **MCP server flags**: Servers configured with read-only environment variables
   where supported (e.g., `GITHUB_READ_ONLY=1`)
2. **Tool allowlist filtering**: Registry filters tool schemas — only whitelisted
   read-only tools are exposed to Claude
3. **Runtime validation**: Executor validates every tool call against the allowlist
   before dispatch

## Processing Flow

```
1. Load config → determine which MCP servers have credentials
2. Start MCP server subprocesses (async context managers)
3. Collect tool schemas from all servers → filter through read-only allowlist
4. Launch Claude agent loop:
   ├── Claude receives system prompt + user request (period, sources)
   ├── Claude calls MCP tools (search, get details, follow threads)
   │   ├── Executor validates tool against allowlist
   │   ├── Executor routes to correct MCP session
   │   ├── Gmail results scrubbed (body removed)
   │   └── Tool result returned to Claude
   ├── Claude receives results, decides next action
   ├── Claude drills into significant items for rich detail
   ├── Turn counter incremented; safety limit checked
   └── Claude produces stop_reason="end_turn" with final report
5. Parse Claude's final message → Report with sections
6. Write RunTrace audit log
7. Record run history
8. Output formatted report to stdout
9. Shutdown MCP servers
```

## Claude's Role

Claude is the **autonomous agent**. It is NOT a formatter that receives pre-collected
data. Claude IS the brain — it explores, investigates, and reports. The agent loop
continues until Claude decides it has enough context (stop_reason="end_turn"), or until
the turn limit is reached.

## Agent CLI

```bash
python -m status_report.main \
  --user alice@example.com \
  --period today \
  --sources jira,github,slack \   # optional; default: all configured
  --format markdown               # text | markdown | json
```

## Code Conventions

- `async/await` for all I/O — MCP lifecycle, Claude API calls, tool dispatch
- Type hints on all function signatures
- Pydantic models for configuration, MCP server configs, and RunTrace
- `structlog` for application logging
- Tests: `pytest` + `pytest-asyncio`; mock MCP sessions + Claude tool_use responses;
  no live API calls or MCP servers in tests

## Container

The agent runs as a standalone container. The image includes Python dependencies,
Node.js (for npm-based MCP servers), Playwright + Chromium (for browser-fallback MCP
server), and the agent CLI.

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

# Agent limits
MAX_AGENT_TURNS=50

# Jira
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_USER_EMAIL=
JIRA_API_TOKEN=

# Slack (primary — browser session tokens, no admin approval needed)
# Extract from Slack web app DevTools (see docs/user-guide.md#slack-setup)
SLACK_MCP_XOXC_TOKEN=xoxc-...
SLACK_MCP_XOXD_TOKEN=xoxd-...
# Fallback: Playwright browser session (run: python -m status_report.auth.slack --login)
# Session stored at ~/.status-report/playwright-state.json

# GitHub
GITHUB_TOKEN=ghp_...

# Google (OAuth client credentials for the consent flow)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_PROJECT_ID=
```

## Security Rules

- **READ ONLY**: 3-layer defense — MCP server flags, tool allowlist filtering,
  runtime validation. No write tools exposed to Claude.
- **No secrets in code**: All credentials from environment variables or
  `~/.status-report/`. Never hardcode.
- **No secrets in logs**: Structured log output must never include raw tokens, passwords,
  or OAuth credentials.
- **MCP credential isolation**: Credentials passed as env vars to MCP server
  subprocesses. Never flow through Claude's context.
- **Gmail body scrub**: Executor removes email body content from Gmail tool results
  before they reach Claude. Permanent, no opt-in.
- **`.env` in `.gitignore`**: Always.

## Error Handling

- Claude handles tool errors directly — it decides whether to retry, skip, or try
  an alternative approach
- If an MCP server fails to start, its tools are excluded and Claude is informed
- Turn limit (`max_agent_turns`) prevents runaway loops
- If no MCP servers start successfully, exit with code 2
- Never forward raw exception tracebacks to Claude

## Active Technologies
- Python 3.12+ + anthropic[vertex], mcp, tenacity, filelock, structlog, pydantic
- Claude via Vertex AI (`AnthropicVertex` client, Google ADC authentication)
- MCP servers: `github/github-mcp-server`, `sooperset/mcp-atlassian`,
  `korotovsky/slack-mcp-server`, `taylorwilsdon/google_workspace_mcp`, Playwright MCP
- `~/.status-report/google_credentials.json` (Google OAuth tokens for Google Workspace MCP)
- `~/.status-report/playwright-state.json` (Playwright browser session for Slack fallback)
- JSONL file at `~/.status-report/run_history.log` + `.lock` sidecar

## Recent Changes
- Migrated from Python-orchestrated skill architecture to MCP-based agentic sub-agent system
- Claude is now the autonomous agent (drives data collection via MCP tools)
- Slack: uses `korotovsky/slack-mcp-server` with browser session tokens (no admin approval)
- Slack fallback: Playwright MCP with persisted browser session
- Removed: skills/ directory, httpx direct calls, google-api-python-client
- Added: mcp/ package, MCP server configs, tool allowlist, agent loop
