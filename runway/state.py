"""Environment state manager for runway.

Provides atomic read/write of ``environment-state.json`` with exclusive file
locking for safe concurrent access on a single orchestrator host.

Design:
- ``environment-state.json.lock`` is a *stable* lock file -- it is never
  renamed or deleted. portalocker is acquired on this file before every read
  or write of the state file.
- The state file itself is written via atomic rename:
  NamedTemporaryFile -> fsync -> os.replace -> release lock.

Scope: single-orchestrator-host only. Not a distributed lock.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import portalocker

from runway.schemas import (
    EnvironmentStateEntry,
    EnvironmentStatus,
    EnvironmentType,
    LockState,
    PromotionRecord,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATE_FILE = "environment-state.json"
_LOCK_FILE = "environment-state.json.lock"
_STATE_DIR = ".runway"

_DEFAULT_LOCK_EXPIRY_MINUTES = 30

_PERSISTENT_HISTORY_LIMIT = 50
_EPHEMERAL_HISTORY_LIMIT = 10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _state_path(project_root: Path) -> Path:
    return project_root / _STATE_DIR / _STATE_FILE


def _lock_path(project_root: Path) -> Path:
    return project_root / _STATE_DIR / _LOCK_FILE


def _ensure_state_dir(project_root: Path) -> None:
    (project_root / _STATE_DIR).mkdir(parents=True, exist_ok=True)


def _parse_state(raw: dict[str, Any]) -> dict[str, EnvironmentStateEntry]:
    """Parse a raw JSON dict into a map of env_name -> EnvironmentStateEntry."""
    result: dict[str, EnvironmentStateEntry] = {}
    for name, entry_data in raw.items():
        if isinstance(entry_data, dict):
            result[name] = EnvironmentStateEntry.model_validate(entry_data)
    return result


def _serialise_state(state: dict[str, EnvironmentStateEntry]) -> dict[str, Any]:
    """Serialise a state map to a JSON-compatible dict."""
    return {name: entry.model_dump(mode="json") for name, entry in state.items()}


def _write_state_atomic(
    project_root: Path,
    state: dict[str, EnvironmentStateEntry],
) -> None:
    """Write state atomically: NamedTemporaryFile -> fsync -> os.replace.

    The file lock must already be held by the caller.
    """
    state_path = _state_path(project_root)
    state_dir = state_path.parent
    state_dir.mkdir(parents=True, exist_ok=True)

    raw = _serialise_state(state)
    encoded = json.dumps(raw, indent=2, default=str)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=state_dir,
        prefix=".state-",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        tmp.write(encoded)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, state_path)
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_state(project_root: Path) -> dict[str, EnvironmentStateEntry]:
    """Read the current environment state file.

    Returns an empty dict if the file does not exist (fresh project).

    Args:
        project_root: The root directory of the consuming project.

    Returns:
        A mapping of environment name to :class:`EnvironmentStateEntry`.
    """
    state_path = _state_path(project_root)
    if not state_path.exists():
        return {}

    raw = json.loads(state_path.read_text(encoding="utf-8"))
    return _parse_state(raw)


def acquire_lock(
    project_root: Path,
    env_name: str,
    actor: str,
    promotion_id: str,
    first_step: str,
    *,
    lock_expiry_minutes: int = _DEFAULT_LOCK_EXPIRY_MINUTES,
) -> bool:
    """Acquire the promotion lock for an environment.

    Uses a dedicated stable lock file (``environment-state.json.lock``) with
    ``portalocker`` for mutual exclusion. The state file is read under the lock,
    checked for an existing non-expired lock, and written back atomically.

    Args:
        project_root: The consuming project root.
        env_name: The environment to lock.
        actor: The actor performing the promotion.
        promotion_id: A unique promotion ID.
        first_step: The first step of the promotion.
        lock_expiry_minutes: How long before a lock is considered expired.

    Returns:
        ``True`` if the lock was acquired, ``False`` if the environment is
        already locked by an active (non-expired) lock.
    """
    _ensure_state_dir(project_root)
    lock_file_path = _lock_path(project_root)

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=lock_expiry_minutes)

    with open(lock_file_path, "a", encoding="utf-8") as lock_fd:
        portalocker.lock(lock_fd, portalocker.LOCK_EX)
        try:
            state = read_state(project_root)
            entry = state.get(env_name, EnvironmentStateEntry())

            existing_lock = entry.lock
            if existing_lock is not None and existing_lock.expires_at > now:
                return False

            if existing_lock is not None and existing_lock.expires_at <= now:
                logger.warning(
                    "Overwriting expired lock for %s (was held by %s, expired %s)",
                    env_name,
                    existing_lock.actor,
                    existing_lock.expires_at.isoformat(),
                )

            new_lock = LockState(
                promotion_id=promotion_id,
                actor=actor,
                started_at=now,
                expires_at=expires_at,
                current_step=first_step,
                step_started_at=now,
            )
            entry.lock = new_lock
            entry.status = EnvironmentStatus.deploying
            entry.state_version += 1
            state[env_name] = entry

            _write_state_atomic(project_root, state)
            return True
        finally:
            portalocker.unlock(lock_fd)


def release_lock(project_root: Path, env_name: str) -> None:
    """Release the promotion lock for an environment.

    Args:
        project_root: The consuming project root.
        env_name: The environment to unlock.
    """
    _ensure_state_dir(project_root)
    lock_file_path = _lock_path(project_root)

    with open(lock_file_path, "a", encoding="utf-8") as lock_fd:
        portalocker.lock(lock_fd, portalocker.LOCK_EX)
        try:
            state = read_state(project_root)
            entry = state.get(env_name, EnvironmentStateEntry())
            entry.lock = None
            entry.state_version += 1
            state[env_name] = entry
            _write_state_atomic(project_root, state)
        finally:
            portalocker.unlock(lock_fd)


def update_step(project_root: Path, env_name: str, step: str) -> None:
    """Update the current step in the active lock record.

    Args:
        project_root: The consuming project root.
        env_name: The environment whose lock step is being updated.
        step: The new step name.
    """
    _ensure_state_dir(project_root)
    lock_file_path = _lock_path(project_root)

    with open(lock_file_path, "a", encoding="utf-8") as lock_fd:
        portalocker.lock(lock_fd, portalocker.LOCK_EX)
        try:
            state = read_state(project_root)
            entry = state.get(env_name, EnvironmentStateEntry())
            if entry.lock is not None:
                entry.lock.current_step = step
                entry.lock.step_started_at = datetime.now(UTC)
                state[env_name] = entry
                _write_state_atomic(project_root, state)
        finally:
            portalocker.unlock(lock_fd)


def commit_promotion(
    project_root: Path,
    env_name: str,
    result: PromotionRecord,
    *,
    env_type: EnvironmentType = EnvironmentType.persistent,
) -> None:
    """Record a completed promotion in the environment state.

    Args:
        project_root: The consuming project root.
        env_name: The environment that was promoted.
        result: The promotion record to commit.
        env_type: Determines the history retention limit
            (50 for persistent, 10 for ephemeral/local).
    """
    _ensure_state_dir(project_root)
    lock_file_path = _lock_path(project_root)

    limit = (
        _PERSISTENT_HISTORY_LIMIT
        if env_type == EnvironmentType.persistent
        else _EPHEMERAL_HISTORY_LIMIT
    )

    with open(lock_file_path, "a", encoding="utf-8") as lock_fd:
        portalocker.lock(lock_fd, portalocker.LOCK_EX)
        try:
            state = read_state(project_root)
            entry = state.get(env_name, EnvironmentStateEntry())

            entry.history = [result, *entry.history][:limit]
            entry.current = result
            entry.status = EnvironmentStatus.healthy
            entry.lock = None
            entry.state_version += 1

            state[env_name] = entry
            _write_state_atomic(project_root, state)
        finally:
            portalocker.unlock(lock_fd)


def mark_degraded(project_root: Path, env_name: str, reason: str) -> None:
    """Mark an environment as degraded (e.g. after a failed health check).

    Args:
        project_root: The consuming project root.
        env_name: The environment to mark degraded.
        reason: A short description of why it was degraded (logged only).
    """
    _ensure_state_dir(project_root)
    lock_file_path = _lock_path(project_root)

    logger.warning("Marking %s as degraded: %s", env_name, reason)

    with open(lock_file_path, "a", encoding="utf-8") as lock_fd:
        portalocker.lock(lock_fd, portalocker.LOCK_EX)
        try:
            state = read_state(project_root)
            entry = state.get(env_name, EnvironmentStateEntry())
            entry.status = EnvironmentStatus.degraded
            entry.state_version += 1
            state[env_name] = entry
            _write_state_atomic(project_root, state)
        finally:
            portalocker.unlock(lock_fd)


def get_lock_state(project_root: Path, env_name: str) -> LockState | None:
    """Return the current lock for the given environment, or None.

    Args:
        project_root: The consuming project root.
        env_name: The environment to query.

    Returns:
        The :class:`LockState` if the environment has a lock (expired or not),
        otherwise ``None``.
    """
    state = read_state(project_root)
    entry = state.get(env_name)
    if entry is None:
        return None
    return entry.lock
