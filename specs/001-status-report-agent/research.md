# Research: Status Report Agent

**Phase**: 0 — Outline & Research
**Branch**: `001-status-report-agent`
**Date**: 2026-02-28

---

## Decision 1: Python Skill Auto-Discovery Pattern

**Decision**: Hybrid `pkgutil.iter_modules()` + `__init_subclass__()` registry

**Rationale**: Skills are internal modules (not distributed packages), so entry_points
overhead is unnecessary. `__init_subclass__()` (PEP 487, Python 3.6+) auto-registers
concrete subclasses the moment their module is imported. `pkgutil.iter_modules()` scans
the `skills/` directory at startup and imports each module, triggering registration.
The registry then provides `get_enabled_skills()` which instantiates each registered
class, calls `is_configured()`, and returns only the ready-to-use instances. This
gives automatic discovery (FR-016) with zero central registry maintenance.

**Pattern sketch**:
```python
# base.py — registry via __init_subclass__
class ActivitySkill(ABC):
    _registry: ClassVar[dict[str, type]] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__abstractmethods__:   # skip abstract intermediaries
            ActivitySkill._registry[cls.__name__.lower().replace("skill", "")] = cls

# skills/__init__.py — discovery via pkgutil
def discover_skills() -> None:
    for _, name, _ in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if not name.startswith("_"):
            importlib.import_module(f"{__name__}.{name}")

discover_skills()  # called at import time
```

**Testing**: `monkeypatch` env vars per-skill class; parametrize tests over
`ActivitySkill.registry().values()` to auto-cover all skills.

**Alternatives considered**:
- `importlib.metadata` entry_points: correct for third-party plugins; overkill for
  internal skills; requires `pyproject.toml` entries per skill
- Naming convention only (`pkgutil` without registry): no interface validation
- `cls.__subclasses__()` introspection: requires explicit imports first; fragile

---

## Decision 2: Gmail API Scope and Metadata Strategy

**Decision**: Use `gmail.metadata` OAuth scope + `format=metadata` + explicit
`metadataHeaders`; classify replies via `In-Reply-To` header

**Rationale**: `gmail.metadata` scope enforces body exclusion at the OAuth layer
(matching FR-010a — body permanently excluded). It returns only message ID, labels,
and the headers listed in `metadataHeaders`. Using `gmail.readonly` would grant
unnecessary body access. Tradeoff: `gmail.metadata` disables the `q` search parameter,
so date filtering must use `labelIds=["SENT"]` combined with client-side date
filtering on the `Date` header value.

**Key API parameters**:
```python
# List sent messages
messages.list(userId="me", labelIds=["SENT"], maxResults=100)

# Fetch metadata for each message
messages.get(
    userId="me", id=msg_id,
    format="metadata",
    metadataHeaders=["From", "To", "Subject", "Date", "In-Reply-To", "References"]
)

# Classify action type
is_reply = "In-Reply-To" in headers  # True → replied, False → new/sent
```

**Rate limits**: 5 quota units per `messages.list` or `messages.get` call;
15,000 units/user/minute limit. A 100-message run costs ~500 units — well within limits.

**Alternatives considered**:
- `gmail.readonly`: grants unnecessary body access; violates least-privilege (Principle V)
- Thread-based analysis (`threads.get`): 10 units/call, slower; not needed for
  sent/replied classification which `In-Reply-To` header already provides

---

## Decision 3: HTTP Retry Library

**Decision**: `tenacity` with `AsyncRetrying`, `wait_exponential`, and a custom
`Retry-After` wait strategy

**Rationale**: Tenacity is the industry-standard async retry library for Python.
`retry_if_exception(is_transient)` cleanly separates transient (5xx, timeout,
`ConnectError`, 429) from permanent (401, 403, 404) failures without if-chains.
`wait_exponential(multiplier=1, min=1, max=30)` gives 1s → 2s → 4s backoff (3
attempts max per FR-008). A custom wait function reads the `Retry-After` header from
429 responses and uses it as the delay (capped at 60s), counting as one of the 3
attempts.

**Transient vs permanent classification**:
```python
def is_transient(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False
```

**Testing**: `respx` mocks `side_effect=[Response(503), Response(503), Response(200)]`
to verify 3-attempt sequences; `monkeypatch` on `time.sleep` avoids slow tests.

**Alternatives considered**:
- `stamina`: cleaner API but less configurable `Retry-After` handling
- `httpx-retries`: less mature; limited async support
- Manual retry loop: complex `Retry-After` parsing; not worth reimplementing

---

## Decision 4: RunTrace Local Log Format and Storage

**Decision**: JSONL at `~/.status-report/runs.log`; `filelock` for atomic appends;
`RotatingFileHandler`-style rotation at 10 MB (5 backups)

**Rationale**: JSONL (one JSON object per line) is the best format for append-only
structured logs — each line is independently parseable, handles nested fields (skipped
sources with reasons, per-skill counts), and is queryable with `jq` or Python's
`json.loads()`. `Path.home() / ".status-report"` is cross-platform and co-locates
with the Google OAuth token file already specified. `filelock` (lightweight, filesystem-
agnostic) serialises concurrent writes. `fsync()` after each write ensures durability.
Rotation at 10 MB (5 backups = 50 MB max) keeps total footprint bounded.

**Log entry schema**:
```json
{
  "schema_version": "1.0",
  "timestamp": "2026-02-28T09:45:30.123456Z",
  "period": "today",
  "user": "alice@example.com",
  "sources_attempted": ["jira", "slack", "github", "calendar", "gdrive", "gmail"],
  "counts": {"jira": 12, "slack": 5, "github": 3, "calendar": 4, "gdrive": 2, "gmail": 8},
  "outcome": "partial",
  "skipped": [{"source": "gdrive", "reason": "credentials_missing", "attempts": 0}],
  "retries": {"slack": 1},
  "duration_seconds": 47.3,
  "format": "markdown"
}
```

**Security**: `log_file.parent.chmod(0o700)` on first creation; log entries MUST NOT
contain credentials or email body content (validated in `RunLogger.log_run()`).

**Testing**: `tmp_path` pytest fixture provides isolated temp directories; no real
`~/.status-report/` is touched in tests. `mock_open` for unit tests of write logic.

**Alternatives considered**:
- CSV: cannot represent nested structures (skipped list with reasons)
- Plain text: unstructured; no reliable programmatic parsing
- SQLite: heavier dependency; overkill for append-only sequential reads
- Time-based rotation: unpredictable file sizes; size-based is simpler for CLI tool
