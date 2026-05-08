"""Tests for the /promote skill helper."""
from __future__ import annotations

import importlib.util
import pathlib
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

# Load helper.py directly without requiring it to be an installed package.
_spec = importlib.util.spec_from_file_location(
    "promote_helper",
    pathlib.Path(__file__).parent.parent / "skills" / "promote" / "helper.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def test_parse_args_two_args():
    result = mod._parse_args(["prog", "local", "preview"])
    assert result == ("local", "preview")


def test_parse_args_arrow_notation():
    result = mod._parse_args(["prog", "local", "->", "preview"])
    assert result == ("local", "preview")


def test_parse_args_invalid_exits():
    with pytest.raises(SystemExit) as exc_info:
        mod._parse_args(["prog"])
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Router mode
# ---------------------------------------------------------------------------


def test_promote_via_router_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"success": True, "commit": "abc123"}

    with patch("httpx.post", return_value=mock_response):
        with pytest.raises(SystemExit) as exc_info:
            mod._promote_via_router("local", "preview", "http://127.0.0.1:8000", "tok")
    assert exc_info.value.code == 0


def test_promote_via_router_failure():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": False,
        "failed_step": "gate",
        "reason": "tests failed",
    }

    with patch("httpx.post", return_value=mock_response):
        with pytest.raises(SystemExit) as exc_info:
            mod._promote_via_router("local", "preview", "http://127.0.0.1:8000", "tok")
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# In-process mode
# ---------------------------------------------------------------------------


@dataclass
class _FakeResult:
    success: bool
    promotion_id: str = "prom-test"
    commit: str | None = None
    duration_seconds: int = 0
    failed_step: str | None = None
    reason: str | None = None


def test_promote_in_process_success():
    fake_result = _FakeResult(success=True, commit="abc123", duration_seconds=5)
    mock_engine = MagicMock()
    mock_engine.promote.return_value = fake_result

    with patch("runway.engine.PromotionEngine", return_value=mock_engine):
        with pytest.raises(SystemExit) as exc_info:
            mod._promote_in_process("local", "preview", pathlib.Path("."))
    assert exc_info.value.code == 0


def test_promote_in_process_failure():
    fake_result = _FakeResult(success=False, failed_step="gate", reason="failed")
    mock_engine = MagicMock()
    mock_engine.promote.return_value = fake_result

    with patch("runway.engine.PromotionEngine", return_value=mock_engine):
        with pytest.raises(SystemExit) as exc_info:
            mod._promote_in_process("local", "preview", pathlib.Path("."))
    assert exc_info.value.code == 1
