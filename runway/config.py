"""Environment config reader for runway.

Loads and validates the consuming project's ``.runway/environments.json``
file against the :class:`EnvironmentConfig` Pydantic schema.

Usage::

    from pathlib import Path
    from runway.config import load_environments, get_environment, ConfigError, load_runway_config

    config = load_environments(project_root=Path(".").resolve())
    env = get_environment(config, "staging")

    runway_cfg = load_runway_config(project_root=Path(".").resolve())
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from runway.schemas import Environment, EnvironmentConfig


class ConfigError(Exception):
    """Raised when environment configuration cannot be loaded or is invalid."""


# ---------------------------------------------------------------------------
# RunwayConfig
# ---------------------------------------------------------------------------


class RouterConfig(BaseModel):
    model_config = ConfigDict(strict=False)

    mount_prefix: str = "/api/admin/runway"
    auth_dependency: str = ""  # dotted import path; empty string means not configured

    @field_validator("mount_prefix")
    @classmethod
    def validate_mount_prefix(cls, v: str) -> str:
        if not re.match(r"^/[a-zA-Z0-9/_-]+$", v):
            raise ValueError(
                f"mount_prefix must start with / and match ^/[a-zA-Z0-9/_-]+$, got {v!r}"
            )
        if len(v) > 64:
            raise ValueError(f"mount_prefix must be <= 64 chars, got {len(v)}")
        return v


class RunwayConfig(BaseModel):
    model_config = ConfigDict(strict=False)

    state_dir: str = ".runway"
    config: str = ".runway/environments.json"
    state: str = ".runway/environment-state.json"
    health_endpoint: str = "/health"
    lock_timeout_minutes: int = 30
    preview_idle_hours: int = 48
    router: RouterConfig = RouterConfig()

    @field_validator("lock_timeout_minutes")
    @classmethod
    def validate_lock_timeout(cls, v: int) -> int:
        if not (1 <= v <= 1440):
            raise ValueError(f"lock_timeout_minutes must be between 1 and 1440, got {v}")
        return v

    @field_validator("preview_idle_hours")
    @classmethod
    def validate_preview_idle(cls, v: int) -> int:
        if not (1 <= v <= 720):
            raise ValueError(f"preview_idle_hours must be between 1 and 720, got {v}")
        return v


def load_runway_config(project_root: Path) -> RunwayConfig:
    """Load and validate ``runway.yaml`` from the project root.

    Args:
        project_root: The root directory of the consuming project.

    Returns:
        A validated :class:`RunwayConfig` instance. Returns defaults if
        ``runway.yaml`` is not present.

    Raises:
        ConfigError: If the file exists but fails Pydantic schema validation.
    """
    config_path = project_root / "runway.yaml"

    if not config_path.exists():
        print(f"Warning: runway.yaml not found at {config_path}; using defaults.", file=sys.stderr)
        return RunwayConfig()

    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read runway.yaml: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"runway.yaml is not valid YAML: {exc}") from exc

    if data is None:
        data = {}

    try:
        return RunwayConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"runway.yaml schema validation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Environment config helpers
# ---------------------------------------------------------------------------


def load_environments(project_root: Path) -> EnvironmentConfig:
    """Load and validate ``environments.json`` from the project's ``.runway/`` directory.

    Args:
        project_root: The root directory of the consuming project.

    Returns:
        A validated :class:`EnvironmentConfig` instance.

    Raises:
        ConfigError: If the file does not exist, cannot be parsed as JSON,
            or fails Pydantic schema validation.
    """
    config_path = project_root / ".runway" / "environments.json"

    if not config_path.exists():
        raise ConfigError(f"No environments.json found at {config_path}")

    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read environments.json at {config_path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"environments.json is not valid JSON: {exc}") from exc

    try:
        return EnvironmentConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"environments.json schema validation failed: {exc}") from exc


def get_environment(config: EnvironmentConfig, name: str) -> Environment:
    """Return the :class:`Environment` with the given name.

    Args:
        config: A validated environment configuration.
        name: The environment name to look up.

    Returns:
        The matching :class:`Environment`.

    Raises:
        ConfigError: If no environment with the given name exists.
    """
    for env in config.environments:
        if env.name == name:
            return env
    raise ConfigError(
        f"Environment {name!r} not found. Available: {[e.name for e in config.environments]}"
    )


def get_promotion_chain(
    config: EnvironmentConfig, from_env: str, to_env: str
) -> tuple[Environment, Environment]:
    """Return the source and target environments for a promotion."""
    source = get_environment(config, from_env)
    target = get_environment(config, to_env)
    return source, target
