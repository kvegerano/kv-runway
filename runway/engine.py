"""Promotion engine for kv-runway v0.1.

Step ordering: acquire lock → run gates → deploy → commit state + release lock.
No SSE, no notifications, no health check, no migrations in v0.1.
"""
from __future__ import annotations

import logging
import os
import secrets
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from runway.config import get_environment, get_promotion_chain, load_environments
from runway.gates import run_gate
from runway.schemas import GateType, PromotionRecord
from runway.state import (
    acquire_lock,
    commit_promotion,
    get_lock_state,
    release_lock,
    update_step,
)
from runway.triggers import ShellTrigger, get_trigger

logger = logging.getLogger(__name__)


@dataclass
class PromotionResult:
    success: bool
    promotion_id: str
    commit: str | None = None
    duration_seconds: int = 0
    failed_step: str | None = None
    reason: str | None = None


class PromotionEngine:
    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._config = load_environments(project_root)

    def promote(self, from_env: str, to_env: str, actor: str) -> PromotionResult:
        resolved_actor = self._resolve_actor(actor)
        promotion_id = f"prom-{secrets.token_urlsafe(16)}"
        start_time = time.monotonic()
        env = get_environment(self._config, to_env)

        # ① ACQUIRE LOCK
        acquired = acquire_lock(
            self._project_root,
            env_name=to_env,
            actor=resolved_actor,
            promotion_id=promotion_id,
            first_step="gate",
        )
        if not acquired:
            existing_lock = get_lock_state(self._project_root, to_env)
            existing_id = existing_lock.promotion_id if existing_lock else promotion_id
            return PromotionResult(
                success=False,
                promotion_id=existing_id,
                reason="already_locked",
                duration_seconds=0,
            )

        try:
            # ② RUN GATES
            import runway.state as state_module
            for gate in env.gates:
                step_name = f"gate:{gate.type.value}"
                update_step(self._project_root, to_env, step_name)
                gate_result = run_gate(gate, to_env, self._project_root, state_module)
                if not gate_result.passed:
                    return self._fail(to_env, promotion_id, step_name, start_time, gate_result.reason)

            # ③ DEPLOY
            update_step(self._project_root, to_env, "deploy")
            current_commit = self._resolve_commit()

            if env.deploy_trigger:
                for tier_name, trigger_config in env.deploy_trigger.items():
                    trigger = get_trigger({"type": trigger_config.provider, "command": trigger_config.env_var or ""})
                    deploy_result = trigger.deploy()
                    if deploy_result.status != "success":
                        return self._fail(
                            to_env, promotion_id, "deploy", start_time,
                            f"deploy trigger {tier_name!r} failed (exit {deploy_result.exit_code})"
                        )

            # ④ COMMIT STATE (releases lock)
            duration = int(time.monotonic() - start_time)
            record = PromotionRecord(
                commit=current_commit,
                branch=env.branch or "main",
                deployed_at=datetime.now(UTC),
                deployed_by=resolved_actor,
                gates_passed=[f"gate:{g.type.value}" for g in env.gates],
                gate_strategy=str(env.gates[0].strategy.value) if env.gates else "none",
                duration_seconds=duration,
            )
            commit_promotion(self._project_root, to_env, record, env_type=env.type)

            return PromotionResult(
                success=True,
                promotion_id=promotion_id,
                commit=current_commit,
                duration_seconds=duration,
            )

        except Exception as exc:
            logger.exception("Unexpected error during promotion of %s", to_env)
            return self._fail(to_env, promotion_id, "unknown", start_time, f"unexpected error: {exc}")

    def _resolve_actor(self, actor: str) -> str:
        if actor:
            return actor
        from_env = os.environ.get("RUNWAY_ACTOR")
        if from_env:
            return from_env
        try:
            return subprocess.check_output(
                ["git", "config", "user.name"], text=True, cwd=str(self._project_root)
            ).strip()
        except Exception:
            return "unknown"

    def _resolve_commit(self) -> str:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, cwd=str(self._project_root)
            ).strip()
        except Exception:
            return "unknown"

    def _fail(
        self, env_name: str, promotion_id: str, step: str, start_time: float, reason: str
    ) -> PromotionResult:
        duration = int(time.monotonic() - start_time)
        try:
            release_lock(self._project_root, env_name)
        except Exception:
            logger.exception("Error releasing lock for %s at %s", env_name, step)
        return PromotionResult(
            success=False,
            promotion_id=promotion_id,
            duration_seconds=duration,
            failed_step=step,
            reason=reason,
        )
