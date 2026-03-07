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
import platform
import stat
import sys
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_STATE_DIR = Path.home() / ".status-report"
_STATE_FILE = _STATE_DIR / "playwright-state.json"
_TOKENS_FILE = _STATE_DIR / "slack_tokens.json"
_SLACK_APP_URL = "https://app.slack.com"

# Playwright channel to try before falling back to bundled Chromium.
# "chrome" uses the user's installed Google Chrome (already logged into Slack).
_PREFERRED_CHANNEL = "chrome"


def _ensure_dir() -> None:
    """Create ~/.status-report/ with restricted permissions if needed."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_STATE_DIR, stat.S_IRWXU)  # chmod 700


def _save_secure(path: Path, data: dict) -> None:
    """Write JSON to path with chmod 600."""
    path.write_text(json.dumps(data, indent=2))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # chmod 600


def _chrome_user_data_dir() -> Path | None:
    """Return the default Chrome user-data directory for this OS, or None."""
    system = platform.system()
    if system == "Darwin":
        p = Path.home() / "Library/Application Support/Google/Chrome"
    elif system == "Linux":
        p = Path.home() / ".config/google-chrome"
    elif system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        p = Path(local) / "Google/Chrome/User Data" if local else None
    else:
        return None
    return p if p and p.exists() else None


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


_EXTRACT_XOXC_JS = """
() => {
    // Try localConfig_v2 — the primary Slack localStorage key
    try {
        const raw = localStorage.getItem('localConfig_v2');
        if (raw) {
            const config = JSON.parse(raw);
            const teams = config.teams || {};

            // Prefer the team matching the current URL (e.g. /client/T03ABC123/)
            const match = document.location.pathname.match(/\\/client\\/([A-Z0-9]+)/i);
            const teamId = match ? match[1].toUpperCase() : null;
            if (teamId && teams[teamId] && teams[teamId].token) {
                return teams[teamId].token;
            }

            // Fallback: return the first team with a token
            for (const team of Object.values(teams)) {
                if (team && typeof team === 'object' && team.token) {
                    return team.token;
                }
            }
        }
    } catch (_) {}

    // Try the older 'localConfig' key (pre-2023 Slack)
    try {
        const raw = localStorage.getItem('localConfig');
        if (raw) {
            const config = JSON.parse(raw);
            if (config.token) return config.token;
        }
    } catch (_) {}

    return null;
}
"""


async def _wait_for_slack_client(page: object, timeout_ms: int = 60_000) -> bool:
    """Wait until the Slack client UI is fully loaded and localStorage is populated.

    Returns True if the client loaded within the timeout, False otherwise.
    """
    try:
        # Wait for the channel sidebar — reliable indicator that the app has booted
        await page.wait_for_selector(  # type: ignore[attr-defined]
            '[data-qa="channel_sidebar"], .p-channel_sidebar',
            timeout=timeout_ms,
        )
        # Give Slack a moment to finish populating localStorage after the DOM is ready
        await asyncio.sleep(2)
        return True
    except Exception:
        return False


async def _run_browser_session(extract_tokens: bool) -> dict[str, str] | None:
    """Open a headed browser, log in to Slack if needed, then extract tokens and/or save state.

    Tries to launch the user's installed Chrome first (so they may already be
    logged in). Falls back to Playwright's bundled Chromium if Chrome is not
    available or fails to launch.

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
        context = None
        used_persistent = False

        # ── Try system Chrome with the user's own profile ──────────────────
        chrome_user_data = _chrome_user_data_dir()
        if chrome_user_data:
            print(
                f"Found Chrome profile at {chrome_user_data}.\n"
                "Attempting to open Chrome with your existing session...\n"
                "(Chrome must be fully closed first — quit Chrome if it is running)"
            )
            try:
                context = await p.chromium.launch_persistent_context(
                    str(chrome_user_data),
                    channel=_PREFERRED_CHANNEL,
                    headless=False,
                    args=["--no-first-run", "--no-default-browser-check"],
                )
                used_persistent = True
                print("Opened Chrome with your existing profile.")
            except Exception as exc:
                print(
                    f"Could not open Chrome with your profile ({exc}).\n"
                    "Falling back to a fresh Playwright Chromium window."
                )
                context = None

        # ── Fallback: fresh Playwright Chromium ────────────────────────────
        if context is None:
            launch_kwargs: dict = {"headless": False}
            if _STATE_FILE.exists():
                print(
                    f"Loading previous browser session from {_STATE_FILE}...\n"
                    "(You may already be logged in)"
                )

            browser = await p.chromium.launch(**launch_kwargs)
            new_context_kwargs: dict = {}
            if _STATE_FILE.exists():
                new_context_kwargs["storage_state"] = str(_STATE_FILE)
            context = await browser.new_context(**new_context_kwargs)

        page = await context.new_page()

        print("Navigating to Slack...")
        await page.goto(_SLACK_APP_URL, wait_until="domcontentloaded")

        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass  # timeout OK — proceed anyway

        # ── Log in if not already on the client ────────────────────────────
        if "/client/" not in page.url:
            print(
                "\nNot logged in to Slack (or no workspace selected).\n"
                "Please sign in to your workspace in the browser window that just opened.\n"
                "Press Enter here once you can see your Slack messages..."
            )
            input()

            # Wait for navigation to /client/
            try:
                await page.wait_for_url("**/client/**", timeout=120_000)
            except Exception:
                print(
                    "ERROR: Timed out waiting for Slack login. "
                    "Please log in within 2 minutes and try again.",
                    file=sys.stderr,
                )
                await context.close()
                sys.exit(1)

        print("Slack client detected. Waiting for app to fully initialize...")
        loaded = await _wait_for_slack_client(page)
        if not loaded:
            print(
                "Warning: Slack client sidebar did not appear within 60 s. "
                "Proceeding anyway — token extraction may fail."
            )

        # ── Save browser state (Playwright MCP fallback) ───────────────────
        print("Saving browser session...")
        await context.storage_state(path=str(_STATE_FILE))
        os.chmod(_STATE_FILE, stat.S_IRUSR | stat.S_IWUSR)
        print(f"Browser state saved → {_STATE_FILE}")

        # ── Extract tokens ─────────────────────────────────────────────────
        tokens = None
        if extract_tokens:
            print("Extracting session tokens from Slack...")

            # Retry up to 5 times — localStorage can be slow to populate
            xoxc_token: str | None = None
            for attempt in range(5):
                xoxc_token = await page.evaluate(_EXTRACT_XOXC_JS)
                if xoxc_token and xoxc_token.startswith("xoxc-"):
                    break
                if attempt < 4:
                    print(f"  xoxc token not ready yet, retrying ({attempt + 1}/5)...")
                    await asyncio.sleep(2)

            # xoxd from the 'd' cookie on slack.com
            cookies = await context.cookies()
            xoxd_token: str | None = next(
                (
                    c["value"]
                    for c in cookies
                    if c["name"] == "d" and "slack.com" in c.get("domain", "")
                ),
                None,
            )

            if not xoxc_token or not xoxc_token.startswith("xoxc-"):
                # Diagnostic: show what localStorage keys exist
                ls_keys = await page.evaluate(
                    "() => Object.keys(localStorage).filter(k => k.includes('Config') || k.includes('slack') || k.includes('token'))"
                )
                print(
                    "ERROR: Could not extract xoxc token from localStorage.\n"
                    f"  Relevant localStorage keys found: {ls_keys}\n"
                    "  Make sure you are fully logged in and a workspace is visible.\n"
                    "  If you see your messages in Slack, you can extract the tokens manually:\n"
                    "    1. Open DevTools (F12) → Application → Local Storage → https://app.slack.com\n"
                    "    2. Find 'localConfig_v2' → expand teams → copy the 'token' value\n"
                    "    3. Open DevTools → Application → Cookies → https://app.slack.com\n"
                    "    4. Copy the value of the 'd' cookie\n"
                    "  Then add both to your .env file as SLACK_MCP_XOXC_TOKEN and SLACK_MCP_XOXD_TOKEN.",
                    file=sys.stderr,
                )
                await context.close()
                sys.exit(1)

            if not xoxd_token:
                slack_cookies = [c["name"] for c in cookies if "slack.com" in c.get("domain", "")]
                print(
                    "ERROR: Could not find the 'd' session cookie.\n"
                    f"  Cookies found for slack.com: {slack_cookies}\n"
                    "  Make sure you are fully logged into a Slack workspace.",
                    file=sys.stderr,
                )
                await context.close()
                sys.exit(1)

            tokens = {"xoxc": xoxc_token, "xoxd": xoxd_token}

        await context.close()
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
