"""An incomplete checkout must not deploy a substitute reverse-proxy policy."""

import asyncio
import os
from pathlib import Path

import pytest

SETUP = Path(__file__).resolve().parents[1] / "scripts/docker-setup.sh"


@pytest.mark.parametrize("directory", [False, True])
async def test_missing_canonical_config_stops_before_any_docker_command(tmp_path, directory):
    root = tmp_path / "checkout"
    script = root / "scripts/docker-setup.sh"
    script.parent.mkdir(parents=True)
    script.write_bytes(SETUP.read_bytes())
    (root / ".env").write_text("FRONTEND_PORT=443\n")
    (root / "nginx/ssl").mkdir(parents=True)
    if directory:
        (root / "nginx/nginx.conf").mkdir()
        (root / "nginx/nginx.conf/keep").write_text("existing data")
    tools = tmp_path / "bin"
    tools.mkdir()
    docker = tools / "docker"
    docker.write_text('#!/bin/sh\ntouch "$DOCKER_TEST_MARKER"\nexit 0\n')
    docker.chmod(0o755)
    marker = tmp_path / "called"
    process = await asyncio.create_subprocess_exec(
        "bash",
        str(script),
        env={
            **os.environ,
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
            "DOCKER_TEST_MARKER": str(marker),
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(process.communicate(), 5)
    assert process.returncode != 0, (out + err).decode()
    assert b"nginx/nginx.conf" in out + err
    assert not marker.exists()
    if directory:
        assert (root / "nginx/nginx.conf/keep").read_text() == "existing data"
