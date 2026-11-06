"""Synthetic public speech is labelled fixture evidence, never asserted game outcomes."""

from typing import Any

from backend.engine.chpm import host_observations, identity_adapter
from backend.engine.chpm.core.contracts import Genesis, Scope
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.evaluation.matrix_cases import MatrixCase
from backend.engine.chpm.host_observation_contracts import HostFacts
from backend.engine.chpm.host_state import Mind, Source, record
from backend.engine.chpm.kernel import digest


def seed(case: MatrixCase, actor: Any, session: str) -> Mind:
    genesis = Genesis(
        scope=Scope(world_id=session, branch_id="session-main-v1", observer_id=actor.id),
        identity=identity_adapter.from_actor(actor),
    )
    mind = Mind(genesis=genesis, snapshot=initial(genesis))
    for turn in range(case.history_turns):
        minute = turn * (1440 if case.daily else 2)
        facts = HostFacts(scene_id="scene" if turn % 2 == 0 else "break-room")
        frame = host_observations.frame(facts)
        mind = record(
            mind,
            Source(
                message_id=f"old-frame-{turn}",
                content_hash=digest(frame),
                role="user",
                speaker_id=actor.id,
                kind="host_frame",
                text=frame,
                facts=facts,
            ),
            minute=minute,
        )
        text = case.history_text(turn, actor.id)
        mind = record(
            mind,
            Source(
                message_id=f"old-reply-{turn}",
                content_hash=digest(text),
                role="assistant",
                speaker_id=actor.id,
                kind="speech",
                text=text,
            ),
            minute=minute,
        )
    return mind
