<!--
SYNC IMPACT REPORT
==================
Version change: 3.0.0 → 3.1.0 (MINOR: New Principle VIII added — Documentation-as-Code)
Added sections:
  - Principle VIII: Documentation-as-Code (README.md + docs/user-guide.md must stay current)
Modified principles: none
Templates requiring updates:
  - .specify/templates/plan-template.md: Constitution Check gate should include
    documentation gate (VIII) for features changing CLI/env/output behaviour ⚠ pending
Follow-up TODOs:
  - Add "VIII. Documentation" row to Constitution Check gate in plan-template.md
New files created by this amendment:
  - README.md (project root)
  - docs/user-guide.md

---

Previous sync report:
====================
Version change: 2.0.0 → 3.0.0 (MAJOR: Principle III fundamentally redefined;
  backward-incompatible governance change — "Skill-Based Tool Orchestration by Claude"
  replaced by "Python-Orchestrated Skill Execution + Claude Synthesis")
Modified principles:
  - Principle II: "Async-First Agent Loop" → "Async-First Skill Execution"
    (re-anchored to asyncio.gather over skills; removed Anthropic SDK tool-use
    orchestration language)
  - Principle III: "Skill-Based Data Collection via Tool Orchestration" →
    "Python-Orchestrated Skill Execution + Claude Synthesis" (complete
    redefinition — MAJOR trigger; Claude no longer decides which tools to call)
  - Principle VI: "Test-First with Mocked Tool Invocations" → "Test-First with
    Mocked Skill I/O" (testing target shifts back to mocking HTTP/browser calls
    within skills; Anthropic SDK mocked for synthesis step only)
  - Principle VII: minor cleanup — removed tool-orchestration-specific language;
    Playwright browser dependency noted for container build
Added sections: none
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md ✅ Constitution Check gate unchanged
  - .specify/templates/spec-template.md ✅ no structural changes required
  - .specify/templates/tasks-template.md ✅ skill task patterns remain valid
  - .specify/templates/agent-file-template.md ✅ no changes needed
Follow-up TODOs:
  - TODO(RATIFICATION_DATE): Set to 2026-02-26; update if prior adoption date applies.
  - TODO(BASE_IMAGE): Confirm exact Python base image tag once Dockerfile is authored.
  - TODO(BROWSER_TOOL): Confirm Playwright vs alternative for browser skill fallback.
-->

# Status Report Agent Constitution

## Core Principles

### I. Read-Only Data Access (NON-NEGOTIABLE)

All skill tools MUST be strictly read-only. No skill or tool may issue any call that
creates, modifies, or deletes data in any external system.

- All HTTP calls within tools MUST use GET or read-equivalent search methods only.
  POST/PUT/PATCH/DELETE are FORBIDDEN in skill and tool modules.
- OAuth scopes and API token permissions MUST be scoped to the minimum read-only set
  defined per platform (e.g., `read:jira-work`, `calendar.readonly`).
- Read-only enforcement MUST be applied at two layers: OAuth/token scope configuration
  AND code-level (only GET/search requests in `skills/` and `tools/`).
- Any new skill added MUST have its read-only contract explicitly stated and reviewed
  before merging.

**Rationale**: The agent aggregates sensitive workplace data. Write access, even
accidental, could corrupt project management, calendar, or communication systems with
serious professional consequences. Two-layer enforcement ensures no single point of
failure.

### II. Async-First Skill Execution

All I/O-bound operations within the agent and its skills MUST use Python `async/await`.
Blocking I/O in the async event loop is FORBIDDEN.

- All skill `fetch_activity` implementations MUST be async coroutines.
- The Python orchestrator MUST dispatch all enabled skills concurrently using
  `asyncio.gather` — never sequentially in a loop.
- All HTTP requests within skills MUST use `httpx.AsyncClient`.
- Browser automation within skills (Playwright) MUST use its async API.
- `pytest-asyncio` MUST be used for all tests involving async code.

