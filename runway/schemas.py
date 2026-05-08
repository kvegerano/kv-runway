"""Pydantic v2 schemas for runway environment management.

Defines the full type hierarchy for environment configuration and state:
- Configuration schemas: EnvironmentConfig, Environment, Gate, DeployTriggerConfig,
  HealthCheck, NotificationConfig
- State schemas: EnvironmentStateEntry, LockState, PromotionRecord, EnvironmentStatus
- Enums: EnvironmentType, GateType, GateStrategy
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EnvironmentType(str, Enum):
    """The lifecycle type of an environment."""

    local = "local"
    ephemeral = "ephemeral"
    persistent = "persistent"


class GateType(str, Enum):
    """The type of gate that must pass before a promotion proceeds."""

    ci_pass = "ci-pass"
    manual_approval = "manual-approval"


class GateStrategy(str, Enum):
    """How a CI gate determines which command to run."""

    local_first = "local-first"
    remote_only = "remote-only"
    any = "any"
    both = "both"


class EnvironmentStatus(str, Enum):
    """The current health status of an environment."""

    healthy = "healthy"
    degraded = "degraded"
    deploying = "deploying"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Configuration schemas
# ---------------------------------------------------------------------------


class Gate(BaseModel):
    """A gate that must pass before a promotion can proceed to an environment."""

    model_config = ConfigDict(strict=False)

    type: GateType
    strategy: GateStrategy = GateStrategy.local_first
    command: str | None = None
    timeout_hours: int = 72


class DeployTriggerConfig(BaseModel):
    """Configuration for a single deploy trigger provider."""

    model_config = ConfigDict(strict=False)

    provider: str
    hook_env_var: str | None = None
    env_var: str | None = None


class HealthCheck(BaseModel):
    """Health check configuration for an environment."""

    model_config = ConfigDict(strict=False)

    url: str
    timeout_seconds: int = 30


class NotificationConfig(BaseModel):
    """Notification sink configuration."""

    model_config = ConfigDict(strict=False)

    provider: str
    webhook_env_var: str


class Environment(BaseModel):
    """A single declared environment in the project's environment chain."""

    model_config = ConfigDict(strict=False)

    name: str
    type: EnvironmentType
    branch: str | None = None
    branch_pattern: str | None = None
    auto_deploy: bool = False
    gates: list[Gate] = []
    deploy_trigger: dict[str, DeployTriggerConfig] | None = None
    health_check: HealthCheck | None = None
    required_env_vars: list[str] = []
    migrations: str | None = None
    urls: dict[str, str] = {}
    notifications: list[NotificationConfig] = []


class EnvironmentConfig(BaseModel):
    """Top-level environment configuration loaded from .runway/environments.json."""

    model_config = ConfigDict(strict=False)

    project: str
    environments: list[Environment]


# ---------------------------------------------------------------------------
# State schemas
# ---------------------------------------------------------------------------


class LockState(BaseModel):
    """A lock held by an in-progress promotion on a specific environment."""

    model_config = ConfigDict(strict=False)

    promotion_id: str
    actor: str
    started_at: datetime
    expires_at: datetime
    current_step: str
    step_started_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None


class PromotionRecord(BaseModel):
    """An audit record for a completed (or in-progress) promotion."""

    model_config = ConfigDict(strict=False)

    commit: str
    branch: str
    deployed_at: datetime
    deployed_by: str
    approved_by: str | None = None
    gates_passed: list[str] = []
    gate_strategy: str
    migration_result: str | None = None
    health_check_result: str | None = None
    duration_seconds: int
    current_step: str | None = None


class EnvironmentStateEntry(BaseModel):
    """The persisted state for a single environment."""

    model_config = ConfigDict(strict=False)

    status: EnvironmentStatus = EnvironmentStatus.unknown
    state_version: int = 0
    lock: LockState | None = None
    current: PromotionRecord | None = None
    history: list[PromotionRecord] = []
