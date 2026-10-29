"""Optional progress is task-local and contains stage codes only."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.api.routes import visual_jobs
from backend.api.routes.settings_normalization import normalize_t2i_settings
from backend.engine.visual_progress import report, reporting
from backend.models.user import User
from tests.conftest import TestSessionLocal


def test_progress_defaults_off():
    assert normalize_t2i_settings({})["show_generation_progress"] is False
    assert normalize_t2i_settings({"image_format": "png"})["show_generation_progress"] is False


@pytest.mark.asyncio
async def test_concurrent_progress_is_isolated_and_scope_resets():
    first, second = [], []

    async def run(target, stage):
        with reporting(target.append):
            await asyncio.sleep(0)
            report(stage)
        report("saving")

    await asyncio.gather(run(first, "analyzing"), run(second, "prompt"))
    assert first == ["analyzing"] and second == ["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_job_reports_stages_only_when_enabled(auth_client, monkeypatch, enabled):
    async with TestSessionLocal() as db:
        user = (await db.scalars(select(User))).first()
        user.t2i_settings = {"show_generation_progress": enabled}
        owner = user.id
        await db.commit()
    job = visual_jobs.VisualJob(
        owner=owner, request=visual_jobs.VisualJobRequest(id=uuid4(), operation="test", payload={})
    )
    observed = []

    async def dispatch(*_args):
        for stage in ("analyzing", "prompt", "waiting", "saving"):
            report(stage)
            observed.append(job.public()["stage"])
        return {"status": "success"}

    monkeypatch.setattr(visual_jobs, "_dispatch", dispatch)
    await visual_jobs._run(job)
    assert job.state == "succeeded"
    assert observed == (["analyzing", "prompt", "waiting", "saving"] if enabled else [None] * 4)
