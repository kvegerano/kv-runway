"""Tests for runway.state — file-locked atomic state management."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from runway.schemas import (
    EnvironmentStatus,
    EnvironmentType,
    PromotionRecord,
)
from runway.state import (
    _write_state_atomic,
    acquire_lock,
    commit_promotion,
    get_lock_state,
    mark_degraded,
    read_state,
    release_lock,
    update_step,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_promotion_record(**overrides) -> PromotionRecord:
    defaults = {
        "commit": "abc1234",
        "branch": "main",
        "deployed_at": datetime.now(UTC),
        "deployed_by": "ci-bot",
        "gates_passed": ["ci-pass"],
        "gate_strategy": "local-first",
        "duration_seconds": 42,
    }
    defaults.update(overrides)
    return PromotionRecord(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_read_state_empty(tmp_path: Path) -> None:
    assert read_state(tmp_path) == {}


def test_acquire_lock_success(tmp_path: Path) -> None:
    result = acquire_lock(tmp_path, "staging", "alice", "prom-1", "preflight")
    assert result is True

    state = read_state(tmp_path)
    assert "staging" in state
    entry = state["staging"]
    assert entry.lock is not None
    assert entry.lock.promotion_id == "prom-1"
    assert entry.lock.actor == "alice"
    assert entry.lock.current_step == "preflight"
    assert entry.status == EnvironmentStatus.deploying


def test_acquire_lock_already_locked(tmp_path: Path) -> None:
    first = acquire_lock(tmp_path, "staging", "alice", "prom-1", "preflight")
    assert first is True

    second = acquire_lock(tmp_path, "staging", "bob", "prom-2", "gate")
    assert second is False

    lock = get_lock_state(tmp_path, "staging")
    assert lock is not None
    assert lock.promotion_id == "prom-1"


def test_acquire_lock_expired_lock(tmp_path: Path) -> None:
    acquire_lock(
        tmp_path, "staging", "alice", "prom-old", "preflight",
        lock_expiry_minutes=0,
    )

    result = acquire_lock(tmp_path, "staging", "bob", "prom-new", "gate")
    assert result is True

    lock = get_lock_state(tmp_path, "staging")
    assert lock is not None
    assert lock.promotion_id == "prom-new"
    assert lock.actor == "bob"


def test_release_lock(tmp_path: Path) -> None:
    acquire_lock(tmp_path, "staging", "alice", "prom-1", "preflight")
    release_lock(tmp_path, "staging")
    assert get_lock_state(tmp_path, "staging") is None


def test_update_step(tmp_path: Path) -> None:
    acquire_lock(tmp_path, "staging", "alice", "prom-1", "preflight")
    update_step(tmp_path, "staging", "deploy")

    lock = get_lock_state(tmp_path, "staging")
    assert lock is not None
    assert lock.current_step == "deploy"


def test_commit_promotion(tmp_path: Path) -> None:
    acquire_lock(tmp_path, "staging", "alice", "prom-1", "preflight")
    record = _make_promotion_record()
    commit_promotion(tmp_path, "staging", record)

    state = read_state(tmp_path)
    entry = state["staging"]
    assert entry.current is not None
    assert entry.current.commit == "abc1234"
    assert entry.lock is None
    assert entry.status == EnvironmentStatus.healthy


def test_commit_promotion_history_trimmed(tmp_path: Path) -> None:
    acquire_lock(tmp_path, "staging", "alice", "prom-1", "preflight")

    for i in range(51):
        record = _make_promotion_record(commit=f"sha-{i}")
        commit_promotion(
            tmp_path, "staging", record,
            env_type=EnvironmentType.persistent,
        )

    state = read_state(tmp_path)
    assert len(state["staging"].history) == 50


def test_mark_degraded(tmp_path: Path) -> None:
    acquire_lock(tmp_path, "staging", "alice", "prom-1", "preflight")
    mark_degraded(tmp_path, "staging", "health check failed")

    state = read_state(tmp_path)
    assert state["staging"].status == EnvironmentStatus.degraded


def test_get_lock_state_no_entry(tmp_path: Path) -> None:
    assert get_lock_state(tmp_path, "nonexistent") is None


def test_atomic_write_no_tmp_leftover(tmp_path: Path) -> None:
    acquire_lock(tmp_path, "staging", "alice", "prom-1", "preflight")
    state = read_state(tmp_path)
    _write_state_atomic(tmp_path, state)

    state_dir = tmp_path / ".runway"
    tmp_files = list(state_dir.glob("*.tmp"))
    assert tmp_files == []


def test_concurrent_lock_acquisition(tmp_path: Path) -> None:
    results: list[bool] = []
    lock = threading.Lock()

    def try_acquire() -> None:
        r = acquire_lock(tmp_path, "staging", "actor", "prom-concurrent", "gate")
        with lock:
            results.append(r)

    t1 = threading.Thread(target=try_acquire)
    t2 = threading.Thread(target=try_acquire)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(results) == [False, True]
