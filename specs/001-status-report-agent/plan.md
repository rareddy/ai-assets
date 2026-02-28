# Implementation Plan: Status Report Agent

**Branch**: `001-status-report-agent` | **Date**: 2026-02-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-status-report-agent/spec.md`

## Summary

Build a containerised Python CLI agent that collects read-only workplace activity from
six sources (Jira, Slack, GitHub, Google Calendar, Google Drive, Gmail) using a
pluggable skill architecture, then synthesises a structured report by calling Claude
once via the Anthropic Python SDK. Each skill auto-discovers itself via
`__init_subclass__()`, executes concurrently via `asyncio.gather`, retries transient
errors up to 3 times with exponential backoff (tenacity), and caps its fetch at 100
items (configurable). Every run is traced to LangFuse and appended to a local JSONL
audit log at `~/.status-report/runs.log`.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: anthropic, httpx, playwright, langfuse, tenacity, filelock,
  pydantic v2, structlog, google-api-python-client, google-auth-oauthlib, uv (build)
**Storage**: `~/.status-report/google_credentials.json` (Google OAuth tokens),
  `~/.status-report/runs.log` (JSONL audit log, 10 MB rotation, 5 backups)
**Testing**: pytest, pytest-asyncio, respx (httpx mocking), unittest.mock
**Target Platform**: Docker container — `python:3.12-slim` + Playwright Chromium;
  non-root user; stateless; secrets via environment variables
**Project Type**: CLI agent (standalone Python application, Anthropic SDK direct)
**Performance Goals**: Complete full 6-skill report within 5 minutes; 100-item default
  fetch cap per skill (configurable via env var); no per-skill timeout enforced
**Constraints**: All API calls read-only (GET/search only); email body content
  permanently excluded; credentials never in logs or traces; `gmail.metadata` OAuth
  scope only
**Scale/Scope**: Single user per run; 6 built-in skills; auto-extensible via skill
  module drop-in

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Read-Only Data Access | ✅ PASS | All skills use GET/read-equivalent only; OAuth scopes are read-only; `gmail.metadata` scope enforces body exclusion at API layer |
| II. Async-First Skill Execution | ✅ PASS | `asyncio.gather` over all enabled skills; `httpx.AsyncClient`; Playwright async API; `pytest-asyncio` for tests |
| III. Python-Orchestrated Skill Execution + Claude Synthesis | ✅ PASS | `agent.py` orchestrates; Claude called exactly once with aggregated `ActivityItem` list; no tool-use API |
| IV. Observability-First with LangFuse | ✅ PASS | Top-level trace per run; child span per skill execution + Claude synthesis; prompts in LangFuse registry; no secrets in spans |
| V. Secrets & Credential Hygiene | ✅ PASS | All credentials from env vars or `~/.status-report/google_credentials.json`; `filelock` log writer validates no credential leakage; `.env` in `.gitignore` |
| VI. Test-First with Mocked Skill I/O | ✅ PASS | `respx` mocks httpx; `unittest.mock` for Anthropic SDK; Playwright mocked; no live API calls in tests |
| VII. Container-First Runtime | ✅ PASS | `Dockerfile` at repo root; `python:3.12-slim`; `playwright install --with-deps chromium`; non-root user; secrets via env vars + volume mount |

**Constitution Check: ALL GATES PASS — proceeding to Phase 0.**

*Post-Phase 1 re-check*: No violations introduced in design phase. Skill auto-discovery
(`__init_subclass__` + `pkgutil`) is a Python-only pattern with no external process
calls. JSONL log writer strips credentials at the `RunLogger` boundary. All gates
remain green.

## Project Structure

### Documentation (this feature)

```text
specs/001-status-report-agent/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── cli-contract.md  # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
status-report/
├── CLAUDE.md
├── Dockerfile
├── pyproject.toml
├── .env                               # secrets — NEVER commit
├── .env.example
├── src/
│   └── status_report/
│       ├── __init__.py
│       ├── main.py                    # CLI entrypoint (argparse)
│       ├── agent.py                   # orchestrator: asyncio.gather + Claude call
│       ├── config.py                  # Pydantic settings, env var loading
│       ├── tracing.py                 # LangFuse setup, @observe wrappers
│       ├── report.py                  # format ActivityItems → text/markdown/json
│       ├── run_log.py                 # RunLogger: JSONL append, filelock, rotation
│       ├── skills/
│       │   ├── __init__.py            # discover_skills(), get_enabled_skills()
│       │   ├── base.py                # ActivitySkill ABC + ActivityItem model
│       │   ├── jira.py                # Jira skill (REST API → Playwright fallback)
│       │   ├── slack.py               # Slack skill (Web API → Playwright fallback)
│       │   ├── github.py              # GitHub skill (REST/GraphQL → Playwright fallback)
│       │   ├── calendar.py            # Google Calendar skill (API → Playwright fallback)
│       │   ├── gdrive.py              # Google Drive skill (API → Playwright fallback)
│       │   └── gmail.py               # Gmail skill (gmail.metadata API → Playwright)
│       └── auth/
│           ├── __init__.py
│           ├── google.py              # OAuth 2.0 consent flow + token refresh
│           └── tokens.py              # API token loading for Jira/GitHub/Slack
└── tests/
    ├── __init__.py
    ├── conftest.py                    # shared fixtures
    ├── test_agent.py                  # orchestrator tests
    ├── test_run_log.py                # RunLogger tests
    └── skills/
        ├── test_jira.py
        ├── test_slack.py
        ├── test_github.py
        ├── test_calendar.py
        ├── test_gdrive.py
        └── test_gmail.py
```

**Structure Decision**: Single-project layout (Option 1). All source under
`src/status_report/`; all tests under `tests/`. No separate frontend, backend, or
mobile components.

## Complexity Tracking

> No constitution violations to justify — all gates pass cleanly.
