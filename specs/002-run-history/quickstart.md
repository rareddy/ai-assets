# Quickstart: Run History Tracking

**Feature**: 002-run-history
**Date**: 2026-02-28

This guide walks through the user-facing behaviour of the run history feature.

---

## Scenario 1: First-Ever Run (no history yet)

```bash
# Run without --period for the first time
python -m status_report.main --user alice@example.com

# Expected output (period auto-set to "today (first run)"):
# STATUS REPORT
# ============================================================
# User   : alice@example.com
# Period : today (first run)
# ...
```

After this run, `~/.status-report/run_history.log` contains:
```json
{"schema_version": "1", "user": "alice@example.com", "completed_at": "2026-02-28T09:45:00.000000Z", "period_label": "today (first run)", "outcome": "success"}
```

---

## Scenario 2: Daily Run (auto-period from history)

```bash
# Run without --period the next morning
python -m status_report.main --user alice@example.com

# Expected output (period auto-computed from last run at 09:45 yesterday):
# STATUS REPORT
# ============================================================
# User   : alice@example.com
# Period : since last run at 2026-02-28T09:45:00Z
# ...
```

The report covers only activity since the previous run — no duplicate data, no manual date calculation.

---

## Scenario 3: Override Auto-Period

```bash
# Explicit --period always takes precedence
python -m status_report.main --user alice@example.com --period yesterday

# Expected: report covers full previous day, history is still updated with today's timestamp
```

---

## Scenario 4: Inspect Run History File

```bash
# View raw history
cat ~/.status-report/run_history.log

# Example output (one entry per line):
# {"schema_version": "1", "user": "alice@example.com", "completed_at": "2026-02-27T09:30:00.000000Z", "period_label": "today (first run)", "outcome": "success"}
# {"schema_version": "1", "user": "alice@example.com", "completed_at": "2026-02-28T09:45:00.000000Z", "period_label": "since last run at 2026-02-27T09:30:00Z", "outcome": "success"}
```

---

## Scenario 5: Two Users on the Same Machine

```bash
# Alice runs the report
python -m status_report.main --user alice@example.com

# Bob runs the report independently
python -m status_report.main --user bob@example.com

# Each user gets their own last-run time; histories are scoped by --user
```

---

## Scenario 6: Failed Run — History Not Updated

```bash
# Simulate a run with no configured skills (exit code 2)
GITHUB_TOKEN="" python -m status_report.main --user alice@example.com

# Expected: exits with code 2, run_history.log is NOT updated
# Next auto-period run still uses the previous successful run timestamp
```

---

## Scenario 7: Corrupted History Entry

If `~/.status-report/run_history.log` contains a malformed line, the tool skips it with a warning and uses the next valid entry:

```
WARNING: Skipping malformed run history entry (line 3): invalid JSON
```

The tool never crashes due to a bad history file.

---

## Acceptance Test Matrix

| Test | Setup | Command | Expected Period Label | History Updated? |
|------|-------|---------|----------------------|-----------------|
| First run | No history file | `--user alice` (no `--period`) | "today (first run)" | Yes |
| Second run | Previous run at T | `--user alice` (no `--period`) | "since last run at T" | Yes |
| Explicit override | Any history | `--user alice --period yesterday` | "yesterday" | Yes |
| Failed run | Any history | Force exit 2 | N/A | No |
| Corrupt history | Bad JSON in file | `--user alice` (no `--period`) | Falls back to "today (first run)" | Yes |
| Future timestamp | Clock-skewed entry | `--user alice` (no `--period`) | Falls back to "today (first run)" | Yes |
| Multi-user | Alice and Bob history | `--user bob` (no `--period`) | Bob's last run time | Yes (Bob's entry) |
