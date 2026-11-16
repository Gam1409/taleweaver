"""OS process adapter for the local launcher, never for HTTP-supplied commands.

The deployment-tools lint policy permits subprocess calls in this directory.
Keep executable selection here; callers cannot supply a shell command.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def service_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--server"]
    return [sys.executable, "-m", "desktop", "--server"]


def start_service(root: Path, env: dict[str, str]) -> subprocess.Popen:
    options: dict = (
        {"start_new_session": True}
        if os.name != "nt"
        else {
            "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        }
    )
    return subprocess.Popen(
        service_command(),
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **options,
    )


def open_log(path: Path) -> None:
    """Open our own text log with an OS viewer; never execute its contents."""
    path = path.resolve(strict=True)
    if path.suffix != ".log":
        raise ValueError("Only the desktop text log can be opened.")
    if sys.platform == "win32":
        executable = str(Path(os.environ["SYSTEMROOT"]) / "System32/notepad.exe")
    elif sys.platform == "darwin":
        executable = "/usr/bin/open"
    else:
        executable = shutil.which("xdg-open") or ""
    if not executable:
        raise RuntimeError("No system text viewer is available. Open desktop.log manually.")
    subprocess.Popen([executable, str(path)])
