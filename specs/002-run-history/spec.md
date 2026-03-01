# Feature Specification: Run History Tracking

**Feature Branch**: `002-run-history`
**Created**: 2026-02-28
**Status**: Draft
**Input**: User description: "I would like to implement the feature to have a log of time when the this report is run and stored in a .status_report file some where where it can keep track of so that when agent runs it can see when it was run last and figure out time span between that and now."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Auto-compute Period Since Last Run (Priority: P1)

A user runs the status report tool without specifying a `--period` argument. The tool reads the run history file, finds the timestamp of the most recent successful run for that user, and automatically sets the report period to cover from that last-run time up to now. This eliminates the need to manually calculate and type a date range every time.

**Why this priority**: This is the core value of the feature — removing manual effort from the most common daily/recurring use case. Without this, the feature delivers no value.

**Independent Test**: Run the tool twice without `--period`. The second run should automatically cover only the time since the first run completed, delivering a report with no duplicate activity.

**Acceptance Scenarios**:

1. **Given** a previous successful run was recorded at 09:00 today, **When** the user runs the tool at 17:00 with no `--period` argument, **Then** the report covers 09:00–17:00 and the new run is recorded at 17:00.
2. **Given** no previous run exists for the user, **When** the user runs the tool with no `--period` argument, **Then** the tool falls back to "today" as the default period and records the run timestamp.
3. **Given** a previous run exists, **When** the user also provides an explicit `--period` argument, **Then** the explicit period takes precedence and the run is still recorded in history.

---

### User Story 2 - Persist Run Timestamp on Every Successful Run (Priority: P1)

After every successful report generation, the tool writes the completion timestamp and user identifier to a persistent run history file stored in the user's home directory (under `~/.status-report/`). The record is appended so history is never lost.

**Why this priority**: Without persisting run history, User Story 1 is impossible. This is a foundational prerequisite and is listed alongside US1 as co-equal P1.

**Independent Test**: Run the tool once with any `--period`. Inspect the run history file and confirm a new timestamped entry for the user appears.

**Acceptance Scenarios**:

1. **Given** the tool completes successfully, **When** the run history file is inspected, **Then** a new entry exists containing the user identifier and the UTC completion timestamp.
2. **Given** the run history file does not yet exist, **When** the tool runs successfully, **Then** the file is created automatically with the first entry.
3. **Given** multiple runs have been recorded, **When** the file is inspected, **Then** all prior entries are preserved (history is never overwritten or truncated beyond the pruning policy).
4. **Given** the tool exits with an error (exit code 2 or 3), **When** the run history file is inspected, **Then** no new entry is added for that failed run.

---

### User Story 3 - Show Last Run Info in Report Output (Priority: P2)

When a report is generated using the auto-computed period (no explicit `--period`), the report output includes a note indicating the period that was automatically selected and when the previous run occurred. This gives the user confidence that the coverage is correct.

**Why this priority**: Transparency and user trust. Without this, users cannot easily verify the auto-computed period is correct.

**Independent Test**: Run the tool twice without `--period`. The second report's header clearly shows "since last run at [timestamp]" so the user knows the period without guessing.

**Acceptance Scenarios**:

1. **Given** the period was auto-computed from run history, **When** the report is displayed, **Then** the report period label indicates "since last run" with the prior run's timestamp rather than a raw date range.
2. **Given** no previous run exists and the period defaulted to "today", **When** the report is displayed, **Then** the period label reads "today (first run)" or equivalent to signal the fallback.

---

### Edge Cases

- What happens when the run history file is corrupted or contains malformed entries? The tool skips bad entries, logs a warning, and proceeds as if no prior run exists rather than crashing.
- What happens when two users share the same machine? Run history is scoped per user identifier so each user's last-run time is tracked independently.
- What happens when the clock jumps (NTP sync, timezone change)? All timestamps are stored and compared in UTC to avoid timezone-related drift.
- What happens when the last recorded run timestamp is in the future (clock skew)? The tool treats it as invalid, logs a warning, and falls back to "today".
- What happens when the run history file grows very large after years of use? Entries older than 90 days are pruned automatically on each write to keep the file compact.
- What happens when `--period` is omitted and there are only failed run entries in history (no successful ones)? The tool skips failed entries and falls back to "today".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST record a run history entry containing the user identifier and UTC completion timestamp after every successful report generation (exit code 0 or 1).
- **FR-002**: The system MUST store run history in the `~/.status-report/` directory in a human-readable, append-friendly format.
- **FR-003**: The system MUST append new entries to run history without overwriting or deleting entries within the 90-day retention window.
- **FR-004**: When no `--period` argument is provided, the system MUST look up the most recent successful run entry for the current user and compute the period as that timestamp to now.
- **FR-005**: When no prior successful run exists for the user and no `--period` is given, the system MUST default to "today" as the period.
- **FR-006**: An explicit `--period` argument MUST always take precedence over any auto-computed period from run history.
- **FR-007**: The system MUST skip malformed or unreadable run history entries without crashing, logging a warning for each skipped entry.
- **FR-008**: Run history entries MUST be scoped per user identifier so different users on the same machine have independent histories.
- **FR-009**: All timestamps in run history MUST be stored in UTC.
- **FR-010**: The system MUST NOT record a run history entry for failed runs (exit code 2 or 3).
- **FR-011**: The system MUST prune run history entries older than 90 days each time a new entry is written.
- **FR-012**: When the period is auto-computed from run history, the report period label MUST communicate this (e.g., "since last run at [time]") rather than showing only a raw date range.
- **FR-013**: If the most recent recorded run timestamp is in the future, the system MUST treat it as invalid, log a warning, and fall back to "today".

### Key Entities

- **RunHistoryEntry**: A single recorded report run. Key attributes: user identifier, UTC timestamp of completion, outcome (success/partial).
- **RunHistoryStore**: The persistent collection of RunHistoryEntry records for all users on the machine. Stored in `~/.status-report/`. Supports: lookup of most recent successful entry by user, append of new entry, pruning of entries older than 90 days.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user running the tool daily without `--period` receives a report covering exactly the time since their last run, with no manual date calculation required.
- **SC-002**: The run history file is created automatically on first use with zero additional setup steps from the user.
- **SC-003**: The auto-period lookup and computation adds no perceptible delay — report startup is not noticeably slower than when `--period` is provided explicitly.
- **SC-004**: After 1 year of daily use (≈365 entries), the run history file remains under 100 KB due to automatic 90-day pruning.
- **SC-005**: When two users run the tool concurrently on the same machine, both entries are recorded correctly with no data loss or corruption.

## Assumptions

- Run history is stored per-machine and not synced across machines. Users running the tool on multiple machines will have independent histories per machine.
- The `~/.status-report/` directory is already created by the existing implementation when first needed.
- "Successful run" means exit code 0 (all sources OK) or exit code 1 (partial — report generated with some sources skipped). Exit codes 2 and 3 do not produce a history entry.
- The run history file is separate from the existing `runs.log` audit log (operational metrics) even though both live in `~/.status-report/`. The history file is optimised for fast last-run lookup; the audit log is optimised for full traceability.
- When `--period` is omitted entirely (not just left blank), that is the trigger for auto-computation. There is no new CLI flag needed; the absence of `--period` is the signal.
