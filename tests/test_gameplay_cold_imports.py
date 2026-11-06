"""Gameplay packages must import before the HTTP app or turn manager warms them."""

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module",
    [
        "backend.engine.gameplay.guardrails",
        "backend.engine.gameplay.combat",
        "backend.engine.gameplay.combat.unlocks",
        "backend.engine.gameplay.combat.narration",
    ],
)
async def test_gameplay_package_imports_in_fresh_process(module):
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import importlib, sys; importlib.import_module(sys.argv[1])",
        module,
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(child.communicate(), 30)
    assert child.returncode == 0, (out + err).decode()
