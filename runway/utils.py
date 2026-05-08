"""Utility functions for the runway module.

Provides ``scrub_secrets`` — a pure function that redacts common token patterns
from command output strings before they are logged or emitted via SSE.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Secret pattern registry
# ---------------------------------------------------------------------------
# Each entry is a (pattern, replacement) pair. Patterns are compiled once at
# module load time for performance.

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # GitHub personal access tokens (classic): ghp_<36 chars>
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "<REDACTED:GH_TOKEN>"),
    # GitHub fine-grained PATs: github_pat_<...>
    (re.compile(r"github_pat_[A-Za-z0-9_]{82}"), "<REDACTED:GH_TOKEN>"),
    # GitHub Actions GITHUB_TOKEN / secrets: ghs_<36 chars>
    (re.compile(r"ghs_[A-Za-z0-9]{36}"), "<REDACTED:GH_TOKEN>"),
    # GitHub OAuth tokens: gho_<...>
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "<REDACTED:GH_TOKEN>"),
    # Slack webhook URLs: https://hooks.slack.com/services/T.../B.../...
    (
        re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+"),
        "<REDACTED:SLACK_WEBHOOK>",
    ),
    # Vercel tokens: typically 24-char alphanumeric after known prefixes,
    # or in Authorization headers
    (
        re.compile(r"vercel[_-]?token[=:\s]+[A-Za-z0-9]{24,}", re.IGNORECASE),
        "<REDACTED:VERCEL_TOKEN>",
    ),
    # Railway tokens (64-char hex UUID-like)
    (
        re.compile(r"railway[_-]?token[=:\s]+[A-Za-z0-9-]{36,}", re.IGNORECASE),
        "<REDACTED:RAILWAY_TOKEN>",
    ),
    # Generic Bearer token in Authorization headers
    (
        re.compile(r"(?i)Authorization:\s*Bearer\s+[A-Za-z0-9._\-]+"),
        "Authorization: Bearer <REDACTED>",
    ),
    # Generic API keys in URL query strings: ?api_key=..., ?token=..., ?key=...
    (
        re.compile(r"(?i)([?&](api[_-]?key|token|key|secret)=)[A-Za-z0-9._\-]{8,}"),
        r"\g<1><REDACTED>",
    ),
]


def scrub_secrets(text: str) -> str:
    """Redact common token patterns from command output or log strings.

    This is a best-effort scrub — it covers known token shapes for GitHub,
    Slack, Vercel, and Railway. It does not guarantee that novel or custom
    secret formats are redacted.

    Args:
        text: The raw string to scrub (e.g. subprocess stdout/stderr).

    Returns:
        A copy of ``text`` with known secret patterns replaced by their
        ``<REDACTED:TYPE>`` placeholders.
    """
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
