"""Tests for runway.config — config reader and helper functions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from runway.config import ConfigError, RunwayConfig, get_environment, get_promotion_chain, load_environments, load_runway_config
from runway.schemas import EnvironmentConfig, EnvironmentType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CONFIG = {
    "project": "myapp",
    "environments": [
        {"name": "local", "type": "local"},
        {"name": "staging", "type": "persistent", "branch": "develop"},
        {"name": "prod", "type": "persistent", "branch": "main"},
    ],
}


def _write_environments(tmp_path: Path, data: dict) -> Path:
    runway_dir = tmp_path / ".runway"
    runway_dir.mkdir()
    (runway_dir / "environments.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def _write_runway_yaml(tmp_path: Path, data: dict) -> Path:
    (tmp_path / "runway.yaml").write_text(yaml.dump(data), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# load_environments
# ---------------------------------------------------------------------------


def test_load_environments_success(tmp_path: Path) -> None:
    project_root = _write_environments(tmp_path, VALID_CONFIG)
    config = load_environments(project_root)
    assert isinstance(config, EnvironmentConfig)
    assert config.project == "myapp"
    assert len(config.environments) == 3


def test_load_environments_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="No environments.json found at"):
        load_environments(tmp_path)


def test_load_environments_invalid_json(tmp_path: Path) -> None:
    runway_dir = tmp_path / ".runway"
    runway_dir.mkdir()
    (runway_dir / "environments.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_environments(tmp_path)


# ---------------------------------------------------------------------------
# load_runway_config
# ---------------------------------------------------------------------------


def test_load_runway_config_missing_returns_defaults(tmp_path: Path) -> None:
    cfg = load_runway_config(tmp_path)
    assert isinstance(cfg, RunwayConfig)
    assert cfg.state_dir == ".runway"
    assert cfg.config == ".runway/environments.json"
    assert cfg.state == ".runway/environment-state.json"
    assert cfg.health_endpoint == "/health"
    assert cfg.lock_timeout_minutes == 30
    assert cfg.preview_idle_hours == 48


def test_load_runway_config_valid(tmp_path: Path) -> None:
    _write_runway_yaml(tmp_path, {
        "state_dir": ".runway",
        "lock_timeout_minutes": 60,
        "preview_idle_hours": 24,
        "router": {
            "mount_prefix": "/api/admin/runway",
            "auth_dependency": "app.deps.require_admin",
        },
    })
    cfg = load_runway_config(tmp_path)
    assert cfg.lock_timeout_minutes == 60
    assert cfg.preview_idle_hours == 24
    assert cfg.router.auth_dependency == "app.deps.require_admin"


def test_load_runway_config_invalid_lock_timeout(tmp_path: Path) -> None:
    _write_runway_yaml(tmp_path, {"lock_timeout_minutes": 0})
    with pytest.raises(ConfigError):
        load_runway_config(tmp_path)


def test_runway_config_defaults() -> None:
    cfg = RunwayConfig()
    assert cfg.state_dir == ".runway"
    assert cfg.config == ".runway/environments.json"
    assert cfg.state == ".runway/environment-state.json"
    assert cfg.health_endpoint == "/health"
    assert cfg.lock_timeout_minutes == 30
    assert cfg.preview_idle_hours == 48
    assert cfg.router.mount_prefix == "/api/admin/runway"
    assert cfg.router.auth_dependency == ""


# ---------------------------------------------------------------------------
# get_environment
# ---------------------------------------------------------------------------


def test_get_environment_found(tmp_path: Path) -> None:
    project_root = _write_environments(tmp_path, VALID_CONFIG)
    config = load_environments(project_root)
    env = get_environment(config, "staging")
    assert env.name == "staging"
    assert env.type == EnvironmentType.persistent


def test_get_environment_not_found(tmp_path: Path) -> None:
    project_root = _write_environments(tmp_path, VALID_CONFIG)
    config = load_environments(project_root)
    with pytest.raises(ConfigError, match="not found"):
        get_environment(config, "nonexistent")


# ---------------------------------------------------------------------------
# get_promotion_chain
# ---------------------------------------------------------------------------


def test_get_promotion_chain(tmp_path: Path) -> None:
    project_root = _write_environments(tmp_path, VALID_CONFIG)
    config = load_environments(project_root)
    source, target = get_promotion_chain(config, "local", "staging")
    assert source.name == "local"
    assert target.name == "staging"


# ---------------------------------------------------------------------------
# load_runway_config — error handling
# ---------------------------------------------------------------------------


def test_load_runway_config_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "runway.yaml").write_text("key: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_runway_config(tmp_path)


def test_load_runway_config_empty_file(tmp_path: Path) -> None:
    (tmp_path / "runway.yaml").write_text("", encoding="utf-8")
    cfg = load_runway_config(tmp_path)
    assert isinstance(cfg, RunwayConfig)
    assert cfg.state_dir == ".runway"
