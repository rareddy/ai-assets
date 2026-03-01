# Implementation Plan: Run History Tracking

**Branch**: `002-run-history` | **Date**: 2026-02-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-run-history/spec.md`

## Summary

Add persistent per-user run history to `~/.status-report/run_history.log` (JSONL + filelock). After each successful or partial run, record a timestamped entry. When `--period` is omitted, auto-compute the report period as the span from the last recorded run to now. Falls back to "today" on the first ever run. All other CLI flags, `parse_period()`, the agent, and the skills are unchanged.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: `filelock` (already in pyproject.toml), `structlog` (already present)
**Storage**: JSONL file at `~/.status-report/run_history.log` + `.lock` sidecar
**Testing**: pytest + pytest-asyncio (existing)
**Target Platform**: macOS/Linux (same as base agent)
**Project Type**: CLI tool (single-project layout)
**Performance Goals**: Run history lookup < 100ms additional overhead at startup
**Constraints**: History file < 100 KB after 90-day pruning; no new external dependencies
**Scale/Scope**: Single user on one machine; multi-user scoped by `--user` identifier

## Constitution Check

| Gate | Status | Notes |
|------|--------|-------|
| I. Read-Only Data Access | ✅ PASS | Run history writes are local file operations, not external API calls. No new external write operations introduced. |
| II. Async-First Skill Execution | ✅ PASS | `RunHistoryStore` I/O is synchronous — called from `main.py` (sync context) before the asyncio event loop starts, and from `agent.py` after the event loop completes. No blocking I/O inside the async loop. |
| III. Python-Orchestrated Skill Execution | ✅ PASS | No new LLM calls. Claude still called exactly once. No changes to skills or the orchestration pattern. |
| IV. Observability-First with LangFuse | ✅ PASS | History lookup and write are logged via `structlog`. No LangFuse span changes required (run history is a local file op, not a skill). |
| V. Secrets & Credential Hygiene | ✅ PASS | `run_history.log` contains only user identifier, timestamp, period label, and outcome. No credentials, tokens, or secrets stored. Entry content is validated before write (existing sentinel pattern from `run_log.py`). |
| VI. Test-First with Mocked Skill I/O | ✅ PASS | `RunHistoryStore` will be tested with a `tmp_path` fixture (no real file system side-effects). No new external I/O to mock. |
| VII. Container-First Runtime | ✅ PASS | History file lives in `~/.status-report/` which is already mounted as a host volume in the Docker quickstart. No Dockerfile changes needed. |

**Complexity Tracking**: No violations — no additional justification required.

## Project Structure

### Documentation (this feature)

```text
specs/002-run-history/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── cli-contract.md  # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created by /speckit.plan)
```

### Source Code Changes

```text
src/status_report/
├── run_history.py       # NEW — RunHistoryStore: get_last_successful_run, record_run
├── main.py              # MODIFIED — --period becomes optional; resolve from RunHistoryStore
└── agent.py             # MODIFIED — call RunHistoryStore.record_run() post-run

tests/
├── test_run_history.py  # NEW — RunHistoryStore unit tests (tmp_path fixture)
└── test_agent.py        # MODIFIED — add tests for history recording after successful run
```

**No changes to**: `config.py`, `run_log.py`, `report.py`, `tracing.py`, any skill module, `Dockerfile`, `pyproject.toml`, `tests/test_config.py`

## Architecture

### New Module: `run_history.py`

```
RunHistoryStore
  ├── _log_path: Path  (~/.status-report/run_history.log)
  ├── _lock_path: Path (~/.status-report/run_history.log.lock)
  │
  ├── get_last_successful_run(user: str) -> tuple[datetime, str] | None
  │     Reads all entries, filters by user + outcome in (success, partial),
  │     returns (completed_at, period_label) of the most recent, or None.
  │     Skips malformed/future-dated entries with structlog warnings.
  │
  └── record_run(user, completed_at, outcome, period_label) -> None
        Holds filelock for full operation:
          1. Read all existing entries
          2. Parse and filter (skip malformed, prune >90 days)
          3. Append new entry
          4. Rewrite file atomically (write + fsync)
        Only called when outcome in ("success", "partial").
```

### Change to `main.py`

```
Before: --period REQUIRED → parse_period() → ReportPeriod

After:  --period OPTIONAL (default=None)
            │
            ├── if args.period is not None:
            │     parse_period(args.period) → ReportPeriod  [unchanged path]
            │
            └── if args.period is None:
                  result = RunHistoryStore().get_last_successful_run(args.user)
                  if result:
                    (last_ts, _) = result
                    period = ReportPeriod(
                        label=f"since last run at {last_ts.isoformat()}",
                        start=last_ts,
                        end=now
                    )
                  else:
                    period = ReportPeriod(label="today (first run)", start=today, end=now)
```

### Change to `agent.py`

```
After RunLogger().log_run(run_trace):
    if outcome in ("success", "partial"):
        try:
            RunHistoryStore().record_run(
                user=user,
                completed_at=datetime.now(UTC),
                outcome=outcome,
                period_label=period.label or str(period.start.date()),
            )
        except Exception as exc:
            logger.warning("Failed to write run history entry", error=str(exc))
```

## Tech Stack

| Component | Technology | Status |
|-----------|-----------|--------|
| History file I/O | Python stdlib `json`, `pathlib.Path` | existing |
| File locking | `filelock` (already in pyproject.toml) | existing |
| Structured logging | `structlog` | existing |
| Testing | `pytest` with `tmp_path` fixture | existing |
| Storage location | `~/.status-report/` | existing (shared with runs.log) |

**No new dependencies required.**