**Rationale**: The agent queries 5+ external platforms per run. Concurrent skill
execution via `asyncio.gather` is the minimal viable approach for a responsive report
generation time. Sequential skill fetching is FORBIDDEN.

### III. Python-Orchestrated Skill Execution + Claude Synthesis

Data collection MUST be performed by the Python orchestrator invoking all enabled
skills deterministically and concurrently. Claude MUST be invoked exactly once per
report run, receiving fully aggregated structured data, and used exclusively for
natural-language synthesis.

**Skill contract**: Each data source MUST be implemented as a skill — a Python module
implementing the `ActivitySkill` abstract base class:

- `async def fetch_activity(user: str, start: datetime, end: datetime) -> list[ActivityItem]`
- `def is_configured(self) -> bool`

Each skill MUST internally manage its own access method, falling back in priority order:
1. Official REST or GraphQL API (preferred — fastest, most structured)
2. Authenticated browser scraping via Playwright (when API is unavailable or
   insufficient)
3. Unauthenticated web scraping (last resort only, and only where permitted)

The fallback decision logic MUST live inside the skill. The orchestrator MUST NOT know
or care which access method a skill used.

**Orchestrator contract**: `agent.py` MUST:
1. Read configuration and call `is_configured()` on each skill at startup.
2. Invoke all enabled skills concurrently via `asyncio.gather`.
3. Collect and aggregate results into a single structured payload.
4. Pass the aggregated payload to Claude once for synthesis.

**Claude's role** is strictly synthesis. Claude MUST NOT:
- Decide which skills to run.
- Make decisions about which URLs, endpoints, or queries to use.
- Receive raw credentials, API blobs, HTML, or stack traces.

Claude's input MUST be structured `ActivityItem` data. Claude's output MUST be the
final formatted report (text, markdown, or JSON). The Anthropic Python SDK MUST be
used directly — Claude CLI or any CLI wrapper MUST NOT be used as the runtime.

**Rationale**: For a fixed set of known data sources, Python orchestration is
deterministic, cheaper (one Claude call vs. one per tool decision), and faster (true
parallel execution). Claude is used for what it does best — language and reasoning —
not for control flow that is better expressed in code.

### IV. Observability-First with LangFuse

Every agent run MUST produce a complete LangFuse trace. All significant operations MUST
be instrumented as child spans.

- Every agent execution MUST create a top-level LangFuse trace.
- Each tool invocation (per skill) AND the final Claude synthesis step MUST be separate
  child spans.
- Claude API token usage MUST be tracked per report generation via LangFuse cost
  tracking.
- The `@observe` decorator from the `langfuse` Python SDK MUST be used for automatic
  span creation wherever applicable.
- Report-generation system prompts MUST be stored in the LangFuse prompt registry for
  versioning, not hardcoded in source files.
- LangFuse spans MUST NEVER contain raw tokens, passwords, OAuth credentials, or any
  secrets. Span attributes MUST be scrubbed before logging.

**Rationale**: LangFuse is the primary auditability and debugging surface for this
agent. Without complete traces, diagnosing incorrect reports or tool failures is not
feasible. Prompt registry versioning enables controlled iteration on report quality.

### V. Secrets & Credential Hygiene (NON-NEGOTIABLE)

Credentials MUST never appear in source code, tool arguments, logs, traces, or version
control.

- All credentials (API tokens, OAuth secrets, client IDs) MUST be loaded exclusively
  from environment variables or the designated secure token store
  (`~/.status-report/google_credentials.json` for Google OAuth).
- Skills MUST resolve credentials at initialization time from env vars and pass only
  opaque, already-authenticated client objects into tool execution — never raw secrets.
- `.env` MUST be listed in `.gitignore`. Committing `.env` is FORBIDDEN.
- `.env.example` MUST be maintained with placeholder values for all required keys.
- `structlog` log statements and LangFuse span attributes MUST be audited to confirm no
  credential leakage before any merge.
- Google OAuth tokens MUST be refreshed automatically; expired tokens MUST NOT cause
  hard failures without a clear re-authentication prompt.

