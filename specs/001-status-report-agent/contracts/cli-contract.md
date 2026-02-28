# CLI Contract: Status Report Agent

**Branch**: `001-status-report-agent`
**Date**: 2026-02-28

---

## Invocation

```
python -m status_report.main [OPTIONS]
```

Or via Docker:

```
docker run --rm --env-file .env \
  -v ~/.status-report:/root/.status-report:ro \
  status-report [OPTIONS]
```

---

## Arguments

| Argument | Required | Type | Description |
|----------|----------|------|-------------|
| `--user` | ✅ | string | Target user identifier: email address or username |
| `--period` | ✅ | string | Time range (see Period Formats below) |
| `--sources` | ❌ | string | Comma-separated skill names to include. Default: all configured skills |
| `--format` | ❌ | enum | Output format: `text` \| `markdown` \| `json`. Default: `text` |

### Period Formats

| Input | Meaning |
|-------|---------|
| `today` | From 00:00 UTC today to now |
| `yesterday` | Full previous calendar day (UTC) |
| `last-24h` | Rolling last 24 hours from now |
| `YYYY-MM-DD` | Full calendar day (UTC) |
| `YYYY-MM-DD:YYYY-MM-DD` | Inclusive date range (UTC) |

### Valid `--sources` Values

`jira`, `slack`, `github`, `calendar`, `gdrive`, `gmail`

Additional skill names are valid if a corresponding skill module is present and
auto-discovered at startup.

---

## Output

Report is written to **stdout**. Logs and errors are written to **stderr**.
The JSONL audit entry is written to `~/.status-report/runs.log` (not stdout).

### Text / Markdown format

Free-form prose with section headings. Sections present only when data exists:

```
# Status Report — alice@example.com — 2026-02-28

## Key Accomplishments
...

## Tickets & Issues
...

## Code Contributions
...

## Meetings & Collaboration
...

## Documents
...

## Email Activity
...

## Suggested Follow-ups
...

---
⚠ Skipped: gdrive (credentials_missing)
```

### JSON format

```json
{
  "user": "alice@example.com",
  "period": { "label": "today", "start": "2026-02-28T00:00:00Z", "end": "2026-02-28T09:45:00Z" },
  "generated_at": "2026-02-28T09:45:30Z",
  "sections": [
    { "heading": "Key Accomplishments", "content": "..." },
    { "heading": "Tickets & Issues", "content": "..." }
  ],
  "skipped_sources": [
    { "source": "gdrive", "reason": "credentials_missing", "attempts": 0 }
  ]
}
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success — report generated from all configured sources |
| `1` | Partial success — report generated; ≥1 source skipped |
| `2` | Complete failure — no data retrieved (all sources failed or none configured) |
| `3` | Invalid arguments (bad `--period`, unknown `--sources` value, future date, etc.) |

---

## Validation Rules

1. `--user` must be a non-empty string.
2. `--period` must match one of the five supported formats. Future dates are rejected
   immediately with exit code `3` before any data collection begins.
3. `--sources` values are validated against the discovered skill registry. Unknown names
   produce a warning (not an error); the remaining valid sources are used.
4. `--format` must be one of `text`, `markdown`, `json`. Invalid value → exit `3`.
5. If no skills are configured after validation, the agent exits with code `2` and
   a message listing the required environment variables for at least one skill.

---

## Error Messages (stderr)

| Scenario | Message format |
|----------|---------------|
| Future date | `ERROR: --period references a future date. Reports can only be generated for past or current periods.` |
| No skills configured | `ERROR: No skills are configured. Set at least one of: JIRA_API_TOKEN, SLACK_BOT_TOKEN, GITHUB_TOKEN, GOOGLE_CLIENT_ID.` |
| Unknown source name | `WARNING: Unknown source "foo" — skipping. Valid sources: jira, slack, github, calendar, gdrive, gmail.` |
| Skill transient failure (retry exhausted) | `WARNING: [jira] Failed after 3 attempts (503 Service Unavailable). Skipping.` |
| Skill permanent failure | `WARNING: [slack] Credentials missing or invalid. Skipping.` |
