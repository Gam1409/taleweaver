"""Exercise the real launcher with inert migration/server executables."""

import asyncio
import os
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


@pytest.fixture
def launch_environment(tmp_path):
    folder = tmp_path / "bin"
    folder.mkdir()
    for name, body in {
        "python": 'printf "migrate\\n" >> "$AUDIT_LAUNCH_LOG"\nexit "${AUDIT_MIGRATE_EXIT:-0}"\n',
        "gunicorn": 'printf "gunicorn\\n" >> "$AUDIT_LAUNCH_LOG"\nprintf "%s\\n" "$@" >> "$AUDIT_LAUNCH_LOG"\n',
    }.items():
        executable = folder / name
        executable.write_text("#!/bin/sh\n" + body)
        executable.chmod(0o700)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"WEB_CONCURRENCY", "GUNICORN_TIMEOUT", "GUNICORN_GRACEFUL_TIMEOUT"}
    }
    env["PATH"] = str(folder) + os.pathsep + env.get("PATH", "")
    env["AUDIT_LAUNCH_LOG"] = str(tmp_path / "launch.log")
    return env


async def launch(env):
    process = await asyncio.create_subprocess_exec(
        "sh",
        str(ENTRYPOINT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    return process.returncode, (stdout + stderr).decode()


@pytest.mark.parametrize("workers", [None, "", "1"])
async def test_container_launches_one_worker_with_existing_timeout_options(
    launch_environment, workers
):
    env = launch_environment
    if workers is not None:
        env["WEB_CONCURRENCY"] = workers
    env["GUNICORN_TIMEOUT"] = "600"
    env["GUNICORN_GRACEFUL_TIMEOUT"] = "45"
    code, output = await launch(env)
    assert code == 0, output
    lines = await asyncio.to_thread(Path(env["AUDIT_LAUNCH_LOG"]).read_text)
    arguments = lines.splitlines()
    assert arguments[:2] == ["migrate", "gunicorn"]
    assert arguments[arguments.index("--workers") + 1] == "1"
    assert arguments[arguments.index("--timeout") + 1] == "600"
    assert arguments[arguments.index("--graceful-timeout") + 1] == "45"


@pytest.mark.parametrize("workers", ["2", "0", "-1", "many"])
async def test_unsupported_worker_configuration_fails_before_database_migration(
    launch_environment, workers
):
    env = {**launch_environment, "WEB_CONCURRENCY": workers}
    code, output = await launch(env)
    assert code != 0
    assert "single worker" in output.lower()
    assert not await asyncio.to_thread(Path(env["AUDIT_LAUNCH_LOG"]).exists)


async def test_failed_migration_does_not_start_server(launch_environment):
    env = {**launch_environment, "AUDIT_MIGRATE_EXIT": "1"}
    code, _ = await launch(env)
    assert code != 0
    assert await asyncio.to_thread(Path(env["AUDIT_LAUNCH_LOG"]).read_text) == "migrate\n"


async def test_separate_sqlite_volume_does_not_silently_replace_existing_db(
    launch_environment, tmp_path
):
    legacy = tmp_path / "legacy.db"
    target = tmp_path / "sqlite/taleweaver.db"
    legacy.write_bytes(b"existing database fixture")
    env = {
        **launch_environment,
        "TALEWEAVER_LEGACY_SQLITE_FILE": str(legacy),
        "TALEWEAVER_SQLITE_FILE": str(target),
        "DATABASE_URL": "sqlite+aiosqlite:///" + str(target),
    }
    code, output = await launch(env)
    assert code == 78
    assert "migrate" in output.lower()
    assert not await asyncio.to_thread(Path(env["AUDIT_LAUNCH_LOG"]).exists)
    assert legacy.read_bytes() == b"existing database fixture"


async def test_explicitly_migrated_sqlite_volume_can_start(launch_environment, tmp_path):
    legacy, target = tmp_path / "old.db", tmp_path / "new.db"
    legacy.write_bytes(b"retained original")
    target.write_bytes(b"operator migrated database")
    env = {
        **launch_environment,
        "TALEWEAVER_LEGACY_SQLITE_FILE": str(legacy),
        "TALEWEAVER_SQLITE_FILE": str(target),
        "DATABASE_URL": "sqlite+aiosqlite:///" + str(target),
    }
    code, output = await launch(env)
    assert code == 0, output
    assert legacy.read_bytes() == b"retained original"
