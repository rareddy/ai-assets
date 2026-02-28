# Quickstart: Status Report Agent

**Branch**: `001-status-report-agent`
**Date**: 2026-02-28

---

## Prerequisites

- Docker installed (for containerised execution), **or** Python 3.12+ with `uv`
- API credentials for at least one data source (see Step 2)
- Google account (for Calendar, Drive, Gmail) — OAuth consent required once

---

## Step 1 — Clone and configure

```bash
git clone <repo-url> status-report
cd status-report
cp .env.example .env
```

Edit `.env` and fill in credentials for the sources you want to enable:

```env
# Required for all runs
ANTHROPIC_API_KEY=sk-ant-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

# Jira (optional)
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_USER_EMAIL=you@yourorg.com
JIRA_API_TOKEN=your-jira-token

# Slack (optional)
SLACK_BOT_TOKEN=xoxb-...

# GitHub (optional)
GITHUB_TOKEN=ghp_...

# Google — Calendar, Drive, Gmail (optional, all share one OAuth client)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_PROJECT_ID=...
```

---

## Step 2 — Google OAuth (one-time consent)

If you configured `GOOGLE_CLIENT_ID`, run the consent flow once to obtain refresh
tokens. This only needs to happen on first use or after token expiry.

```bash
# Local Python (no Docker needed for this step)
uv run python -m status_report.auth.google --consent
```

The browser will open. Sign in and grant the requested read-only scopes. Tokens are
saved to `~/.status-report/google_credentials.json` (chmod 600, never committed).

---

## Step 3 — Build the container

```bash
docker build -t status-report .
```

The Dockerfile installs `uv`, project dependencies, and Playwright + Chromium (for
skill browser-fallback paths).

---

## Step 4 — Run your first report

```bash
docker run --rm \
  --env-file .env \
  -v ~/.status-report:/root/.status-report:ro \
  status-report \
  --user you@yourorg.com \
  --period today \
  --format markdown
```

Expected output (Markdown):

```markdown
# Status Report — you@yourorg.com — 2026-02-28

## Key Accomplishments
- Reviewed and merged PR #412 (auth-refactor) on github/your-repo
- Updated JIRA-1023 (Deploy pipeline fix) from In Progress → Done
...

## Suggested Follow-ups
- Follow up on JIRA-1019 (blocked on design review)
```

---

## Step 5 — Common invocation patterns

```bash
# Yesterday's report in plain text
docker run --rm --env-file .env -v ~/.status-report:/root/.status-report:ro \
  status-report --user you@yourorg.com --period yesterday

# GitHub and Slack only, markdown output
docker run --rm --env-file .env -v ~/.status-report:/root/.status-report:ro \
  status-report --user you@yourorg.com --period today \
  --sources github,slack --format markdown

# Specific date range
docker run --rm --env-file .env -v ~/.status-report:/root/.status-report:ro \
  status-report --user you@yourorg.com --period 2026-02-24:2026-02-28

# JSON output (pipe to jq)
docker run --rm --env-file .env -v ~/.status-report:/root/.status-report:ro \
  status-report --user you@yourorg.com --period today --format json | jq '.sections'
```

---

## Step 6 — Inspect the audit log

Every run appends a JSONL entry to `~/.status-report/runs.log`:

```bash
# View the last 5 runs
tail -n 5 ~/.status-report/runs.log | jq .

# Check for any partial/failed runs today
grep '"outcome":"partial"\|"outcome":"failed"' ~/.status-report/runs.log | jq .
```

---

## Step 7 — Adding a new skill

1. Create `src/status_report/skills/myservice.py`:

```python
from .base import ActivitySkill, ActivityItem
from datetime import datetime

class MyServiceSkill(ActivitySkill):
    def is_configured(self) -> bool:
        return bool(os.getenv("MYSERVICE_API_TOKEN"))

    async def fetch_activity(
        self, user: str, start: datetime, end: datetime
    ) -> list[ActivityItem]:
        # implement API fetch with httpx + tenacity retry
        ...
```

2. Add credentials to `.env` and `.env.example`.
3. Add a test file at `tests/skills/test_myservice.py`.
4. Rebuild the container — the skill is auto-discovered at startup via
   `pkgutil.iter_modules()`.

No changes to `agent.py`, `config.py`, or any other core module are required.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ERROR: No skills are configured` | All env vars missing | Set at least one skill's credentials in `.env` |
| `WARNING: [jira] Credentials missing` | `JIRA_API_TOKEN` not set | Add to `.env` |
| `WARNING: [gmail] Failed after 3 attempts` | Gmail API rate limit or network issue | Retry later; check quota in Google Cloud Console |
| Google OAuth error on first run | Consent not completed | Run `uv run python -m status_report.auth.google --consent` |
| Container can't find `google_credentials.json` | Volume mount missing | Add `-v ~/.status-report:/root/.status-report:ro` |
| Report generation takes > 5 minutes | Very slow skill or network | Check `runs.log` for per-source durations; one skill may be using browser fallback |
