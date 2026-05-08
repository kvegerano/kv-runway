"""Tests for the /env skill helper."""
from __future__ import annotations

import importlib.util
import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

# Load helper.py directly without requiring it to be an installed package.
_spec = importlib.util.spec_from_file_location(
    "env_helper",
    pathlib.Path(__file__).parent.parent / "skills" / "env" / "helper.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CONFIG = {
    "project": "myapp",
    "environments": [
        {"name": "local", "type": "local"},
        {"name": "staging", "type": "persistent", "branch": "develop"},
    ],
}


def _write_environments(tmp_path: pathlib.Path, data: dict) -> pathlib.Path:
    runway_dir = tmp_path / ".runway"
    runway_dir.mkdir(parents=True, exist_ok=True)
    (runway_dir / "environments.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# test_status_local_prints_table
# ---------------------------------------------------------------------------


def test_status_local_prints_table(tmp_path, capsys):
    project_root = _write_environments(tmp_path, _VALID_CONFIG)
    mod._cmd_status_local(project_root)
    out = capsys.readouterr().out
    assert "name" in out
    assert "local" in out
    assert "staging" in out


# ---------------------------------------------------------------------------
# test_status_local_shows_locked_by
# ---------------------------------------------------------------------------


def test_status_local_shows_locked_by(tmp_path, capsys):
    from datetime import UTC, datetime, timedelta

    from runway.schemas import (
        EnvironmentStateEntry,
        EnvironmentStatus,
        LockState,
    )

    project_root = _write_environments(tmp_path, _VALID_CONFIG)

    now = datetime.now(UTC)
    lock = LockState(
        promotion_id="prom-1",
        actor="ci-bot",
        started_at=now,
        expires_at=now + timedelta(minutes=30),
        current_step="deploy",
        step_started_at=now,
    )
    entry = EnvironmentStateEntry(status=EnvironmentStatus.deploying, lock=lock)
    state = {"staging": entry.model_dump(mode="json")}

    runway_dir = tmp_path / ".runway"
    (runway_dir / "environment-state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    mod._cmd_status_local(project_root)
    out = capsys.readouterr().out
    assert "ci-bot" in out


# ---------------------------------------------------------------------------
# test_status_router_success
# ---------------------------------------------------------------------------


def test_status_router_success(capsys):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"name": "local", "type": "local", "status": "healthy", "locked_by": None},
        {"name": "staging", "type": "persistent", "status": "deploying", "locked_by": "ci-bot"},
    ]

    with patch("httpx.get", return_value=mock_response):
        mod._cmd_status_router("http://127.0.0.1:8000", "tok")

    out = capsys.readouterr().out
    assert "local" in out
    assert "staging" in out
    assert "ci-bot" in out


# ---------------------------------------------------------------------------
# test_status_router_failure
# ---------------------------------------------------------------------------


def test_status_router_failure(capsys):
    mock_response = MagicMock()
    mock_response.status_code = 401

    with patch("httpx.get", return_value=mock_response):
        with pytest.raises(SystemExit) as exc_info:
            mod._cmd_status_router("http://127.0.0.1:8000", "bad-tok")
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# test_lock_release_confirmed
# ---------------------------------------------------------------------------


def test_lock_release_confirmed(tmp_path):
    mock_release = MagicMock()

    with patch("builtins.input", return_value="y"):
        with patch("runway.state.release_lock", mock_release):
            mod._cmd_lock_release("staging", tmp_path)

    mock_release.assert_called_once_with(tmp_path, "staging")


# ---------------------------------------------------------------------------
# test_lock_release_cancelled
# ---------------------------------------------------------------------------


def test_lock_release_cancelled(tmp_path, capsys):
    mock_release = MagicMock()

    with patch("builtins.input", return_value="n"):
        with patch("runway.state.release_lock", mock_release):
            with pytest.raises(SystemExit) as exc_info:
                mod._cmd_lock_release("staging", tmp_path)

    assert exc_info.value.code == 0
    mock_release.assert_not_called()
    out = capsys.readouterr().out
    assert "Cancelled." in out


# ---------------------------------------------------------------------------
# test_unknown_subcommand_exits_1
# ---------------------------------------------------------------------------


def test_unknown_subcommand_exits_1():
    with pytest.raises(SystemExit) as exc_info:
        mod.main(["prog", "unknown"])
    assert exc_info.value.code == 1
