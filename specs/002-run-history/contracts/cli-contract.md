# CLI Contract: Run History Tracking

**Feature**: 002-run-history
**Date**: 2026-02-28
**Extends**: `specs/001-status-report-agent/contracts/cli-contract.md`

---

## Changed: --period Argument

The `--period` argument is now **optional**. All previously valid period strings continue to work unchanged.

### Before (001)
```
--period <value>    REQUIRED
```

### After (002)
```
--period <value>    OPTIONAL (default: auto-computed from run history)
```

**Behaviour when omitted**:
1. The tool reads `~/.status-report/run_history.log` for the current `--user`'s most recent successful run
2. If found: the report covers from that run's `completed_at` timestamp to now
3. If not found (first run): the report covers "today" (00:00 UTC to now)

**Explicit `--period` always takes precedence** — providing it skips run history entirely.

---

## Updated Usage Examples

```bash
# Auto-period from run history (NEW — most common daily use)
python -m status_report.main --user alice@example.com

# Explicit period still works identically (unchanged)
python -m status_report.main --user alice@example.com --period today
python -m status_report.main --user alice@example.com --period yesterday
python -m status_report.main --user alice@example.com --period 2026-02-28
python -m status_report.main --user alice@example.com --period 2026-02-24:2026-02-28
python -m status_report.main --user alice@example.com --period last-24h

# Combined with other flags (unchanged)
python -m status_report.main --user alice@example.com --format markdown
python -m status_report.main --user alice@example.com --sources github,slack
```

---

## Updated Period Label in Report Output

When the period is auto-computed from run history, the period label in the report output changes:

| Condition | Period Label |
|-----------|-------------|
| Explicit `--period today` | `today` |
| Auto-computed, previous run found at 09:00 | `since last run at 2026-02-28T09:00:00Z` |
| Auto-computed, no previous run (first run) | `today (first run)` |

This label appears in all three output formats:

**Text format**: Header line `Period: since last run at 2026-02-28T09:00:00Z`

**Markdown format**: H1 title `# Status Report — alice@example.com — since last run at 2026-02-28T09:00:00Z`

**JSON format**: `period.label` field
```json
{
  "period": {
    "label": "since last run at 2026-02-28T09:00:00Z",
    "start": "2026-02-28T09:00:00.000000+00:00",
    "end": "2026-02-28T17:00:00.000000+00:00"
  }
}
```

---

## Exit Codes (unchanged)

| Code | Meaning |
|------|---------|
| 0 | Success — all sources returned data |
| 1 | Partial — report generated; ≥1 source skipped |
| 2 | Failure — no data; all sources failed or none configured |
| 3 | Invalid arguments — bad `--period`, unknown format, future date, etc. |

**New case for exit code 3**: If `--period` is omitted AND run history lookup fails (e.g. corrupted file with no valid entries), the tool falls back to "today" rather than exiting 3. Exit code 3 is only for truly unrecoverable argument errors.

---

## Run History File Contract

The run history file at `~/.status-report/run_history.log` is a JSONL file. Each line is a JSON object:

```json
{
  "schema_version": "1",
  "user": "<user-identifier>",
  "completed_at": "<ISO-8601-UTC>",
  "period_label": "<human-readable-period>",
  "outcome": "success" | "partial"
}
```

**Guarantees**:
- File is created automatically on first run (no manual setup)
- Each line is independently valid JSON
- Entries are append-only within the 90-day window
- Entries older than 90 days are pruned on every write
- File never exceeds ~100 KB under normal daily use
- Multiple users on the same machine have independent history (scoped by `user` field)
