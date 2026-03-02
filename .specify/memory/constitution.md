<!--
SYNC IMPACT REPORT
==================
Version change: 3.1.0 → 4.0.0 (MAJOR: Principles II, III, VI, VII fundamentally
  redefined for MCP-based agentic architecture — backward-incompatible governance change)
Modified principles:
  - Principle II: "Async-First Skill Execution" → "Async-First MCP Lifecycle"
    (MCP server subprocess management replaces asyncio.gather over skills)
  - Principle III: "Python-Orchestrated Skill Execution + Claude Synthesis" →
    "Agent-Orchestrated Data Collection via MCP" (complete redefinition — MAJOR trigger;
    Claude IS the agent — it decides what to investigate via MCP tools; Python is
    infrastructure only)
  - Principle IV: Retitled "Structured Observability" — LangFuse references removed,
    structlog + RunTrace JSONL is the sole observability surface
  - Principle V: Updated for MCP credential isolation (env vars passed to MCP server
    subprocesses, never to Claude)
  - Principle VI: "Test-First with Mocked Skill I/O" → "Test-First with Mocked MCP
    Sessions" (testing target shifts to mocking MCP tool calls + Claude agent loop)
  - Principle VII: "Container-First Runtime" updated for Node.js + MCP servers
Added sections: none
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md: Constitution Check gate should reference
    MCP tool allowlist and agent loop safety ⚠ pending
Follow-up TODOs:
  - Confirm MCP server npm packages once installed
-->

# Status Report Agent Constitution

## Core Principles

### I. Read-Only Data Access (NON-NEGOTIABLE)

All MCP tools exposed to Claude MUST be strictly read-only. No tool may issue any call
that creates, modifies, or deletes data in any external system.

- MCP servers MUST be configured with read-only flags where available (e.g.,
  `GITHUB_READ_ONLY=1` for github-mcp-server).
- A tool allowlist in the registry MUST filter out any write/mutate tools before
  exposing them to Claude's agent loop.
- Runtime validation in the executor MUST reject tool calls not on the allowlist.
- Read-only enforcement MUST be applied at three layers: MCP server configuration,
  tool allowlist filtering, AND runtime validation before dispatch.
- Any new MCP server added MUST have its read-only tool set explicitly defined and
  reviewed before merging.

**Rationale**: The agent aggregates sensitive workplace data. Write access, even
accidental, could corrupt project management, calendar, or communication systems with
serious professional consequences. Three-layer enforcement ensures no single point of
failure.

### II. Async-First MCP Lifecycle

All I/O-bound operations — MCP server management, Claude API calls, and tool
dispatch — MUST use Python `async/await`. Blocking I/O in the async event loop is
FORBIDDEN.

- MCP server subprocesses MUST be started and stopped via async context managers.
- The Claude agent loop (tool_use → result → next turn) MUST be fully async.
- Tool call dispatch to MCP sessions MUST use the MCP SDK's async `call_tool` method.
- `pytest-asyncio` MUST be used for all tests involving async code.

**Rationale**: The agent manages multiple MCP server subprocesses and runs an
iterative agent loop with Claude. Async lifecycle management ensures responsive
startup/shutdown and non-blocking tool dispatch.

### III. Agent-Orchestrated Data Collection via MCP

Claude MUST be the autonomous agent that drives data collection, investigation, and
synthesis. Python is infrastructure — it starts MCP servers, enforces safety rails,
and formats output. All intelligence lives in Claude's agent loop.

**Agent contract**: Claude operates in a `tool_use` loop via the `AnthropicVertex` SDK:
1. Claude receives a system prompt guiding its sub-agent behavior (discover → investigate
   → report).
2. Claude decides which MCP tools to call based on the user's request and period.
3. Tool results flow back to Claude, which decides the next action.
4. Claude drills into significant items for rich detail (reading PR diffs, ticket
   descriptions, thread context).
5. Claude produces the final report when it has enough context.

**Python's role** is strictly infrastructure. Python MUST:
1. Start MCP server subprocesses and collect their tool schemas.
2. Filter tools through the read-only allowlist.
3. Route Claude's `tool_use` blocks to the correct MCP session.
4. Enforce safety: turn limits, Gmail body scrubbing, tool allowlist validation.
5. Capture the final report text from Claude's last response.

**Claude's role** is autonomous investigation and synthesis. Claude MUST:
- Decide which tools to call and in what order.
- Determine what deserves deeper investigation vs. surface-level mention.
- Handle tool errors by retrying, skipping, or trying alternatives.
- Produce a rich, detailed report — not just a list of titles.

