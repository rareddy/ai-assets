"""Slack session token extractor and browser state manager.

Automates extraction of browser session tokens (xoxc + xoxd) from the Slack
web app using Playwright. These tokens are required by korotovsky/slack-mcp-server
for full search.messages access — no workspace admin approval needed.

The same browser session is saved as playwright-state.json, which is also used
by the Playwright MCP fallback server when the primary Slack MCP is unavailable.
One login flow serves both purposes.

Usage:
    # Extract xoxc/xoxd tokens (also saves browser state for Playwright fallback)
    uv run python -m status_report.auth.slack --extract

    # Login only — establish Playwright browser session for MCP fallback
    uv run python -m status_report.auth.slack --login
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_STATE_DIR = Path.home() / ".status-report"
_STATE_FILE = _STATE_DIR / "playwright-state.json"
_TOKENS_FILE = _STATE_DIR / "slack_tokens.json"
_SLACK_APP_URL = "https://app.slack.com"


def _ensure_dir() -> None:
    """Create ~/.status-report/ with restricted permissions if needed."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_STATE_DIR, stat.S_IRWXU)  # chmod 700


def _save_secure(path: Path, data: dict) -> None:
    """Write JSON to path with chmod 600."""
    path.write_text(json.dumps(data, indent=2))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # chmod 600


def load_slack_tokens() -> dict[str, str] | None:
    """Load stored Slack session tokens.

    Returns a dict with 'xoxc' and 'xoxd' keys, or None if not found.
    Called by the MCP config builder to pass tokens to korotovsky/slack-mcp-server.
    """
    if not _TOKENS_FILE.exists():
        return None
    try:
        data = json.loads(_TOKENS_FILE.read_text())
        xoxc = data.get("xoxc_token")
        xoxd = data.get("xoxd_token")
        if xoxc and xoxd:
            return {"xoxc": xoxc, "xoxd": xoxd}
    except Exception:
        pass
    return None


async def _run_browser_session(extract_tokens: bool) -> dict[str, str] | None:
    """Open a headed browser, log in to Slack if needed, then extract tokens and/or save state.

    Args:
        extract_tokens: If True, extract xoxc/xoxd tokens in addition to saving state.

    Returns:
        Dict with 'xoxc' and 'xoxd' keys if extract_tokens=True, else None.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "ERROR: playwright not installed.\n"
            "Run: uv sync && uv run playwright install chromium",
            file=sys.stderr,
        )
        sys.exit(1)

    _ensure_dir()

    async with async_playwright() as p:
        # Always headed — user must be able to interact with the login page
        browser = await p.chromium.launch(headless=False)

        # Load persisted state if it exists (may already be logged in)
        state_kwargs: dict = {}
        if _STATE_FILE.exists():
            print(f"Found existing browser state at {_STATE_FILE} — trying to reuse session.")
            state_kwargs["storage_state"] = str(_STATE_FILE)

        context = await browser.new_context(**state_kwargs)
        page = await context.new_page()

        print("Opening Slack...")
        await page.goto(_SLACK_APP_URL)

        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass  # timeout is OK — page may still be usable

        # Check if already on the Slack client (i.e., already logged in)
        if "/client/" not in page.url:
            print(
                "\nNot logged in to Slack.\n"
                "Please sign in to your workspace in the browser window.\n"
                "Press Enter here once you are fully logged in and can see your messages..."
            )
            input()
            # Wait for navigation to the /client/ path
            try:
                await page.wait_for_url("**/client/**", timeout=120_000)
            except Exception:
                print(
                    "ERROR: Timed out waiting for Slack login. "
                    "Please log in within 2 minutes and try again.",
                    file=sys.stderr,
                )
                await browser.close()
                sys.exit(1)

        print("Logged in. Saving browser session...")

        # Save browser state (used by Playwright MCP fallback)
        await context.storage_state(path=str(_STATE_FILE))
        os.chmod(_STATE_FILE, stat.S_IRUSR | stat.S_IWUSR)  # chmod 600
        print(f"Browser state saved → {_STATE_FILE}")

        tokens = None
        if extract_tokens:
            print("Extracting session tokens...")

            # Extract xoxc token from Slack's localStorage
            xoxc_token: str | None = await page.evaluate("""() => {
                try {
                    const config = JSON.parse(localStorage.localConfig_v2);
                    // Prefer the team matching the current URL
                    const match = document.location.pathname.match(/\\/client\\/([A-Z0-9]+)/);
                    const teamId = match ? match[1] : null;
                    if (teamId && config.teams && config.teams[teamId]) {
                        return config.teams[teamId].token;
                    }
                    // Fallback: use the first available team
                    const teams = Object.values(config.teams || {});
                    return teams.length > 0 ? teams[0].token : null;
                } catch (e) {
                    return null;
                }
            }""")

            # Extract xoxd session cookie
            cookies = await context.cookies()
            xoxd_token: str | None = next(
                (
                    c["value"]
                    for c in cookies
                    if c["name"] == "d" and "slack.com" in c.get("domain", "")
                ),
                None,
            )

            if not xoxc_token:
                print(
                    "ERROR: Could not extract xoxc token from localStorage.\n"
                    "Make sure you are fully logged into a Slack workspace.",
                    file=sys.stderr,
                )
                await browser.close()
                sys.exit(1)

            if not xoxd_token:
                print(
                    "ERROR: Could not find the 'd' session cookie.\n"
                    "Make sure you are fully logged into a Slack workspace.",
                    file=sys.stderr,
                )
                await browser.close()
                sys.exit(1)

            tokens = {"xoxc": xoxc_token, "xoxd": xoxd_token}

        await browser.close()
        return tokens


async def extract_and_save() -> None:
    """Extract xoxc/xoxd tokens, save to credentials file, and print .env instructions."""
    tokens = await _run_browser_session(extract_tokens=True)
    assert tokens is not None  # guaranteed when extract_tokens=True

    _ensure_dir()
    _save_secure(
        _TOKENS_FILE,
        {"xoxc_token": tokens["xoxc"], "xoxd_token": tokens["xoxd"]},
    )
    print(f"Tokens saved → {_TOKENS_FILE}")
    print(
        "\nAdd these to your .env file:\n"
        f"SLACK_MCP_XOXC_TOKEN={tokens['xoxc']}\n"
        f"SLACK_MCP_XOXD_TOKEN={tokens['xoxd']}\n"
        "\nDone! The agent will use these tokens for Slack activity search.\n"
        f"Browser state also saved → {_STATE_FILE} (used by Playwright MCP fallback)."
    )


async def login_only() -> None:
    """Establish a Playwright browser session for the Slack MCP fallback only."""
    await _run_browser_session(extract_tokens=False)
    print(
        f"\nDone! Playwright session saved → {_STATE_FILE}\n"
        "The Playwright MCP fallback server will use this session to access Slack."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Slack session token manager — no admin approval required"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--extract",
        action="store_true",
        help=(
            "Open Slack in browser, extract xoxc/xoxd tokens, and save browser state. "
            "Run this when setting up or refreshing Slack tokens."
        ),
    )
    group.add_argument(
        "--login",
        action="store_true",
        help=(
            "Open Slack in browser and save browser state only. "
            "Use this when you only need the Playwright MCP fallback (not the primary token-based MCP)."
        ),
    )
    args = parser.parse_args()

    if args.extract:
        asyncio.run(extract_and_save())
    else:
        asyncio.run(login_only())
