"""Tests for source filtering: get_enabled_skills() and _parse_sources()."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from status_report.config import Config
from status_report.skills.base import ActivitySkill


@pytest.fixture(autouse=True)
def real_skills_only():
    """Restore registry to only real skill classes (avoids test-stub pollution)."""
    from status_report.skills import discover_skills

    discover_skills()
    saved = dict(ActivitySkill._registry)
    # Keep only classes defined in status_report.skills.* modules
    real = {
        name: cls
        for name, cls in saved.items()
        if cls.__module__.startswith("status_report.skills.")
    }
    ActivitySkill._registry.clear()
    ActivitySkill._registry.update(real)
    yield
    ActivitySkill._registry.clear()
    ActivitySkill._registry.update(saved)


# ── get_enabled_skills ────────────────────────────────────────────────────────


class TestGetEnabledSkills:
    def test_returns_all_configured_when_no_filter(self, config: Config):
        """No requested_sources → all configured skills returned."""
        from status_report.skills import discover_skills, get_enabled_skills

        discover_skills()
        enabled, not_configured = get_enabled_skills(config)
        # Config fixture has all credentials set → all skills should be enabled
        assert len(enabled) > 0
        assert not_configured == []

    def test_filters_to_single_requested_source(self, config: Config):
        """requested_sources=["github"] → only GitHubSkill returned."""
        from status_report.skills import get_enabled_skills

        enabled, not_configured = get_enabled_skills(config, ["github"])
        assert len(enabled) == 1
        assert enabled[0].__class__.__name__ == "GitHubSkill"
        assert not_configured == []

    def test_filters_to_multiple_requested_sources(self, config: Config):
        """requested_sources=["github", "slack"] → only those two skills."""
        from status_report.skills import get_enabled_skills

        enabled, not_configured = get_enabled_skills(config, ["github", "slack"])
        names = {s.__class__.__name__ for s in enabled}
        assert names == {"GitHubSkill", "SlackSkill"}
        assert not_configured == []

    def test_unknown_source_silently_skipped(self, config: Config):
        """Skill names not in registry are silently ignored (warning emitted by main.py)."""
        from status_report.skills import get_enabled_skills

        enabled, not_configured = get_enabled_skills(config, ["totally_unknown"])
        assert enabled == []
        # Unknown names are not in not_configured (they're not even in registry)
        assert not_configured == []

    def test_unconfigured_requested_source_in_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A requested source that exists in registry but has no credentials → not_configured."""
        from status_report.skills import discover_skills, get_enabled_skills

        # Remove GitHub token so GitHubSkill.is_configured() returns False
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        config_no_github = Config()
        discover_skills()
        enabled, not_configured = get_enabled_skills(config_no_github, ["github"])

        assert enabled == []
        assert "github" in not_configured

    def test_mixed_configured_and_unconfigured(self, monkeypatch: pytest.MonkeyPatch):
        """When requesting two sources, one configured and one not → correct split."""
        from status_report.skills import discover_skills, get_enabled_skills

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

        config_partial = Config()
        discover_skills()
        enabled, not_configured = get_enabled_skills(config_partial, ["github", "slack"])

        enabled_names = {s.__class__.__name__ for s in enabled}
        assert "GitHubSkill" in enabled_names
        assert "SlackSkill" not in enabled_names
        assert "slack" in not_configured
        assert "github" not in not_configured

    def test_no_requested_sources_unconfigured_not_populated(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """When requested_sources=None, not_configured is always [] (no specific request)."""
        from status_report.skills import discover_skills, get_enabled_skills

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        config_partial = Config()
        discover_skills()
        enabled, not_configured = get_enabled_skills(config_partial)

        # not_configured is empty when no filter — unconfigured skills just aren't returned
        assert not_configured == []


# ── _parse_sources (main.py) ──────────────────────────────────────────────────


class TestParseSourcesFunction:
    def test_returns_known_sources(self):
        from status_report.main import _parse_sources

        result = _parse_sources("github,slack")
        assert "github" in result
        assert "slack" in result

    def test_warns_and_excludes_unknown_source(self, capsys):
        from status_report.main import _parse_sources

        result = _parse_sources("unknown_source,github")
        captured = capsys.readouterr()
        assert "unknown_source" in captured.err
        assert "WARNING" in captured.err
        assert "github" in result
        assert "unknown_source" not in result

    def test_case_insensitive_normalisation(self):
        from status_report.main import _parse_sources

        result = _parse_sources("GitHub,SLACK")
        assert "github" in result
        assert "slack" in result

    def test_trims_whitespace(self):
        from status_report.main import _parse_sources

        result = _parse_sources("  github , slack  ")
        assert "github" in result
        assert "slack" in result

    def test_all_unknown_returns_empty(self, capsys):
        from status_report.main import _parse_sources

        result = _parse_sources("fake1,fake2")
        assert result == []
        captured = capsys.readouterr()
        assert "fake1" in captured.err
        assert "fake2" in captured.err

    def test_valid_source_names(self):
        from status_report.main import _parse_sources

        for source in ("jira", "slack", "github", "calendar", "gdrive", "gmail"):
            result = _parse_sources(source)
            assert source in result
