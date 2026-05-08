"""Unified gate execution for runway promotions.

Two gate types:
- **auto** (``ci-pass``): runs a shell command via ``subprocess.run`` with
  ``shell=False`` and checks the exit code.
- **manual** (``manual-approval``): polls the state file for an approval
  flag until approved, timed out, or the lock is released externally.

Security invariants:
- ``subprocess.run`` is ALWAYS called with ``shell=False``.
- Commands are split via ``shlex.split`` -- never passed as a raw string.
- Shell operators (``|``, ``&``, ``;``, ``>``, ``<``, ``$``, `````) are
  rejected before execution.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import shlex
import subprocess
import time
from pathlib import Path

from runway import state as _default_state_module
from runway.schemas import Gate, GateType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shell-operator validation
# ---------------------------------------------------------------------------

_SHELL_OPERATORS = re.compile(r"[|&;><$`]")


def _validate_command(command: str) -> None:
    """Raise if *command* contains shell operators."""
    if _SHELL_OPERATORS.search(command):
        raise ValueError(
            f"Gate command contains shell operators which are not allowed: {command!r}"
        )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class GateResult:
    """Outcome of a gate evaluation."""

    passed: bool
    gate_type: str  # "auto" or "manual"
    reason: str = ""
    exit_code: int | None = None


# ---------------------------------------------------------------------------
# Auto gate
# ---------------------------------------------------------------------------

_MANUAL_POLL_INTERVAL = 10  # seconds


def _run_auto_gate(gate: Gate, env_name: str) -> GateResult:
    if gate.command is None:
        return GateResult(
            passed=False, gate_type="auto", reason="no command configured"
        )

    _validate_command(gate.command)

    cmd = shlex.split(gate.command)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=gate.timeout_hours * 3600,
        shell=False,
    )
    passed = result.returncode == 0
    return GateResult(
        passed=passed,
        gate_type="auto",
        reason=f"exit {result.returncode}",
        exit_code=result.returncode,
    )


# ---------------------------------------------------------------------------
# Manual gate
# ---------------------------------------------------------------------------


def _run_manual_gate(
    gate: Gate,
    env_name: str,
    project_root: Path,
    state_module: object,
) -> GateResult:
    deadline = time.monotonic() + gate.timeout_hours * 3600

    while time.monotonic() < deadline:
        lock = state_module.get_lock_state(project_root, env_name)  # type: ignore[union-attr]

        if lock is None:
            return GateResult(
                passed=False,
                gate_type="manual",
                reason="lock released before approval",
            )

        if lock.approved_by is not None:
            return GateResult(
                passed=True,
                gate_type="manual",
                reason=f"approved by {lock.approved_by}",
            )

        time.sleep(_MANUAL_POLL_INTERVAL)

    return GateResult(
        passed=False,
        gate_type="manual",
        reason="timed out waiting for approval",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_gate(
    gate: Gate,
    env_name: str,
    project_root: Path,
    state_module: object | None = None,
) -> GateResult:
    """Evaluate a single gate and return the result.

    Args:
        gate: The gate configuration to evaluate.
        env_name: Name of the target environment.
        project_root: Root of the consuming project (needed for manual gates).
        state_module: Module providing ``get_lock_state``; defaults to
            ``runway.state``.

    Returns:
        A :class:`GateResult` describing whether the gate passed.

    Raises:
        ValueError: If the gate type is unknown.
    """
    if state_module is None:
        state_module = _default_state_module

    if gate.type == GateType.ci_pass:
        return _run_auto_gate(gate, env_name)

    if gate.type == GateType.manual_approval:
        return _run_manual_gate(gate, env_name, project_root, state_module)

    raise ValueError(f"Unknown gate type: {gate.type!r}")
