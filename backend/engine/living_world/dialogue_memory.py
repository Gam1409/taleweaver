"""Source-bound private intentions; never authoritative world-state updates."""

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models.chat import ChatMessage


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["UNKNOWN", "COMPLETED", "BLOCKED", "ABANDONED"] = "UNKNOWN"
    quote: str = Field(default="", max_length=300)


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "ACCEPT",
        "REFUSE",
        "NEGOTIATE",
        "EVADE",
        "ASK_CLARIFICATION",
        "DEFER",
        "INITIATE",
        "CONTINUE",
    ]
    motive: str = Field(min_length=1, max_length=300)
    intention: str = Field(min_length=1, max_length=300)
    next_action: str = Field(default="", max_length=200)
    reconsider_if: str = Field(default="", max_length=200)
    previous_outcome: Outcome = Field(default_factory=Outcome)


class IntentionMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_message_id: str
    source_revision_id: str | None = None
    content_hash: str
    scene_id: str | None = None
    choice: Choice


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def previous_context(manager: Any, simulation: Any, actor_id: str) -> dict:
    memory = simulation.dialogue_intentions.get(actor_id)
    if memory is None or memory.scene_id != manager.state.current_scene_id:
        return {}
    message = await manager.db.get(ChatMessage, memory.source_message_id)
    if (
        message is None
        or message.session_id != manager.game_id
        or message.role != "assistant"
        or message.revision_id != memory.source_revision_id
        or digest(message.content) != memory.content_hash
    ):
        simulation.dialogue_intentions.pop(actor_id, None)
        return {}
    return {
        "source_message_id": message.id,
        "proposal_not_fact": memory.choice.model_dump(exclude={"previous_outcome"}),
        "result_narration_untrusted": message.content[:4000],
    }


def grounded_choice(choice: Choice, previous: dict) -> Choice:
    """Literal evidence rejects fabricated quotes; semantic review remains fallible."""
    outcome = choice.previous_outcome
    evidence = previous.get("result_narration_untrusted", "")
    if outcome.status == "UNKNOWN" or not outcome.quote.strip() or outcome.quote not in evidence:
        return choice.model_copy(update={"previous_outcome": Outcome()})
    return choice


def remember_completed(manager: Any, message: Any, *, completed: bool) -> None:
    """Called inside the completed turn transaction, after the reply has an ID."""
    from backend.engine.living_world.state import load, save

    pending = getattr(manager, "_dialogue_intention", None)
    manager._dialogue_intention = None
    if not completed or not pending or not message.content.strip():
        return
    actor_id, scene_id, choice = pending
    if scene_id != message.scene_id:
        return
    simulation = load(manager.state)
    if (
        actor_id not in simulation.dialogue_intentions
        and len(simulation.dialogue_intentions) >= 128
    ):
        return
    # Previous assessments are turn-local: never carry an old evidence claim into a new source.
    clean = choice.model_copy(update={"previous_outcome": Outcome()})
    simulation.dialogue_intentions[actor_id] = IntentionMemory(
        source_message_id=message.id,
        source_revision_id=message.revision_id,
        content_hash=digest(message.content),
        scene_id=scene_id,
        choice=clean,
    )
    save(manager.state, simulation)


def retract(state: Any, message_id: str) -> None:
    from backend.engine.living_world.state import load, save

    if not getattr(state, "living_world", None):
        return
    simulation = load(state)
    retained = {
        actor: memory
        for actor, memory in simulation.dialogue_intentions.items()
        if memory.source_message_id != message_id
    }
    if len(retained) == len(simulation.dialogue_intentions):
        return
    simulation.dialogue_intentions = retained
    save(state, simulation)
