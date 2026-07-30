from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "YouTube Investor Digest"


def _powershell_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def install_task(digest_time: str) -> str:
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is only available on Windows.")
    executable = Path(sys.executable).resolve()
    working_directory = Path.cwd().resolve()
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name",
            (
                "$action = New-ScheduledTaskAction "
                f"-Execute {_powershell_quote(executable)} "
                "-Argument '-m youtube_digest run' "
                f"-WorkingDirectory {_powershell_quote(working_directory)}"
            ),
            f"$trigger = New-ScheduledTaskTrigger -Daily -At {_powershell_quote(digest_time)}",
            (
                "$settings = New-ScheduledTaskSettingsSet "
                "-StartWhenAvailable -MultipleInstances IgnoreNew "
                "-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) "
                "-ExecutionTimeLimit (New-TimeSpan -Hours 6)"
            ),
            (
                "$principal = New-ScheduledTaskPrincipal "
                "-UserId $identity -LogonType Interactive -RunLevel Limited"
            ),
            (
                f"Register-ScheduledTask -TaskName {_powershell_quote(TASK_NAME)} "
                "-Action $action -Trigger $trigger -Settings $settings "
                "-Principal $principal -Force | Out-Null"
            ),
            f"Write-Output {_powershell_quote(TASK_NAME + ' installed')}",
        ]
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def remove_task() -> str:
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is only available on Windows.")
    script = (
        f"Unregister-ScheduledTask -TaskName {_powershell_quote(TASK_NAME)} "
        "-Confirm:$false -ErrorAction Stop; "
        f"Write-Output {_powershell_quote(TASK_NAME + ' removed')}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def task_status() -> str:
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is only available on Windows.")
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"{TASK_NAME} is not installed."
    return result.stdout.strip()
