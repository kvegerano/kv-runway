from unittest.mock import MagicMock, patch

import pytest

from runway.triggers import DeployResult, ShellTrigger, Trigger, get_trigger


def _make_proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_shell_trigger_success():
    with patch("runway.triggers.subprocess.run", return_value=_make_proc(0, stdout="ok")) as _:
        result = ShellTrigger("echo ok").deploy()
    assert result == DeployResult(status="success", exit_code=0, stdout="ok", stderr="")


def test_shell_trigger_failure():
    with patch("runway.triggers.subprocess.run", return_value=_make_proc(1, stderr="err")):
        result = ShellTrigger("false").deploy()
    assert result == DeployResult(status="failed", exit_code=1, stdout="", stderr="err")


def test_shell_trigger_shell_false():
    mock_proc = _make_proc(0)
    with patch("runway.triggers.subprocess.run", return_value=mock_proc) as mock_run:
        ShellTrigger("echo hi").deploy()
    _, kwargs = mock_run.call_args
    assert kwargs.get("shell") is False


def test_shell_trigger_uses_shlex_split():
    mock_proc = _make_proc(0)
    with patch("runway.triggers.subprocess.run", return_value=mock_proc) as mock_run:
        ShellTrigger("echo hello world").deploy()
    args, _ = mock_run.call_args
    cmd = args[0]
    assert isinstance(cmd, list)
    assert cmd == ["echo", "hello", "world"]


def test_get_trigger_shell():
    trigger = get_trigger({"type": "shell", "command": "pytest"})
    assert isinstance(trigger, ShellTrigger)


def test_get_trigger_unknown_raises():
    with pytest.raises(ValueError, match="Unknown trigger type"):
        get_trigger({"type": "vercel"})


def test_get_trigger_missing_command_raises():
    with pytest.raises(ValueError, match="requires 'command'"):
        get_trigger({"type": "shell"})
