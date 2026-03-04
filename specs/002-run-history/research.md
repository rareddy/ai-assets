# Research: Run History Tracking

**Feature**: 002-run-history
**Date**: 2026-02-28

---

## Decision 1: Run History File Format

**Decision**: JSONL (one JSON object per line) with `filelock` at `~/.status-report/run_history.log`

**Rationale**:
- The existing `RunLogger` (runs.log) uses the identical pattern and is already validated in production
- JSONL is append-O(1) and human-readable for debugging
- `filelock` makes concurrent multi-user appends safe
- For the 90-day pruning case (read → filter → write), holding the lock for the entire operation makes it safe — no entries can be appended between the read and write phases as long as the lock is held continuously
- O(n) full-file scan for "most recent successful run by user" is acceptable: at 90-day pruning, there are at most ~365 entries per user, making lookup sub-millisecond

**Alternatives considered**:
- **JSON dict keyed by user** (latest-only): Rejected because (a) requires read-modify-write which is concurrency-risky if lock is not held across both operations, and (b) cannot support "most recent *successful* run" — only stores one entry per user, not outcome-aware
- **SQLite**: Rejected as overkill for this use case — adds schema management, binary format (harder to audit), and new dependency. Viable future upgrade if team-level analytics are added

---

## Decision 2: Run History Entry Schema

**Decision**: Minimal JSONL entry — only the fields needed for last-run lookup

```json
{
  "schema_version": "1",
  "user": "alice@example.com",
  "completed_at": "2026-02-28T09:45:00.000000Z",
  "period_label": "today",
  "outcome": "success"
}
```

**Rationale**:
- `user` is the lookup key
- `completed_at` is the value used to compute the next auto-period
- `outcome` is needed to skip failed runs (only "success" and "partial" count)
- `period_label` is stored for the "since last run at..." label in the report
- Minimal schema avoids bloating the history file with data already in `runs.log`
- `schema_version` enables forward-compatible migrations if the schema changes

**Not included**: sources, counts, retries, duration — these are audit concerns, already captured in `runs.log`

---

## Decision 3: Separate File vs. Re-using runs.log

**Decision**: Separate `run_history.log` file, purpose-built for last-run lookup

**Rationale**:
- `runs.log` is an audit log with a different purpose: full operational traceability
- `run_history.log` is a lightweight index: fast last-run lookup, per-user scoping, 90-day pruning
- Coupling the two would bloat `runs.log` lookup logic with history-specific concerns
- The separation also means the history file can be pruned aggressively (90 days) while `runs.log` could have a different retention policy in the future

---

## Decision 4: Making --period Optional

**Decision**: Change `--period` argparse argument to `required=False, default=None`. When `None`, resolve from `RunHistoryStore.get_last_successful_run(user)`. Explicit `--period` always takes precedence.

**Rationale**:
- `parse_period()` stays completely unchanged — it still expects a non-None string
- Resolution happens at the CLI layer in `main.py` before calling `parse_period()`
- This is the minimal-change approach: zero impact on `config.py`, `test_config.py`, or `agent.py`
- No new fallback default (e.g. "today") is needed in `parse_period()` — the fallback logic lives in `main.py` where it can log a clear message and use a run-history-aware default

**Fallback chain** when `--period` is omitted:
1. Look up most recent successful run for this user in `run_history.log`
2. If found: use `"{last_run_timestamp}:{now}"` range as the period → labels it "since last run at {time}"
3. If not found (first run ever): use `"today"` as the period → labels it "today (first run)"

---

## Decision 5: Where to Record History

**Decision**: Record run history in `agent.py` immediately after `RunLogger.log_run()`, only when `outcome` is "success" or "partial". Called via a new `RunHistoryStore` class in `src/status_report/run_history.py`.

**Rationale**:
- `agent.py` already determines `outcome` and writes the audit log — adding a history write here is a natural extension
- Outcome filter (only success/partial, not failed) is enforced at write time, not read time
- If `run_history.log` write fails, it is treated as a non-fatal warning (same pattern as `RunLogger`)

---

## Decision 6: 90-Day Pruning Trigger

**Decision**: Prune on every write (append new entry then prune in the same locked operation)

**Rationale**:
- Simplest approach — no scheduled job, no separate cron, no background thread
- Acceptable performance: file is small (≤365 entries × ~200 bytes = ~70 KB at 1-year max), so read-filter-write is fast
- Holds the filelock for the full operation (read + filter + write + fsync) to prevent data loss from concurrent appends

---

## Decision 7: New Module Location

**Decision**: `src/status_report/run_history.py`

**Rationale**:
- Separate from `run_log.py` (audit log) to maintain separation of concerns
- Small, focused module: one class (`RunHistoryStore`) with two public methods
- No changes to `RunLogger` in `run_log.py`

---

## Integration Map

```
main.py
  └─ [startup] RunHistoryStore().get_last_successful_run(user)
               → returns datetime | None
               → None → period = "today" (first-run fallback)
               → datetime → period computed as "{ts}:{now}" range

agent.py
  └─ [post-run] RunHistoryStore().record_run(user, completed_at, outcome, period_label)
                → only when outcome in ("success", "partial")
                → appends entry + prunes 90-day-old entries
```

---

## No-Change Zones

- `config.py` / `parse_period()` — unchanged
- `run_log.py` / `RunLogger` — unchanged
- `tests/test_config.py` — unchanged (all tests call `parse_period()` directly, not via CLI)
- `tracing.py` — unchanged
- All 6 skill modules — unchanged
