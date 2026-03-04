# Feature Specification: Status Report Agent (MCP Agentic Architecture)

**Feature Branch**: `001-status-report-agent`
**Created**: 2026-02-27
**Updated**: 2026-03-01
**Status**: Active
**Architecture**: MCP-based agentic sub-agent system

## Overview

An agentic system where Claude autonomously investigates workplace activity via MCP
tools and produces rich, detailed status reports. Python is infrastructure — it starts
MCP servers, enforces safety rails (read-only allowlist, Gmail body scrubbing, turn
limits), and formats output. All intelligence lives in Claude's agent loop.

## User Scenarios & Testing

### User Story 1 - Generate Today's Status Report (Priority: P1)

A professional runs the agent and receives a detailed, insightful summary of their day.
Claude autonomously searches across all connected tools, investigates significant items
(reads PR diffs, ticket descriptions, thread context), and produces a report with
genuine insight — not just a list of titles.

**Acceptance Scenarios**:

1. **Given** a user with at least one configured MCP server, **When** they request a
   report for "today", **Then** they receive a detailed report summarizing their
   activity with context and insight.
2. **Given** a user with multiple configured sources, **When** they request a report,
   **Then** Claude investigates across all available tools and produces a unified report.
3. **Given** a user with no activity on a particular source, **When** they request a
   report, **Then** the report omits that source naturally.

### User Story 2 - Request a Report for a Past Period (Priority: P2)

A professional requests a report for a past date, date range, or "yesterday". The agent
scopes all tool calls to the requested period.

**Acceptance Scenarios**:

1. **Given** a user requests a report for "yesterday", **When** Claude investigates,
   **Then** all tool calls are scoped to the previous calendar day.
2. **Given** an explicit date range, **When** the report is generated, **Then** only
   activity within that range is included.

### User Story 3 - Filter Report to Specific Sources (Priority: P2)

A professional filters the report to specific MCP servers (e.g., only GitHub and Slack).
Only tools from those servers are available to Claude.

**Acceptance Scenarios**:

1. **Given** a user specifies `--sources github,slack`, **When** Claude generates the
   report, **Then** only GitHub and Slack MCP tools are available.
2. **Given** a requested source is not configured, **When** the agent runs, **Then** it
   warns the user and generates the report from remaining sources.

### User Story 4 - Receive Report in a Chosen Format (Priority: P3)

Output in text, Markdown, or JSON format.

### User Story 5 - Graceful Handling of Unavailable Sources (Priority: P1)

If an MCP server fails to start or a tool returns errors, Claude handles it directly —
it decides whether to retry, skip, or try an alternative approach. The report notes
any unavailable sources.

**Acceptance Scenarios**:

1. **Given** one MCP server fails to start, **When** the report is requested, **Then**
   Claude works with the remaining tools and notes the unavailable source.
2. **Given** a tool returns an error, **When** Claude encounters it, **Then** Claude
   decides whether to retry, skip, or try an alternative.
3. **Given** all MCP servers fail to start, **When** the agent runs, **Then** it exits
   with code 2 and a clear error message.

### Edge Cases

- Future date: rejected before agent loop starts (exit code 3).
- No activity: Claude reports no activity found.
- No MCP servers configured: exit code 2 with helpful message.
- Turn limit reached: Claude produces best report with data collected so far.

## Requirements

### Functional Requirements

- **FR-001**: The agent MUST accept a target user identifier and scope all investigation
  to that user's activity.
- **FR-002**: The agent MUST support time period inputs: `today`, `yesterday`, `last-24h`,
  `YYYY-MM-DD`, and `YYYY-MM-DD:YYYY-MM-DD`.
- **FR-003**: The agent MUST run a Claude agent loop using the `tool_use` API — Claude
  decides what to investigate by calling MCP tools, receives results, and iterates until
  it has enough context to write the report.
- **FR-004**: The agent MUST produce reports with rich detail — Claude investigates
  significant items (reads PR diffs, ticket descriptions, thread context), not just
  lists titles.
- **FR-005**: The agent MUST support filtering to a user-specified subset of MCP servers.
- **FR-006**: The agent MUST support output in plain text, Markdown, and JSON formats.
- **FR-007**: If an MCP server fails to start, the agent MUST exclude its tools and
  continue with remaining servers. Claude is informed of unavailable sources.
- **FR-008**: Claude handles tool errors directly — it decides whether to retry, skip,
  or try an alternative approach.
- **FR-009**: All MCP tools exposed to Claude MUST be read-only. Enforced via 3-layer
  defense: MCP server configuration, tool allowlist filtering, runtime validation.
- **FR-010**: No credentials, tokens, or raw tracebacks in the report or user output.
- **FR-010a**: Gmail body content MUST be scrubbed from tool results by the executor
  before reaching Claude. Permanent, no opt-in.
- **FR-011**: MCP servers provide tool access. For Slack, the primary integration uses
  `korotovsky/slack-mcp-server` with browser-extracted session tokens (`xoxc-` + `xoxd-`
  cookie) — no workspace admin approval required. Browser fallback via Playwright MCP
  server (with persisted browser session) when the primary Slack MCP is unavailable or
  tokens are expired. Playwright MCP requires a one-time interactive login to establish
  the session; the session state is persisted to `~/.status-report/playwright-state.json`
  for reuse.
- **FR-012**: Every run MUST produce a RunTrace audit entry capturing: MCP servers
  started, tool calls count, agent turns, total tokens, outcome, skipped sources,
  and duration.
- **FR-013**: The agent MUST validate at startup that at least one MCP server can start.
- **FR-014**: Future dates rejected before agent loop starts.
- **FR-015**: Adding a new data source = adding an MCP server config (command, env vars,
  tool allowlist). No changes to core agent loop or output logic.
- **FR-016**: The agent MUST enforce a configurable turn limit (`max_agent_turns`,
  default 50). When reached, Claude is asked to produce its best report with data
  collected so far.

### Key Entities

- **User**: Individual whose workplace activity is being reported on.
- **ReportPeriod**: Time window for the report.
- **MCPServerConfig**: Configuration for one MCP server (command, args, env vars,
  tool allowlist, source name).
- **Report**: Final output with sections, available in text/Markdown/JSON.
- **RunTrace**: Audit record capturing agent_turns, tool_calls_count, total_tokens,
  mcp_servers_started, outcome, duration.

## Success Criteria

- **SC-001**: Reports contain rich detail — Claude investigates and describes work,
  not just lists titles.
- **SC-002**: When one MCP server is unavailable, the agent delivers a report from
  remaining sources.
- **SC-003**: 100% of runs produce a complete RunTrace audit entry.
- **SC-004**: No write tools exposed to Claude (3-layer defense verified).
- **SC-005**: Gmail body content never reaches Claude (executor scrubbing verified).
- **SC-006**: Agent loop terminates within `max_agent_turns`.
- **SC-007**: Exit codes preserved: 0 (success), 1 (partial), 2 (failure), 3 (bad args).
- **SC-008**: Adding a new data source requires only an MCP server config — no changes
  to agent loop or output logic.
