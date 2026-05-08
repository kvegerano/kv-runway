"""Tests for runway.gates — auto + manual gate execution."""

from __future__ import annotations

import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from runway.gates import GateResult, run_gate
from runway.schemas import Gate, GateType, LockState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auto_gate(command: str | None = "pytest tests/", **kw) -> Gate:
    return Gate(type=GateType.ci_pass, command=command, **kw)


def _manual_gate(**kw) -> Gate:
    return Gate(type=GateType.manual_approval, **kw)


def _completed_process(returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["pytest", "tests/"], returncode=returncode, stdout="", stderr=""
    )


def _make_lock_state(approved_by: str | None = None) -> LockState:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    return LockState(
        promotion_id="prom-1",
        actor="ci-bot",
        started_at=now,
        expires_at=now + timedelta(hours=1),
        current_step="gate",
        step_started_at=now,
        approved_by=approved_by,
    )


def _state_module(get_lock_state_fn):
    """Build a minimal state-module stand-in with a get_lock_state callable."""
    mod = types.SimpleNamespace()
    mod.get_lock_state = get_lock_state_fn
    return mod


# ---------------------------------------------------------------------------
# Auto gate tests
# ---------------------------------------------------------------------------


@patch("runway.gates.subprocess.run")
def test_auto_gate_pass(mock_run: MagicMock) -> None:
    mock_run.return_value = _completed_process(returncode=0)
    result = run_gate(_auto_gate(), "staging", Path("/fake"))
    assert result.passed is True
    assert result.gate_type == "auto"
    assert result.exit_code == 0
    assert result.reason == "exit 0"


@patch("runway.gates.subprocess.run")
def test_auto_gate_fail(mock_run: MagicMock) -> None:
    mock_run.return_value = _completed_process(returncode=1)
    result = run_gate(_auto_gate(), "staging", Path("/fake"))
    assert result.passed is False
    assert result.gate_type == "auto"
    assert result.exit_code == 1
    assert result.reason == "exit 1"


def test_auto_gate_no_command() -> None:
    result = run_gate(_auto_gate(command=None), "staging", Path("/fake"))
    assert result.passed is False
    assert result.gate_type == "auto"
    assert result.reason == "no command configured"
    assert result.exit_code is None


@patch("runway.gates.subprocess.run")
def test_auto_gate_shell_false(mock_run: MagicMock) -> None:
    mock_run.return_value = _completed_process(returncode=0)
    run_gate(_auto_gate(command="pytest tests/"), "staging", Path("/fake"))
    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs["shell"] is False


def test_auto_gate_shell_operators_rejected() -> None:
    for cmd in [
        "echo foo | bar",
        "cmd1 && cmd2",
        "cmd1 || cmd2",
        "echo foo > out.txt",
        "cat < in.txt",
        "echo $(whoami)",
        "echo `id`",
        "cmd1 ; cmd2",
    ]:
        with pytest.raises(ValueError, match="shell operators"):
            run_gate(_auto_gate(command=cmd), "staging", Path("/fake"))


# ---------------------------------------------------------------------------
# Manual gate tests
# ---------------------------------------------------------------------------


@patch("runway.gates.time.sleep")
def test_manual_gate_approved(mock_sleep: MagicMock) -> None:
    lock = _make_lock_state(approved_by="alice")
    mod = _state_module(lambda _root, _env: lock)

    result = run_gate(
        _manual_gate(timeout_hours=1), "staging", Path("/fake"),
        state_module=mod,
    )
    assert result.passed is True
    assert result.gate_type == "manual"
    assert "alice" in result.reason


@patch("runway.gates.time.monotonic")
@patch("runway.gates.time.sleep")
def test_manual_gate_timeout(
    mock_sleep: MagicMock, mock_monotonic: MagicMock,
) -> None:
    lock = _make_lock_state(approved_by=None)
    mod = _state_module(lambda _root, _env: lock)

    # First call sets time.monotonic(); subsequent calls exceed deadline.
    mock_monotonic.side_effect = [0.0, 1.0, 999999.0]

    result = run_gate(
        _manual_gate(timeout_hours=1), "staging", Path("/fake"),
        state_module=mod,
    )
    assert result.passed is False
    assert result.gate_type == "manual"
    assert "timed out" in result.reason


@patch("runway.gates.time.sleep")
def test_manual_gate_lock_gone(mock_sleep: MagicMock) -> None:
    mod = _state_module(lambda _root, _env: None)

    result = run_gate(
        _manual_gate(timeout_hours=1), "staging", Path("/fake"),
        state_module=mod,
    )
    assert result.passed is False
    assert result.gate_type == "manual"
    assert "lock released" in result.reason


# ---------------------------------------------------------------------------
# Unknown gate type
# ---------------------------------------------------------------------------


def test_unknown_gate_type_raises() -> None:
    gate = _auto_gate()
    # Force an invalid type value past Pydantic validation.
    object.__setattr__(gate, "type", "unknown")

    with pytest.raises(ValueError, match="Unknown gate type"):
        run_gate(gate, "staging", Path("/fake"))
