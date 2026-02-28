# Feature Specification: Status Report Agent

**Feature Branch**: `001-status-report-agent`
**Created**: 2026-02-27
**Status**: Draft
**Input**: User description: "lookat the claude.md for the project and create specification"

## Clarifications

### Session 2026-02-28

- Q: Should the agent enforce a per-skill timeout? → A: No per-skill timeout; total report generation time budget is 5 minutes.
- Q: What email content should the Gmail skill collect and include in the report? → A: Only sent, replied-to, and key-action emails; subject line, sender, recipients, and action type only — no body content, no opt-in path, permanent exclusion.
- Q: Where is the RunTrace audit trail persisted? → A: Both LangFuse traces and a local append-only log file (e.g., ~/.status-report/runs.log).
- Q: Should the agent retry a skill before skipping it on failure? → A: Up to 3 retries with exponential backoff for transient errors (network timeouts, 5xx); permanent failures (auth errors, 404) skip immediately with no retry.
- Q: Should there be a cap on items fetched per skill per run? → A: Yes — configurable via env var, default 100 most-recent items per skill; oldest items dropped when the limit is reached.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate Today's Status Report (Priority: P1)

An individual professional wants to know what they accomplished today across all their
workplace tools without manually checking each one. They run the agent with a single
command and receive a consolidated, readable summary of their day.

The agent launches with six built-in sources: Jira, Slack, GitHub, Google Calendar,
Google Drive, and Gmail. Additional sources can be added in the future as new skills
without changing how the agent works.

**Why this priority**: This is the core use case. Without this, the agent delivers no
value. Every other story is a refinement of this flow.

**Independent Test**: Run the agent for a single user with a "today" time range. Verify
a non-empty report is produced that contains activity from at least one connected source.

**Acceptance Scenarios**:

1. **Given** a user with at least one configured data source, **When** they request a
   report for "today", **Then** they receive a consolidated report summarizing their
   activity within 5 minutes.
2. **Given** a user with all currently configured sources enabled, **When** they request
   a report, **Then** the report covers activity from every configured source in a single
   unified output.
3. **Given** a user with no activity on a particular source today, **When** they request
   a report, **Then** the report omits that source or notes no activity — it does not
   error or leave a section confusingly blank.

---

### User Story 2 - Request a Report for a Past Period (Priority: P2)

A professional needs to write a weekly update, review yesterday's work, or prepare for
a retrospective. They can request a report for a past date, explicit date range, or
relative period such as "yesterday".

**Why this priority**: Past-period reporting is the second most common workflow and
unlocks weekly reviews without any additional tooling.

**Independent Test**: Run the agent with `--period yesterday` and with an explicit date
range. Verify that all activity items in the report fall within the requested window.

**Acceptance Scenarios**:

1. **Given** a user requests a report for "yesterday", **When** the report is generated,
   **Then** all activity items fall within the previous calendar day.
2. **Given** a user supplies an explicit date range, **When** the report is generated,
   **Then** only activity within that range is included.
3. **Given** a user requests a report for a date with no activity, **When** the report
   is generated, **Then** it clearly states no activity was found rather than returning
   an empty or broken output.

---

### User Story 3 - Filter Report to Specific Sources (Priority: P2)

A professional only cares about certain tools for a given report — a GitHub-only summary
for a code review meeting, or a calendar and Slack summary for a team sync. They can
filter the report to one or more sources without reconfiguring anything.

**Why this priority**: Different reporting contexts require different views. Source
filtering also lets users work with a partially configured agent.

**Independent Test**: Run the agent with `--sources github,slack`. Verify the report
contains only GitHub and Slack activity, and no Jira or calendar items appear.

**Acceptance Scenarios**:

1. **Given** a user specifies one or more source names, **When** the report is
   generated, **Then** only activity from those sources appears in the report.
2. **Given** a user specifies a source that is not configured, **When** the agent runs,
   **Then** it warns the user that the source is unavailable and generates the report
   from the remaining valid sources.

---

### User Story 4 - Receive Report in a Chosen Format (Priority: P3)

A professional wants the output in a format that fits their workflow — plain text for
the terminal, Markdown for pasting into a wiki or pull request description, or JSON for
piping into another tool.

**Why this priority**: Format flexibility increases utility across contexts but does not
block the core value of producing a report.

**Independent Test**: Run the agent with `--format markdown` and `--format json`. Verify
the Markdown output contains headings and the JSON output is parseable.

**Acceptance Scenarios**:

1. **Given** a user requests Markdown format, **When** the report is generated, **Then**
   the output is valid Markdown with clear section headings.
