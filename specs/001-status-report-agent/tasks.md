---

description: "Task list for Status Report Agent implementation"
---

# Tasks: Status Report Agent

**Input**: Design documents from `/specs/001-status-report-agent/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/cli-contract.md ✅ quickstart.md ✅

**Tests**: Included — Principle VI of the project constitution mandates test-first with mocked skill I/O.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US5 from spec.md)
- Exact file paths are included in all descriptions

## Path Conventions

Single-project layout per plan.md: `src/status_report/`, `tests/` at repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, tooling, and container scaffold.

- [x] T001 Create full directory structure per plan.md: `src/status_report/skills/`, `src/status_report/auth/`, `tests/skills/`, `specs/`, `.specify/`
- [x] T002 Initialize `pyproject.toml` with uv: python 3.12+, all dependencies (anthropic, httpx, playwright, langfuse, tenacity, filelock, pydantic[v2], structlog, google-api-python-client, google-auth-oauthlib, pytest, pytest-asyncio, respx)
- [x] T003 [P] Create `Dockerfile` scaffold: FROM python:3.12-slim, install uv, copy pyproject.toml — leave ENTRYPOINT and Playwright install for Polish phase
- [x] T004 [P] Create `.env.example` with placeholder values for all 14 env vars (ANTHROPIC_API_KEY, LANGFUSE_*, JIRA_*, SLACK_BOT_TOKEN, GITHUB_TOKEN, GOOGLE_*, SKILL_FETCH_LIMIT)
- [x] T005 [P] Configure ruff linting and formatting in `pyproject.toml` (line-length=100, target-version=py312, select=["E","W","F","I","UP"])

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core models, abstractions, auth, tracing, and logging that every user story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T006 Create `src/status_report/__init__.py`, `src/status_report/skills/__init__py` stub, `src/status_report/auth/__init__.py`, `tests/__init__.py`, `tests/skills/__init__.py` (empty package files)
- [x] T007 Implement `src/status_report/config.py`: Pydantic BaseSettings class loading all 14 env vars with types and defaults; `ReportPeriod` dataclass with `label`, `start` (datetime UTC), `end` (datetime UTC); parse "today" → 00:00 UTC to now()
- [x] T008 Implement `src/status_report/skills/base.py`: `ActivityItem` Pydantic model (source, action_type, title, timestamp, url, metadata); `ActivitySkill` ABC with `_registry: ClassVar[dict]`, `__init_subclass__()` auto-registration (normalized name = class.lower().replace("skill","")), `is_configured() -> bool` abstract, `fetch_activity(user, start, end) -> list[ActivityItem]` abstract
- [x] T009 Implement `src/status_report/skills/__init__.py`: `discover_skills()` using `pkgutil.iter_modules` to import all non-underscore modules in skills/ directory; `get_enabled_skills(config) -> list[ActivitySkill]` instantiates registry, calls `is_configured()`, returns enabled instances; call `discover_skills()` at module import time
- [x] T010 [P] Implement `src/status_report/auth/google.py`: OAuth 2.0 consent flow (browser-based), token save to `~/.status-report/google_credentials.json` (chmod 600), token refresh logic; `--consent` CLI mode for one-time setup per quickstart.md
- [x] T011 [P] Implement `src/status_report/auth/tokens.py`: load Jira (email+token), GitHub PAT, Slack bot token from env via config; return typed credential objects for each service
- [x] T012 Implement `src/status_report/tracing.py`: LangFuse client init from config; `create_trace(user, period, format)` → top-level trace; `create_skill_span(trace, skill_name)` → child span; `create_synthesis_span(trace)` → child span; `@observe` decorator wrapper; MUST NOT include credentials in span data
- [x] T013 Implement `src/status_report/run_log.py`: `RunLogger` class; `log_run(run_trace: RunTrace)` validates no credentials/email-body in entry, acquires filelock, appends JSONL entry to `~/.status-report/runs.log`, calls fsync(); directory creation with chmod 700; `RotatingFileHandler`-style 10 MB / 5-backup rotation; `RunTrace` Pydantic model (schema_version, timestamp, user, period, format, sources_attempted, counts, outcome, skipped, retries, duration_seconds)
- [x] T014 Create `tests/conftest.py`: shared pytest fixtures — `mock_config` (all env vars set), `tmp_log_dir` (tmp_path-based ~/.status-report override), `mock_langfuse` (patch LangFuse client), `mock_anthropic` (patch Anthropic SDK), sample `ActivityItem` factory
- [x] T015 [P] Create `tests/test_run_log.py`: unit tests for RunLogger — atomic append, credential-in-entry rejection, filelock concurrent write safety, log rotation trigger, RunTrace schema validation; use `tmp_path` fixture, never touch real `~/.status-report/`

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 — Generate Today's Status Report (Priority: P1) 🎯 MVP

**Goal**: User with ≥1 configured source runs agent with `--user` and `--period today`, receives a consolidated text report within 5 minutes.

**Independent Test**: `python -m status_report.main --user alice@example.com --period today` with mocked APIs returns a non-empty text report and exits 0.

### Tests for User Story 1 (write first — verify FAIL before implementing skills)

- [x] T016 [P] [US1] Write `tests/skills/test_jira.py`: test `fetch_activity` returns `ActivityItem` list using `respx` mock for Jira REST API `/rest/api/3/search`; test `is_configured()` True/False based on env vars
- [x] T017 [P] [US1] Write `tests/skills/test_slack.py`: test `fetch_activity` using `respx` mock for Slack Web API `search.messages` + `conversations.history`; test `is_configured()` check
- [x] T018 [P] [US1] Write `tests/skills/test_github.py`: test `fetch_activity` using `respx` mock for GitHub REST `/search/issues` and `/users/{user}/events`; test `is_configured()` check
- [x] T019 [P] [US1] Write `tests/skills/test_calendar.py`: test `fetch_activity` using `unittest.mock` patch on google-api-python-client Calendar API; test `is_configured()` check
- [x] T020 [P] [US1] Write `tests/skills/test_gdrive.py`: test `fetch_activity` with mocked Drive API and Activity API; test `is_configured()` check
- [x] T021 [P] [US1] Write `tests/skills/test_gmail.py`: test `fetch_activity` returns only subject/sender/recipients/action_type (no body); test `is_configured()` check; test reply detection via `In-Reply-To` header; test body is absent from all returned `ActivityItem.metadata` values
- [x] T022 [US1] Write `tests/test_agent.py`: test `run_agent()` calls `asyncio.gather` over all enabled skills, passes aggregated `ActivityItem` list to Claude once (assert single Anthropic SDK call), returns `Report`; use `mock_anthropic` fixture and stub all skills to return 2 items each

### Implementation for User Story 1

- [x] T023 [P] [US1] Implement `src/status_report/skills/jira.py`: `JiraSkill(ActivitySkill)` — primary: `httpx.AsyncClient` Basic Auth GET `/rest/api/3/search` with JQL `updatedBy=currentUser()` + date filter; `SKILL_FETCH_LIMIT` cap (newest first); Playwright authenticated fallback; return `ActivityItem` list with source="jira"
- [x] T024 [P] [US1] Implement `src/status_report/skills/slack.py`: `SlackSkill(ActivitySkill)` — primary: `search.messages` + `conversations.history` for user's sent messages; `SKILL_FETCH_LIMIT` cap; Playwright fallback; return `ActivityItem` list with source="slack"
- [x] T025 [P] [US1] Implement `src/status_report/skills/github.py`: `GitHubSkill(ActivitySkill)` — primary: REST `/search/issues?q=author:{user}+type:pr` + `/users/{user}/events` for pushes and reviews; `SKILL_FETCH_LIMIT` cap; Playwright fallback; return `ActivityItem` list with source="github"
- [x] T026 [P] [US1] Implement `src/status_report/skills/calendar.py`: `CalendarSkill(ActivitySkill)` — primary: Google Calendar API v3 `events.list` for attended events in period; OAuth token from `auth/google.py`; `SKILL_FETCH_LIMIT` cap; Playwright fallback; return `ActivityItem` list with source="calendar" (metadata: attendee count, duration; never meeting notes)
- [x] T027 [P] [US1] Implement `src/status_report/skills/gdrive.py`: `GDriveSkill(ActivitySkill)` — primary: Drive Activity API `query` for docs created/modified/viewed by user in period; `SKILL_FETCH_LIMIT` cap; Playwright fallback; return `ActivityItem` list with source="gdrive"
- [x] T028 [P] [US1] Implement `src/status_report/skills/gmail.py`: `GmailSkill(ActivitySkill)` — `gmail.metadata` OAuth scope ONLY; `messages.list(labelIds=["SENT"])` + client-side date filter on `Date` header; `messages.get(format="metadata", metadataHeaders=["From","To","Subject","Date","In-Reply-To","References"])`; classify action_type via `In-Reply-To` header ("replied" if present, "sent" otherwise); body MUST NOT be fetched at any point; `SKILL_FETCH_LIMIT` cap; Playwright fallback; return `ActivityItem` list with source="gmail"
- [x] T029 [US1] Implement `src/status_report/agent.py`: `run_agent(config, user, period, enabled_skills, format, langfuse_trace)` — `asyncio.gather(*[skill.fetch_activity(user, period.start, period.end) for skill in enabled_skills])`; aggregate all `ActivityItem` results; call Anthropic SDK once with system prompt (from LangFuse prompt registry) + all items serialized; parse Claude response into `Report` (sections + skipped_sources); write `RunTrace` via `RunLogger.log_run()`
- [x] T030 [P] [US1] Implement text report formatter in `src/status_report/report.py`: `format_report(report: Report, fmt: str) -> str`; text format: plain prose with section headings; `SkippedSource` rendered as `⚠ Skipped: {source} ({reason})` footer line; omit sections with no content
- [x] T031 [US1] Implement `src/status_report/main.py`: argparse CLI with `--user` (required), `--period` (required, "today" only for now), `--format` (optional, default "text"); validate args; call `get_enabled_skills(config)`; create LangFuse trace; call `run_agent()`; write report to stdout, logs to stderr; exit 0

**Checkpoint**: US1 independently testable — `python -m status_report.main --user alice@example.com --period today` produces a text report.

---

## Phase 4: User Story 5 — Graceful Handling of Unavailable Sources (Priority: P1)

**Goal**: Agent skips failing sources with a note in the report; retries transient errors 3× before skipping; exits with appropriate code; never crashes on partial failure.

**Independent Test**: Remove JIRA env vars, run agent — report generated from remaining sources, exit code 1, stderr shows credential warning.

### Tests for User Story 5 (write first)

- [x] T032 [P] [US5] Extend `tests/test_agent.py` with failure scenarios: credential-missing → source skipped, SkippedSource in Report; transient 503 → 3 retry attempts then skip (assert tenacity called); all-sources-fail → exit code 2; assert retry counts in RunTrace
- [x] T033 [P] [US5] Extend `tests/test_run_log.py` with security validation: `log_run()` rejects entries containing credential-like strings (token=, password=, Authorization=) or email body indicators; assert `ValueError` raised and no file written

### Implementation for User Story 5

- [x] T034 [US5] Add tenacity retry to `src/status_report/skills/base.py`: `is_transient(exc) -> bool` (True for 5xx, 429, httpx.TimeoutException, ConnectError, NetworkError; False for 401/403/404); `_retry_fetch(skill, user, start, end)` using `AsyncRetrying(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=30), retry=retry_if_exception(is_transient))` with custom 429 Retry-After header wait; wrap in `fetch_activity` base implementation that calls `_retry_fetch`, catches `RetryError`, logs warning, returns `[]`; track retry count in result metadata
- [x] T035 [US5] Add startup validation in `src/status_report/main.py`: after `get_enabled_skills()`, if zero skills configured → print `ERROR: No skills are configured. Set at least one of: JIRA_API_TOKEN, SLACK_BOT_TOKEN, GITHUB_TOKEN, GOOGLE_CLIENT_ID.` to stderr → exit 2
- [x] T036 [US5] Add exit codes and stderr messages in `src/status_report/main.py`: exit 0 (all sources succeeded), exit 1 (≥1 source skipped, partial report), exit 2 (no data — all failed or none configured), exit 3 (invalid args); pipe all warnings and errors to stderr using structlog; stdout remains report only
- [x] T037 [US5] Wire `SkippedSource` collection into `src/status_report/agent.py`: any skill returning `[]` after retries + a `RetryError` or credential check failure → add `SkippedSource(source, reason, attempts)` to `Report.skipped_sources`; determine outcome ("success"/"partial"/"failed") for `RunTrace`

**Checkpoint**: US1 + US5 both independently functional — partial failure returns report from surviving sources.

---

## Phase 5: User Story 2 — Request a Report for a Past Period (Priority: P2)

**Goal**: User requests report for "yesterday", "last-24h", a specific date, or an explicit date range; all activity items fall within the requested window.

**Independent Test**: `--period yesterday` produces report where all ActivityItem timestamps fall in previous calendar day UTC; `--period 2026-02-01:2026-02-07` produces report with items only within that range.

### Tests for User Story 2 (write first)

- [x] T038 [P] [US2] Write `tests/test_config.py`: parametrized tests for all 5 period format inputs → correct `ReportPeriod.start/end` UTC datetimes; future date input → `ValueError`; `start > end` → `ValueError`; "today" → start=00:00 UTC today, end=now(); "yesterday" → full previous day; "last-24h" → rolling 24h; "YYYY-MM-DD" → full day; "YYYY-MM-DD:YYYY-MM-DD" → inclusive range

### Implementation for User Story 2

- [x] T039 [US2] Expand `src/status_report/config.py`: implement `parse_period(value: str) -> ReportPeriod` handling all 5 formats (today, yesterday, last-24h, YYYY-MM-DD, YYYY-MM-DD:YYYY-MM-DD); all datetimes in UTC; `yesterday` → 00:00:00 to 23:59:59 UTC previous day; `last-24h` → now() − 24h to now()
- [x] T040 [US2] Add future date validation (FR-014) in `src/status_report/config.py`→`parse_period()`: if `period.end > now()` UTC → raise `ValueError`; catch in `src/status_report/main.py`, print `ERROR: --period references a future date. Reports can only be generated for past or current periods.` to stderr, exit 3

**Checkpoint**: US2 independently testable — all period formats accepted; future dates rejected before any data collection.

---

## Phase 6: User Story 3 — Filter Report to Specific Sources (Priority: P2)

**Goal**: `--sources github,slack` produces report containing only those sources; unknown source names produce a warning (not an error); remaining valid sources are used.

**Independent Test**: `--sources github,slack` with all sources configured — report contains only github and slack items; Jira/Calendar/GDrive/Gmail items absent.

### Tests for User Story 3 (write first)

- [x] T041 [P] [US3] Extend `tests/test_agent.py` with source filtering: `--sources github` → only GitHub skill's `fetch_activity` called; `--sources unknown,github` → warning on stderr for "unknown", GitHub used; `--sources jira` with Jira unconfigured → warning that source unavailable, remaining sources used

### Implementation for User Story 3

- [x] T042 [US3] Add `--sources` argument in `src/status_report/main.py`: optional comma-separated string; parse to list; pass to `get_enabled_skills(config, requested_sources)`; print `WARNING: Unknown source "{name}" — skipping. Valid sources: jira, slack, github, calendar, gdrive, gmail.` to stderr for each unrecognized name (not exit 3)
- [x] T043 [US3] Update `src/status_report/skills/__init__.py` → `get_enabled_skills(config, requested_sources=None)`: if `requested_sources` provided, filter registry to those names only; unrecognized names already warned in main.py; unconfigured-but-requested names → add to skipped_sources with reason "not_configured"

**Checkpoint**: US3 independently testable — source filtering works without affecting US1/US2 flows.

---

## Phase 7: User Story 4 — Receive Report in a Chosen Format (Priority: P3)

**Goal**: `--format markdown` produces valid Markdown with section headings; `--format json` produces parseable JSON matching the contract schema; default (no flag) produces plain text.

**Independent Test**: `--format json | python -m json.tool` exits 0; `--format markdown` output contains `## Key Accomplishments` heading.

