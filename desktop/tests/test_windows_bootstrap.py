"""The Windows deployment helper cannot replace the canonical proxy policy."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/docker-setup.bat"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Native cmd.exe check")


@pytest.mark.parametrize("directory", [False, True])
async def test_missing_proxy_config_stops_before_docker(tmp_path, directory):
    root = tmp_path / "checkout with spaces"
    script = root / "scripts/docker-setup.bat"
    script.parent.mkdir(parents=True)
    script.write_bytes(SOURCE.read_bytes())
    (root / ".env").write_text("HTTPS_PORT=443\n")
    (root / "nginx").mkdir()
    config = root / "nginx/nginx.conf"
    if directory:
        config.mkdir()
        (config / "keep.txt").write_text("preserve")
    tools = tmp_path / "bin"
    tools.mkdir()
    marker = tmp_path / "docker-called"
    (tools / "docker.cmd").write_text(
        '@echo off\necho called > "%DOCKER_TEST_MARKER%"\nexit /b 0\n'
    )
    child = await asyncio.create_subprocess_exec(
        "cmd.exe",
        "/c",
        str(script),
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
            "DOCKER_TEST_MARKER": str(marker),
        },
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(child.communicate(), 10)
    assert child.returncode != 0, (out + err).decode(errors="replace")
    assert not marker.exists()
    if directory:
        assert (config / "keep.txt").read_text() == "preserve"