2. **Given** a user requests JSON format, **When** the report is generated, **Then**
   the output is a valid, parseable JSON document.
3. **Given** no format is specified, **When** the report is generated, **Then** the
   output defaults to plain text.

---

### User Story 5 - Graceful Handling of Unavailable Sources (Priority: P1)

A professional's credentials for one source expire, a service is temporarily down, or a
source hits a rate limit. The agent does not crash — it skips the affected source,
notes the issue in the report, and delivers results from all other sources.

**Why this priority**: Partial failure tolerance is non-negotiable for daily use. A
single broken integration must not prevent the entire report from being generated.

**Independent Test**: Remove credentials for one source. Run the agent. Verify the
report is produced with all other sources and includes a clear note about the skipped
source.

**Acceptance Scenarios**:

1. **Given** one source has missing or invalid credentials, **When** the report is
   requested, **Then** that source is skipped with a note in the report, and all other
   configured sources are included.
2. **Given** one source returns a transient error (timeout or 5xx), **When** that
   occurs, **Then** the agent retries up to 3 times with exponential backoff before
   skipping; if all retries fail it includes a note with the failure reason and
   continues with other sources.
3. **Given** all sources fail simultaneously, **When** the report is requested, **Then**
   the agent informs the user clearly that no data could be retrieved and suggests
   checking credentials or connectivity.

---

### Edge Cases

- What happens when the user requests a report for a future date?
  The agent rejects the request with a clear error message before any data collection
  begins.
- What happens when the specified user has no activity on any source for the period?
  The report clearly states no activity was found; it does not silently return an empty
  document.
- What happens when the agent is run without any sources configured?
  The agent exits immediately with a helpful message listing the credentials needed to
  configure at least one source.
- What happens when a source returns an unusually large volume of data (e.g., hundreds
  of Slack messages)?
  Each skill caps its fetch at a configurable limit (default 100 most-recent items).
  Items beyond the cap are dropped; the audit trail notes how many were dropped. The
  report summarizes the retained items without dumping raw data at the user.
- What happens when a transient error persists beyond 3 retries?
  The skill is skipped after the third failed attempt; the report notes the source,
  failure reason, and number of attempts made.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The agent MUST accept a target user identifier (email or username) and
  scope all data collection to that user's activity only.
- **FR-002**: The agent MUST support the following time period inputs: `today`,
  `yesterday`, `last-24h`, a specific date (`YYYY-MM-DD`), and an explicit date range.
- **FR-003**: The agent MUST collect activity data from all configured sources
  concurrently and aggregate results before producing the report.
- **FR-004**: The agent MUST synthesize aggregated activity into a structured report
  covering: key accomplishments, issues/tickets worked on with status changes, code
  contributions, meetings and collaboration, documents produced or consumed, email
  activity (sent, replied-to, and key-action emails — summarized by subject and action
  type to infer work done; body content MUST NOT be collected or included under any
  circumstance), and suggested follow-ups or open items.
- **FR-005**: The agent MUST support filtering data collection to a user-specified subset
  of sources.
- **FR-006**: The agent MUST support output in plain text, Markdown, and JSON formats.
- **FR-007**: The agent MUST skip any source whose credentials are missing or invalid
  (permanent failures), include a human-readable note about the skip in the report, and
  continue processing remaining sources. Permanent failures MUST NOT trigger retries.
- **FR-008**: For transient errors (network timeouts, HTTP 5xx responses), the agent
  MUST retry the affected skill up to 3 times using exponential backoff before skipping
  it. If all 3 retries are exhausted, the skill is skipped and noted in the report with
  the failure reason. Rate-limit responses MUST be treated as transient and retried
  after the server-indicated retry-after delay (counting as one of the 3 attempts).
- **FR-009**: The agent MUST collect only read-only activity data. No write, modify, or
  delete operations may be performed on any connected system under any circumstance.
- **FR-010**: The agent MUST NOT include raw credentials, access tokens, or internal
  error tracebacks in the generated report or any user-facing output.
- **FR-010a**: The Gmail skill MUST NOT collect, store, transmit, or pass email body
  content to any component — including Claude. This exclusion is permanent and has no
  opt-in override. Only subject line, sender, recipients, timestamp, and action type
  (sent / replied / key action) are permitted.
- **FR-011**: Each source integration MUST attempt its primary data access method first
  and fall back to an alternative method automatically if the primary is unavailable,
  without requiring user intervention.
