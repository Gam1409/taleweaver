"""The day-two Bash launcher supports Poetry and cleans up companion services."""

import asyncio
import os
import signal
from contextlib import suppress
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="Bash process-group behavior is POSIX-specific"
)


def executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def checkout(
    tmp_path: Path, kind: str, backend_exit: str = "", frontend_exit: str = ""
) -> tuple[Path, dict, Path]:
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    (root / "run.sh").write_bytes((Path(__file__).resolve().parents[1] / "run.sh").read_bytes())
    (root / ".env").write_text("# Disposable launcher fixture\n")
    (root / "frontend/node_modules/.bin").mkdir(parents=True)
    executable(root / "frontend/node_modules/.bin/vite", "#!/bin/sh\nexit 0\n")
    target = (
        root / kind / "bin/python"
        if kind != "poetry"
        else tmp_path / "Poetry environment/bin/python"
    )
    executable(
        target,
        """#!/bin/bash
printf 'backend|%s|%s\n' "$PWD" "$*" >> "$RUNNER_TEST_LOG"
trap 'printf "backend stopped\\n" >> "$RUNNER_TEST_LOG"; exit 0' TERM
if [ -n "$RUNNER_TEST_BACKEND_EXIT" ]; then exit "$RUNNER_TEST_BACKEND_EXIT"; fi
while :; do sleep 0.1; done
""",
    )
    if kind != "poetry":
        target.with_name("python3").symlink_to(target)
    tools = tmp_path / "tools"
    executable(tools / "poetry", '#!/bin/bash\nprintf "%s\\n" "$RUNNER_TEST_PYTHON"\n')
    executable(
        tools / "npm",
        """#!/bin/bash
printf 'frontend|%s|%s\n' "$PWD" "$*" >> "$RUNNER_TEST_LOG"
trap 'printf "frontend stopped\\n" >> "$RUNNER_TEST_LOG"; exit 0' TERM
if [ -n "$RUNNER_TEST_FRONTEND_EXIT" ]; then exit "$RUNNER_TEST_FRONTEND_EXIT"; fi
while :; do sleep 0.1; done
""",
    )
    log = tmp_path / "runner.log"
    env = {
        **os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "RUNNER_TEST_LOG": str(log),
        "RUNNER_TEST_PYTHON": str(target),
        "RUNNER_TEST_BACKEND_EXIT": backend_exit,
        "RUNNER_TEST_FRONTEND_EXIT": frontend_exit,
    }
    env.pop("VIRTUAL_ENV", None)
    return root, env, log


async def launch(root: Path, env: dict) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        "bash",
        str(root / "run.sh"),
        "--no-update",
        cwd=root,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )


async def stop(process: asyncio.subprocess.Process) -> None:
    # Kill only the isolated test launcher group, including legacy orphaned children.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.communicate(), timeout=4)
    except TimeoutError:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.communicate()


@pytest.mark.parametrize("kind", ["venv", ".venv", "poetry"])
async def test_supported_environments_start_from_spaced_paths_and_stop_together(tmp_path, kind):
    root, env, log = checkout(tmp_path, kind)
    process = await launch(root, env)
    try:
        for _ in range(100):
            if log.exists() and "frontend|" in log.read_text() and "backend|" in log.read_text():
                break
            await asyncio.sleep(0.02)
        assert process.returncode is None
        lines = log.read_text()
        assert f"backend|{root}|-m backend.main" in lines
        assert f"frontend|{root / 'frontend'}|run dev" in lines
        await stop(process)
        assert process.returncode == 143
        assert "backend stopped" in log.read_text() and "frontend stopped" in log.read_text()
    finally:
        await stop(process)


@pytest.mark.parametrize("backend_exit,frontend_exit,expected", [("17", "", 17), ("", "23", 23)])
async def test_early_service_failure_stops_the_companion_and_preserves_exit_status(
    tmp_path, backend_exit, frontend_exit, expected
):
    root, env, _ = checkout(tmp_path, ".venv", backend_exit, frontend_exit)
    process = await launch(root, env)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=4)
        assert process.returncode == expected, (stdout + stderr).decode()
    finally:
        await stop(process)
