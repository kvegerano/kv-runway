"""Tests for runway.utils — scrub_secrets pure utility function."""

from __future__ import annotations

from runway.utils import scrub_secrets


def test_scrub_github_token() -> None:
    token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"
    result = scrub_secrets(f"Cloning with token {token}")
    assert token not in result
    assert "<REDACTED:GH_TOKEN>" in result


def test_scrub_slack_webhook() -> None:
    url = "https://hooks.slack.com/services/T12345/B67890/abcdefghijklmnopqrstuvwx"
    result = scrub_secrets(f"Sending to {url}")
    assert url not in result
    assert "<REDACTED:SLACK_WEBHOOK>" in result


def test_scrub_bearer_token() -> None:
    text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
    result = scrub_secrets(text)
    assert "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9" not in result
    assert "Authorization: Bearer <REDACTED>" in result


def test_scrub_clean_string_unchanged() -> None:
    text = "Promotion started for staging environment, step: preflight"
    assert scrub_secrets(text) == text
