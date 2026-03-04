# Data Model: Run History Tracking

**Feature**: 002-run-history
**Date**: 2026-02-28

---

## Entities

### RunHistoryEntry

A single record written to `~/.status-report/run_history.log` after each successful or partial report run.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | yes | Schema version for forward compatibility. Always `"1"` for this release. |
| `user` | string | yes | User identifier (email or username) passed via `--user`. Used as the lookup key. |
| `completed_at` | string (ISO 8601 UTC) | yes | UTC timestamp when the run completed (e.g., `"2026-02-28T09:45:00.000000Z"`). Used to compute the next auto-period. |
| `period_label` | string | yes | Human-readable label for the period used in this run (e.g., `"today"`, `"2026-02-27"`, `"since last run at 09:00"`). Displayed in the next report's header. |
| `outcome` | enum | yes | Run outcome: `"success"` (exit 0) or `"partial"` (exit 1). Failed runs (exit 2/3) are never recorded. |

**Storage format**: One JSON object per line (JSONL). Entries are never deleted individually — the file is rewritten atomically during 90-day pruning.

**Example entry**:
```json
{"schema_version": "1", "user": "alice@example.com", "completed_at": "2026-02-28T09:45:00.000000Z", "period_label": "today", "outcome": "success"}
```

---

### RunHistoryStore

The read/write abstraction over `~/.status-report/run_history.log`.

**Storage location**: `~/.status-report/run_history.log`
**Lock file**: `~/.status-report/run_history.log.lock`
**Pruning**: Entries older than 90 days from `completed_at` are removed on every write.

**Operations**:

| Operation | Description | Notes |
|-----------|-------------|-------|
| `get_last_successful_run(user)` | Returns the `completed_at` datetime and `period_label` of the most recent entry for `user` where `outcome` is `"success"` or `"partial"`. Returns `None` if no such entry exists. | Read-only; no lock held (file is atomically written) |
| `record_run(user, completed_at, outcome, period_label)` | Appends a new `RunHistoryEntry` to the log, then prunes entries older than 90 days from the file. Only called when `outcome` is `"success"` or `"partial"`. | Holds filelock for full read-filter-write to prevent data loss |

---

## Relationships to Existing Entities

```
RunHistoryEntry (new)
  ├─ shares ~/.status-report/ directory with RunTrace (runs.log)
  ├─ user field matches the --user CLI argument
  └─ outcome mirrors RunTrace.outcome ("success" | "partial")

RunTrace (existing, unchanged)
  └─ NOT used for history lookup — separate concerns
```

---

## Auto-Period Computation

When `--period` is omitted, the period is resolved as follows:

```
last_run = RunHistoryStore.get_last_successful_run(user)

if last_run is None:
    period = ReportPeriod(label="today (first run)", start=today_start, end=now)
else:
    period = ReportPeriod(
        label=f"since last run at {last_run.completed_at}",
        start=last_run.completed_at,
        end=now
    )
```

The resulting `ReportPeriod` flows into `run_agent()` unchanged — no changes to the agent or skills.

---

## File Layout

```
~/.status-report/
├── google_credentials.json      # Google OAuth tokens (existing)
├── runs.log                     # Full audit log / RunTrace (existing)
├── runs.log.lock                # Filelock for runs.log (existing)
├── run_history.log              # Per-user run history / RunHistoryEntry (NEW)
└── run_history.log.lock         # Filelock for run_history.log (NEW)
```

---

## Validation Rules

- `schema_version` MUST be `"1"` (entries with unrecognised versions are skipped with a warning)
- `user` MUST be non-empty
- `completed_at` MUST be parseable as ISO 8601 UTC; entries with invalid timestamps are skipped with a warning
- `outcome` MUST be `"success"` or `"partial"`; other values are skipped with a warning
- Entries where `completed_at` is in the future (clock skew) are skipped with a warning
- Entries older than 90 days are silently pruned on every write

---

## State Transitions

```
Tool run completes
       │
       ├─ outcome = "success" (exit 0)   ─┐
       │                                   ├─ RunHistoryStore.record_run() called
       └─ outcome = "partial" (exit 1)   ─┘

       └─ outcome = "failed" (exit 2)    ─┐
                                           ├─ RunHistoryStore NOT called
       └─ outcome = "invalid" (exit 3)   ─┘
```
