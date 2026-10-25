"""Checkpoint commits cannot overwrite a cancelled or newer generation attempt."""

import pytest

from backend.engine.generation_control import generation_run
from backend.engine.staged_world.checkpoints import Checkpoints
from backend.models.adventure_template import AdventureTemplate, GenerationCancelled
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_checkpoint_roundtrips_in_a_new_database_session():
    async with TestSessionLocal() as db:
        adventure = AdventureTemplate(
            id="checkpoint-world",
            title="World",
            creation_status="Planning",
            generation_run_id="attempt-one",
        )
        db.add(adventure)
        await db.commit()
        store = Checkpoints(db, adventure, "same-input")
        await store.save("plan", {"canon": "Saved facts"}, 1.5)
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "checkpoint-world")
        resumed = Checkpoints(db, adventure, "same-input")
        assert resumed.results["plan"] == {"canon": "Saved facts"}
        assert resumed.data["timings"]["plan"] == 1.5
        changed = Checkpoints(db, adventure, "different-input")
        assert changed.results == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [{"generation_run_id": "new-attempt"}, {"creation_status": "Cancelled"}]
)
async def test_stale_writer_cannot_commit_after_successful_preflight_check(change):
    async with TestSessionLocal() as db:
        adventure = AdventureTemplate(
            id="fenced-world",
            title="World",
            creation_status="Planning",
            generation_run_id="old-attempt",
        )
        db.add(adventure)
        await db.commit()
        store = Checkpoints(db, adventure, "input")
        await store.check()
        # Simulate the cancellation/replacement racing AFTER the check and before
        # the write. The writer retains the old ORM row and attempt context.
        async with TestSessionLocal() as other:
            current = await other.get(AdventureTemplate, "fenced-world")
            for key, value in change.items():
                setattr(current, key, value)
            await other.commit()
        token = generation_run.set("old-attempt")
        try:
            with pytest.raises(GenerationCancelled):
                await store.flush()
        finally:
            generation_run.reset(token)
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "fenced-world")
        assert adventure.generation_checkpoint is None
        for key, value in change.items():
            assert getattr(adventure, key) == value
