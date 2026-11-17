"""Host-stamp synthetic turn outcomes at the same boundary as production capture."""

from types import SimpleNamespace

from backend.engine import turn_controls
from backend.engine.npc_actions import control


def bind_observation(manager, observation):
    """Bind the canonical input supplied by pure fixtures instead of a database message."""
    expected = {
        "input_id": observation.message_id,
        "input_revision": observation.revision_id,
        "input_hash": observation.content_hash,
    }
    turn_controls.scope(manager, "npc_preparation")
    current = getattr(manager, "_turn_control_input", None)
    # Never repair a deliberately stale fixture by silently rebinding its source.
    assert current is None or current == expected
    assert (
        getattr(manager, "_vn_player_message_id", observation.message_id) == observation.message_id
    )
    manager._vn_player_message_id = observation.message_id
    manager._turn_control_input = expected


def bind_turn(manager, turn):
    observation = next(
        (
            decision.observation
            for decision in getattr(turn, "decisions", {}).values()
            if decision is not None
        ),
        None,
    )
    if observation is not None:
        bind_observation(manager, observation)
    turn.control = turn_controls.scope(manager, "narration_review", observation=observation)
    turn.action_outcomes = {
        actor: [
            {
                **row,
                **control.result(
                    turn_controls.operation(
                        {**turn.control, "phase": "npc_command_publication"},
                        row.get("tool", "interact"),
                        actor_id=actor,
                    ),
                    row["status"],
                    **{
                        key: value
                        for key, value in row.items()
                        if key not in {*turn_controls.Operation.model_fields, "event_id", "status"}
                    },
                ),
            }
            for row in rows
        ]
        for actor, rows in turn.action_outcomes.items()
    }
    turn.action_drafts = {
        actor: SimpleNamespace(
            operations=[
                turn_controls.Operation.model_validate(
                    {key: row[key] for key in turn_controls.Operation.model_fields if key in row}
                )
                for row in rows
            ]
        )
        for actor, rows in turn.action_outcomes.items()
    }
    return turn
