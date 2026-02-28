# Data Model: Status Report Agent

**Branch**: `001-status-report-agent`
**Date**: 2026-02-28

---

## ActivityItem

The atomic unit of workplace activity returned by every skill.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | `str` | ✅ | Skill name: `jira`, `slack`, `github`, `calendar`, `gdrive`, `gmail` |
| `action_type` | `str` | ✅ | Platform-specific action: e.g. `updated`, `commented`, `merged`, `attended`, `created`, `sent`, `replied` |
| `title` | `str` | ✅ | Human-readable summary: issue title, PR title, meeting name, email subject |
| `timestamp` | `datetime` | ✅ | UTC datetime of the activity |
| `url` | `str \| None` | ❌ | Deep link to the item in its platform (omit if unavailable) |
| `metadata` | `dict[str, str]` | ❌ | Source-specific extras: e.g. Jira status, PR state, attendee count |

**Constraints**:
- `timestamp` MUST fall within the requested `ReportPeriod`.
- `metadata` MUST NOT contain email body content, credentials, or OAuth tokens.
- For Gmail items: `title` = email subject; `action_type` = `sent` | `replied` | `actioned`; `metadata` MAY include `{"from": "...", "to": "...", "reply_count": "2"}`. Body content is permanently excluded.
- Max items returned per skill per run: 100 (default, configurable via `SKILL_FETCH_LIMIT` env var). Oldest items dropped when limit reached.

---

## ReportPeriod

Represents the time window for a report run.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `label` | `str \| None` | ❌ | Original input label: `today`, `yesterday`, `last-24h` |
| `start` | `datetime` | ✅ | UTC start of period (inclusive) |
| `end` | `datetime` | ✅ | UTC end of period (inclusive) |

**Supported input formats** (parsed in `config.py`):

| Input | `start` | `end` |
|-------|---------|-------|
| `today` | 00:00:00 UTC today | now() UTC |
| `yesterday` | 00:00:00 UTC yesterday | 23:59:59 UTC yesterday |
| `last-24h` | now() − 24h | now() |
| `YYYY-MM-DD` | 00:00:00 UTC that date | 23:59:59 UTC that date |
| `YYYY-MM-DD:YYYY-MM-DD` | 00:00:00 UTC start date | 23:59:59 UTC end date |

**Validation rules**:
- `end` MUST NOT be in the future (FR-014). Reject with clear error before any fetch.
- `start` MUST be ≤ `end`.

---

## Report

The final synthesised output produced by Claude.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `period` | `ReportPeriod` | ✅ | The time window this report covers |
| `user` | `str` | ✅ | Target user identifier (email or username) |
| `format` | `Literal["text", "markdown", "json"]` | ✅ | Output format |
| `sections` | `list[ReportSection]` | ✅ | Ordered content sections |
| `skipped_sources` | `list[SkippedSource]` | ✅ | Sources excluded from this run (may be empty) |
| `generated_at` | `datetime` | ✅ | UTC timestamp of report generation |

**`ReportSection`**:

| Field | Type | Description |
|-------|------|-------------|
| `heading` | `str` | Section title, e.g. "Code Contributions", "Email Activity" |
| `content` | `str` | Claude-synthesised prose for this domain |

**Standard sections** (included when data exists):
1. Key Accomplishments
2. Tickets & Issues
3. Code Contributions
4. Meetings & Collaboration
5. Documents
6. Email Activity
7. Suggested Follow-ups

**`SkippedSource`**:

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | Skill name |
| `reason` | `str` | Human-readable reason: `credentials_missing`, `rate_limited`, `transient_error_exhausted`, `not_configured` |
| `attempts` | `int` | Number of fetch attempts made (0 for credential failures, 1–3 for transient retries) |

---

## RunTrace

Audit record for one agent execution. Written to both LangFuse and the local JSONL log.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | `str` | ✅ | Log schema version (`"1.0"`) for forward compatibility |
| `timestamp` | `str` | ✅ | ISO 8601 UTC, e.g. `"2026-02-28T09:45:30.123456Z"` |
| `user` | `str` | ✅ | Target user identifier |
| `period` | `str` | ✅ | Period label or date range string |
| `format` | `str` | ✅ | Output format used |
| `sources_attempted` | `list[str]` | ✅ | All skill names that `is_configured()` returned True |
| `counts` | `dict[str, int]` | ✅ | Items retrieved per source, e.g. `{"jira": 12, "slack": 5}` |
| `outcome` | `Literal["success", "partial", "failed"]` | ✅ | `success`: all sources returned data; `partial`: ≥1 source skipped; `failed`: no data retrieved |
| `skipped` | `list[dict]` | ✅ | One entry per skipped source: `{"source", "reason", "attempts"}` |
| `retries` | `dict[str, int]` | ✅ | Retry counts per source, e.g. `{"slack": 2}` |
| `duration_seconds` | `float` | ✅ | Wall-clock seconds from first skill call to report output |

**Storage**:
- **LangFuse**: top-level trace with child spans per skill + synthesis; token usage tracked
- **Local**: `~/.status-report/runs.log` — JSONL, one entry per line; `filelock` atomic
  append; `fsync()` on write; 10 MB rotation, 5 backups; directory `chmod 700`

**Security constraints**:
- MUST NOT contain credentials, OAuth tokens, or email body content.
- `RunLogger.log_run()` validates the entry before writing.

---

## ActivitySkill (Abstract Base)

| Member | Kind | Signature | Description |
|--------|------|-----------|-------------|
| `fetch_activity` | abstract method | `async (user: str, start: datetime, end: datetime) → list[ActivityItem]` | Fetch and return activity items; handles fallback internally |
| `is_configured` | abstract method | `() → bool` | Return `True` if all required credentials are present |
| `_registry` | class var | `dict[str, type[ActivitySkill]]` | Auto-populated by `__init_subclass__()` |

**Skill registration** (automatic):
```
Module imported → __init_subclass__() fires → skill registered under normalised name
```
Normalised name = `ClassName.lower().replace("skill", "")`, e.g. `JiraSkill` → `jira`.

**Fallback chain** (internal to each skill):
```
1. Official API (httpx.AsyncClient + tenacity retry)
2. Playwright authenticated browser session
3. Log warning + return [] if all methods exhausted
```

---

## Config

Loaded once at startup from environment variables via Pydantic `BaseSettings`.

| Env Var | Type | Default | Description |
|---------|------|---------|-------------|
| `ANTHROPIC_API_KEY` | `str` | — | Required |
| `LANGFUSE_PUBLIC_KEY` | `str` | — | Required |
| `LANGFUSE_SECRET_KEY` | `str` | — | Required |
| `LANGFUSE_HOST` | `str` | `https://cloud.langfuse.com` | |
| `JIRA_BASE_URL` | `str` | — | e.g. `https://org.atlassian.net` |
| `JIRA_USER_EMAIL` | `str` | — | |
| `JIRA_API_TOKEN` | `str` | — | |
| `SLACK_BOT_TOKEN` | `str` | — | `xoxb-...` |
| `GITHUB_TOKEN` | `str` | — | `ghp_...` |
| `GOOGLE_CLIENT_ID` | `str` | — | OAuth client credential |
| `GOOGLE_CLIENT_SECRET` | `str` | — | OAuth client credential |
| `GOOGLE_PROJECT_ID` | `str` | — | |
| `SKILL_FETCH_LIMIT` | `int` | `100` | Max ActivityItems per skill per run |