### Tests for User Story 4 (write first)

- [x] T044 [P] [US4] Write `tests/test_report.py`: test text format — section headings present, skipped sources rendered as ⚠ footer; test markdown format — `##` headings, `---` divider, valid Markdown structure; test JSON format — output parses as valid JSON, matches cli-contract.md schema (user, period, generated_at, sections[], skipped_sources[])

### Implementation for User Story 4

- [x] T045 [P] [US4] Implement Markdown formatter in `src/status_report/report.py`: `_format_markdown(report: Report) -> str` — `# Status Report — {user} — {date}` title, `## {heading}` per section, `---` divider, `⚠ Skipped: {source} ({reason})` footer lines
- [x] T046 [P] [US4] Implement JSON formatter in `src/status_report/report.py`: `_format_json(report: Report) -> str` — serialize `Report` Pydantic model to JSON matching cli-contract.md schema; `generated_at` in ISO 8601 UTC; `period` as `{label, start, end}` object; `sections` as `[{heading, content}]`; `skipped_sources` as `[{source, reason, attempts}]`

**Checkpoint**: All 5 user stories independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Container hardening, observability, security verification, and quickstart validation.

- [x] T047 Finalize `Dockerfile`: add `playwright install --with-deps chromium`; create non-root user (`useradd -m appuser`); `USER appuser`; `ENTRYPOINT ["python", "-m", "status_report.main"]`; ensure `.env` is not `COPY`'d in
- [x] T048 [P] Finalize `.env.example`: verify all 14 env vars present with placeholder values and inline comments matching config.py field descriptions and quickstart.md Step 1
- [x] T049 [P] Add `structlog` structured logging throughout: configure JSON renderer in `src/status_report/tracing.py`; add `log.info/warning/error` calls in `agent.py` (skill start/end, item counts), `main.py` (startup, exit code), each skill (retry attempts); MUST NOT log credential values
- [x] T050 [P] Security audit: verify `RunLogger.log_run()` sentinel check rejects any entry where JSON serialization contains "token", "password", "Authorization", or "body"; verify LangFuse spans contain no credential fields; verify Gmail `ActivityItem.metadata` never includes body-like keys; run `tests/test_run_log.py` security tests
- [x] T051 [P] Run quickstart.md validation: `docker build -t status-report .` succeeds; `docker run --rm --env-file .env -v ~/.status-report:/root/.status-report:ro status-report --user test@example.com --period today --format json` with mock/stub credentials produces JSON output and exits 0 or 1 (not 3)
- [x] T052 [P] Cross-cutting review: verify all 7 constitution gates satisfied — read-only API calls only (no POST/PUT/DELETE in any skill), asyncio.gather used in agent.py, Claude called exactly once per run, LangFuse trace + local log written for every run, no secrets in any output, all external calls mocked in tests, Dockerfile complete

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — **BLOCKS all user stories**
- **US1 (Phase 3)**: Depends on Phase 2 completion — P1 priority
- **US5 (Phase 4)**: Depends on Phase 3 completion — P1 priority, builds on agent.py and skill base
- **US2 (Phase 5)**: Depends on Phase 2 completion — P2, can start after Phase 2 independently of Phase 3/4
- **US3 (Phase 6)**: Depends on Phase 2 completion — P2, can start after Phase 2 independently
- **US4 (Phase 7)**: Depends on Phase 3 (T030 report.py baseline) — P3
- **Polish (Phase 8)**: Depends on all user story phases complete

