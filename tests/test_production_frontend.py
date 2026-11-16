"""Exercise the real application with the production frontend branch enabled."""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.core.frontend import install

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def frontend(tmp_path):
    root = tmp_path / "frontend"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text('<div id="app"></div><script src="/assets/app.js"></script>')
    (root / "assets/app.js").write_text("/* compiled fixture */")
    return root


async def test_real_app_imports_and_health_remains_json(frontend, tmp_path):
    program = """
import asyncio
from httpx import ASGITransport, AsyncClient
from backend.main import app
async def check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get("/health")).json() == {"status": "ok"}
        assert 'id="app"' in (await client.get("/")).text
        assert (await client.get("/assets/app.js")).text == "/* compiled fixture */"
        assert (await client.get("/assets/missing.js")).status_code == 404
        assert (await client.get("/api/missing")).status_code == 404
asyncio.run(check())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        program,
        cwd=ROOT,
        env={
            **os.environ,
            "TALEWEAVER_FRONTEND_DIR": str(frontend),
            "DATA_DIR": str(tmp_path / "data"),
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(process.communicate(), 30)
    assert process.returncode == 0, (out + err).decode()


async def test_frontend_asset_symlink_cannot_escape_configured_root(frontend, tmp_path):
    secret = tmp_path / "private.txt"
    secret.write_text("must not be served")
    try:
        (frontend / "assets/escape.js").symlink_to(secret)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this test platform.")
    assets = tmp_path / "backend_assets"
    assets.mkdir()
    app = FastAPI()
    install(app, frontend, assets)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        result = await client.get("/assets/escape.js")
    assert result.status_code == 404
    assert "must not be served" not in result.text