**Rationale**: This agent has access to broad workplace data across multiple systems.
A credential leak would expose the user's entire digital work footprint. Non-negotiable
hygiene is the only acceptable posture.

### VI. Test-First with Mocked Skill I/O

All external I/O within skills and the Anthropic SDK call for synthesis MUST be mocked
in tests. Tests for new skills MUST be written before or alongside the implementation.

- `pytest` with `pytest-asyncio` is the required test framework.
- All HTTP calls within skill API paths MUST be mocked using `respx` or an equivalent
  `httpx` mock library. Live API calls in tests are FORBIDDEN.
- Playwright browser automation within skill browser-fallback paths MUST be mocked or
  run against a local test server. Live browser sessions in tests are FORBIDDEN.
- The Anthropic SDK synthesis call in `agent.py` MUST be mocked using `unittest.mock`.
  Live Anthropic API calls in tests are FORBIDDEN.
- Each skill MUST have a corresponding test file in `tests/skills/`.
- `conftest.py` MUST centralize shared fixtures: mock `httpx` client, mock Playwright
  page, mock Anthropic client, sample `ActivityItem` lists, and date range helpers.
- Skill tests MUST cover: successful API fetch, successful browser-fallback fetch,
  `is_configured()` returning `False` when credentials are absent, API rate-limit
  error handling, and empty result sets.
- Orchestrator tests MUST cover: concurrent skill dispatch, partial skill failure
  (one skill errors, others succeed), and the aggregated payload passed to Claude.

**Rationale**: Skills and the orchestrator depend on external services and the
Anthropic API. Without mocking, tests are slow, flaky, and require live credentials.
Mocked tests document each skill's expected I/O contract independently of live systems.

### VII. Container-First Runtime (Standalone Agent Package)

The agent MUST be packaged as a standalone Python application and executed inside a
container using the Anthropic Python SDK directly. No CLI wrapper or external agent
runtime is permitted.

- A `Dockerfile` MUST be maintained at the repository root using the official Python
  slim base image pinned to the project's required minor version
  (e.g., `python:3.12-slim`).
- `uv` MUST be used inside the container to install dependencies from `pyproject.toml`,
  ensuring reproducible builds.
- The `Dockerfile` MUST install Playwright and its browser binaries to support skill
  browser-fallback paths (`playwright install --with-deps chromium`).
- The agent MUST be invocable as a self-contained CLI:
  `python -m status_report.main` or the equivalent `pyproject.toml` script entrypoint.
- The container MUST be stateless. All configuration and credentials MUST be injected
  via environment variables at runtime. Baking credentials into the image is FORBIDDEN.
- Google OAuth refresh tokens MUST be mounted via a host volume
  (e.g., `-v ~/.status-report:/root/.status-report:ro`) rather than embedded in the
  image.
- The container image MUST NOT run as root. A dedicated non-root user MUST be declared
  in the `Dockerfile`.
- Container builds MUST be reproducible: the same source commit MUST produce a
  functionally identical image across environments.
- The `Dockerfile` MUST be validated in CI on every PR.

**Rationale**: A container encapsulates Python dependencies, Playwright browsers (for
skill fallbacks), and the agent CLI in one portable artifact. This eliminates
environment inconsistencies across local, CI, and cloud-scheduler execution contexts.

### VIII. Documentation-as-Code

`README.md` and `docs/user-guide.md` MUST be kept current with every change that
affects user-visible behaviour. Documentation is part of the feature, not an afterthought.

**Triggers — documentation MUST be updated before merging when**:
- A CLI argument is added, removed, or its default changes
- A new data source (skill) is added or removed
- A new environment variable is introduced or renamed
- The auto-period or run-history behaviour changes
- Output format (text, markdown, JSON) structure changes
- Exit code semantics change
- Installation or setup steps change

**Scope**:
- `README.md`: Quick-start, configuration table, CLI argument table, period formats,
  output format samples, exit code table. Keep concise; link to the user guide for depth.
