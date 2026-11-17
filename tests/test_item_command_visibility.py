"""Command-owned descriptive state follows the existing public clothing surfaces."""

from backend.engine.clothing.context import actor_records
from backend.engine.physical_conditions.item_commands import apply_command
from backend.engine.physical_conditions.visuals import project
from tests.observable_state_support import world
from tests.test_item_command_state import proof


def test_public_command_fact_on_visible_clothing_reaches_public_visual_consumers():
    host, rows = world()
    host.state.entity_states, identifier = apply_command(
        {},
        item_id="COAT",
        dimension="damage",
        detail="The cuff is torn.",
        owned_item_ids={"COAT"},
        proof=proof(),
        message_id="input",
        request_hash="a" * 64,
        session_id="session",
        minute=5,
    )
    visible = project(host.state, actor_records(host, rows), detailed=False, limit=None)
    assert any(row["id"] == identifier and row["detail"] == "The cuff is torn." for row in visible)


def test_public_command_fact_does_not_reveal_a_covered_inner_layer():
    host, rows = world()
    host.state.entity_states, identifier = apply_command(
        {},
        item_id="LINING",
        dimension="damage",
        detail="The hidden cuff is torn.",
        owned_item_ids={"LINING"},
        proof=proof(),
        message_id="input",
        request_hash="b" * 64,
        session_id="session",
        minute=5,
    )
    visible = project(host.state, actor_records(host, rows), detailed=False, limit=None)
    assert not any(row["id"] == identifier for row in visible)
