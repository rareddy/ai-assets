---

description: "Task list for Run History Tracking implementation"
---

# Tasks: Run History Tracking

**Input**: Design documents from `/specs/002-run-history/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/cli-contract.md ✅ quickstart.md ✅

**Tests**: Included — Constitution Principle VI mandates test-first; `RunHistoryStore` is tested with `tmp_path` fixtures (no real file system side effects).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US3 from spec.md)
- Exact file paths are included in all descriptions

## Path Conventions

Single-project layout per plan.md: `src/status_report/`, `tests/` at repository root.

**Files changed by this feature**:
- NEW: `src/status_report/run_history.py`
- NEW: `tests/test_run_history.py`
- MODIFIED: `src/status_report/agent.py`
- MODIFIED: `src/status_report/main.py`
- MODIFIED: `tests/test_agent.py`

---

## Phase 1: Setup

**Purpose**: Create the new module and test file stubs so all phases can reference concrete paths.

- [x] T001 Create `src/status_report/run_history.py` as an empty module stub (module docstring, `from __future__ import annotations`, placeholder `pass`) — establishes the file for T002 to fill

---

## Phase 2: Foundational (Blocking Prerequisite)

**Purpose**: Implement the `RunHistoryStore` class that both US1 and US2 depend on. No user story work can begin until this is complete.

**⚠️ CRITICAL**: US1 (auto-period lookup) and US2 (persist timestamp) both depend on `RunHistoryStore` existing.

- [x] T002 Implement `RunHistoryStore` in `src/status_report/run_history.py`: dataclass `RunHistoryEntry(schema_version, user, completed_at, period_label, outcome)` stored as JSONL at `~/.status-report/run_history.log`; method `get_last_successful_run(user: str) -> tuple[datetime, str] | None` — reads all lines, skips malformed JSON (structlog warning), skips entries where `outcome not in ("success", "partial")`, skips entries where `completed_at > now` (structlog warning), returns `(completed_at, period_label)` of most recent matching entry or `None`; method `record_run(user, completed_at, outcome, period_label) -> None` — holds `filelock` for full read-filter-write operation: read all entries, prune entries older than 90 days from `completed_at`, append new entry, rewrite file atomically with `fsync()`; `_log_path = Path.home() / ".status-report" / "run_history.log"`, `_lock_path = _log_path.with_suffix(".log.lock")`; creates `~/.status-report/` dir if absent; imports: `structlog`, `filelock.FileLock`, `json`, `os`, `pathlib.Path`, `datetime`, `timedelta`

**Checkpoint**: `RunHistoryStore` exists with both methods — US1 and US2 can now be implemented.

---

## Phase 3: User Story 2 — Persist Run Timestamp (Priority: P1)

**Goal**: After every successful or partial run, a timestamped `RunHistoryEntry` is appended to `~/.status-report/run_history.log`. Failed runs write nothing.

**Independent Test**: Run the tool once with any `--period`. Inspect `~/.status-report/run_history.log` and confirm a valid JSONL entry for the user exists.

### Tests for User Story 2

- [x] T003 [P] [US2] Write `tests/test_run_history.py`: class `TestRunHistoryStoreRecordRun` using `tmp_path` fixture (monkeypatch `RunHistoryStore._log_path` and `_lock_path` to `tmp_path`); tests: `test_creates_file_on_first_record` — file does not exist before, exists after; `test_entry_has_correct_fields` — JSONL line parses to dict with `schema_version="1"`, `user`, `completed_at` (ISO 8601 UTC), `period_label`, `outcome`; `test_appends_multiple_entries` — two `record_run` calls → two lines; `test_preserves_existing_entries_within_90_days` — pre-populate file with a 30-day-old entry, call `record_run`, both entries present; `test_prunes_entries_older_than_90_days` — pre-populate with 91-day-old entry, call `record_run`, old entry gone, new entry present; `test_does_not_record_failed_outcome` — should not be called with "failed" but guard test: if called with outcome="failed", raise ValueError; `test_multiple_users_stored_independently` — record for alice, record for bob, both entries in file with correct user fields; `test_file_created_in_correct_directory` — log path is under `~/.status-report/` by default

### Implementation for User Story 2

- [x] T004 [P] [US2] Modify `src/status_report/agent.py`: add `from status_report.run_history import RunHistoryStore` import; after the existing `RunLogger().log_run(run_trace)` call (and its try/except), add: `if outcome in ("success", "partial"): try: RunHistoryStore().record_run(user=user, completed_at=datetime.now(UTC), outcome=outcome, period_label=period.label or str(period.start.date())) except Exception as exc: logger.warning("Failed to write run history", error=str(exc))`

**Checkpoint**: `run_history.log` is created and populated after a successful agent run. US2 independently testable.

---

## Phase 4: User Story 1 — Auto-compute Period Since Last Run (Priority: P1)

**Goal**: When `--period` is omitted, the tool reads run history and sets the period to cover from the last successful run to now. Falls back to "today (first run)" if no history exists. Explicit `--period` always wins.

**Independent Test**: Run the tool twice without `--period`. The second run's period starts exactly at the first run's completion timestamp.

### Tests for User Story 1

- [x] T005 [P] [US1] Add class `TestRunHistoryStoreGetLastSuccessfulRun` to `tests/test_run_history.py` (same `tmp_path` fixture approach); tests: `test_returns_none_when_file_does_not_exist` — no file present → returns `None`; `test_returns_none_when_file_is_empty` — empty file → returns `None`; `test_returns_most_recent_success_entry_for_user` — three entries for alice at T1 < T2 < T3, all outcome="success" → returns T3; `test_ignores_entries_for_other_users` — entries for alice and bob → `get_last_successful_run("alice")` returns alice's entry only; `test_skips_malformed_json_lines_with_warning` — file has one valid line and one garbage line → returns the valid entry, emits structlog warning; `test_skips_future_dated_entries_with_warning` — entry with `completed_at` 1 hour in the future → skipped with warning, returns `None`; `test_returns_none_when_only_failed_entries` — entries with outcome="failed" only → returns `None`; `test_returns_partial_outcome_as_valid` — entry with outcome="partial" → returned as valid

### Implementation for User Story 1

- [x] T006 [P] [US1] Modify `src/status_report/main.py`: (1) change `--period` argparse argument to `required=False, default=None` and update help text to "Time range: today | yesterday | last-24h | YYYY-MM-DD | YYYY-MM-DD:YYYY-MM-DD. If omitted, auto-computed from run history."; (2) add `from status_report.run_history import RunHistoryStore` import; (3) replace the `--period` validation block with: `if args.period is not None: try: period = parse_period(args.period) except ValueError as exc: print(str(exc), file=sys.stderr); sys.exit(3)` else: `now = datetime.now(UTC); today_start = now.replace(hour=0, minute=0, second=0, microsecond=0); result = RunHistoryStore().get_last_successful_run(args.user); if result: last_ts, _ = result; period = ReportPeriod(label=f"since last run at {last_ts.strftime('%Y-%m-%dT%H:%M:%SZ')}", start=last_ts, end=now); logger.info("Period auto-computed from run history", last_run=str(last_ts)) else: period = ReportPeriod(label="today (first run)", start=today_start, end=now); logger.info("No run history found — defaulting to today (first run)")`; (4) add `from datetime import UTC, datetime` and `from status_report.config import ReportPeriod` to imports if not already present

**Checkpoint**: Running without `--period` automatically uses last run time. US1 independently testable.

---

## Phase 5: User Story 3 — Show Last Run Info in Report Output (Priority: P2)

**Goal**: The report period label clearly communicates when the auto-computed period started (e.g., "since last run at 2026-02-28T09:00:00Z") or that it is the first run ("today (first run)").

**Independent Test**: Run the tool twice without `--period`. The second report's header shows "since last run at [timestamp]" in text, markdown, and JSON output formats.

### Tests for User Story 3

- [x] T007 [US3] Add class `TestAutoperiodLabelInOutput` to `tests/test_agent.py`: mock `RunHistoryStore` to return a known last-run timestamp; run `run_agent()` with `pre_period=None` scenario; verify `report.period.label` equals `f"since last run at {ts}"` (text: period line contains "since last run", markdown: `# Status Report` title contains "since last run", JSON: `period.label` field contains "since last run"); also test first-run fallback: mock `RunHistoryStore.get_last_successful_run` to return `None`; verify `report.period.label` equals `"today (first run)"`; verify label flows correctly through `format_report()` for all three output formats using the existing `_make_report()` helper pattern from `tests/test_report.py`