- `docs/user-guide.md`: Complete reference for all features — full CLI reference, all
  period formats, auto-period behaviour, all data sources, multi-user setup, Docker
  usage, custom skill authoring, observability, troubleshooting, security.

**Enforcement**:
- Every PR that changes user-visible behaviour MUST include documentation updates in
  the same commit or PR. A PR with code changes but no doc update for user-visible
  features MUST NOT be merged.
- The Constitution Check gate in `plan-template.md` MUST include a documentation gate
  for every feature that changes CLI behaviour, environment variables, or output format.

**Rationale**: Users rely on `README.md` and `docs/user-guide.md` as the authoritative
reference. Stale documentation is indistinguishable from a bug — it erodes trust and
wastes debugging time. Treating documentation as a first-class deliverable ensures the
project remains usable as it evolves.

## Security Requirements

- **Scope minimization**: OAuth and token scopes MUST be the minimum read-only set
  defined per platform. Requests for broader scopes MUST be explicitly justified and
  approved.
- **No write operations**: Enforced by Principle I. Any code path introducing a
  non-GET HTTP method in `skills/` or `tools/` MUST be rejected at code review.
- **Secret scanning**: CI MUST include a secrets scanner (e.g., `detect-secrets` or
  `truffleHog`) to prevent accidental credential commits.
- **Privacy by design**: The Google Calendar skill MUST fetch only meeting metadata
  (title, time, attendee count). Meeting notes, attachments, and body content MUST NOT
  be fetched unless explicitly opt-in configured by the user.
- **Token storage**: Google OAuth refresh tokens MUST be stored in
  `~/.status-report/google_credentials.json` with `600` file permissions. Token files
  MUST NOT be stored in the project directory or any version-controlled path.
- **Tool argument safety**: Tool schemas registered with Claude MUST NOT include fields
  that accept raw credentials. Authentication MUST be pre-resolved before tool
  registration.

## Error Handling & Resilience

- **Graceful degradation**: If a skill's credentials are missing, invalid, or all
  access methods (API, browser, scrape) are exhausted, that skill MUST return a
  structured error result. The agent MUST include a note in the final report and
  continue without failing the entire run.
- **Fallback transparency**: When a skill falls back from API to browser scraping (or
  further), this MUST be logged via `structlog` at `warning` level and recorded as a
  span attribute in LangFuse.
- **Rate limit transparency**: Rate-limit errors MUST be surfaced clearly in the
  structured tool result with retry-after guidance. Silent swallowing is FORBIDDEN.
- **Structured logging**: All errors MUST be logged via `structlog` at the appropriate
  level. Raw exception tracebacks MUST NOT be forwarded to Claude or appear in
  LangFuse span attributes visible to end users.
- **Configuration validation**: Each skill's `is_configured()` method MUST be called
  at agent startup. Unconfigured skills MUST be logged as warnings and excluded from
  the tool registry for that run.

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
4. Propagate changes to dependent templates (plan-template, spec-template,
   tasks-template) as required.

**Versioning policy**:
- MAJOR: Removal or fundamental redefinition of an existing principle
  (backward-incompatible governance change).
- MINOR: New principle or section added, or materially expanded guidance.
- PATCH: Clarifications, wording improvements, typo fixes, non-semantic refinements.

**Compliance review**:
- Every PR MUST be reviewed against the Constitution Check gate in `plan-template.md`
  before implementation begins.
- Principle I (Read-Only) and Principle V (Secrets) MUST be verified as a mandatory
  checklist item on every PR touching `skills/`, `tools/`, or `auth/`.
- Constitution adherence is a blocking criterion for merge approval.

**Runtime guidance**: For day-to-day development conventions (commands, code style,
active technologies), refer to the auto-generated agent guidance file at
`.specify/memory/agent-guidance.md` (generated by `/speckit.plan`).

**Version**: 3.1.0 | **Ratified**: 2026-02-26 | **Last Amended**: 2026-02-28