The Anthropic Python SDK (`AnthropicVertex`) MUST be used directly — Claude CLI or any
CLI wrapper MUST NOT be used as the runtime.

**Rationale**: The old architecture produced shallow reports because Claude only saw
pre-collected summaries. By making Claude the agent with direct tool access, it can
investigate, follow threads, read PR diffs, and produce reports with genuine insight.
The quality comes from Claude's judgment, not from Python data pipelines.

### IV. Structured Observability

Every agent run MUST produce a complete audit trail via `structlog` and the `RunTrace`
JSONL log.

- Every agent execution MUST create a `RunTrace` entry in `~/.status-report/runs.log`.
- `RunTrace` MUST capture: timestamp, user, period, MCP servers started, sources
  attempted, tool calls count, agent turns, total tokens, outcome, skipped sources,
  and duration.
- `structlog` MUST log significant events: MCP server start/stop, agent loop turns,
  tool calls dispatched, errors, and report generation.
- Log output MUST NEVER contain raw tokens, passwords, OAuth credentials, or any
  secrets. Log attributes MUST be scrubbed before logging.

**Rationale**: `structlog` plus the JSONL audit log provide complete observability for
debugging agent behavior, tracking tool usage, and monitoring costs.

### V. Secrets & Credential Hygiene (NON-NEGOTIABLE)

Credentials MUST never appear in source code, tool arguments, logs, or version control.

- All credentials (API tokens, OAuth secrets, client IDs) MUST be loaded exclusively
  from environment variables or the designated secure token store
  (`~/.status-report/google_credentials.json` for Google OAuth).
- Credentials MUST be passed to MCP server subprocesses as environment variables at
  launch time. Raw secrets MUST NOT flow through Claude's context, tool arguments,
  or tool results.
- `.env` MUST be listed in `.gitignore`. Committing `.env` is FORBIDDEN.
- `.env.example` MUST be maintained with placeholder values for all required keys.
- `structlog` log statements MUST be audited to confirm no credential leakage before
  any merge.
- Google OAuth tokens MUST be refreshed automatically; expired tokens MUST NOT cause
  hard failures without a clear re-authentication prompt.

**Rationale**: This agent has access to broad workplace data across multiple systems.
A credential leak would expose the user's entire digital work footprint. Non-negotiable
hygiene is the only acceptable posture.

### VI. Test-First with Mocked MCP Sessions

All MCP interactions and Claude API calls MUST be mocked in tests. Tests for new MCP
integrations MUST be written before or alongside the implementation.

- `pytest` with `pytest-asyncio` is the required test framework.
- MCP tool calls MUST be mocked using `unittest.mock` or custom MCP session mocks
  that return predetermined tool results. Live MCP server processes in tests are
  FORBIDDEN.
- The Claude agent loop MUST be tested with staged `tool_use` responses that simulate
  multi-turn investigation. Live Anthropic API calls in tests are FORBIDDEN.
- `conftest.py` MUST centralize shared fixtures: mock MCP sessions, Claude `tool_use`
  response factories, config fixtures, and sample tool results.
- Agent loop tests MUST cover: successful multi-turn investigation, tool errors handled
  by Claude, turn limit enforcement, Gmail body scrubbing, and partial source failure.
- MCP manager tests MUST cover: server startup, shutdown, and process lifecycle.
- MCP registry tests MUST cover: tool allowlist filtering, unknown tool rejection.
- MCP executor tests MUST cover: tool dispatch routing, Gmail body scrubbing, safety
  validation.

**Rationale**: The agent loop and MCP interactions depend on external services and the
Anthropic API. Without mocking, tests are slow, flaky, and require live credentials.
Mocked tests document the agent's expected behavior independently of live systems.

### VII. Container-First Runtime (Standalone Agent Package)

The agent MUST be packaged as a standalone Python application and executed inside a
container using the Anthropic Python SDK directly. No CLI wrapper or external agent
runtime is permitted.

- A `Dockerfile` MUST be maintained at the repository root using the official Python
  slim base image pinned to the project's required minor version
  (e.g., `python:3.12-slim`).
- `uv` MUST be used inside the container to install Python dependencies from
  `pyproject.toml`, ensuring reproducible builds.
- The `Dockerfile` MUST install Node.js and npm MCP server packages at build time
  for stdio-based MCP servers (GitHub, Jira, Slack, Google Workspace).
- The `Dockerfile` MUST install Playwright and its browser binaries to support the
  Playwright MCP server browser-fallback path.