**Checkpoint**: All three user stories independently functional. Period label visible in all output formats.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verify full test suite integrity and validate against quickstart scenarios.

- [x] T008 Run full test suite `uv run pytest --tb=short -q` and confirm all prior 164 tests still pass plus new tests for `RunHistoryStore` and agent history integration; fix any regressions
- [x] T009 [P] Cross-check `specs/002-run-history/quickstart.md` acceptance test matrix: verify each of the 7 scenarios (first run, daily run, explicit override, inspect file, multi-user, failed run, corrupt entry) behaves as documented; mark any deviations as bugs

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — **BLOCKS both US1 and US2**
- **US2 (Phase 3)**: Depends on Phase 2 — implements the write side of RunHistoryStore
- **US1 (Phase 4)**: Depends on Phase 2 — implements the read side; logically benefits from US2 being complete for end-to-end testing
- **US3 (Phase 5)**: Depends on US1 (Phase 4) — label formatting is set in US1's main.py changes; tests verify propagation
- **Polish (Phase 6)**: Depends on all user story phases complete

### User Story Dependencies

- **US2 (P1)**: After Foundational — write side of `RunHistoryStore`; no dependency on US1
- **US1 (P1)**: After Foundational — read side of `RunHistoryStore`; end-to-end test requires US2 complete
- **US3 (P2)**: After US1 — period label is set in US1's `main.py` resolution; US3 only adds tests to confirm propagation

