"""Tests for runway.engine — PromotionEngine lock→gate→deploy→commit flow."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from runway.engine import PromotionEngine, PromotionResult
from runway.gates import GateResult
from runway.triggers import DeployResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENVS_NO_GATES = {
    "project": "test",
    "environments": [
        {"name": "local", "type": "local"},
        {"name": "preview", "type": "persistent", "gates": [], "deploy_trigger": None},
    ],
}

_ENVS_WITH_CI_GATE = {
    "project": "test",
    "environments": [
        {"name": "local", "type": "local"},
        {
            "name": "preview",
            "type": "persistent",
            "gates": [{"type": "ci-pass", "command": "pytest tests/"}],
            "deploy_trigger": None,
        },
    ],
}

_ENVS_WITH_TRIGGER = {
    "project": "test",
    "environments": [
        {"name": "local", "type": "local"},
        {
            "name": "preview",
            "type": "persistent",
            "gates": [],
            "deploy_trigger": {
                "web": {"provider": "shell", "env_var": "echo deploy"}
            },
        },
    ],
}


def _write_envs(tmp_path: Path, envs: dict) -> Path:
    runway_dir = tmp_path / ".runway"
    runway_dir.mkdir()
    (runway_dir / "environments.json").write_text(json.dumps(envs), encoding="utf-8")
    return tmp_path


def _make_gate_result(passed: bool, reason: str = "") -> GateResult:
    return GateResult(passed=passed, gate_type="auto", reason=reason)


def _make_deploy_result(status: str, exit_code: int = 0) -> DeployResult:
    return DeployResult(status=status, exit_code=exit_code)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_promote_happy_path(tmp_path):
    root = _write_envs(tmp_path, _ENVS_WITH_CI_GATE)
    engine = PromotionEngine(root)

    with (
        patch("runway.engine.acquire_lock", return_value=True),
        patch("runway.engine.update_step"),
        patch("runway.engine.run_gate", return_value=_make_gate_result(True)),
        patch("runway.engine.commit_promotion") as mock_commit,
        patch.object(engine, "_resolve_commit", return_value="abc123"),
    ):
        result = engine.promote("local", "preview", "ci-bot")

    assert result.success is True
    assert result.commit == "abc123"
    mock_commit.assert_called_once()


def test_promote_already_locked(tmp_path):
    root = _write_envs(tmp_path, _ENVS_NO_GATES)
    engine = PromotionEngine(root)

    mock_lock = MagicMock()
    mock_lock.promotion_id = "prom-existing"

    with (
        patch("runway.engine.acquire_lock", return_value=False),
        patch("runway.engine.get_lock_state", return_value=mock_lock),
    ):
        result = engine.promote("local", "preview", "ci-bot")

    assert result.success is False
    assert result.reason == "already_locked"
    assert result.promotion_id == "prom-existing"


def test_promote_gate_fail(tmp_path):
    root = _write_envs(tmp_path, _ENVS_WITH_CI_GATE)
    engine = PromotionEngine(root)

    with (
        patch("runway.engine.acquire_lock", return_value=True),
        patch("runway.engine.update_step"),
        patch("runway.engine.run_gate", return_value=_make_gate_result(False, reason="exit 1")),
        patch("runway.engine.release_lock"),
    ):
        result = engine.promote("local", "preview", "ci-bot")

    assert result.success is False
    assert result.failed_step is not None
    assert result.failed_step.startswith("gate:")


def test_promote_lock_released_on_gate_fail(tmp_path):
    root = _write_envs(tmp_path, _ENVS_WITH_CI_GATE)
    engine = PromotionEngine(root)

    with (
        patch("runway.engine.acquire_lock", return_value=True),
        patch("runway.engine.update_step"),
        patch("runway.engine.run_gate", return_value=_make_gate_result(False, reason="exit 1")),
        patch("runway.engine.release_lock") as mock_release,
    ):
        engine.promote("local", "preview", "ci-bot")

    mock_release.assert_called_once_with(root, "preview")


def test_promote_no_gates(tmp_path):
    root = _write_envs(tmp_path, _ENVS_NO_GATES)
    engine = PromotionEngine(root)

    with (
        patch("runway.engine.acquire_lock", return_value=True),
        patch("runway.engine.update_step"),
        patch("runway.engine.commit_promotion") as mock_commit,
        patch.object(engine, "_resolve_commit", return_value="deadbeef"),
    ):
        result = engine.promote("local", "preview", "ci-bot")

    assert result.success is True
    assert result.commit == "deadbeef"
    mock_commit.assert_called_once()


def test_promote_deploy_trigger_fail(tmp_path):
    root = _write_envs(tmp_path, _ENVS_WITH_TRIGGER)
    engine = PromotionEngine(root)

    mock_trigger = MagicMock()
    mock_trigger.deploy.return_value = _make_deploy_result("failed", exit_code=1)

    with (
        patch("runway.engine.acquire_lock", return_value=True),
        patch("runway.engine.update_step"),
        patch("runway.engine.get_trigger", return_value=mock_trigger),
        patch("runway.engine.release_lock") as mock_release,
        patch.object(engine, "_resolve_commit", return_value="deadbeef"),
    ):
        result = engine.promote("local", "preview", "ci-bot")

    assert result.success is False
    assert result.failed_step == "deploy"
    mock_release.assert_called_once_with(root, "preview")
