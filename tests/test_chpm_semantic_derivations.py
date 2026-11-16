"""Derived judgments remain psychology, never raw message episodes or index failures."""

import pytest
from sqlalchemy import select

from backend.engine.chpm import semantic_sources
from backend.engine.chpm.core.contracts import Citation, Interpret
from backend.engine.chpm.core.ports import accept_interpretation
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.state import KEY, load
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_semantic_integration import (
    _run_index,
    portrait_world,
    semantic_world,
)
from tests.test_chpm_semantic_memory import remembered

__all__ = ["portrait_world", "semantic_world"]


def interpreted(mind: Mind, kind: str) -> Mind:
    source_id, source = next(iter(mind.sources.items()))
    body = Interpret(
        record_id="interpretation",
        belief_id="reported-storage",
        statement="The storage report may be accurate.",
        about_id=source.speaker_id,
        domain="reliability",
        stance="support",
        source_kind=kind,
        citations=(Citation(record_id=source_id, quote=source.text),),
        unknowns=("Independent confirmation",),
    )
    changed = accept_interpretation(
        mind.snapshot,
        body.model_dump(),
        event_id=body.record_id,
        sequence=mind.snapshot.cursor + 1,
        sim_minute=mind.snapshot.sim_minute,
        expected_revision=mind.snapshot.revision,
    ).snapshot
    return Mind(genesis=mind.genesis, snapshot=changed, sources=mind.sources)


@pytest.mark.parametrize("kind", ["inference", "reflection"])
def test_episode_projection_keeps_checked_messages_and_skips_derived_judgments(kind):
    original, rows, _, _ = remembered()
    before = original.model_dump_json()
    value = interpreted(original, kind)
    value = Mind.model_validate_json(value.model_dump_json())
    assert len(value.snapshot.evidence) == 2 and len(value.sources) == 1
    projected = semantic_sources.episodes(value, "owner", "template", rows)
    assert projected == semantic_sources.episodes(original, "owner", "template", rows)
    assert semantic_sources.embedding_text(projected[0], value).endswith(rows["old"].content)
    assert original.model_dump_json() == before
    assert len(value.snapshot.beliefs) == 1


async def test_idle_observer_index_handles_saved_appraisals_and_remains_idempotent(semantic_world):
    owner, base, _, calls = semantic_world
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        kernel = load(state)
        for actor, mind in kernel.minds.items():
            kernel.minds[actor] = interpreted(mind, "inference")
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
    assert await _run_index(owner, base)
    assert not await _run_index(owner, base)
    assert len(calls) == 1 and len(calls[0][0]) == 2
    assert all("storage report may be accurate" not in text for text in calls[0][0])