### User Story Dependencies

- **US1 (Phase 3)**: After Foundational — no story dependencies
- **US5 (Phase 4)**: After US1 — adds retry, exit codes, and SkippedSource wiring to US1 components
- **US2 (Phase 5)**: After Foundational — independent of US1/US5; integrates seamlessly once merged
- **US3 (Phase 6)**: After Foundational — independent of US1/US5/US2
- **US4 (Phase 7)**: After US1 (report.py baseline exists) — extends report.py with additional formatters

### Within Each User Story

- Test tasks MUST be written and FAIL before implementation begins
- base.py (T008) → skills (T023–T028) → agent.py (T029) → report.py (T030) → main.py (T031)
- Skills (T023–T028) are fully parallel to each other
- agent.py (T029) depends on all skills complete

### Parallel Opportunities

- All Phase 1 tasks marked [P]: run together
- Phase 2: T010 and T011 [P] together; T006–T009 sequential; T012–T015 parallel after T006
- Phase 3 tests T016–T022: T016–T021 fully parallel; T022 after T016–T021
- Phase 3 implementations T023–T028: fully parallel with each other
- Phase 7 tasks T044–T046: all [P] — write test and both formatters simultaneously

---

## Parallel Example: User Story 1

```bash
# Step 1: Write all skill tests in parallel (T016-T021):
Task: "Write tests/skills/test_jira.py"      # T016
Task: "Write tests/skills/test_slack.py"     # T017
Task: "Write tests/skills/test_github.py"    # T018
Task: "Write tests/skills/test_calendar.py"  # T019
Task: "Write tests/skills/test_gdrive.py"    # T020
Task: "Write tests/skills/test_gmail.py"     # T021

# Step 2: Implement all skills in parallel (T023-T028):
Task: "Implement src/status_report/skills/jira.py"     # T023
Task: "Implement src/status_report/skills/slack.py"    # T024
Task: "Implement src/status_report/skills/github.py"   # T025
Task: "Implement src/status_report/skills/calendar.py" # T026
Task: "Implement src/status_report/skills/gdrive.py"   # T027
Task: "Implement src/status_report/skills/gmail.py"    # T028

# Step 3: Sequential (T029 → T030+T031):
Task: "Implement src/status_report/agent.py"   # T029
Task: "Implement text formatter in report.py"  # T030 [P with T031]
Task: "Implement src/status_report/main.py"    # T031
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (today's report, text format)
4. **STOP and VALIDATE**: `python -m status_report.main --user alice@example.com --period today`
5. Demo if ready — this is a fully usable daily status report tool

### Incremental Delivery

1. Setup + Foundational → infrastructure ready
2. US1 → text report from all configured skills (MVP!)
3. US5 → retry, graceful failure, exit codes (reliability)
4. US2 → past period support (weekly reviews)
5. US3 → source filtering (context-specific reports)
6. US4 → format selection (Markdown for wikis, JSON for pipelines)
7. Polish → container hardened, security verified

### Parallel Team Strategy

After Phase 2 (Foundational) completes:
- **Developer A**: US1 skills (T023–T028) + agent (T029) + main (T031)
- **Developer B**: US2 period parsing (T039–T040) + US3 filtering (T042–T043)
- **Developer C**: US4 formatters (T045–T046) + Polish (T047–T052)

---

## Notes

- [P] tasks operate on different files with no dependency on incomplete tasks
- [Story] label maps each task to a specific user story for traceability
- Each user story is independently completable and testable
- Tests MUST fail before implementation begins (constitution Principle VI)
- Commit after each completed task or logical group
- Stop at any checkpoint to validate the story independently
- Gmail skill: NEVER fetch body content at any point — `gmail.metadata` scope enforces this at the API layer (FR-010a)
- Playwright fallback is internal to each skill — if time-constrained, stub the fallback with `return []` and complete primary API path first
- All external API calls (httpx, Google APIs, Anthropic SDK) MUST be mocked in tests — no live API calls in the test suite
