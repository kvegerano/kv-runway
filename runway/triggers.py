import dataclasses
import shlex
import subprocess
from abc import ABC, abstractmethod


@dataclasses.dataclass
class DeployResult:
    status: str  # "success" or "failed"
    exit_code: int
    stdout: str = ""
    stderr: str = ""


class Trigger(ABC):
    @abstractmethod
    def deploy(self) -> DeployResult:
        ...


class ShellTrigger(Trigger):
    def __init__(self, command: str) -> None:
        self._command = command

    def deploy(self) -> DeployResult:
        cmd = shlex.split(self._command)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=False,  # NEVER shell=True
        )
        status = "success" if result.returncode == 0 else "failed"
        return DeployResult(
            status=status,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def get_trigger(trigger_config: dict) -> Trigger:
    trigger_type = trigger_config.get("type")
    if trigger_type == "shell":
        command = trigger_config.get("command")
        if not command:
            raise ValueError("ShellTrigger requires 'command' in trigger config")
        return ShellTrigger(command)
    raise ValueError(f"Unknown trigger type {trigger_type!r}. Only 'shell' is supported in v0.1.")
