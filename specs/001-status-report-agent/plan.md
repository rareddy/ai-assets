# Implementation Plan: MCP-Based Agentic Architecture

**Branch**: `001-status-report-agent` | **Date**: 2026-03-01 | **Spec**: [spec.md](spec.md)

## Summary

Rebuild the Status Report Agent as a truly agentic sub-agent system where Claude drives
data collection, investigation, and synthesis via MCP (Model Context Protocol) tools.
Python is minimal infrastructure — it starts MCP servers as subprocesses, enforces
read-only safety via a 3-layer defense (server flags, tool allowlist, runtime validation),
scrubs Gmail body content, and formats output. All intelligence lives in Claude's agent
loop via the `AnthropicVertex` SDK's `tool_use` cycle.

## Architecture

```
Python wrapper → start MCP servers → Claude agent loop:
  ├── Claude decides what to investigate
  ├── Claude calls MCP tools (search, get details, follow threads)
  ├── Claude receives results, decides next action
  ├── Claude drills into significant items for rich detail
  └── Claude produces the final report with full context
```

## MCP Server Stack

| Source | MCP Server | Transport |
|--------|-----------|-----------|
| GitHub | `github/github-mcp-server` (official) | stdio |
| Jira | `sooperset/mcp-atlassian` | stdio |
| Slack (primary) | `korotovsky/slack-mcp-server` | stdio |
| Slack (fallback) | Playwright MCP (browser session) | stdio |
| Google Workspace | `taylorwilsdon/google_workspace_mcp` | stdio |
| Browser fallback | Playwright MCP server | stdio |

### Slack Authentication (no admin approval required)

The official Slack MCP server requires workspace admin approval and is cloud-hosted
(HTTP transport only) — incompatible with this architecture. Instead:

**Primary**: `korotovsky/slack-mcp-server` with browser session tokens extracted from
the Slack web app (no app registration or admin involvement):
- `SLACK_MCP_XOXC_TOKEN`: extracted from `localStorage` in browser DevTools
- `SLACK_MCP_XOXD_TOKEN`: extracted from the `d` cookie in browser DevTools
- Provides full `search.messages` access for finding the user's activity
- Tokens expire on browser logout; must be re-extracted periodically

**Fallback**: Playwright MCP server navigates `slack.com` as a logged-in user.
- Requires a one-time interactive login: `python -m status_report.auth.slack --login`
- Session state persisted to `~/.status-report/playwright-state.json`
- Reused on subsequent runs; requires re-login when Slack session expires

## Constitution Check (v4.0.0)

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Read-Only Data Access | ✅ PASS | 3-layer defense: MCP server flags, tool allowlist, runtime validation |
| II. Async-First MCP Lifecycle | ✅ PASS | MCP servers managed via async context managers; agent loop fully async |
| III. Agent-Orchestrated via MCP | ✅ PASS | Claude IS the agent; Python is infrastructure |
| IV. Structured Observability | ✅ PASS | structlog + RunTrace JSONL with agent_turns, tool_calls_count, total_tokens |
| V. Secrets & Credential Hygiene | ✅ PASS | Env vars passed to MCP subprocesses; never in Claude's context |
| VI. Test-First with Mocked MCP | ✅ PASS | Mock MCP sessions + staged Claude tool_use responses |
| VII. Container-First Runtime | ✅ PASS | Dockerfile with Node.js + MCP servers + Playwright |
| VIII. Documentation-as-Code | ✅ PASS | CLAUDE.md, README.md, docs/user-guide.md updated |

## Phases

### Phase 0 — Spec & Constitution Updates
Update constitution.md (v4.0.0), spec.md, CLAUDE.md, plan.md for agentic architecture.

### Phase 0.5 — Remove Old Tests
Delete tests for old skill-based architecture. Keep test_config.py, test_report.py,
test_run_history.py (architecture-independent).

### Phase 1 — MCP Foundation (`src/status_report/mcp/`)
- `config.py`: MCPServerConfig + MCPConfig Pydantic models
- `manager.py`: Start/stop MCP server subprocesses via `stdio_client`
- `registry.py`: Collect + filter tool schemas (read-only allowlist)
- `executor.py`: Route tool_use to correct MCP session, Gmail body scrub, safety

### Phase 2 — Agent Loop (core rewrite)
- `agent.py`: Complete rewrite — Claude agent loop with `tool_use`
- `config.py`: Add `max_agent_turns`
- `main.py`: MCP server lifecycle: start → agent loop → shutdown

### Phase 3 — MCP Server Configs
Define server commands, env mappings, and read-only tool allowlists for all 5 servers.

### Phase 4 — Audit & Observability
Update RunTrace with `agent_turns`, `tool_calls_count`, `total_tokens`, `mcp_servers_started`.

### Phase 5 — Cleanup
Delete `src/status_report/skills/` and `src/status_report/auth/tokens.py`.

### Phase 6 — Container & Docs
Update pyproject.toml, Dockerfile (add Node.js), .env.example, README.md, user-guide.md.

### Phase 7 — Final Validation
Run all tests, verify constitution compliance, check safety rails.