### Within Each Phase

- T003 [P] and T004 [P] in Phase 3 touch different files (`test_run_history.py` vs `agent.py`) → run in parallel after T002
- T005 [P] and T006 [P] in Phase 4 touch different files (`test_run_history.py` vs `main.py`) → run in parallel after T003/T004 complete
- T005 extends `test_run_history.py` started in T003 — must complete T003 before T005

### Parallel Opportunities

- **Phase 3**: T003 (test_run_history.py record tests) ∥ T004 (agent.py wiring)
- **Phase 4**: T005 (test_run_history.py get tests) ∥ T006 (main.py optional period)
- **Phase 6**: T008 (pytest run) ∥ T009 (quickstart validation)

---

## Parallel Example: Phase 3 (US2)

```bash
# After T002 (RunHistoryStore) completes, run T003 and T004 simultaneously:
Task A: "Write record_run tests in tests/test_run_history.py"   # T003
Task B: "Wire record_run into src/status_report/agent.py"       # T004

# After T003/T004 complete, run T005 and T006 simultaneously:
Task A: "Write get_last_successful_run tests in tests/test_run_history.py"  # T005
Task B: "Make --period optional in src/status_report/main.py"              # T006
```

---

## Implementation Strategy

### MVP First (US2 + US1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002) — **CRITICAL**, blocks everything
3. Complete Phase 3: US2 (T003 + T004) — persistence working
4. Complete Phase 4: US1 (T005 + T006) — auto-period working
5. **STOP and VALIDATE**: `python -m status_report.main --user alice@example.com` twice in a row — second run covers only the time since first run
6. Deploy if ready — this is a fully usable daily workflow improvement

### Incremental Delivery

1. T001 + T002 → `RunHistoryStore` ready (no user-visible change yet)
2. T003 + T004 → US2 done (history file is written after each run)
3. T005 + T006 → US1 done (MVP: `--period` now optional for daily use)
4. T007 → US3 done (label confirmed in all output formats)
5. T008 + T009 → Polish (full validation)

---

## Notes

- `tmp_path` fixture (pytest built-in) is used for all `RunHistoryStore` tests — no writes to real `~/.status-report/` during test runs
- `filelock` is already in `pyproject.toml` — no new dependencies
- `RunHistoryStore._log_path` and `_lock_path` should be overridable in tests via constructor parameter `(log_dir: Path = Path.home() / ".status-report")` to make `tmp_path` injection clean
- The existing 164 tests MUST all continue to pass — no regression is acceptable
- US3 delivers no new implementation code — the period label flows through existing `ReportPeriod.label` → `format_report()` unchanged; T007 is purely verification tests