- The agent MUST be invocable as a self-contained CLI:
  `python -m status_report.main` or the equivalent `pyproject.toml` script entrypoint.
- The container MUST be stateless. All configuration and credentials MUST be injected
  via environment variables at runtime. Baking credentials into the image is FORBIDDEN.
- Google OAuth refresh tokens MUST be mounted via a host volume
  (e.g., `-v ~/.status-report:/root/.status-report:ro`) rather than embedded in the
  image.
- The container image MUST NOT run as root. A dedicated non-root user MUST be declared
  in the `Dockerfile`.
- Container builds MUST be reproducible.

**Rationale**: A container encapsulates Python dependencies, Node.js MCP servers,
Playwright browsers (for the browser-fallback MCP server), and the agent CLI in one
portable artifact. This eliminates environment inconsistencies across local, CI, and
cloud-scheduler execution contexts.

### VIII. Documentation-as-Code

`README.md` and `docs/user-guide.md` MUST be kept current with every change that
affects user-visible behaviour. Documentation is part of the feature, not an afterthought.

**Triggers — documentation MUST be updated before merging when**:
- A CLI argument is added, removed, or its default changes
- A new data source (MCP server) is added or removed
- A new environment variable is introduced or renamed
- The auto-period or run-history behaviour changes
- Output format (text, markdown, JSON) structure changes
- Exit code semantics change
- Installation or setup steps change

**Scope**:
- `README.md`: Quick-start, configuration table, CLI argument table, period formats,
  output format samples, exit code table. Keep concise; link to the user guide for depth.
- `docs/user-guide.md`: Complete reference for all features.

**Enforcement**:
- Every PR that changes user-visible behaviour MUST include documentation updates in
  the same commit or PR.

**Rationale**: Users rely on `README.md` and `docs/user-guide.md` as the authoritative
reference. Stale documentation is indistinguishable from a bug.

## Security Requirements

- **Scope minimization**: MCP servers MUST be configured with the minimum read-only
  tool set. Write tools MUST be filtered out at the registry layer.
- **No write operations**: Enforced by Principle I. Any tool not on the read-only
  allowlist MUST be rejected at code review and at runtime.
- **Secret scanning**: CI MUST include a secrets scanner to prevent accidental
  credential commits.
- **Privacy by design**: Gmail tool results MUST have body content scrubbed by the
  executor before reaching Claude. Google Calendar tools MUST return only meeting
  metadata (title, time, attendee count) — no notes, attachments, or body content.
- **Token storage**: Google OAuth refresh tokens MUST be stored in
  `~/.status-report/google_credentials.json` with `600` file permissions.
- **MCP credential isolation**: Credentials are passed as environment variables to MCP
  server subprocesses. They MUST NOT appear in tool schemas, tool arguments, or tool
  results visible to Claude.

## Error Handling & Resilience

- **Graceful degradation**: If an MCP server fails to start or a tool returns an error,
  Claude handles it directly — it decides whether to retry, skip, or try an alternative.
  The agent loop continues with available tools.
- **Turn limits**: The agent loop MUST enforce a configurable maximum number of turns
  (`max_agent_turns`, default 50). If the limit is reached, Claude is asked to produce
  its best report with the data collected so far.
- **Structured logging**: All errors MUST be logged via `structlog` at the appropriate
  level. Raw exception tracebacks MUST NOT be forwarded to Claude.
- **MCP server health**: If an MCP server process exits unexpectedly, the executor
  MUST log a warning and exclude that source's tools from subsequent turns.

## Governance

This constitution is the authoritative governance document for the Status Report Agent.
It supersedes any conflicting conventions in individual feature specs, plan files, or
ad-hoc decisions made during implementation.

**Amendment procedure**:
1. Propose the amendment in writing, citing the principle or section being changed and
   the rationale.
2. Amendment MUST be reviewed and approved before merging any code that depends on the
   changed rule.
3. After approval, update this file, increment the version per the semantic versioning
   policy below, and update `LAST_AMENDED_DATE`.
4. Propagate changes to dependent templates as required.

**Versioning policy**:
- MAJOR: Removal or fundamental redefinition of an existing principle.
- MINOR: New principle or section added, or materially expanded guidance.
- PATCH: Clarifications, wording improvements, typo fixes.

**Compliance review**:
- Every PR MUST be reviewed against the Constitution.
- Principle I (Read-Only) and Principle V (Secrets) MUST be verified on every PR
  touching `mcp/`, `auth/`, or agent loop code.

**Version**: 4.0.0 | **Ratified**: 2026-02-26 | **Last Amended**: 2026-03-01