- **FR-012**: The agent MUST produce a complete audit trail for every run, capturing
  which sources were queried, what volume of data was retrieved per source, the synthesis
  step, and any errors or skips. The audit trail MUST be written to two destinations:
  (a) a LangFuse trace, and (b) a local append-only log file at
  `~/.status-report/runs.log`. The log file entry MUST include: timestamp, period
  requested, sources attempted, item counts per source, overall outcome (success /
  partial / failed), and any skipped sources with reasons. Raw credentials and email
  content MUST NOT appear in the log file.
- **FR-013**: The agent MUST validate at startup that at least one source is configured
  and exit with a helpful message if none are.
- **FR-014**: The agent MUST reject requests for future dates with a clear error message
  before any data collection begins.
- **FR-015**: The agent MUST be designed so that a new data source can be added by
  writing a single new skill module and providing its credentials — with zero changes
  required to the core orchestration, synthesis, or output logic.
- **FR-016**: The agent MUST automatically discover and register any skill module present
  in the skills directory at startup, without requiring code changes to a central source
  registry or configuration file.
- **FR-017**: Each skill MUST enforce a configurable maximum item fetch limit per run,
  defaulting to 100 most-recent items. When the limit is reached, older items MUST be
  dropped and a note included in the audit trail. The limit MUST be overridable per
  skill via environment variable without code changes.

### Key Entities

- **User**: The individual whose workplace activity is being reported on. Identified by
  email or username; all data collection is scoped to this person.
- **ReportPeriod**: The time window for the report. Expressed as a relative label
  (today, yesterday, last-24h) or an explicit date or date range.
- **ActivityItem**: A single unit of workplace activity from any source — a ticket
  update, message, code contribution, calendar event, document action, or email action.
  Carries a timestamp, source name, action type, description, and relevant metadata.
  For email items: subject line, sender, recipients, and action type only — body
  content is permanently excluded.
- **Report**: The final synthesized output. Structured into sections by activity type;
  available in text, Markdown, or JSON. Includes a note for each skipped source.
- **Skill**: A pluggable, self-contained integration for one data source. Each skill
  knows how to authenticate with its platform and retrieve the target user's activity
  for a given period. The agent ships with six built-in skills (Jira, Slack, GitHub,
  Google Calendar, Google Drive, Gmail) and is designed to accept additional skills in
  the future without modification to any other part of the system.
- **RunTrace**: An audit record of one agent execution. Captures sources attempted,
  item counts per source, overall outcome, synthesis metadata, and any errors or skips.
  Persisted in two places: a LangFuse trace (for observability and cost tracking) and
  an entry appended to `~/.status-report/runs.log` (for local queryability). The log
  file MUST NOT contain credentials or email body content.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with the initial six sources configured receives a complete daily
  status report within 5 minutes of invoking the agent; this time budget MUST hold as
  additional skills are added in the future. No per-skill timeout is enforced — skills
  run to natural completion or failure within the overall 5-minute budget.
- **SC-002**: When one source is unavailable, the agent delivers a partial report from
  the remaining sources within the same 5-minute window — without requiring the user
  to re-run or reconfigure.
- **SC-003**: 100% of agent runs produce a complete audit trail in both LangFuse and
  the local `~/.status-report/runs.log` file, capturing all sources queried, item
  counts per source, overall outcome, and any skips or errors.
- **SC-004**: The report covers all activity domains for every configured skill when data
  exists — no configured source is silently omitted. The initial six domains are:
  issues, code contributions, messages, meetings, documents, and email activity.
- **SC-005**: Users can switch between plain text, Markdown, and JSON output formats
  without changing credentials or source configuration.
- **SC-006**: No credentials, access tokens, or raw error tracebacks appear in any
  generated report or audit log visible to the user.
- **SC-007**: Adding support for a new data source requires only writing a new skill
  module and providing its credentials — zero changes to core orchestration, synthesis,
  or output logic are required, and the new source is automatically included in reports.

## Assumptions

- The target user has completed any one-time authentication setup (OAuth consent for
  Google, API token generation for Jira/GitHub/Slack) before invoking the agent.
- "Activity" for each source is scoped to actions performed by the target user, not all
  activity in shared spaces (e.g., all Jira tickets on a board).
- The agent operates in a single-user, single-run model: the person running it is the
  same person whose activity is being reported. Multi-user and team-level reports are
  out of scope.
- The agent ships with six built-in skills (Jira, Slack, GitHub, Google Calendar,
  Google Drive, Gmail). All are optional — the agent is fully useful with any configured
  subset. Additional skills may be introduced in future iterations without altering
  this specification's core requirements.
- Report synthesis quality is assumed to meet a professional standard suitable for
  sharing in a team standup or weekly update without manual editing.
- The agent is run on-demand by the user (command-line invocation). Scheduled or
  automated runs are a future consideration and out of scope for this specification.
